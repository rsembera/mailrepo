"""
MailRepo API - Email Routes

Handles search and archived email retrieval endpoints.
"""

import base64
import time
import email as email_lib
from flask import request, jsonify, Response
from core import Database
from core import Config
from core import Encryption
from utils.log import get_logger
from .email_parser import decode_email_header, extract_body_text
from . import api_bp

log = get_logger()


@api_bp.route("/search", methods=["GET"])
def search_emails():
    """Search archived emails using full-text search."""
    query = request.args.get("q", "").strip()
    folder_id = request.args.get("folder_id")
    limit = int(request.args.get("limit", 50))
    
    if not query:
        return jsonify({"error": "Search query is required"}), 400
    
    fts_query = query.replace('"', '""')
    
    if folder_id:
        results = Database.fetchall(
            """
            SELECT m.id, m.folder_id, m.subject, m.sender, m.date, f.name as folder_name
            FROM messages m
            JOIN messages_fts fts ON m.id = fts.rowid
            JOIN folders f ON m.folder_id = f.id
            WHERE messages_fts MATCH ? AND m.folder_id = ? AND m.deleted_at IS NULL
            ORDER BY m.date DESC
            LIMIT ?
            """,
            (fts_query, folder_id, limit)
        )
    else:
        results = Database.fetchall(
            """
            SELECT m.id, m.folder_id, m.subject, m.sender, m.date, f.name as folder_name
            FROM messages m
            JOIN messages_fts fts ON m.id = fts.rowid
            JOIN folders f ON m.folder_id = f.id
            WHERE messages_fts MATCH ? AND m.deleted_at IS NULL
            ORDER BY m.date DESC
            LIMIT ?
            """,
            (fts_query, limit)
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

    emails = [{
        "id": r["id"],
        "folder_id": r["folder_id"],
        "folder_name": r["folder_name"],
        "folder_path": get_folder_path(r["folder_id"]),
        "subject": r["subject"],
        "sender": r["sender"],
        "date": r["date"],
    } for r in results]
    
    return jsonify({"query": query, "count": len(emails), "emails": emails})


@api_bp.route("/folders/<int:folder_id>/emails", methods=["GET"])
def get_folder_emails(folder_id):
    """Get all emails in an archive folder."""
    folder = Database.fetchone("SELECT id FROM folders WHERE id = ?", (folder_id,))
    if not folder:
        return jsonify({"error": "Folder not found"}), 404
    
    messages = Database.fetchall(
        """
        SELECT id, subject, sender, date, filepath
        FROM messages WHERE folder_id = ? AND deleted_at IS NULL
        ORDER BY date DESC
        """,
        (folder_id,)
    )
    
    emails = [{
        "id": m["id"],
        "subject": m["subject"],
        "sender": m["sender"],
        "date": m["date"],
    } for m in messages]
    
    return jsonify({"emails": emails})


def _decode_header(header):
    """Decode an email header value. Delegates to email_parser."""
    return decode_email_header(header)


@api_bp.route("/folders/<int:folder_id>/emails/<int:message_id>", methods=["GET"])
def get_archived_email(folder_id, message_id):
    """Get a single archived email with full content."""
    message = Database.fetchone(
        """
        SELECT id, folder_id, subject, sender, date, filepath
        FROM messages WHERE id = ? AND folder_id = ?
        """,
        (message_id, folder_id)
    )
    if not message:
        return jsonify({"error": "Message not found"}), 404
    
    filepath = Config.get_base_path() / message["filepath"]
    if not filepath.exists():
        return jsonify({"error": "Email file not found"}), 404

    try:
        raw_bytes = filepath.read_bytes()
        raw_bytes = Encryption.decrypt(raw_bytes)
        msg = email_lib.message_from_bytes(raw_bytes)
        
        result = {
            "id": message["id"],
            "subject": _decode_header(msg.get("Subject", "")),
            "from": _decode_header(msg.get("From", "")),
            "to": _decode_header(msg.get("To", "")),
            "cc": _decode_header(msg.get("Cc", "")),
            "date": msg.get("Date", ""),
            "text_body": None,
            "html_body": None,
            "attachments": [],
        }
        
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))
                filename = part.get_filename()
                content_id = part.get("Content-ID")
                
                # Skip inline images that are embedded in HTML body (have Content-ID)
                # These are displayed within the email via cid: references, not as separate attachments
                if content_id:
                    continue
                
                # Treat as attachment if explicitly marked as attachment,
                # OR if it has a filename (even if inline) and isn't text
                if "attachment" in content_disposition or (filename and part.get_content_maintype() != "text"):
                    if filename:
                        result["attachments"].append({
                            "filename": _decode_header(filename),
                            "content_type": content_type,
                            "size": len(part.get_payload(decode=True) or b""),
                        })
                    continue
                
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    body = payload.decode(charset, errors="replace")
                    if content_type == "text/plain" and not result["text_body"]:
                        result["text_body"] = body
                    elif content_type == "text/html" and not result["html_body"]:
                        result["html_body"] = body
        else:
            content_type = msg.get_content_type()
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                body = payload.decode(charset, errors="replace")
                if content_type == "text/html":
                    result["html_body"] = body
                else:
                    result["text_body"] = body
        
        return jsonify({"email": result})
    except Exception as e:
        return jsonify({"error": f"Failed to read email: {e}"}), 500


@api_bp.route("/messages/<int:message_id>", methods=["DELETE"])
def delete_message(message_id):
    """Soft-delete a message (move to trash)."""
    message = Database.fetchone("SELECT id FROM messages WHERE id = ?", (message_id,))
    if not message:
        return jsonify({"error": "Message not found"}), 404
    
    now = int(time.time())
    Database.execute(
        "UPDATE messages SET deleted_at = ? WHERE id = ?",
        (now, message_id)
    )
    Database.commit()
    return jsonify({"success": True})


@api_bp.route("/messages/<int:message_id>/restore", methods=["POST"])
def restore_message(message_id):
    """Restore a message from trash."""
    message = Database.fetchone(
        "SELECT id, deleted_at FROM messages WHERE id = ?",
        (message_id,)
    )
    if not message:
        return jsonify({"error": "Message not found"}), 404
    if not message["deleted_at"]:
        return jsonify({"error": "Message is not in trash"}), 400
    
    Database.execute(
        "UPDATE messages SET deleted_at = NULL WHERE id = ?",
        (message_id,)
    )
    Database.commit()
    return jsonify({"success": True})


@api_bp.route("/messages/<int:message_id>/permanent", methods=["DELETE"])
def permanently_delete_message(message_id):
    """Permanently delete a message from trash."""
    message = Database.fetchone(
        "SELECT id, deleted_at, filepath FROM messages WHERE id = ?",
        (message_id,)
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


@api_bp.route("/messages/<int:message_id>", methods=["PATCH"])
def update_message(message_id):
    """Update message properties (move to different folder)."""
    message = Database.fetchone(
        "SELECT id, folder_id FROM messages WHERE id = ?",
        (message_id,)
    )
    if not message:
        return jsonify({"error": "Message not found"}), 404
    
    data = request.get_json()
    
    if "folder_id" in data:
        new_folder_id = data["folder_id"]
        # Verify destination folder exists
        folder = Database.fetchone(
            "SELECT id FROM folders WHERE id = ? AND deleted_at IS NULL",
            (new_folder_id,)
        )
        if not folder:
            return jsonify({"error": "Destination folder not found"}), 404
        
        Database.execute(
            "UPDATE messages SET folder_id = ? WHERE id = ?",
            (new_folder_id, message_id)
        )
        Database.commit()
    
    return jsonify({"success": True})


@api_bp.route("/trash/emails", methods=["GET"])
def get_trashed_emails():
    """Get all trashed emails."""
    messages = Database.fetchall(
        """
        SELECT m.id, m.subject, m.sender, m.date, m.deleted_at, m.folder_id, f.name as folder_name
        FROM messages m
        LEFT JOIN folders f ON m.folder_id = f.id
        WHERE m.deleted_at IS NOT NULL
        ORDER BY m.deleted_at DESC
        """,
        ()
    )
    
    emails = [{
        "id": m["id"],
        "subject": m["subject"],
        "sender": m["sender"],
        "date": m["date"],
        "deleted_at": m["deleted_at"],
        "folder_id": m["folder_id"],
        "folder_name": m["folder_name"],
    } for m in messages]
    
    return jsonify({"emails": emails})


@api_bp.route("/folders/<int:folder_id>/emails/<int:message_id>/download", methods=["GET"])
def download_archived_email(folder_id, message_id):
    """Download an archived email as .eml file."""
    message = Database.fetchone(
        """
        SELECT id, folder_id, subject, filepath
        FROM messages WHERE id = ? AND folder_id = ?
        """,
        (message_id, folder_id)
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
        safe_filename = "".join(c for c in subject if c.isalnum() or c in " -_")[:50].strip() or "email"
        filename = f"{safe_filename}.eml"
        
        return Response(
            raw_bytes,
            mimetype="message/rfc822",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    except Exception as e:
        return jsonify({"error": f"Failed to read email: {e}"}), 500


@api_bp.route("/folders/<int:folder_id>/emails/<int:message_id>/attachments/<int:index>", methods=["GET"])
def download_archived_attachment(folder_id, message_id, index):
    """Download an attachment from an archived email."""
    message = Database.fetchone(
        """
        SELECT id, folder_id, filepath
        FROM messages WHERE id = ? AND folder_id = ?
        """,
        (message_id, folder_id)
    )
    if not message:
        return jsonify({"error": "Message not found"}), 404
    
    filepath = Config.get_base_path() / message["filepath"]
    if not filepath.exists():
        return jsonify({"error": "Email file not found"}), 404

    try:
        raw_bytes = filepath.read_bytes()
        raw_bytes = Encryption.decrypt(raw_bytes)
        msg = email_lib.message_from_bytes(raw_bytes)
        
        # Find attachments (must match filtering in get_archived_email)
        attachments = []
        if msg.is_multipart():
            for part in msg.walk():
                content_disposition = str(part.get("Content-Disposition", ""))
                filename = part.get_filename()
                content_id = part.get("Content-ID")
                
                # Skip inline images that are embedded in HTML body (have Content-ID)
                if content_id:
                    continue
                
                # Treat as attachment if explicitly marked as attachment,
                # OR if it has a filename (even if inline) and isn't text
                if "attachment" in content_disposition or (filename and part.get_content_maintype() != "text"):
                    if filename:
                        attachments.append({
                            "filename": _decode_header(filename),
                            "content_type": part.get_content_type(),
                            "payload": part.get_payload(decode=True),
                        })
        
        if index < 0 or index >= len(attachments):
            return jsonify({"error": "Attachment not found"}), 404
        
        att = attachments[index]
        
        # Check if user wants to view inline (for PDFs, images, etc.)
        view_inline = request.args.get("view") == "1"
        disposition = "inline" if view_inline else "attachment"
        
        return Response(
            att["payload"],
            mimetype=att["content_type"],
            headers={"Content-Disposition": f'{disposition}; filename="{att["filename"]}"'}
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
        (message_id, folder_id)
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
            source = raw_bytes.decode('utf-8')
        except UnicodeDecodeError:
            source = raw_bytes.decode('latin-1')
        
        return jsonify({"source": source})
    except Exception as e:
        return jsonify({"error": f"Failed to read email source: {e}"}), 500


@api_bp.route("/search/reindex", methods=["POST"])
def reindex_search():
    """Rebuild FTS index by re-extracting body text from archived .eml files."""
    try:
        messages = Database.fetchall(
            "SELECT id, filepath FROM messages WHERE deleted_at IS NULL",
            ()
        )
        
        updated = 0
        errors = 0
        
        for msg in messages:
            try:
                filepath = Config.get_base_path() / msg["filepath"]
                if not filepath.exists():
                    errors += 1
                    continue
                raw_email = filepath.read_bytes()
                raw_email = Encryption.decrypt(raw_email)
                body_text = extract_body_text(raw_email)
                Database.execute(
                    "UPDATE messages SET body_text = ? WHERE id = ?",
                    (body_text, msg["id"])
                )
                updated += 1
            except Exception as e:
                log.warning(f"Failed to reindex message {msg['id']}: {e}")
                errors += 1
        
        # Rebuild FTS index
        Database.execute("INSERT INTO messages_fts(messages_fts) VALUES('rebuild')", ())
        
        return jsonify({
            "message": f"Reindexed {updated} emails ({errors} errors)",
            "updated": updated,
            "errors": errors
        })
    except Exception as e:
        return jsonify({"error": f"Reindex failed: {e}"}), 500
