"""
MailRepo API - Commit Workflow

Handles committing staged emails and folders to the archive.
Supports post-commit actions (archive, trash, delete) for IMAP emails.
"""

import os

from core import Config, Database, Encryption, ImapPool

from .email_parser import (
    count_emails_in_import_folder,
    extract_body_text,
    get_raw_email_from_import,
    iter_emails_from_import_folder,
    parse_email_metadata,
)


def create_archive_folder_from_path(archive_path: str, parent_folder_id: int) -> int:
    """
    Create archive folder(s) from a path string.

    Args:
        archive_path: Path like "Parent/Child" or just "Child"
        parent_folder_id: Destination folder ID (the folder user selected)

    Returns:
        ID of the deepest folder created/found

    Example:
        archive_path="Fan Mail/2024", parent_folder_id=5
        Creates: [5] -> "Fan Mail" -> "2024"
        Returns: ID of "2024" folder
    """
    if not archive_path:
        return parent_folder_id

    parts = archive_path.split("/")
    current_parent_id = parent_folder_id

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Check if folder already exists
        existing = Database.fetchone(
            "SELECT id FROM folders WHERE name = ? AND parent_id = ? AND deleted_at IS NULL",
            (part, current_parent_id),
        )

        if existing:
            current_parent_id = existing["id"]
        else:
            # Create new folder
            cursor = Database.execute(
                "INSERT INTO folders (name, parent_id) VALUES (?, ?)", (part, current_parent_id)
            )
            current_parent_id = cursor.lastrowid
            # Commit immediately so subsequent lookups can find this folder
            Database.commit()

    return current_parent_id


def _effective_message_id(message_id: str, raw_email: bytes) -> str:
    """The Message-ID used for dedup and storage.

    Emails without a Message-ID header (malformed, some exports) used to
    bypass duplicate detection entirely — _check_duplicate treats an
    empty id as "not a duplicate" — so an interrupted commit retried
    after a connection drop filed them twice (found in the Session 88
    .deb acceptance test). A deterministic content-derived id closes
    that: identical raw bytes always map to the same synthetic id.
    """
    if message_id:
        return message_id
    import hashlib

    return f"<{hashlib.sha256(raw_email).hexdigest()}@mailrepo.dedup>"


def _same_message(a: bytes, b: bytes) -> bool:
    """Byte-for-byte the same message, ignoring line-ending convention.

    IMAP hands over CRLF; an mbox import of the same message arrives with
    LF. Those are the same message and must not be archived twice.
    """
    return a.replace(b"\r\n", b"\n") == b.replace(b"\r\n", b"\n")


def _has_message_id(folder_id: int, message_id: str) -> bool:
    """True if the folder already holds a (non-trashed) message with this Message-ID."""
    if not message_id:
        return False
    existing = Database.fetchone(
        "SELECT id FROM messages WHERE folder_id = ? AND message_id = ? AND deleted_at IS NULL",
        (folder_id, message_id),
    )
    return existing is not None


def _check_duplicate(folder_id: int, message_id: str, raw_email: bytes | None = None) -> bool:
    """Is this message already in the folder (excluding trashed)?

    A matching Message-ID is not enough. The sender chooses it, and anyone
    who has seen a thread knows the ids of its earlier messages, so a
    DIFFERENT message can carry the same one. Treating that as a
    duplicate meant it was never archived and was then removed from the
    server by the post-commit action (code review 2026-11, #2).

    So with ``raw_email`` a duplicate is a row with the same Message-ID
    whose archived file holds the same message. If the archived copy
    cannot be read, the answer is "not a duplicate": a second copy is
    harmless, and a message that exists only on the server is not.

    Without ``raw_email`` this answers the Message-ID question only; no
    caller that goes on to act on the server should use it that way.
    """
    if not message_id:
        return False
    rows = Database.fetchall(
        """SELECT filepath FROM messages
           WHERE folder_id = ? AND message_id = ? AND deleted_at IS NULL""",
        (folder_id, message_id),
    )
    if not rows:
        return False
    if raw_email is None:
        return True
    for row in rows:
        try:
            stored = Encryption.decrypt((Config.get_base_path() / row["filepath"]).read_bytes())
        except Exception:
            continue
        if _same_message(stored, raw_email):
            return True
    return False


def _safe_uid(uid) -> str:
    """An IMAP UID is a decimal integer; anything else is not used as a
    filename component. The fixed account prefix already prevented
    traversal; this makes the shape explicit."""
    s = str(uid).strip()
    if not s.isdigit():
        raise ValueError(f"Malformed IMAP UID: {uid!r}")
    return s


def _write_new_file(path, data: bytes, durable: bool) -> bool:
    """Create ``path`` holding exactly ``data``. False if it already exists.

    os.write may write fewer bytes than asked (a disk filling up
    mid-write does exactly that, without raising), so it is looped until
    everything is out. On any failure the file is removed before the
    error propagates: a half-written or empty .eml.enc left behind opens
    under no key and used to halt every later key rotation.

    ``durable`` also flushes the file and its directory entry to disk.
    Used when the source is an IMAP server, because the original may be
    removed from that server moments later.
    """
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    try:
        try:
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                view = view[written:]
            if durable:
                os.fsync(fd)
        finally:
            os.close(fd)
        if durable:
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
    except BaseException:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    return True


def _save_email_to_archive(
    raw_email: bytes, folder_id: int, account_id: int | None, uid_prefix: str
) -> None:
    """
    Encrypt and save a raw email to the archive, inserting a DB row.

    This operation is made atomic: if the DB insert fails, the file is deleted.
    If the file write fails, no file is left behind and no DB record is created.

    Before the row is inserted the file is read back from disk and
    decrypted, and must come out as the message that went in. Callers
    treat a return from here as "this message is safely in the archive"
    and may then remove the original from the mail server.

    Args:
        raw_email: Raw RFC 2822 email bytes.
        folder_id: Destination archive folder ID.
        account_id: Source IMAP account ID (None for imports).
        uid_prefix: Safe filename prefix (e.g. "import_mbox-3" or "2_145").
    """
    metadata = parse_email_metadata(raw_email)
    metadata["message_id"] = _effective_message_id(metadata.get("message_id", ""), raw_email)
    body_text = extract_body_text(raw_email)

    archive_path = Config.get_archive_path() / str(folder_id)
    archive_path.mkdir(parents=True, exist_ok=True)

    encrypted_data = Encryption.encrypt(raw_email)

    # Never overwrite. IMAP UIDs are unique only per UIDVALIDITY, so a
    # rebuilt mailbox (or a server that re-issues UIDs) can hand back a
    # UID whose file already exists — and a database row still points at
    # it. O_EXCL makes the collision explicit; disambiguate with a
    # suffix, as core/importer.py does (security review 2026-09, #16).
    filepath = None
    for attempt in range(1000):
        candidate = archive_path / (
            f"{uid_prefix}.eml.enc" if attempt == 0 else f"{uid_prefix}_{attempt}.eml.enc"
        )
        if _write_new_file(candidate, encrypted_data, durable=account_id is not None):
            filepath = candidate
            break
    if filepath is None:
        raise OSError(f"Could not find a free archive filename for {uid_prefix}")

    # Read it back: what is on disk must decrypt to what was handed in.
    try:
        if Encryption.decrypt(filepath.read_bytes()) != raw_email:
            raise OSError(f"Archive file {filepath.name} does not match the message written")
    except Exception as e:
        try:
            filepath.unlink()
        except OSError:
            pass
        raise OSError(f"Archive file {filepath.name} failed its read-back check: {e}") from e

    # Insert DB record - if this fails, clean up the file
    try:
        Database.execute(
            """INSERT INTO messages
               (folder_id, source_account_id, message_id, subject, sender, recipients, date, filepath, body_text)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                folder_id,
                account_id,
                metadata.get("message_id", ""),
                metadata.get("subject", ""),
                metadata.get("sender", ""),
                metadata.get("recipients", ""),
                metadata.get("date"),
                str(filepath.relative_to(Config.get_base_path())),
                body_text,
            ),
        )
    except Exception:
        # DB insert failed - remove the orphaned file
        try:
            filepath.unlink()
        except OSError:
            pass  # Best effort cleanup
        raise  # Re-raise the original exception


def commit_import_email(item: dict, results: dict) -> dict:
    """
    Commit a single email from an import source.

    Args:
        item: Staged item dict with email data and destinationFolderId
        results: Results dict to update with success/failed/skipped

    Returns:
        Progress event dict with status
    """
    email_data = item.get("email", {})
    folder_id = item.get("destinationFolderId")
    uid = email_data.get("uid", "")
    subject = email_data.get("subject", "(no subject)")[:50]

    try:
        # Check destination folder exists
        folder = Database.fetchone("SELECT id FROM folders WHERE id = ?", (folder_id,))
        if not folder:
            raise ValueError(f"Folder {folder_id} not found")

        # Get raw email from source file (before the duplicate check:
        # a missing Message-ID is replaced by a content hash, which
        # needs the bytes)
        source_path = email_data.get("sourcePath")
        if not source_path:
            raise ValueError("No source path for imported email")

        raw_email = get_raw_email_from_import(source_path, uid)
        if not raw_email:
            raise ValueError("Could not retrieve email content")

        # Check for duplicate
        message_id = _effective_message_id(email_data.get("message_id", ""), raw_email)
        if _check_duplicate(folder_id, message_id, raw_email):
            results["skipped"].append({"uid": uid, "reason": "duplicate", "subject": subject})
            return {"status": "skipped", "subject": subject, "uid": uid}

        safe_id = f"import_{uid.replace('/', '_').replace(':', '_')}"
        _save_email_to_archive(raw_email, folder_id, None, safe_id)

        results["success"].append(uid)
        return {"status": "success", "subject": subject, "uid": uid}

    except Exception as e:
        results["failed"].append({"uid": uid, "error": str(e)})
        return {"status": "failed", "subject": subject, "uid": uid, "error": str(e)}


def commit_imap_email(
    client,
    account_id: int,
    email_data: dict,
    folder_id: int,
    source_folder: str,
    results: dict,
    committed_emails: dict,
) -> dict:
    """
    Commit a single email from IMAP.

    Args:
        client: Connected IMAP client
        account_id: IMAP account ID
        email_data: Email header data
        folder_id: Destination archive folder ID
        source_folder: IMAP source folder name
        results: Results dict to update
        committed_emails: Dict tracking committed emails for post-actions

    Returns:
        Progress event dict with status
    """
    uid = email_data.get("uid")
    subject = email_data.get("subject", "(no subject)")[:50]

    try:
        # Check destination folder exists
        folder = Database.fetchone("SELECT id FROM folders WHERE id = ?", (folder_id,))
        if not folder:
            raise ValueError(f"Folder {folder_id} not found")

        # Check for duplicate. A Message-ID the folder has never seen
        # needs no fetch to rule out; one it HAS seen is only a candidate,
        # and the message is fetched so its content can be compared. A
        # skipped message is removed from the server by the post-commit
        # action, so "skipped" has to mean "this exact message is here".
        message_id = email_data.get("message_id", "")
        raw_email = None
        if not message_id:
            raw_email = client.fetch_raw(uid)
            message_id = _effective_message_id("", raw_email)
        if _has_message_id(folder_id, message_id):
            if raw_email is None:
                raw_email = client.fetch_raw(uid)
            if _check_duplicate(folder_id, message_id, raw_email):
                results["skipped"].append({"uid": uid, "reason": "duplicate", "subject": subject})
                return {"status": "skipped", "subject": subject, "uid": uid}

        # Fetch and save email
        if raw_email is None:
            raw_email = client.fetch_raw(uid)
        safe_id = f"{account_id}_{_safe_uid(uid)}"
        _save_email_to_archive(raw_email, folder_id, account_id, safe_id)

        results["success"].append(uid)

        # Track for post-commit actions
        if account_id not in committed_emails:
            committed_emails[account_id] = {}
        if source_folder not in committed_emails[account_id]:
            committed_emails[account_id][source_folder] = []
        committed_emails[account_id][source_folder].append((uid, folder_id))

        return {"status": "success", "subject": subject, "uid": uid}

    except Exception as e:
        results["failed"].append({"uid": uid, "error": str(e)})
        return {"status": "failed", "subject": subject, "uid": uid, "error": str(e)}


def commit_import_folder(
    folder_item: dict, target_folder_id: int, folder_idx: int, folder_count: int, results: dict
):
    """
    Generator that commits all emails from an import folder.

    Yields progress events for each email.
    """
    import_path = folder_item.get("importPath")
    folder_path = folder_item.get("folder")
    import_type = folder_item.get("importType", "apple-mbox")
    archive_path = folder_item.get("archivePath", "")
    folder_name = archive_path.split("/")[-1] if archive_path else "folder"

    # Counted first for the progress bar, then read one message at a time:
    # a large mbox no longer has to fit in memory.
    folder_email_count = count_emails_in_import_folder(import_path, folder_path, import_type)
    emails = iter_emails_from_import_folder(import_path, folder_path, import_type)

    # Yield folder start status
    yield {
        "type": "status",
        "phase": "folder",
        "message": f"Folder {folder_idx + 1} of {folder_count}: {folder_name} ({folder_email_count} emails)",
        "folderIndex": folder_idx + 1,
        "folderCount": folder_count,
    }

    for i, (uid, raw_email) in enumerate(emails):
        try:
            subject = parse_email_metadata(raw_email).get("subject", "(no subject)")[:50]
            safe_id = f"import_{uid.replace('/', '_').replace(':', '_')}"
            _save_email_to_archive(raw_email, target_folder_id, None, safe_id)
            results["success"].append(uid)

            # Commit every 10 emails for durability
            if (i + 1) % 10 == 0:
                Database.commit()

            yield {
                "type": "progress",
                "current": i + 1,
                "total": folder_email_count,
                "percent": int((i + 1) / folder_email_count * 100)
                if folder_email_count > 0
                else 100,
                "status": "success",
                "subject": subject,
                "folder": folder_name,
                "folderIndex": folder_idx + 1,
                "folderCount": folder_count,
                "commitPhase": "folders",
            }
        except Exception as e:
            results["failed"].append({"uid": uid, "error": str(e)})
            yield {
                "type": "progress",
                "current": i + 1,
                "total": folder_email_count,
                "percent": int((i + 1) / folder_email_count * 100)
                if folder_email_count > 0
                else 100,
                "status": "failed",
                "subject": "(error)",
                "folder": folder_name,
                "error": str(e),
                "folderIndex": folder_idx + 1,
                "folderCount": folder_count,
                "commitPhase": "folders",
            }


def commit_imap_folder(
    folder_item: dict, target_folder_id: int, folder_idx: int, folder_count: int, results: dict
):
    """
    Generator that commits all emails from an IMAP folder.

    Yields progress events for each email.
    """
    account_id = folder_item.get("accountId")
    imap_folder = folder_item.get("folder")
    archive_path = folder_item.get("archivePath", "")
    folder_name = archive_path.split("/")[-1] if archive_path else "folder"

    account = Database.fetchone(
        "SELECT credentials_encrypted FROM accounts WHERE id = ?", (account_id,)
    )
    if not account:
        raise ValueError(f"Account {account_id} not found")

    client = ImapPool.acquire(account_id, account["credentials_encrypted"])
    try:
        folder_info = client.select_folder(imap_folder)
        if folder_info.get("message_count", 0) == 0:
            return

        uids = client.search(criteria="ALL", limit=0)
        folder_email_count = len(uids)

        # Yield folder start status
        yield {
            "type": "status",
            "phase": "folder",
            "message": f"Folder {folder_idx + 1} of {folder_count}: {folder_name} ({folder_email_count} emails)",
            "folderIndex": folder_idx + 1,
            "folderCount": folder_count,
        }

        for i, uid in enumerate(uids):
            try:
                raw_email = client.fetch_raw(uid)

                if not raw_email:
                    results["failed"].append({"uid": uid, "error": "Empty"})
                    yield {
                        "type": "progress",
                        "current": i + 1,
                        "total": folder_email_count,
                        "percent": int((i + 1) / folder_email_count * 100),
                        "status": "failed",
                        "subject": "(empty)",
                        "folder": folder_name,
                        "folderIndex": folder_idx + 1,
                        "folderCount": folder_count,
                        "commitPhase": "folders",
                    }
                    continue

                metadata = parse_email_metadata(raw_email)
                subject = (metadata.get("subject", "") or "(no subject)")[:50]
                message_id = _effective_message_id(metadata.get("message_id", ""), raw_email)

                if _check_duplicate(target_folder_id, message_id, raw_email):
                    results["skipped"].append({"uid": uid})
                    yield {
                        "type": "progress",
                        "current": i + 1,
                        "total": folder_email_count,
                        "percent": int((i + 1) / folder_email_count * 100),
                        "status": "skipped",
                        "subject": subject,
                        "folder": folder_name,
                        "folderIndex": folder_idx + 1,
                        "folderCount": folder_count,
                        "commitPhase": "folders",
                    }
                    continue

                safe_id = f"{account_id}_{_safe_uid(uid)}"
                _save_email_to_archive(raw_email, target_folder_id, account_id, safe_id)
                results["success"].append(uid)

                # Commit every 10 emails for durability
                if (i + 1) % 10 == 0:
                    Database.commit()

                yield {
                    "type": "progress",
                    "current": i + 1,
                    "total": folder_email_count,
                    "percent": int((i + 1) / folder_email_count * 100),
                    "status": "success",
                    "subject": subject,
                    "folder": folder_name,
                    "folderIndex": folder_idx + 1,
                    "folderCount": folder_count,
                    "commitPhase": "folders",
                }
            except Exception as e:
                results["failed"].append({"uid": uid, "error": str(e)})
                yield {
                    "type": "progress",
                    "current": i + 1,
                    "total": folder_email_count,
                    "percent": int((i + 1) / folder_email_count * 100),
                    "status": "failed",
                    "subject": "(error)",
                    "folder": folder_name,
                    "error": str(e),
                    "folderIndex": folder_idx + 1,
                    "folderCount": folder_count,
                    "commitPhase": "folders",
                }
    finally:
        client.release()


def apply_email_action(client, action: str, uid: str, source_folder: str, is_gmail: bool) -> None:
    """Apply one post-commit action to one message on the IMAP server.

    The single dispatcher for post-commit server actions, used by the live
    /api/commit/stream workflow (progress_commit.py). Keep provider-aware
    routing HERE — a previous version duplicated this logic per call site
    and the Gmail-aware delete ended up wired into a function nothing called.

    Caller contract: ``source_folder`` must be SELECTed before calling. On
    the Gmail delete path this function re-selects it itself, because
    delete_email_via_trash changes the selected folder; callers iterating
    multiple UIDs therefore stay correct without re-selecting.

    Raises IMAPError on failure (propagated from the client methods).
    """
    if action == "archive":
        client.archive_email(uid)
    elif action == "trash":
        client.trash_email(uid)
    elif action == "delete":
        if is_gmail:
            # delete_email_via_trash changes the selected folder; re-select
            # the source before each message.
            client.select_folder(source_folder)
            client.delete_email_via_trash(uid, source_folder)
        else:
            client.delete_email(uid)


def build_commit_summary(results: dict) -> str:
    """Build a human-readable summary message from commit results."""
    msg_parts = []

    if results["success"]:
        count = len(results["success"])
        msg_parts.append(f"{count} email{'s' if count != 1 else ''} filed")
    if results["folders_success"]:
        count = results["folders_success"]
        msg_parts.append(f"{count} folder{'s' if count != 1 else ''} archived")
    if results["skipped"]:
        count = len(results["skipped"])
        msg_parts.append(f"{count} skipped (duplicate{'s' if count != 1 else ''})")
    if results["failed"] or results["folders_failed"]:
        fail_count = len(results["failed"]) + results["folders_failed"]
        msg_parts.append(f"{fail_count} failed")
    if results["post_actions"]["success"]:
        by_action = results["post_actions"].get("by_action", {})
        action_parts = []
        for act, cnt in by_action.items():
            if cnt > 0:
                verb = {"archive": "archived", "trash": "trashed", "delete": "deleted"}.get(
                    act, act
                )
                action_parts.append(f"{cnt} {verb}")
        if action_parts:
            msg_parts.append(", ".join(action_parts) + " on server")
        else:
            count = results["post_actions"]["success"]
            msg_parts.append(f"{count} updated on server")
    if results["post_actions"]["failed"]:
        count = results["post_actions"]["failed"]
        msg_parts.append(
            f"{count} server update{'s' if count != 1 else ''} failed — your emails are archived safely, but you may need to remove them from the server manually"
        )
    if results["post_actions"].get("skipped_folders"):
        count = results["post_actions"]["skipped_folders"]
        msg_parts.append(
            f"{count} folder{'s' if count != 1 else ''} left untouched on the server because some emails could not be archived — nothing was removed"
        )

    return ". ".join(msg_parts) + "." if msg_parts else "Nothing committed."
