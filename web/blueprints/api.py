"""
MailRepo - API blueprint.

Provides JSON API endpoints for the frontend.
"""

import email as email_lib
import html
import re
import time
from pathlib import Path
from flask import Blueprint, jsonify, request

from core import (
    Database, IMAP, IMAPError, Encryption, Config,
    import_eml_file, import_mbox_file, scan_mbox_file, ImportError
)


api_bp = Blueprint("api", __name__, url_prefix="/api")


def extract_body_text(raw_email: bytes) -> str:
    """
    Extract plain text body from raw email for full-text indexing.
    
    Args:
        raw_email: Raw RFC 2822 email bytes.
        
    Returns:
        Plain text content suitable for FTS indexing.
    """
    msg = email_lib.message_from_bytes(raw_email)
    
    text_parts = []
    
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))
            
            # Skip attachments
            if "attachment" in content_disposition:
                continue
            
            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        text_parts.append(payload.decode(charset, errors="replace"))
                    except:
                        pass
            elif content_type == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        html_content = payload.decode(charset, errors="replace")
                        # Strip HTML tags for indexing
                        text = html.unescape(html_content)
                        text = re.sub(r'<[^>]+>', ' ', text)
                        text = re.sub(r'\s+', ' ', text).strip()
                        text_parts.append(text)
                    except:
                        pass
    else:
        content_type = msg.get_content_type()
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            try:
                text = payload.decode(charset, errors="replace")
                if content_type == "text/html":
                    text = html.unescape(text)
                    text = re.sub(r'<[^>]+>', ' ', text)
                    text = re.sub(r'\s+', ' ', text).strip()
                text_parts.append(text)
            except:
                pass
    
    return "\n".join(text_parts)


# ============================================
# FOLDERS
# ============================================

@api_bp.route("/folders", methods=["GET"])
def list_folders():
    """Get all archive folders."""
    folders = Database.fetchall(
        "SELECT id, name, parent_id, color, deleted_at, created_at FROM folders ORDER BY name"
    )
    
    return jsonify({
        "folders": [dict(f) for f in folders]
    })


@api_bp.route("/folders", methods=["POST"])
def create_folder():
    """Create a new archive folder."""
    data = request.get_json()
    
    name = data.get("name", "").strip()
    parent_id = data.get("parent_id")
    
    # Validation
    if not name:
        return jsonify({"error": "Folder name is required"}), 400
    
    if len(name) > 100:
        return jsonify({"error": "Folder name must be 100 characters or less"}), 400
    
    # Check for duplicate name at same level
    if parent_id:
        existing = Database.fetchone(
            "SELECT id FROM folders WHERE name = ? AND parent_id = ?",
            (name, parent_id)
        )
    else:
        existing = Database.fetchone(
            "SELECT id FROM folders WHERE name = ? AND parent_id IS NULL",
            (name,)
        )
    
    if existing:
        return jsonify({"error": "A folder with this name already exists"}), 400
    
    # Create folder
    cursor = Database.execute(
        "INSERT INTO folders (name, parent_id) VALUES (?, ?)",
        (name, parent_id)
    )
    Database.commit()
    
    folder_id = cursor.lastrowid
    
    return jsonify({
        "folder": {
            "id": folder_id,
            "name": name,
            "parent_id": parent_id,
        }
    }), 201


@api_bp.route("/folders/<int:folder_id>", methods=["GET"])
def get_folder(folder_id):
    """Get a single folder."""
    folder = Database.fetchone(
        "SELECT id, name, parent_id, created_at FROM folders WHERE id = ?",
        (folder_id,)
    )
    
    if not folder:
        return jsonify({"error": "Folder not found"}), 404
    
    return jsonify({"folder": dict(folder)})


@api_bp.route("/folders/<int:folder_id>", methods=["DELETE"])
def delete_folder(folder_id):
    """Soft-delete a folder (move to trash)."""
    folder = Database.fetchone("SELECT id FROM folders WHERE id = ?", (folder_id,))
    
    if not folder:
        return jsonify({"error": "Folder not found"}), 404
    
    # Soft delete - set deleted_at timestamp
    now = int(time.time())
    Database.execute(
        "UPDATE folders SET deleted_at = ? WHERE id = ?",
        (now, folder_id)
    )
    # Also soft-delete children
    Database.execute(
        "UPDATE folders SET deleted_at = ? WHERE parent_id = ?",
        (now, folder_id)
    )
    Database.commit()
    
    return jsonify({"success": True})


@api_bp.route("/folders/<int:folder_id>", methods=["PATCH"])
def update_folder(folder_id):
    """Update folder properties (name, color)."""
    folder = Database.fetchone("SELECT id, name FROM folders WHERE id = ?", (folder_id,))
    
    if not folder:
        return jsonify({"error": "Folder not found"}), 404
    
    data = request.get_json()
    updates = []
    params = []
    
    if "name" in data:
        name = data["name"].strip()
        if not name:
            return jsonify({"error": "Folder name cannot be empty"}), 400
        if len(name) > 100:
            return jsonify({"error": "Folder name must be 100 characters or less"}), 400
        updates.append("name = ?")
        params.append(name)
    
    if "color" in data:
        # Allow None/null to remove color
        color = data["color"]
        updates.append("color = ?")
        params.append(color)
    
    if "parent_id" in data:
        new_parent_id = data["parent_id"]
        
        # Validate: can't move folder into itself
        if new_parent_id == folder_id:
            return jsonify({"error": "Cannot move folder into itself"}), 400
        
        # Validate: can't move folder into one of its descendants
        if new_parent_id is not None:
            # Check if new_parent_id is a descendant of folder_id
            def is_descendant(parent_id, target_id):
                children = Database.fetchall(
                    "SELECT id FROM folders WHERE parent_id = ? AND deleted_at IS NULL",
                    (parent_id,)
                )
                for child in children:
                    if child["id"] == target_id:
                        return True
                    if is_descendant(child["id"], target_id):
                        return True
                return False
            
            if is_descendant(folder_id, new_parent_id):
                return jsonify({"error": "Cannot move folder into one of its subfolders"}), 400
            
            # Validate: new parent exists and is not deleted
            new_parent = Database.fetchone(
                "SELECT id, deleted_at FROM folders WHERE id = ?",
                (new_parent_id,)
            )
            if not new_parent or new_parent["deleted_at"]:
                return jsonify({"error": "Destination folder not found"}), 404
        
        updates.append("parent_id = ?")
        params.append(new_parent_id)
    
    if not updates:
        return jsonify({"error": "No updates provided"}), 400
    
    params.append(folder_id)
    Database.execute(
        f"UPDATE folders SET {', '.join(updates)} WHERE id = ?",
        tuple(params)
    )
    Database.commit()
    
    return jsonify({"success": True})


@api_bp.route("/folders/<int:folder_id>/restore", methods=["POST"])
def restore_folder(folder_id):
    """Restore a folder from trash."""
    folder = Database.fetchone(
        "SELECT id, name, parent_id, deleted_at FROM folders WHERE id = ?",
        (folder_id,)
    )
    
    if not folder:
        return jsonify({"error": "Folder not found"}), 404
    
    if not folder["deleted_at"]:
        return jsonify({"error": "Folder is not in trash"}), 400
    
    # Determine target parent_id
    target_parent_id = folder["parent_id"]
    
    # Check if parent still exists and is not deleted
    if target_parent_id:
        parent = Database.fetchone(
            "SELECT id, deleted_at FROM folders WHERE id = ?",
            (target_parent_id,)
        )
        if not parent or parent["deleted_at"]:
            # Parent was permanently deleted or is still in trash - restore to root
            target_parent_id = None
    
    # Check for name conflict at target location
    folder_name = folder["name"]
    if target_parent_id:
        conflict = Database.fetchone(
            "SELECT id FROM folders WHERE name = ? AND parent_id = ? AND deleted_at IS NULL",
            (folder_name, target_parent_id)
        )
    else:
        conflict = Database.fetchone(
            "SELECT id FROM folders WHERE name = ? AND parent_id IS NULL AND deleted_at IS NULL",
            (folder_name,)
        )
    
    # If conflict exists, generate a unique name
    if conflict:
        base_name = folder_name
        counter = 2
        while True:
            new_name = f"{base_name} ({counter})"
            if target_parent_id:
                existing = Database.fetchone(
                    "SELECT id FROM folders WHERE name = ? AND parent_id = ? AND deleted_at IS NULL",
                    (new_name, target_parent_id)
                )
            else:
                existing = Database.fetchone(
                    "SELECT id FROM folders WHERE name = ? AND parent_id IS NULL AND deleted_at IS NULL",
                    (new_name,)
                )
            if not existing:
                folder_name = new_name
                break
            counter += 1
            if counter > 100:  # Safety limit
                return jsonify({"error": "Could not generate unique folder name"}), 500
    
    # Restore the folder
    Database.execute(
        "UPDATE folders SET deleted_at = NULL, parent_id = ?, name = ? WHERE id = ?",
        (target_parent_id, folder_name, folder_id)
    )
    
    # Also restore children
    Database.execute(
        "UPDATE folders SET deleted_at = NULL WHERE parent_id = ?",
        (folder_id,)
    )
    
    Database.commit()
    
    # Return the possibly-renamed folder info
    return jsonify({
        "success": True,
        "folder": {
            "id": folder_id,
            "name": folder_name,
            "renamed": folder_name != folder["name"]
        }
    })


@api_bp.route("/folders/<int:folder_id>/permanent", methods=["DELETE"])
def permanently_delete_folder(folder_id):
    """Permanently delete a folder from trash."""
    folder = Database.fetchone(
        "SELECT id, deleted_at FROM folders WHERE id = ?",
        (folder_id,)
    )
    
    if not folder:
        return jsonify({"error": "Folder not found"}), 404
    
    # For safety, only allow permanent delete if already in trash
    if not folder["deleted_at"]:
        return jsonify({"error": "Folder must be in trash before permanent deletion"}), 400
    
    # Get all message filepaths before deleting
    messages = Database.fetchall(
        "SELECT filepath FROM messages WHERE folder_id = ? OR folder_id IN (SELECT id FROM folders WHERE parent_id = ?)",
        (folder_id, folder_id)
    )
    
    # Delete files from disk
    for msg in messages:
        try:
            filepath = Config.get_base_path() / msg["filepath"]
            if filepath.exists():
                filepath.unlink()
        except Exception as e:
            # Log but continue
            print(f"Warning: Could not delete file {msg['filepath']}: {e}")
    
    # Delete folder directory if empty
    try:
        folder_path = Config.get_archive_path() / str(folder_id)
        if folder_path.exists() and folder_path.is_dir():
            folder_path.rmdir()  # Only removes if empty
    except:
        pass
    
    # Delete from database (CASCADE will handle messages)
    Database.execute("DELETE FROM folders WHERE id = ? OR parent_id = ?", (folder_id, folder_id))
    Database.commit()
    
    return jsonify({"success": True})


@api_bp.route("/trash/empty", methods=["POST"])
def empty_trash():
    """Permanently delete all items in trash."""
    # Get all trashed folders
    trashed = Database.fetchall(
        "SELECT id FROM folders WHERE deleted_at IS NOT NULL"
    )
    
    if not trashed:
        return jsonify({"success": True, "deleted": 0})
    
    # Get all message filepaths
    folder_ids = [f["id"] for f in trashed]
    placeholders = ",".join(["?" for _ in folder_ids])
    
    messages = Database.fetchall(
        f"SELECT filepath FROM messages WHERE folder_id IN ({placeholders})",
        tuple(folder_ids)
    )
    
    # Delete files
    for msg in messages:
        try:
            filepath = Config.get_base_path() / msg["filepath"]
            if filepath.exists():
                filepath.unlink()
        except Exception as e:
            print(f"Warning: Could not delete file {msg['filepath']}: {e}")
    
    # Delete folders from database
    Database.execute(
        f"DELETE FROM folders WHERE id IN ({placeholders})",
        tuple(folder_ids)
    )
    Database.commit()
    
    return jsonify({"success": True, "deleted": len(trashed)})


@api_bp.route("/search", methods=["GET"])
def search_emails():
    """
    Search archived emails using full-text search.
    
    Query params:
        q: Search query (required)
        folder_id: Limit search to a specific folder (optional)
        limit: Max results (default: 50)
    """
    query = request.args.get("q", "").strip()
    folder_id = request.args.get("folder_id")
    limit = int(request.args.get("limit", 50))
    
    if not query:
        return jsonify({"error": "Search query is required"}), 400
    
    # Build the FTS5 query
    # Escape special characters for FTS5
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
    
    emails = []
    for r in results:
        emails.append({
            "id": r["id"],
            "folder_id": r["folder_id"],
            "folder_name": r["folder_name"],
            "subject": r["subject"],
            "sender": r["sender"],
            "date": r["date"],
        })
    
    return jsonify({
        "query": query,
        "count": len(emails),
        "emails": emails,
    })


@api_bp.route("/folders/<int:folder_id>/emails", methods=["GET"])
def get_folder_emails(folder_id):
    """Get all emails in an archive folder."""
    folder = Database.fetchone("SELECT id FROM folders WHERE id = ?", (folder_id,))
    
    if not folder:
        return jsonify({"error": "Folder not found"}), 404
    
    messages = Database.fetchall(
        """
        SELECT id, subject, sender, date, filepath
        FROM messages 
        WHERE folder_id = ?
        ORDER BY date DESC
        """,
        (folder_id,)
    )
    
    emails = []
    for m in messages:
        emails.append({
            "id": m["id"],
            "subject": m["subject"],
            "sender": m["sender"],
            "date": m["date"],
        })
    
    return jsonify({"emails": emails})


@api_bp.route("/folders/<int:folder_id>/emails/<int:message_id>", methods=["GET"])
def get_archived_email(folder_id, message_id):
    """Get a single archived email with full content."""
    from email.header import decode_header
    
    message = Database.fetchone(
        """
        SELECT id, folder_id, subject, sender, date, filepath
        FROM messages 
        WHERE id = ? AND folder_id = ?
        """,
        (message_id, folder_id)
    )
    
    if not message:
        return jsonify({"error": "Message not found"}), 404
    
    # Read the .eml file
    filepath = Config.get_base_path() / message["filepath"]
    if not filepath.exists():
        return jsonify({"error": "Email file not found"}), 404
    
    try:
        raw_bytes = filepath.read_bytes()
        
        # All emails are now encrypted
        raw_bytes = Encryption.decrypt(raw_bytes)
        
        # Parse the email
        msg = email_lib.message_from_bytes(raw_bytes)
        
        def decode_header_value(header):
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
        
        result = {
            "id": message["id"],
            "subject": decode_header_value(msg.get("Subject", "")),
            "from": decode_header_value(msg.get("From", "")),
            "to": decode_header_value(msg.get("To", "")),
            "cc": decode_header_value(msg.get("Cc", "")),
            "date": msg.get("Date", ""),
            "text_body": None,
            "html_body": None,
            "attachments": [],
        }
        
        # Parse body
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))
                
                if "attachment" in content_disposition:
                    filename = part.get_filename()
                    if filename:
                        result["attachments"].append({
                            "filename": decode_header_value(filename),
                            "content_type": content_type,
                            "size": len(part.get_payload(decode=True) or b""),
                        })
                    continue
                
                if content_type == "text/plain" and not result["text_body"]:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        result["text_body"] = payload.decode(charset, errors="replace")
                
                elif content_type == "text/html" and not result["html_body"]:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        result["html_body"] = payload.decode(charset, errors="replace")
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


# ============================================
# ACCOUNTS (IMAP)
# ============================================

@api_bp.route("/accounts", methods=["GET"])
def list_accounts():
    """Get all email accounts."""
    accounts = Database.fetchall(
        "SELECT id, name, email, provider, last_sync FROM accounts ORDER BY name"
    )
    
    return jsonify({
        "accounts": [dict(a) for a in accounts]
    })


@api_bp.route("/accounts", methods=["POST"])
def create_account():
    """Create a new IMAP email account."""
    data = request.get_json()
    
    name = data.get("name", "").strip()
    email_addr = data.get("email", "").strip()
    password = data.get("password", "")
    host = data.get("host", "").strip()
    port = int(data.get("port", 993))
    use_ssl = data.get("use_ssl", True)
    
    if not name:
        return jsonify({"error": "Account name is required"}), 400
    
    if not email_addr:
        return jsonify({"error": "Email address is required"}), 400
    
    if not password:
        return jsonify({"error": "Password is required"}), 400
    
    # Auto-detect server if not provided
    if not host:
        detected = IMAP.detect_server(email_addr)
        if detected:
            host, port = detected
        else:
            return jsonify({
                "error": "Could not auto-detect IMAP server. Please enter server details manually."
            }), 400
    
    # Test connection before saving
    test_result = IMAP.test_connection(email_addr, password, host, port, use_ssl)
    if not test_result["success"]:
        return jsonify({"error": test_result["error"]}), 400
    
    # Create account record
    cursor = Database.execute(
        "INSERT INTO accounts (name, email, provider) VALUES (?, ?, ?)",
        (name, email_addr, "imap")
    )
    Database.commit()
    
    account_id = cursor.lastrowid
    
    # Save encrypted credentials
    IMAP.save_credentials(account_id, email_addr, password, host, port, use_ssl)
    
    return jsonify({
        "account": {
            "id": account_id,
            "name": name,
            "email": email_addr,
            "provider": "imap",
        },
        "message": test_result["message"],
    }), 201


@api_bp.route("/accounts/<int:account_id>/test", methods=["POST"])
def test_account_connection(account_id):
    """Test connection to an existing IMAP account."""
    account = Database.fetchone(
        "SELECT id, credentials_encrypted FROM accounts WHERE id = ?",
        (account_id,)
    )
    
    if not account:
        return jsonify({"error": "Account not found"}), 404
    
    if not account["credentials_encrypted"]:
        return jsonify({"error": "Account has no saved credentials"}), 400
    
    creds = IMAP.load_credentials(account["credentials_encrypted"])
    if not creds:
        return jsonify({"error": "Failed to load credentials"}), 400
    
    test_result = IMAP.test_connection(
        creds["email"], creds["password"], 
        creds["host"], creds["port"], 
        creds.get("use_ssl", True)
    )
    
    if test_result["success"]:
        # Update last_sync
        Database.execute(
            "UPDATE accounts SET last_sync = ? WHERE id = ?",
            (int(time.time()), account_id)
        )
        Database.commit()
    
    return jsonify(test_result)


@api_bp.route("/accounts/<int:account_id>/emails", methods=["GET"])
def get_account_emails(account_id):
    """
    Get emails from an IMAP account.
    
    Query params:
        folder: IMAP folder to fetch from (default: INBOX)
        limit: Max results (default: 50)
    """
    account = Database.fetchone(
        "SELECT id, credentials_encrypted FROM accounts WHERE id = ?",
        (account_id,)
    )
    
    if not account:
        return jsonify({"error": "Account not found"}), 404
    
    if not account["credentials_encrypted"]:
        return jsonify({"error": "Account not configured. Add credentials first."}), 401
    
    folder = request.args.get("folder", "INBOX")
    limit = int(request.args.get("limit", 50))
    
    client = None
    try:
        client = IMAP.connect_with_credentials(account["credentials_encrypted"])
        client.select_folder(folder)
        
        uids = client.search("ALL", limit=limit)
        
        emails = []
        for uid in uids:
            headers = client.fetch_headers(uid)
            emails.append(headers)
        
        return jsonify({"emails": emails})
        
    except IMAPError as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if client:
            client.disconnect()


@api_bp.route("/accounts/<int:account_id>/emails/<uid>", methods=["GET"])
def get_account_email(account_id, uid):
    """
    Get a single email with full content for viewing.
    
    Query params:
        folder: IMAP folder the email is in (default: INBOX)
    """
    account = Database.fetchone(
        "SELECT id, credentials_encrypted FROM accounts WHERE id = ?",
        (account_id,)
    )
    
    if not account:
        return jsonify({"error": "Account not found"}), 404
    
    if not account["credentials_encrypted"]:
        return jsonify({"error": "Account not configured"}), 401
    
    folder = request.args.get("folder", "INBOX")
    
    client = None
    try:
        client = IMAP.connect_with_credentials(account["credentials_encrypted"])
        client.select_folder(folder)
        email_data = client.fetch_full(uid)
        
        return jsonify({"email": email_data})
        
    except IMAPError as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if client:
            client.disconnect()


@api_bp.route("/accounts/<int:account_id>/folders", methods=["GET"])
def get_account_folders(account_id):
    """
    Get IMAP folders (mailboxes) for an account.
    
    Uses cached folder list if available and fresh (< 1 hour old).
    Query param: refresh=1 to force refresh from server.
    """
    import json
    
    account = Database.fetchone(
        "SELECT id, credentials_encrypted, cached_folders, cached_folders_at FROM accounts WHERE id = ?",
        (account_id,)
    )
    
    if not account:
        return jsonify({"error": "Account not found"}), 404
    
    if not account["credentials_encrypted"]:
        return jsonify({"error": "Account not configured"}), 401
    
    force_refresh = request.args.get("refresh") == "1"
    cache_max_age = 3600  # 1 hour
    
    # Check if we have a fresh cache
    if not force_refresh and account["cached_folders"] and account["cached_folders_at"]:
        cache_age = int(time.time()) - account["cached_folders_at"]
        if cache_age < cache_max_age:
            try:
                folders = json.loads(account["cached_folders"])
                return jsonify({"folders": folders, "cached": True})
            except json.JSONDecodeError:
                pass  # Fall through to fetch from server
    
    # Fetch from server
    client = None
    try:
        client = IMAP.connect_with_credentials(account["credentials_encrypted"])
        folders = client.list_folders()
        
        # Update cache
        Database.execute(
            "UPDATE accounts SET cached_folders = ?, cached_folders_at = ? WHERE id = ?",
            (json.dumps(folders), int(time.time()), account_id)
        )
        Database.commit()
        
        return jsonify({"folders": folders, "cached": False})
        
    except IMAPError as e:
        # If we have stale cache, return it with error note
        if account["cached_folders"]:
            try:
                folders = json.loads(account["cached_folders"])
                return jsonify({"folders": folders, "cached": True, "stale": True, "error": str(e)})
            except:
                pass
        return jsonify({"error": str(e)}), 500
    finally:
        if client:
            client.disconnect()


@api_bp.route("/accounts/<int:account_id>", methods=["DELETE"])
def delete_account(account_id):
    """Delete an email account."""
    account = Database.fetchone("SELECT id FROM accounts WHERE id = ?", (account_id,))
    
    if not account:
        return jsonify({"error": "Account not found"}), 404
    
    Database.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    Database.commit()
    
    return jsonify({"success": True})


@api_bp.route("/accounts/detect-server", methods=["POST"])
def detect_imap_server():
    """Auto-detect IMAP server from email address."""
    data = request.get_json()
    email_addr = data.get("email", "").strip()
    
    if not email_addr:
        return jsonify({"error": "Email address required"}), 400
    
    detected = IMAP.detect_server(email_addr)
    if detected:
        host, port = detected
        return jsonify({
            "detected": True,
            "host": host,
            "port": port,
        })
    else:
        return jsonify({
            "detected": False,
            "message": "Could not auto-detect server. Please enter manually."
        })


# ============================================
# STAGING & COMMIT
# ============================================

@api_bp.route("/commit", methods=["POST"])
def commit_staged():
    """
    Commit staged emails to archive.
    
    Expects JSON body:
    {
        "staged": [
            {
                "email": { uid, subject, sender, date, ... },
                "destinationFolderId": 123,
                "sourceAccountId": 456,
                "sourceFolder": "INBOX"
            },
            ...
        ]
    }
    """
    data = request.get_json()
    staged = data.get("staged", [])
    
    if not staged:
        return jsonify({"error": "No emails to commit"}), 400
    
    results = {
        "success": [],
        "failed": [],
        "skipped": [],
    }
    
    # Group by account for efficiency
    by_account = {}
    for item in staged:
        acc_id = item.get("sourceAccountId")
        if acc_id not in by_account:
            by_account[acc_id] = []
        by_account[acc_id].append(item)
    
    for account_id, items in by_account.items():
        # Get account and credentials
        account = Database.fetchone(
            "SELECT id, credentials_encrypted FROM accounts WHERE id = ?",
            (account_id,)
        )
        
        if not account or not account["credentials_encrypted"]:
            for item in items:
                results["failed"].append({
                    "uid": item["email"].get("uid"),
                    "error": "Account not found or not configured",
                })
            continue
        
        client = None
        try:
            client = IMAP.connect_with_credentials(account["credentials_encrypted"])
        except Exception as e:
            for item in items:
                results["failed"].append({
                    "uid": item["email"].get("uid"),
                    "error": f"Failed to connect: {e}",
                })
            continue
        
        # Group by source folder
        by_folder = {}
        for item in items:
            src_folder = item.get("sourceFolder", "INBOX")
            if src_folder not in by_folder:
                by_folder[src_folder] = []
            by_folder[src_folder].append(item)
        
        for source_folder, folder_items in by_folder.items():
            try:
                client.select_folder(source_folder)
            except IMAPError as e:
                for item in folder_items:
                    results["failed"].append({
                        "uid": item["email"].get("uid"),
                        "error": f"Failed to select folder: {e}",
                    })
                continue
            
            for item in folder_items:
                email_data = item.get("email", {})
                folder_id = item.get("destinationFolderId")
                uid = email_data.get("uid")
                
                try:
                    # Verify destination folder exists
                    folder = Database.fetchone(
                        "SELECT id FROM folders WHERE id = ?",
                        (folder_id,)
                    )
                    if not folder:
                        raise ValueError(f"Folder {folder_id} not found")
                    
                    # Check for duplicate by Message-ID in destination folder
                    message_id = email_data.get("message_id", "")
                    if message_id:
                        existing = Database.fetchone(
                            "SELECT id FROM messages WHERE folder_id = ? AND message_id = ?",
                            (folder_id, message_id)
                        )
                        if existing:
                            results["skipped"].append({
                                "uid": uid,
                                "reason": "duplicate",
                                "subject": email_data.get("subject", ""),
                            })
                            continue
                    
                    # Download raw email
                    raw_email = client.fetch_raw(uid)
                    
                    # Extract body text for full-text search
                    body_text = extract_body_text(raw_email)
                    
                    # Determine filepath - always encrypted now
                    archive_path = Config.get_archive_path() / str(folder_id)
                    archive_path.mkdir(parents=True, exist_ok=True)
                    
                    # Use UID as filename base
                    safe_id = f"{account_id}_{uid}"
                    
                    # Always encrypt .eml files
                    encrypted_data = Encryption.encrypt(raw_email)
                    filepath = archive_path / f"{safe_id}.eml.enc"
                    filepath.write_bytes(encrypted_data)
                    
                    # Create database record
                    Database.execute(
                        """
                        INSERT INTO messages 
                        (folder_id, source_account_id, message_id, subject, sender, date, filepath, body_text)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            folder_id,
                            account_id,
                            email_data.get("message_id", ""),
                            email_data.get("subject", ""),
                            email_data.get("from", email_data.get("sender", "")),
                            email_data.get("date"),
                            str(filepath.relative_to(Config.get_base_path())),
                            body_text,
                        )
                    )
                    
                    results["success"].append(uid)
                    
                except Exception as e:
                    results["failed"].append({
                        "uid": uid,
                        "error": str(e),
                    })
        
        if client:
            client.disconnect()
    
    Database.commit()
    
    # Build message
    msg_parts = [f"{len(results['success'])} emails filed successfully"]
    if results["skipped"]:
        msg_parts.append(f"{len(results['skipped'])} skipped (already archived)")
    if results["failed"]:
        msg_parts.append(f"{len(results['failed'])} failed")
    
    return jsonify({
        "results": results,
        "message": ". ".join(msg_parts) + "."
    })


# ============================================
# IMPORT
# ============================================

@api_bp.route("/import/mbox/scan", methods=["POST"])
def scan_mbox():
    """
    Scan an mbox file and return summary.
    
    Expects JSON: { "path": "/path/to/file.mbox" }
    """
    data = request.get_json()
    mbox_path = data.get("path", "").strip()
    
    if not mbox_path:
        return jsonify({"error": "Path is required"}), 400
    
    path = Path(mbox_path).expanduser()
    if not path.exists():
        return jsonify({"error": "File not found"}), 404
    
    try:
        result = scan_mbox_file(path)
        return jsonify(result)
    except ImportError as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/import/mbox", methods=["POST"])
def import_mbox():
    """
    Import an mbox file into a folder.
    
    Expects JSON: { "path": "/path/to/file.mbox", "folder_id": 123 }
    """
    data = request.get_json()
    mbox_path = data.get("path", "").strip()
    folder_id = data.get("folder_id")
    
    if not mbox_path:
        return jsonify({"error": "Path is required"}), 400
    
    if not folder_id:
        return jsonify({"error": "Folder ID is required"}), 400
    
    path = Path(mbox_path).expanduser()
    if not path.exists():
        return jsonify({"error": "File not found"}), 404
    
    folder = Database.fetchone(
        "SELECT id FROM folders WHERE id = ?",
        (folder_id,)
    )
    if not folder:
        return jsonify({"error": "Folder not found"}), 404
    
    try:
        result = import_mbox_file(path, folder_id)
        return jsonify({
            "success": True,
            "total": result["total"],
            "imported": result["success_count"],
            "failed": result["failed_count"],
            "errors": result["errors"][:10],  # Limit error details
        })
    except ImportError as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/import/eml", methods=["POST"])
def import_eml():
    """
    Import a single .eml file into a folder.
    
    Expects JSON: { "path": "/path/to/email.eml", "folder_id": 123 }
    """
    data = request.get_json()
    eml_path = data.get("path", "").strip()
    folder_id = data.get("folder_id")
    
    if not eml_path:
        return jsonify({"error": "Path is required"}), 400
    
    if not folder_id:
        return jsonify({"error": "Folder ID is required"}), 400
    
    path = Path(eml_path).expanduser()
    if not path.exists():
        return jsonify({"error": "File not found"}), 404
    
    folder = Database.fetchone(
        "SELECT id FROM folders WHERE id = ?",
        (folder_id,)
    )
    if not folder:
        return jsonify({"error": "Folder not found"}), 404
    
    result = import_eml_file(path, folder_id)
    
    if result["success"]:
        Database.commit()
        return jsonify({
            "success": True,
            "subject": result["subject"],
        })
    else:
        return jsonify({
            "success": False,
            "error": result["error"],
        }), 500


# ============================================
# EXPORT
# ============================================

@api_bp.route("/folders/<int:folder_id>/export", methods=["POST"])
def export_folder(folder_id):
    """
    Export a folder as ZIP file.
    
    Decrypts all .eml.enc files on the fly and produces standard .eml files.
    """
    folder = Database.fetchone("SELECT id, name FROM folders WHERE id = ?", (folder_id,))
    
    if not folder:
        return jsonify({"error": "Folder not found"}), 404
    
    # TODO: Implement ZIP export
    # - Fetch all messages in folder
    # - For each message:
    #   - Read .eml or .eml.enc file
    #   - Decrypt if necessary
    #   - Add to ZIP archive
    # - Return ZIP file
    
    return jsonify({
        "error": "Export not yet implemented"
    }), 501
