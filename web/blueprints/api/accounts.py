"""
MailRepo API - Account Routes

Handles all /api/accounts/* endpoints for managing IMAP accounts.
"""

import json
import time
from flask import request, jsonify
from core import Database
from core import IMAP, IMAPError
from . import api_bp


@api_bp.route("/accounts", methods=["GET"])
def list_accounts():
    """Get all email accounts."""
    accounts = Database.fetchall(
        "SELECT id, name, email, provider, last_sync FROM accounts ORDER BY name"
    )
    return jsonify({"accounts": [dict(a) for a in accounts]})


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
            return jsonify({
                "error": "Could not auto-detect IMAP server. Please enter server details manually."
            }), 400
    
    test_result = IMAP.test_connection(email_addr, password, host, port, use_ssl)
    if not test_result["success"]:
        return jsonify({"error": test_result["error"]}), 400
    
    cursor = Database.execute(
        "INSERT INTO accounts (name, email, provider) VALUES (?, ?, ?)",
        (name, email_addr, "imap")
    )
    Database.commit()
    
    account_id = cursor.lastrowid
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
        Database.execute(
            "UPDATE accounts SET last_sync = ? WHERE id = ?",
            (int(time.time()), account_id)
        )
        Database.commit()
    
    return jsonify(test_result)


@api_bp.route("/accounts/<int:account_id>/emails", methods=["GET"])
def get_account_emails(account_id):
    """Get emails from an IMAP account."""
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
    """Get a single email with full content for viewing."""
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
    """Get IMAP folders (mailboxes) for an account. Uses cache if fresh."""
    account = Database.fetchone(
        "SELECT id, credentials_encrypted, cached_folders, cached_folders_at FROM accounts WHERE id = ?",
        (account_id,)
    )
    if not account:
        return jsonify({"error": "Account not found"}), 404
    if not account["credentials_encrypted"]:
        return jsonify({"error": "Account not configured"}), 401
    
    force_refresh = request.args.get("refresh") == "1"
    cache_max_age = 3600
    
    if not force_refresh and account["cached_folders"] and account["cached_folders_at"]:
        cache_age = int(time.time()) - account["cached_folders_at"]
        if cache_age < cache_max_age:
            try:
                folders = json.loads(account["cached_folders"])
                return jsonify({"folders": folders, "cached": True})
            except json.JSONDecodeError:
                pass
    
    client = None
    try:
        client = IMAP.connect_with_credentials(account["credentials_encrypted"])
        folders = client.list_folders()
        
        Database.execute(
            "UPDATE accounts SET cached_folders = ?, cached_folders_at = ? WHERE id = ?",
            (json.dumps(folders), int(time.time()), account_id)
        )
        Database.commit()
        
        return jsonify({"folders": folders, "cached": False})
    except IMAPError as e:
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
        return jsonify({"detected": True, "host": host, "port": port})
    else:
        return jsonify({
            "detected": False,
            "message": "Could not auto-detect server. Please enter manually."
        })
