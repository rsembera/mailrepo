"""
MailRepo API - Email Routes

Handles search and archived email retrieval endpoints.
"""

import email as email_lib
from email.header import decode_header
from flask import request, jsonify
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
        FROM messages WHERE folder_id = ?
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
