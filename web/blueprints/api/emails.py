"""
MailRepo API - Email Routes

Handles search and archived email retrieval endpoints.
"""

import time

from flask import jsonify, request

from core import Config, Database, Encryption
from core.database import build_fts_match
from core.message_view import attachment_at, view_fields
from utils.log import get_logger
from web.responses import attachment_response, eml_download

from . import api_bp
from .email_parser import decode_email_header, extract_body_text
from .folders import tree_email_counts

log = get_logger()


def _get_folder_and_descendants(folder_id: int) -> list[int]:
    """Get a folder ID and all its descendant folder IDs."""
    all_folders = Database.fetchall("SELECT id, parent_id FROM folders WHERE deleted_at IS NULL")
    folder_map = {}
    for f in all_folders:
        parent = f["parent_id"]
        if parent not in folder_map:
            folder_map[parent] = []
        folder_map[parent].append(f["id"])

    result = [folder_id]
    queue = [folder_id]
    while queue:
        current = queue.pop()
        children = folder_map.get(current, [])
        result.extend(children)
        queue.extend(children)
    return result


@api_bp.route("/search", methods=["GET"])
def search_emails():
    """Search archived emails using full-text search."""
    query = request.args.get("q", "").strip()
    folder_id = request.args.get("folder_id")
    limit = int(request.args.get("limit", 50))
    # When a folder is selected, decide whether to also search its descendants.
    # Defaults to True to preserve previous behavior.
    include_subfolders_arg = request.args.get("include_subfolders", "true").lower()
    include_subfolders = include_subfolders_arg not in ("0", "false", "no")

    if not query:
        return jsonify({"error": "Search query is required"}), 400

    fts_query = build_fts_match(query)
    if fts_query is None:
        # Nothing searchable in the input (e.g. "-", "..."): no matches.
        return jsonify({"results": [], "count": 0, "query": query})

    if folder_id:
        # Either the folder alone, or the folder + all descendants
        if include_subfolders:
            folder_ids = _get_folder_and_descendants(int(folder_id))
        else:
            folder_ids = [int(folder_id)]
        placeholders = ",".join("?" * len(folder_ids))
        results = Database.fetchall(
            f"""
            SELECT m.id, m.folder_id, m.subject, m.sender, m.date, m.flagged_at, f.name as folder_name
            FROM messages m
            JOIN messages_fts fts ON m.id = fts.rowid
            JOIN folders f ON m.folder_id = f.id
            WHERE messages_fts MATCH ? AND m.folder_id IN ({placeholders}) AND m.deleted_at IS NULL
            ORDER BY m.date DESC
            LIMIT ?
            """,
            (fts_query, *folder_ids, limit),
        )
    else:
        results = Database.fetchall(
            """
            SELECT m.id, m.folder_id, m.subject, m.sender, m.date, m.flagged_at, f.name as folder_name
            FROM messages m
            JOIN messages_fts fts ON m.id = fts.rowid
            JOIN folders f ON m.folder_id = f.id
            WHERE messages_fts MATCH ? AND m.deleted_at IS NULL
            ORDER BY m.date DESC
            LIMIT ?
            """,
            (fts_query, limit),
        )

    # Build folder path map from a single query (avoids N+1 per result)
    all_folders = Database.fetchall(
        "SELECT id, name, parent_id FROM folders WHERE deleted_at IS NULL"
    )
    folder_map = {f["id"]: f for f in all_folders}

    def get_folder_path(fid):
        """Build full folder path from folder_id using in-memory map."""
        path_parts = []
        current_id = fid
        seen = set()
        while current_id and current_id not in seen:
            seen.add(current_id)
            folder = folder_map.get(current_id)
            if not folder:
                break
            path_parts.insert(0, folder["name"])
            current_id = folder["parent_id"]
        return " › ".join(path_parts) if path_parts else ""

    emails = [
        {
            "id": r["id"],
            "folder_id": r["folder_id"],
            "folder_name": r["folder_name"],
            "folder_path": get_folder_path(r["folder_id"]),
            "subject": r["subject"],
            "sender": r["sender"],
            "date": r["date"],
            "flagged_at": r["flagged_at"],
        }
        for r in results
    ]

    return jsonify({"query": query, "count": len(emails), "emails": emails})


@api_bp.route("/folders/<int:folder_id>/emails", methods=["GET"])
def get_folder_emails(folder_id):
    """Get all emails in an archive folder.

    Also returns a count for each direct subfolder, so a folder whose mail
    is all filed one level down can say so instead of looking empty. The
    subfolder numbers are tree totals and add up to the folder's own total.
    """
    folder = Database.fetchone("SELECT id FROM folders WHERE id = ?", (folder_id,))
    if not folder:
        return jsonify({"error": "Folder not found"}), 404

    messages = Database.fetchall(
        """
        SELECT id, subject, sender, date, filepath, flagged_at
        FROM messages WHERE folder_id = ? AND deleted_at IS NULL
        ORDER BY date DESC
        """,
        (folder_id,),
    )

    emails = [
        {
            "id": m["id"],
            "subject": m["subject"],
            "sender": m["sender"],
            "date": m["date"],
            "flagged_at": m["flagged_at"],
        }
        for m in messages
    ]

    counts = tree_email_counts()
    subfolder_counts = {
        str(child["id"]): counts.get(child["id"], 0)
        for child in Database.fetchall(
            "SELECT id FROM folders WHERE parent_id = ? AND deleted_at IS NULL",
            (folder_id,),
        )
    }

    return jsonify({"emails": emails, "subfolder_counts": subfolder_counts})


def _decode_header(header):
    """Decode an email header value. Delegates to email_parser."""
    return decode_email_header(header)


@api_bp.route("/folders/<int:folder_id>/emails/<int:message_id>", methods=["GET"])
def get_archived_email(folder_id, message_id):
    """Get a single archived email with full content."""
    message = Database.fetchone(
        """
        SELECT id, folder_id, subject, sender, date, filepath, flagged_at
        FROM messages WHERE id = ? AND folder_id = ?
        """,
        (message_id, folder_id),
    )
    if not message:
        return jsonify({"error": "Message not found"}), 404

    filepath = Config.get_base_path() / message["filepath"]
    if not filepath.exists():
        return jsonify({"error": "Email file not found"}), 404

    try:
        raw_bytes = Encryption.decrypt(filepath.read_bytes())
        result = {
            "id": message["id"],
            "flagged_at": message["flagged_at"],
            **view_fields(raw_bytes),
        }
        return jsonify({"email": result})
    except Exception as e:
        return jsonify({"error": f"Failed to read email: {e}"}), 500


@api_bp.route("/messages/<int:message_id>", methods=["DELETE"])
def delete_message(message_id):
    """Soft-delete a message (move to trash).

    Detaches the message from its folder by moving folder_id ->
    original_folder_id, then setting folder_id to NULL. This ensures
    that if the original folder is later permanently deleted, the
    cascade won't take this individually-trashed message with it.
    The user sees the email's original location preserved via
    original_folder_id; restore reads from that.
    """
    message = Database.fetchone("SELECT id, folder_id FROM messages WHERE id = ?", (message_id,))
    if not message:
        return jsonify({"error": "Message not found"}), 404

    now = int(time.time())
    Database.execute(
        """
        UPDATE messages
        SET deleted_at = ?,
            original_folder_id = folder_id,
            folder_id = NULL
        WHERE id = ?
        """,
        (now, message_id),
    )
    Database.commit()
    return jsonify({"success": True})


@api_bp.route("/messages/<int:message_id>/restore", methods=["POST"])
def restore_message(message_id):
    """Restore a message from trash.

    Re-attaches the message to its original folder by moving
    original_folder_id -> folder_id, then clearing original_folder_id
    and deleted_at.

    If the original folder no longer exists or is itself trashed, the
    caller can pass {"folder_id": N} in the body to specify an alternate
    destination. If neither is available, returns 409 so the frontend
    can prompt the user.
    """
    message = Database.fetchone(
        "SELECT id, deleted_at, original_folder_id FROM messages WHERE id = ?", (message_id,)
    )
    if not message:
        return jsonify({"error": "Message not found"}), 404
    if not message["deleted_at"]:
        return jsonify({"error": "Message is not in trash"}), 400

    # Caller may override the destination (used when the original folder
    # is gone or trashed and the user picks elsewhere from a modal).
    data = request.get_json(silent=True) or {}
    requested_dest = data.get("folder_id")

    destination_id = None
    if requested_dest is not None:
        dest = Database.fetchone(
            "SELECT id FROM folders WHERE id = ? AND deleted_at IS NULL", (requested_dest,)
        )
        if not dest:
            return jsonify({"error": "Destination folder not found or in trash"}), 400
        destination_id = dest["id"]
    elif message["original_folder_id"] is not None:
        # Try the original folder; only use it if it still exists and is alive
        dest = Database.fetchone(
            "SELECT id FROM folders WHERE id = ? AND deleted_at IS NULL",
            (message["original_folder_id"],),
        )
        if dest:
            destination_id = dest["id"]

    if destination_id is None:
        # Original is gone (or trashed) and caller didn't pick. Frontend
        # should present a folder picker.
        return jsonify(
            {
                "error": "Original folder is unavailable. Please choose a destination.",
                "needs_destination": True,
            }
        ), 409

    Database.execute(
        """
        UPDATE messages
        SET deleted_at = NULL,
            folder_id = ?,
            original_folder_id = NULL
        WHERE id = ?
        """,
        (destination_id, message_id),
    )
    Database.commit()
    return jsonify({"success": True, "folder_id": destination_id})


@api_bp.route("/messages/<int:message_id>/permanent", methods=["DELETE"])
def permanently_delete_message(message_id):
    """Permanently delete a message from trash."""
    message = Database.fetchone(
        "SELECT id, deleted_at, filepath FROM messages WHERE id = ?", (message_id,)
    )
    if not message:
        return jsonify({"error": "Message not found"}), 404
    if not message["deleted_at"]:
        return jsonify({"error": "Message must be in trash before permanent deletion"}), 400

    # Delete the email file
    try:
        filepath = Config.get_base_path() / message["filepath"]
        if filepath.exists():
            filepath.unlink()
    except Exception as e:
        log.warning(f"Could not delete file {message['filepath']}: {e}")

    Database.execute("DELETE FROM messages WHERE id = ?", (message_id,))
    Database.commit()
    return jsonify({"success": True})


@api_bp.route("/messages/<int:message_id>/flag", methods=["PATCH"])
def flag_message(message_id):
    """Set or clear the flagged_at timestamp on a message.

    Body: {"flagged": true} sets flagged_at to now; {"flagged": false}
    clears it. Returns the resulting flagged_at value (timestamp or null)
    so the frontend can sync local state without re-fetching."""
    message = Database.fetchone("SELECT id FROM messages WHERE id = ?", (message_id,))
    if not message:
        return jsonify({"error": "Message not found"}), 404

    data = request.get_json(silent=True) or {}
    if "flagged" not in data:
        return jsonify({"error": "Body must include 'flagged' (true or false)"}), 400

    if data["flagged"]:
        now = int(time.time())
        Database.execute("UPDATE messages SET flagged_at = ? WHERE id = ?", (now, message_id))
        Database.commit()
        return jsonify({"flagged_at": now})
    else:
        Database.execute("UPDATE messages SET flagged_at = NULL WHERE id = ?", (message_id,))
        Database.commit()
        return jsonify({"flagged_at": None})


@api_bp.route("/messages/flagged", methods=["GET"])
def get_flagged_emails():
    """Return all flagged messages across the archive.

    Excludes trashed messages (deleted_at IS NULL). Sorted by flagged_at DESC
    so the most-recently-flagged appear first. Each result includes the
    folder_name and a computed folder_path so the user can see where
    in the archive each flagged email lives."""
    messages = Database.fetchall(
        """
        SELECT m.id, m.subject, m.sender, m.date, m.flagged_at, m.folder_id,
               f.name AS folder_name
        FROM messages m
        JOIN folders f ON m.folder_id = f.id
        WHERE m.flagged_at IS NOT NULL
          AND m.deleted_at IS NULL
          AND f.deleted_at IS NULL
        ORDER BY m.flagged_at DESC
        """,
        (),
    )

    # Build a folder-path map once (avoid N+1 per result)
    all_folders = Database.fetchall(
        "SELECT id, name, parent_id FROM folders WHERE deleted_at IS NULL"
    )
    folder_map = {f["id"]: f for f in all_folders}

    def get_folder_path(fid):
        path_parts = []
        current_id = fid
        seen = set()
        while current_id and current_id not in seen:
            seen.add(current_id)
            folder = folder_map.get(current_id)
            if not folder:
                break
            path_parts.insert(0, folder["name"])
            current_id = folder["parent_id"]
        return " › ".join(path_parts) if path_parts else ""

    emails = [
        {
            "id": m["id"],
            "subject": m["subject"],
            "sender": m["sender"],
            "date": m["date"],
            "flagged_at": m["flagged_at"],
            "folder_id": m["folder_id"],
            "folder_name": m["folder_name"],
            "folder_path": get_folder_path(m["folder_id"]),
        }
        for m in messages
    ]

    return jsonify({"emails": emails})


@api_bp.route("/messages/<int:message_id>", methods=["PATCH"])
def update_message(message_id):
    """Update message properties (move to different folder)."""
    message = Database.fetchone("SELECT id, folder_id FROM messages WHERE id = ?", (message_id,))
    if not message:
        return jsonify({"error": "Message not found"}), 404

    data = request.get_json()

    if "folder_id" in data:
        new_folder_id = data["folder_id"]
        # Verify destination folder exists
        folder = Database.fetchone(
            "SELECT id FROM folders WHERE id = ? AND deleted_at IS NULL", (new_folder_id,)
        )
        if not folder:
            return jsonify({"error": "Destination folder not found"}), 404

        Database.execute(
            "UPDATE messages SET folder_id = ? WHERE id = ?", (new_folder_id, message_id)
        )
        Database.commit()

    return jsonify({"success": True})


@api_bp.route("/trash/emails", methods=["GET"])
def get_trashed_emails():
    """Get all trashed emails.

    Individually-trashed emails are now detached from their folder
    (folder_id IS NULL, original_folder_id holds the previous location).
    We expose the original location as folder_name/folder_id so the
    frontend can show 'Originally in: X' without knowing about the
    rename. The original folder may itself be trashed or deleted — the
    LEFT JOIN handles that by leaving folder_name as NULL.
    """
    messages = Database.fetchall(
        """
        SELECT m.id, m.subject, m.sender, m.date, m.deleted_at,
               m.original_folder_id AS folder_id, m.flagged_at,
               f.name AS folder_name, f.deleted_at AS folder_deleted_at
        FROM messages m
        LEFT JOIN folders f ON m.original_folder_id = f.id
        WHERE m.deleted_at IS NOT NULL
        ORDER BY m.deleted_at DESC
        """,
        (),
    )

    emails = [
        {
            "id": m["id"],
            "subject": m["subject"],
            "sender": m["sender"],
            "date": m["date"],
            "deleted_at": m["deleted_at"],
            "folder_id": m["folder_id"],
            "folder_name": m["folder_name"],
            # True if the original folder is itself in trash or gone, which
            # affects the restore flow (user will need to pick a destination)
            "original_folder_unavailable": (
                m["folder_id"] is None or m["folder_deleted_at"] is not None
            ),
            "flagged_at": m["flagged_at"],
        }
        for m in messages
    ]

    return jsonify({"emails": emails})


@api_bp.route("/folders/<int:folder_id>/emails/<int:message_id>/download", methods=["GET"])
def download_archived_email(folder_id, message_id):
    """Download an archived email as .eml file."""
    message = Database.fetchone(
        """
        SELECT id, folder_id, subject, filepath
        FROM messages WHERE id = ? AND folder_id = ?
        """,
        (message_id, folder_id),
    )
    if not message:
        return jsonify({"error": "Message not found"}), 404

    filepath = Config.get_base_path() / message["filepath"]
    if not filepath.exists():
        return jsonify({"error": "Email file not found"}), 404

    try:
        raw_bytes = filepath.read_bytes()
        raw_bytes = Encryption.decrypt(raw_bytes)

        # Clean subject for filename
        subject = message["subject"] or "email"
        safe_filename = (
            "".join(c for c in subject if c.isalnum() or c in " -_")[:50].strip() or "email"
        )
        filename = f"{safe_filename}.eml"

        return eml_download(raw_bytes, filename)
    except Exception as e:
        return jsonify({"error": f"Failed to read email: {e}"}), 500


@api_bp.route(
    "/folders/<int:folder_id>/emails/<int:message_id>/attachments/<int:index>", methods=["GET"]
)
def download_archived_attachment(folder_id, message_id, index):
    """Download an attachment from an archived email."""
    message = Database.fetchone(
        """
        SELECT id, folder_id, filepath
        FROM messages WHERE id = ? AND folder_id = ?
        """,
        (message_id, folder_id),
    )
    if not message:
        return jsonify({"error": "Message not found"}), 404

    filepath = Config.get_base_path() / message["filepath"]
    if not filepath.exists():
        return jsonify({"error": "Email file not found"}), 404

    try:
        # The same list the viewer route reported, so the index that was
        # clicked is the file that is served (core/message_view.py).
        att = attachment_at(Encryption.decrypt(filepath.read_bytes()), index)
        if att is None:
            return jsonify({"error": "Attachment not found"}), 404

        # Inline only for a short list of inert types; see web/responses.py.
        view_inline = request.args.get("view") == "1"
        return attachment_response(
            att["payload"], att["content_type"], att["filename"], inline=view_inline
        )
    except Exception as e:
        return jsonify({"error": f"Failed to read attachment: {e}"}), 500


@api_bp.route("/folders/<int:folder_id>/emails/<int:message_id>/source", methods=["GET"])
def get_archived_email_source(folder_id, message_id):
    """Get raw source of an archived email."""
    message = Database.fetchone(
        """
        SELECT id, folder_id, filepath
        FROM messages WHERE id = ? AND folder_id = ?
        """,
        (message_id, folder_id),
    )
    if not message:
        return jsonify({"error": "Message not found"}), 404

    filepath = Config.get_base_path() / message["filepath"]
    if not filepath.exists():
        return jsonify({"error": "Email file not found"}), 404

    try:
        raw_bytes = filepath.read_bytes()
        raw_bytes = Encryption.decrypt(raw_bytes)

        # Try to decode as text, fallback to latin-1 if UTF-8 fails
        try:
            source = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            source = raw_bytes.decode("latin-1")

        return jsonify({"source": source})
    except Exception as e:
        return jsonify({"error": f"Failed to read email source: {e}"}), 500


# Bumped whenever extract_body_text changes what it produces, so that
# existing archives are re-read once and search sees the improvement.
#   2: HTML entities decoded; limit raised from 10,000 to 200,000 chars.
SEARCH_INDEX_VERSION = "2"


class _ReindexAborted(Exception):
    pass


def reindex_all(should_continue=None) -> tuple[int, int]:
    """Re-extract search text for every archived message.

    Returns ``(updated, errors)``. Only rows whose text actually changes
    are written. ``should_continue`` is polled between messages; when it
    returns False the run stops (raising _ReindexAborted) with whatever
    it had done already committed.
    """
    messages = Database.fetchall(
        "SELECT id, filepath, body_text FROM messages WHERE deleted_at IS NULL", ()
    )
    updated = 0
    errors = 0
    for n, msg in enumerate(messages, 1):
        if should_continue is not None and not should_continue():
            raise _ReindexAborted()
        try:
            filepath = Config.get_base_path() / msg["filepath"]
            if not filepath.exists():
                errors += 1
                continue
            body_text = extract_body_text(Encryption.decrypt(filepath.read_bytes()))
            if body_text != (msg["body_text"] or ""):
                # The messages_au trigger keeps the FTS index in step.
                Database.execute(
                    "UPDATE messages SET body_text = ? WHERE id = ?", (body_text, msg["id"])
                )
                updated += 1
        except Exception as e:
            log.warning(f"Failed to reindex message {msg['id']}: {e}")
            errors += 1
        if n % 200 == 0:
            Database.commit()
    Database.commit()
    return updated, errors


def start_reindex_if_needed() -> bool:
    """After login: bring an older archive's search text up to date, once.

    Runs in the background under idle.busy, so the idle lock waits for
    it. Returns True if a run was started. If it is cut short (logout,
    quit) nothing is recorded and the next login starts it again.
    """
    import threading

    from core.database import get_setting, set_setting
    from web import idle

    if get_setting("search_index_version", "1") == SEARCH_INDEX_VERSION:
        return False
    if Database.fetchone("SELECT 1 FROM messages LIMIT 1") is None:
        set_setting("search_index_version", SEARCH_INDEX_VERSION)
        return False

    login_id = idle.current_login_id()

    def still_this_session() -> bool:
        return Encryption.is_unlocked() and idle.current_login_id() == login_id

    def work():
        try:
            updated, errors = reindex_all(still_this_session)
            if still_this_session():
                set_setting("search_index_version", SEARCH_INDEX_VERSION)
                log.info(f"Search index brought up to date: {updated} updated, {errors} errors")
        except _ReindexAborted:
            log.info("Search reindex stopped early; it will resume at the next login")
        except Exception as e:  # noqa: BLE001 - background housekeeping must not crash
            log.warning(f"Search reindex failed: {e}")

    threading.Thread(
        target=idle.run_busy, args=("reindex", work), daemon=True, name="search-reindex"
    ).start()
    return True


@api_bp.route("/search/reindex", methods=["POST"])
def reindex_search():
    """Rebuild FTS index by re-extracting body text from archived .eml files."""
    try:
        updated, errors = reindex_all()

        # Rebuild FTS index
        Database.execute("INSERT INTO messages_fts(messages_fts) VALUES('rebuild')", ())
        Database.commit()

        return jsonify(
            {
                "message": f"Reindexed {updated} emails ({errors} errors)",
                "updated": updated,
                "errors": errors,
            }
        )
    except Exception as e:
        return jsonify({"error": f"Reindex failed: {e}"}), 500
