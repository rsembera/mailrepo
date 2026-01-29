"""
MailRepo API - Email Routes

Handles search and archived email retrieval endpoints.
"""

import base64
import time
import email as email_lib
from email.header import decode_header
from flask import request, jsonify, Response
from core import Database
from core import Config
from core import Encryption
from . import api_bp


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
            WHERE messages_fts MATCH ? AND m.folder_id = ?
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
            WHERE messages_fts MATCH ?
            ORDER BY m.date DESC
            LIMIT ?
            """,
            (fts_query, limit)
        )

    emails = [{
        "id": r["id"],
        "folder_id": r["folder_id"],
        "folder_name": r["folder_name"],
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


def _decode_header_value(header):
    """Decode an email header value."""
    if not header:
        return ""
    try:
        parts = decode_header(header)
        decoded = []
        for content, charset in parts:
            if isinstance(content, bytes):
                decoded.append(content.decode(charset or "utf-8", errors="replace"))
            else:
                decoded.append(content)
        return " ".join(decoded)
    except:
        return header


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
            "subject": _decode_header_value(msg.get("Subject", "")),
            "from": _decode_header_value(msg.get("From", "")),
            "to": _decode_header_value(msg.get("To", "")),
            "cc": _decode_header_value(msg.get("Cc", "")),
            "date": msg.get("Date", ""),
            "text_body": None,
            "html_body": None,
            "attachments": [],
        }
        
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))
                
                if "attachment" in content_disposition:
                    filename = part.get_filename()
                    if filename:
                        result["attachments"].append({
                            "filename": _decode_header_value(filename),
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
        print(f"Warning: Could not delete file {message['filepath']}: {e}")
    
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
        
        # Find attachments
        attachments = []
        if msg.is_multipart():
            for part in msg.walk():
                content_disposition = str(part.get("Content-Disposition", ""))
                if "attachment" in content_disposition:
                    filename = part.get_filename()
                    if filename:
                        attachments.append({
                            "filename": _decode_header_value(filename),
                            "content_type": part.get_content_type(),
                            "payload": part.get_payload(decode=True),
                        })
        
        if index < 0 or index >= len(attachments):
            return jsonify({"error": "Attachment not found"}), 404
        
        att = attachments[index]
        return Response(
            att["payload"],
            mimetype=att["content_type"],
            headers={"Content-Disposition": f'attachment; filename="{att["filename"]}"'}
        )
    except Exception as e:
        return jsonify({"error": f"Failed to read attachment: {e}"}), 500
