"""
MailRepo API - Commit Workflow

Handles committing staged emails and folders to the archive.
Supports post-commit actions (archive, trash, delete) for IMAP emails.
"""

from core import Database
from core import IMAP, IMAPError
from core import Config
from core import Encryption
from .email_parser import (
    get_emails_from_import_folder,
    get_raw_email_from_import,
    extract_body_text,
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
    
    parts = archive_path.split('/')
    current_parent_id = parent_folder_id
    
    for part in parts:
        part = part.strip()
        if not part:
            continue
            
        # Check if folder already exists
        existing = Database.fetchone(
            "SELECT id FROM folders WHERE name = ? AND parent_id = ? AND deleted_at IS NULL",
            (part, current_parent_id)
        )
        
        if existing:
            current_parent_id = existing["id"]
        else:
            # Create new folder
            cursor = Database.execute(
                "INSERT INTO folders (name, parent_id) VALUES (?, ?)",
                (part, current_parent_id)
            )
            current_parent_id = cursor.lastrowid
            # Commit immediately so subsequent lookups can find this folder
            Database.commit()
    
    return current_parent_id


def _check_duplicate(folder_id: int, message_id: str) -> bool:
    """Check if an email with this message_id already exists in the folder."""
    if not message_id:
        return False
    existing = Database.fetchone(
        "SELECT id FROM messages WHERE folder_id = ? AND message_id = ?",
        (folder_id, message_id)
    )
    return existing is not None


def _save_email_to_archive(raw_email: bytes, folder_id: int, account_id: int | None,
                           uid_prefix: str) -> None:
    """
    Encrypt and save a raw email to the archive, inserting a DB row.
    
    Args:
        raw_email: Raw RFC 2822 email bytes.
        folder_id: Destination archive folder ID.
        account_id: Source IMAP account ID (None for imports).
        uid_prefix: Safe filename prefix (e.g. "import_mbox-3" or "2_145").
    """
    metadata = parse_email_metadata(raw_email)
    body_text = extract_body_text(raw_email)

    archive_path = Config.get_archive_path() / str(folder_id)
    archive_path.mkdir(parents=True, exist_ok=True)

    encrypted_data = Encryption.encrypt(raw_email)
    filepath = archive_path / f"{uid_prefix}.eml.enc"
    filepath.write_bytes(encrypted_data)

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
        )
    )


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
        folder = Database.fetchone(
            "SELECT id FROM folders WHERE id = ?", (folder_id,)
        )
        if not folder:
            raise ValueError(f"Folder {folder_id} not found")
        
        # Check for duplicate
        message_id = email_data.get("message_id", "")
        if _check_duplicate(folder_id, message_id):
            results["skipped"].append({"uid": uid, "reason": "duplicate", "subject": subject})
            return {"status": "skipped", "subject": subject, "uid": uid}

        # Get raw email from source file
        source_path = email_data.get("sourcePath")
        if not source_path:
            raise ValueError("No source path for imported email")
        
        raw_email = get_raw_email_from_import(source_path, uid)
        if not raw_email:
            raise ValueError("Could not retrieve email content")
        
        safe_id = f"import_{uid.replace('/', '_').replace(':', '_')}"
        _save_email_to_archive(raw_email, folder_id, None, safe_id)
        
        results["success"].append(uid)
        return {"status": "success", "subject": subject, "uid": uid}
        
    except Exception as e:
        results["failed"].append({"uid": uid, "error": str(e)})
        return {"status": "failed", "subject": subject, "uid": uid, "error": str(e)}


def commit_imap_email(client, account_id: int, email_data: dict, folder_id: int, 
                      source_folder: str, results: dict, committed_emails: dict) -> dict:
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
        folder = Database.fetchone(
            "SELECT id FROM folders WHERE id = ?", (folder_id,)
        )
        if not folder:
            raise ValueError(f"Folder {folder_id} not found")
        
        # Check for duplicate
        message_id = email_data.get("message_id", "")
        if _check_duplicate(folder_id, message_id):
            results["skipped"].append({"uid": uid, "reason": "duplicate", "subject": subject})
            return {"status": "skipped", "subject": subject, "uid": uid}
        
        # Fetch and save email
        raw_email = client.fetch_raw(uid)
        safe_id = f"{account_id}_{uid}"
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


def commit_import_folder(folder_item: dict, target_folder_id: int, folder_idx: int, 
                         folder_count: int, results: dict):
    """
    Generator that commits all emails from an import folder.
    
    Yields progress events for each email.
    """
    import_path = folder_item.get("importPath")
    folder_path = folder_item.get("folder")
    import_type = folder_item.get("importType", "apple-mbox")
    archive_path = folder_item.get("archivePath", "")
    folder_name = archive_path.split('/')[-1] if archive_path else "folder"
    
    emails = get_emails_from_import_folder(import_path, folder_path, import_type)
    folder_email_count = len(emails)

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
                "percent": int((i + 1) / folder_email_count * 100) if folder_email_count > 0 else 100,
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
                "percent": int((i + 1) / folder_email_count * 100) if folder_email_count > 0 else 100,
                "status": "failed",
                "subject": "(error)",
                "folder": folder_name,
                "error": str(e),
                "folderIndex": folder_idx + 1,
                "folderCount": folder_count,
                "commitPhase": "folders",
            }


def commit_imap_folder(folder_item: dict, target_folder_id: int, folder_idx: int,
                       folder_count: int, results: dict):
    """
    Generator that commits all emails from an IMAP folder.
    
    Yields progress events for each email.
    """
    account_id = folder_item.get("accountId")
    imap_folder = folder_item.get("folder")
    archive_path = folder_item.get("archivePath", "")
    folder_name = archive_path.split('/')[-1] if archive_path else "folder"
    
    account = Database.fetchone(
        "SELECT credentials_encrypted FROM accounts WHERE id = ?", (account_id,)
    )
    if not account:
        raise ValueError(f"Account {account_id} not found")
    
    client = IMAP.connect_with_credentials(account["credentials_encrypted"])
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
                message_id = metadata.get("message_id", "")
                
                if _check_duplicate(target_folder_id, message_id):
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
                
                safe_id = f"{account_id}_{uid}"
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
        client.disconnect()


def apply_post_commit_actions(committed_emails: dict, source_actions: dict, results: dict):
    """
    Apply post-commit actions (archive, trash, delete) on IMAP server.
    
    Args:
        committed_emails: Dict of {account_id: {folder: [(uid, dest_folder_id), ...]}}
        source_actions: Dict of action keys to action type
        results: Results dict with post_actions counters
    
    Yields status events.
    """
    if not committed_emails or not source_actions:
        return
    
    yield {
        "type": "status",
        "phase": "post_actions",
        "message": "Applying post-commit actions on server...",
    }
    
    for account_id, folders_data in committed_emails.items():
        account = Database.fetchone(
            "SELECT id, credentials_encrypted FROM accounts WHERE id = ?",
            (account_id,)
        )
        if not account or not account["credentials_encrypted"]:
            continue
        
        client = None
        try:
            client = IMAP.connect_with_credentials(account["credentials_encrypted"])
            
            for source_folder, email_list in folders_data.items():
                action = _find_action_for_source(source_actions, account_id, source_folder)
                
                if not action or action == 'leave':
                    continue
                
                try:
                    client.select_folder(source_folder)

                    for uid, dest_folder_id in email_list:
                        try:
                            if action == 'archive':
                                client.archive_email(uid)
                                results["post_actions"]["success"] += 1
                            elif action == 'trash':
                                client.trash_email(uid)
                                results["post_actions"]["success"] += 1
                            elif action == 'delete':
                                client.delete_email(uid)
                                results["post_actions"]["success"] += 1
                        except IMAPError:
                            results["post_actions"]["failed"] += 1
                except IMAPError:
                    results["post_actions"]["failed"] += len(email_list)
        
        except Exception:
            for folder_emails in folders_data.values():
                results["post_actions"]["failed"] += len(folder_emails)
        finally:
            if client:
                try:
                    client.disconnect()
                except:
                    pass


def _find_action_for_source(source_actions: dict, account_id: int, source_folder: str) -> str | None:
    """
    Find the action for a specific source folder.
    
    Source action keys can be in various formats:
    - "account:1:5" (account:account_id:dest_folder_id)
    - "account:1:INBOX:5" (account:account_id:source_folder:dest_folder_id)
    """
    for key, action in source_actions.items():
        if not key.startswith(f"account:{account_id}"):
            continue
        
        parts = key.split(':')
        if len(parts) == 3:
            # "account:1:5" format - applies to all folders for this dest
            return action
        elif len(parts) >= 4:
            # "account:1:INBOX:5" format (folder name may contain colons)
            folder_part = ':'.join(parts[2:-1])
            if folder_part == source_folder:
                return action
    
    return None


def build_commit_summary(results: dict) -> str:
    """Build a human-readable summary message from commit results."""
    msg_parts = []
    
    if results["success"]:
        msg_parts.append(f"{len(results['success'])} emails filed")
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
        count = results["post_actions"]["success"]
        msg_parts.append(f"{count} server action{'s' if count != 1 else ''} applied")
    if results["post_actions"]["failed"]:
        count = results["post_actions"]["failed"]
        msg_parts.append(f"{count} server action{'s' if count != 1 else ''} failed")
    
    return ". ".join(msg_parts) + "." if msg_parts else "Nothing committed."
