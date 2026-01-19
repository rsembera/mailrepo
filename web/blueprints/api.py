"""
MailRepo - API blueprint.

Provides JSON API endpoints for the frontend.
"""

import time
from flask import Blueprint, jsonify, request

from core import Database, Gmail, GmailError, Encryption, Config


api_bp = Blueprint("api", __name__, url_prefix="/api")


# ============================================
# FOLDERS
# ============================================

@api_bp.route("/folders", methods=["GET"])
def list_folders():
    """Get all archive folders."""
    folders = Database.fetchall(
        "SELECT id, name, parent_id, encrypted, created_at FROM folders ORDER BY name"
    )
    
    return jsonify({
        "folders": [dict(f) for f in folders]
    })


@api_bp.route("/folders", methods=["POST"])
def create_folder():
    """Create a new archive folder."""
    data = request.get_json()
    
    name = data.get("name", "").strip()
    encrypted = data.get("encrypted", True)
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
    
    # If nested folder, inherit encryption from parent
    if parent_id:
        parent = Database.fetchone("SELECT encrypted FROM folders WHERE id = ?", (parent_id,))
        if parent:
            encrypted = bool(parent["encrypted"])
    
    # Create folder
    cursor = Database.execute(
        "INSERT INTO folders (name, parent_id, encrypted) VALUES (?, ?, ?)",
        (name, parent_id, 1 if encrypted else 0)
    )
    Database.commit()
    
    folder_id = cursor.lastrowid
    
    return jsonify({
        "folder": {
            "id": folder_id,
            "name": name,
            "parent_id": parent_id,
            "encrypted": encrypted,
        }
    }), 201


@api_bp.route("/folders/<int:folder_id>", methods=["GET"])
def get_folder(folder_id):
    """Get a single folder."""
    folder = Database.fetchone(
        "SELECT id, name, parent_id, encrypted, created_at FROM folders WHERE id = ?",
        (folder_id,)
    )
    
    if not folder:
        return jsonify({"error": "Folder not found"}), 404
    
    return jsonify({"folder": dict(folder)})


@api_bp.route("/folders/<int:folder_id>", methods=["DELETE"])
def delete_folder(folder_id):
    """Delete a folder and its contents."""
    folder = Database.fetchone("SELECT id FROM folders WHERE id = ?", (folder_id,))
    
    if not folder:
        return jsonify({"error": "Folder not found"}), 404
    
    # Delete folder (CASCADE will delete messages)
    Database.execute("DELETE FROM folders WHERE id = ?", (folder_id,))
    Database.commit()
    
    return jsonify({"success": True})


@api_bp.route("/folders/<int:folder_id>/emails", methods=["GET"])
def get_folder_emails(folder_id):
    """Get all emails in an archive folder."""
    folder = Database.fetchone("SELECT id FROM folders WHERE id = ?", (folder_id,))
    
    if not folder:
        return jsonify({"error": "Folder not found"}), 404
    
    messages = Database.fetchall(
        """
        SELECT id, subject, sender, date, filepath, encrypted
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
            "encrypted": bool(m["encrypted"]),
        })
    
    return jsonify({"emails": emails})


# ============================================
# ACCOUNTS
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
    """Create a new email account (before OAuth)."""
    data = request.get_json()
    
    name = data.get("name", "").strip()
    provider = data.get("provider", "gmail")
    
    if not name:
        return jsonify({"error": "Account name is required"}), 400
    
    if provider not in ["gmail", "imap"]:
        return jsonify({"error": "Invalid provider"}), 400
    
    # Create account record (email will be populated after OAuth)
    cursor = Database.execute(
        "INSERT INTO accounts (name, email, provider) VALUES (?, ?, ?)",
        (name, "", provider)
    )
    Database.commit()
    
    return jsonify({
        "account": {
            "id": cursor.lastrowid,
            "name": name,
            "provider": provider,
        }
    }), 201


@api_bp.route("/accounts/<int:account_id>/authorize", methods=["POST"])
def authorize_account(account_id):
    """
    Start OAuth flow for a Gmail account.
    
    This will open a browser window for the user to sign in.
    """
    account = Database.fetchone(
        "SELECT id, provider FROM accounts WHERE id = ?",
        (account_id,)
    )
    
    if not account:
        return jsonify({"error": "Account not found"}), 404
    
    if account["provider"] != "gmail":
        return jsonify({"error": "OAuth only supported for Gmail accounts"}), 400
    
    # Check for credentials.json
    if not Gmail.has_client_credentials():
        return jsonify({
            "error": "credentials.json not found",
            "message": "Download OAuth credentials from Google Cloud Console and place in ~/mailrepo/config/credentials.json"
        }), 400
    
    try:
        # Run OAuth flow (opens browser)
        credentials = Gmail.authorize(account_id)
        
        # Get profile to update email address
        service = Gmail.get_service(credentials)
        profile = Gmail.get_profile(service)
        
        # Update account with email
        Database.execute(
            "UPDATE accounts SET email = ?, last_sync = ? WHERE id = ?",
            (profile["email"], int(time.time()), account_id)
        )
        Database.commit()
        
        return jsonify({
            "success": True,
            "email": profile["email"],
        })
        
    except GmailError as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/accounts/<int:account_id>/emails", methods=["GET"])
def get_account_emails(account_id):
    """
    Get emails from a Gmail account.
    
    Query params:
        label: Gmail label to filter by (default: INBOX)
        q: Search query
        max: Max results (default: 50)
        pageToken: Pagination token
    """
    account = Database.fetchone(
        "SELECT id, provider, credentials_encrypted FROM accounts WHERE id = ?",
        (account_id,)
    )
    
    if not account:
        return jsonify({"error": "Account not found"}), 404
    
    if account["provider"] != "gmail":
        return jsonify({"error": "Only Gmail accounts supported currently"}), 400
    
    if not account["credentials_encrypted"]:
        return jsonify({"error": "Account not authorized. Run OAuth flow first."}), 401
    
    try:
        # Get credentials
        credentials = Gmail.get_credentials(account_id, account["credentials_encrypted"])
        if not credentials:
            return jsonify({"error": "Failed to load credentials. Re-authorize account."}), 401
        
        # Build service
        service = Gmail.get_service(credentials)
        
        # Get params
        label = request.args.get("label", "INBOX")
        query = request.args.get("q")
        max_results = int(request.args.get("max", 50))
        page_token = request.args.get("pageToken")
        
        # List messages (just IDs)
        result = Gmail.list_messages(
            service,
            label_ids=[label] if label else None,
            query=query,
            max_results=max_results,
            page_token=page_token,
        )
        
        # Fetch metadata for each message
        emails = []
        for msg in result.get("messages", []):
            msg_data = Gmail.get_message(service, msg["id"], format="metadata")
            emails.append({
                "id": msg_data["id"],
                "threadId": msg_data["threadId"],
                "subject": msg_data["subject"],
                "sender": msg_data["from"],
                "date": msg_data["date"],
                "snippet": msg_data["snippet"],
                "labelIds": msg_data["labelIds"],
            })
        
        return jsonify({
            "emails": emails,
            "nextPageToken": result.get("nextPageToken"),
            "resultSizeEstimate": result.get("resultSizeEstimate"),
        })
        
    except GmailError as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/accounts/<int:account_id>/labels", methods=["GET"])
def get_account_labels(account_id):
    """Get Gmail labels (folders) for an account."""
    account = Database.fetchone(
        "SELECT id, provider, credentials_encrypted FROM accounts WHERE id = ?",
        (account_id,)
    )
    
    if not account:
        return jsonify({"error": "Account not found"}), 404
    
    if not account["credentials_encrypted"]:
        return jsonify({"error": "Account not authorized"}), 401
    
    try:
        credentials = Gmail.get_credentials(account_id, account["credentials_encrypted"])
        if not credentials:
            return jsonify({"error": "Failed to load credentials"}), 401
        
        service = Gmail.get_service(credentials)
        labels = Gmail.list_labels(service)
        
        return jsonify({"labels": labels})
        
    except GmailError as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/accounts/<int:account_id>", methods=["DELETE"])
def delete_account(account_id):
    """Delete an email account."""
    account = Database.fetchone("SELECT id FROM accounts WHERE id = ?", (account_id,))
    
    if not account:
        return jsonify({"error": "Account not found"}), 404
    
    Database.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    Database.commit()
    
    return jsonify({"success": True})


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
                "email": { id, subject, sender, date, ... },
                "destinationFolderId": 123,
                "sourceAccountId": 456,
                "sourceAction": "archive" | "trash" | "delete" | "leave"
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
            "SELECT id, provider, credentials_encrypted FROM accounts WHERE id = ?",
            (account_id,)
        )
        
        if not account or not account["credentials_encrypted"]:
            for item in items:
                results["failed"].append({
                    "id": item["email"].get("id"),
                    "error": "Account not found or not authorized",
                })
            continue
        
        try:
            credentials = Gmail.get_credentials(account_id, account["credentials_encrypted"])
            service = Gmail.get_service(credentials)
        except Exception as e:
            for item in items:
                results["failed"].append({
                    "id": item["email"].get("id"),
                    "error": f"Failed to connect: {e}",
                })
            continue
        
        # Process each email
        for item in items:
            email = item.get("email", {})
            folder_id = item.get("destinationFolderId")
            source_action = item.get("sourceAction", "leave")
            
            try:
                # Verify folder exists
                folder = Database.fetchone(
                    "SELECT id, encrypted FROM folders WHERE id = ?",
                    (folder_id,)
                )
                if not folder:
                    raise ValueError(f"Folder {folder_id} not found")
                
                # Download raw email
                raw_email = Gmail.get_message_raw(service, email["id"])
                
                # Determine filepath
                archive_path = Config.get_archive_path() / str(folder_id)
                archive_path.mkdir(parents=True, exist_ok=True)
                
                if folder["encrypted"]:
                    # Encrypt and save
                    encrypted_data = Encryption.encrypt(raw_email)
                    filepath = archive_path / f"{email['id']}.eml.enc"
                    filepath.write_bytes(encrypted_data)
                else:
                    # Save as plain .eml
                    filepath = archive_path / f"{email['id']}.eml"
                    filepath.write_bytes(raw_email)
                
                # Create database record
                Database.execute(
                    """
                    INSERT INTO messages 
                    (folder_id, source_account_id, message_id, subject, sender, date, filepath, encrypted)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        folder_id,
                        account_id,
                        email.get("id", ""),
                        email.get("subject", ""),
                        email.get("sender", ""),
                        email.get("date"),
                        str(filepath.relative_to(Config.get_base_path())),
                        1 if folder["encrypted"] else 0,
                    )
                )
                
                # Execute source action
                if source_action == "archive":
                    Gmail.archive_message(service, email["id"])
                elif source_action == "trash":
                    Gmail.trash_message(service, email["id"])
                elif source_action == "delete":
                    Gmail.delete_message(service, email["id"])
                # "leave" = do nothing
                
                results["success"].append(email.get("id"))
                
            except Exception as e:
                results["failed"].append({
                    "id": email.get("id"),
                    "error": str(e),
                })
    
    Database.commit()
    
    return jsonify({
        "results": results,
        "message": f"{len(results['success'])} emails filed successfully. {len(results['failed'])} failed."
    })


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
