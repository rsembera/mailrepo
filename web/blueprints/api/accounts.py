"""
MailRepo API - Account Routes

Handles all /api/accounts/* endpoints for managing IMAP accounts.
"""

import email
import json
import time
from email.header import decode_header

from flask import Response, jsonify, request

from core import IMAP, Database, IMAPError
from core.account_utils import is_gmail_host

from . import api_bp


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
    except Exception:
        return header


@api_bp.route("/accounts", methods=["GET"])
def list_accounts():
    """Get all email accounts."""
    accounts = Database.fetchall(
        "SELECT id, name, email, provider, credentials_encrypted, last_sync FROM accounts ORDER BY name"
    )

    result = []
    for a in accounts:
        account_dict = {
            "id": a["id"],
            "name": a["name"],
            "email": a["email"],
            "provider": a["provider"],
            "last_sync": a["last_sync"],
            "is_gmail": False,
        }
        # Check if this is a Gmail/Google Workspace account by examining the IMAP server
        if a["credentials_encrypted"]:
            try:
                creds = IMAP.load_credentials(a["credentials_encrypted"])
                if creds and is_gmail_host(creds.get("host")):
                    account_dict["is_gmail"] = True
            except Exception:
                pass  # If decryption fails, default to False
        result.append(account_dict)

    return jsonify({"accounts": result})


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

    if not host:
        detected = IMAP.detect_server(email_addr)
        if detected:
            host, port = detected
        else:
            return jsonify(
                {
                    "error": "Could not auto-detect IMAP server. Please enter server details manually."
                }
            ), 400

    test_result = IMAP.test_connection(email_addr, password, host, port, use_ssl)
    if not test_result["success"]:
        return jsonify({"error": test_result["error"]}), 400

    cursor = Database.execute(
        "INSERT INTO accounts (name, email, provider) VALUES (?, ?, ?)", (name, email_addr, "imap")
    )
    Database.commit()

    account_id = cursor.lastrowid
    IMAP.save_credentials(account_id, email_addr, password, host, port, use_ssl)

    return jsonify(
        {
            "account": {
                "id": account_id,
                "name": name,
                "email": email_addr,
                "provider": "imap",
            },
            "message": test_result["message"],
        }
    ), 201


@api_bp.route("/accounts/<int:account_id>", methods=["PATCH"])
def update_account(account_id):
    """Update an existing IMAP email account."""
    account = Database.fetchone(
        "SELECT id, name, email, credentials_encrypted FROM accounts WHERE id = ?", (account_id,)
    )
    if not account:
        return jsonify({"error": "Account not found"}), 404

    data = request.get_json()

    name = data.get("name", "").strip()
    email_addr = data.get("email", "").strip()
    password = data.get("password", "")  # Empty means don't change
    host = data.get("host", "").strip()
    port = int(data.get("port", 993))
    use_ssl = data.get("use_ssl", True)

    if not name:
        return jsonify({"error": "Account name is required"}), 400
    if not email_addr:
        return jsonify({"error": "Email address is required"}), 400

    # If password provided, update credentials; otherwise keep existing
    if password:
        if not host:
            detected = IMAP.detect_server(email_addr)
            if detected:
                host, port = detected
            else:
                return jsonify(
                    {
                        "error": "Could not auto-detect IMAP server. Please enter server details manually."
                    }
                ), 400

        # Test connection with new credentials
        test_result = IMAP.test_connection(email_addr, password, host, port, use_ssl)
        if not test_result["success"]:
            return jsonify({"error": test_result["message"]}), 400

        # Save new credentials
        IMAP.save_credentials(account_id, email_addr, password, host, port, use_ssl)
        message = test_result["message"]
    else:
        message = "Account updated (password unchanged)"

    # Update account name and email
    Database.execute(
        "UPDATE accounts SET name = ?, email = ? WHERE id = ?", (name, email_addr, account_id)
    )
    Database.commit()

    return jsonify(
        {
            "account": {
                "id": account_id,
                "name": name,
                "email": email_addr,
                "provider": "imap",
            },
            "message": message,
        }
    )


@api_bp.route("/accounts/<int:account_id>/test", methods=["POST"])
def test_account_connection(account_id):
    """Test connection to an existing IMAP account."""
    account = Database.fetchone(
        "SELECT id, credentials_encrypted FROM accounts WHERE id = ?", (account_id,)
    )
    if not account:
        return jsonify({"error": "Account not found"}), 404
    if not account["credentials_encrypted"]:
        return jsonify({"error": "Account has no saved credentials"}), 400

    creds = IMAP.load_credentials(account["credentials_encrypted"])
    if not creds:
        return jsonify({"error": "Failed to load credentials"}), 400

    test_result = IMAP.test_connection(
        creds["email"], creds["password"], creds["host"], creds["port"], creds.get("use_ssl", True)
    )

    if test_result["success"]:
        Database.execute(
            "UPDATE accounts SET last_sync = ? WHERE id = ?", (int(time.time()), account_id)
        )
        Database.commit()

    return jsonify(test_result)


@api_bp.route("/accounts/<int:account_id>/emails", methods=["GET"])
def get_account_emails(account_id):
    """Get emails from an IMAP account."""
    account = Database.fetchone(
        "SELECT id, credentials_encrypted FROM accounts WHERE id = ?", (account_id,)
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
    """Get a single email with full content for viewing."""
    account = Database.fetchone(
        "SELECT id, credentials_encrypted FROM accounts WHERE id = ?", (account_id,)
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
    """Get IMAP folders (mailboxes) for an account. Uses cache if fresh."""
    account = Database.fetchone(
        "SELECT id, credentials_encrypted, cached_folders, cached_folders_at FROM accounts WHERE id = ?",
        (account_id,),
    )
    if not account:
        return jsonify({"error": "Account not found"}), 404
    if not account["credentials_encrypted"]:
        return jsonify({"error": "Account not configured"}), 401

    force_refresh = request.args.get("refresh") == "1"

    # Use cache if available (no time-based expiry - folders rarely change)
    # Only refresh on explicit request or when cache is missing
    if not force_refresh and account["cached_folders"]:
        try:
            folders = json.loads(account["cached_folders"])
            # Invalidate cache if missing noselect field (schema upgrade)
            if folders and "noselect" not in folders[0]:
                pass  # Fall through to live fetch
            else:
                return jsonify({"folders": folders, "cached": True})
        except (json.JSONDecodeError, IndexError, TypeError):
            pass

    client = None
    try:
        client = IMAP.connect_with_credentials(account["credentials_encrypted"])
        folders = client.list_folders()

        # Only update cache if folder list actually changed
        new_folders_json = json.dumps(folders)
        if new_folders_json != account["cached_folders"]:
            Database.execute(
                "UPDATE accounts SET cached_folders = ?, cached_folders_at = ? WHERE id = ?",
                (new_folders_json, int(time.time()), account_id),
            )
            Database.commit()

        return jsonify({"folders": folders, "cached": False})
    except IMAPError as e:
        if account["cached_folders"]:
            try:
                folders = json.loads(account["cached_folders"])
                return jsonify({"folders": folders, "cached": True, "stale": True, "error": str(e)})
            except Exception:
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
        return jsonify({"detected": True, "host": host, "port": port})
    else:
        return jsonify(
            {"detected": False, "message": "Could not auto-detect server. Please enter manually."}
        )


@api_bp.route("/accounts/<int:account_id>/emails/<uid>/download", methods=["GET"])
def download_imap_email(account_id, uid):
    """Download an IMAP email as .eml file."""
    account = Database.fetchone(
        "SELECT id, credentials_encrypted FROM accounts WHERE id = ?", (account_id,)
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
        raw_bytes = client.fetch_raw(uid)

        # Parse to get subject for filename
        msg = email.message_from_bytes(raw_bytes)
        subject = _decode_header_value(msg.get("Subject", "")) or "email"
        safe_filename = (
            "".join(c for c in subject if c.isalnum() or c in " -_")[:50].strip() or "email"
        )
        filename = f"{safe_filename}.eml"

        return Response(
            raw_bytes,
            mimetype="message/rfc822",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except IMAPError as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if client:
            client.disconnect()


@api_bp.route("/accounts/<int:account_id>/emails/<uid>/attachments/<int:index>", methods=["GET"])
def download_imap_attachment(account_id, uid, index):
    """Download an attachment from an IMAP email."""
    account = Database.fetchone(
        "SELECT id, credentials_encrypted FROM accounts WHERE id = ?", (account_id,)
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
        raw_bytes = client.fetch_raw(uid)
        msg = email.message_from_bytes(raw_bytes)

        # Find attachments (must match filtering in IMAP.fetch_email)
        attachments = []
        if msg.is_multipart():
            for part in msg.walk():
                content_disposition = str(part.get("Content-Disposition", ""))
                content_id = part.get("Content-ID")
                content_type = part.get_content_type()

                # Skip inline images - they're handled via cid: replacement in HTML
                # Only skip if it's an image with Content-ID (actual inline embedded image)
                if content_id and content_type.startswith("image/"):
                    continue

                if "attachment" in content_disposition:
                    filename = part.get_filename()
                    if filename:
                        attachments.append(
                            {
                                "filename": _decode_header_value(filename),
                                "content_type": content_type,
                                "payload": part.get_payload(decode=True),
                            }
                        )

        if index < 0 or index >= len(attachments):
            return jsonify({"error": "Attachment not found"}), 404

        att = attachments[index]

        # Check if user wants to view inline (for PDFs, images, etc.)
        view_inline = request.args.get("view") == "1"
        disposition = "inline" if view_inline else "attachment"

        return Response(
            att["payload"],
            mimetype=att["content_type"],
            headers={"Content-Disposition": f'{disposition}; filename="{att["filename"]}"'},
        )
    except IMAPError as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if client:
            client.disconnect()


@api_bp.route("/accounts/<int:account_id>/emails/<uid>/source", methods=["GET"])
def get_imap_email_source(account_id, uid):
    """Get raw source of an IMAP email."""
    account = Database.fetchone(
        "SELECT id, credentials_encrypted FROM accounts WHERE id = ?", (account_id,)
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
        raw_bytes = client.fetch_raw(uid)

        # Try to decode as text, fallback to latin-1 if UTF-8 fails
        try:
            source = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            source = raw_bytes.decode("latin-1")

        return jsonify({"source": source})
    except IMAPError as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if client:
            client.disconnect()
