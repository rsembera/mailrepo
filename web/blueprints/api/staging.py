"""
MailRepo API - Staging & Commit Routes

Handles committing staged emails and folders to the archive.
"""

from flask import request, jsonify
from core import Database
from core import Config
from core import Encryption
from core import IMAP, IMAPError
from . import api_bp


def _extract_body_text(raw_email: bytes) -> str:
    """Extract plain text from email for full-text search indexing."""
    import email
    from email.header import decode_header
    
    try:
        msg = email.message_from_bytes(raw_email)
        text_parts = []
        
        def decode_part(part):
            payload = part.get_payload(decode=True)
            if payload:
                charset = part.get_content_charset() or 'utf-8'
                try:
                    return payload.decode(charset, errors='replace')
                except:
                    return payload.decode('utf-8', errors='replace')
            return ""
        
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == 'text/plain':
                    text_parts.append(decode_part(part))
        else:
            if msg.get_content_type() == 'text/plain':
                text_parts.append(decode_part(msg))
        
        return "\n".join(text_parts)[:10000]
    except:
        return ""


@api_bp.route("/commit", methods=["POST"])
def commit_staged():
    """Commit staged emails to archive."""
    data = request.get_json()
    staged = data.get("staged", [])
    
    if not staged:
        return jsonify({"error": "No emails to commit"}), 400
    
    results = {"success": [], "failed": [], "skipped": []}
    
    # Group by account
    by_account = {}
    for item in staged:
        acc_id = item.get("sourceAccountId")
        if acc_id not in by_account:
            by_account[acc_id] = []
        by_account[acc_id].append(item)
    
    for account_id, items in by_account.items():
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
                    folder = Database.fetchone(
                        "SELECT id FROM folders WHERE id = ?", (folder_id,)
                    )
                    if not folder:
                        raise ValueError(f"Folder {folder_id} not found")
                    
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
                    
                    raw_email = client.fetch_raw(uid)
                    body_text = _extract_body_text(raw_email)
                    
                    archive_path = Config.get_archive_path() / str(folder_id)
                    archive_path.mkdir(parents=True, exist_ok=True)
                    
                    safe_id = f"{account_id}_{uid}"
                    encrypted_data = Encryption.encrypt(raw_email)
                    filepath = archive_path / f"{safe_id}.eml.enc"
                    filepath.write_bytes(encrypted_data)

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
                    results["failed"].append({"uid": uid, "error": str(e)})
        
        if client:
            client.disconnect()
    
    Database.commit()
    
    msg_parts = [f"{len(results['success'])} emails filed successfully"]
    if results["skipped"]:
        msg_parts.append(f"{len(results['skipped'])} skipped (already archived)")
    if results["failed"]:
        msg_parts.append(f"{len(results['failed'])} failed")
    
    return jsonify({"results": results, "message": ". ".join(msg_parts) + "."})


def _create_archive_folder_path(imap_folder: str, delimiter: str, parent_id: int) -> tuple[int, int]:
    """
    Create archive folders to mirror the IMAP folder path.
    
    Returns:
        Tuple of (final_folder_id, folders_created_count)
    """
    parts = imap_folder.split(delimiter)
    current_parent_id = parent_id
    folders_created = 0
    
    for part in parts:
        existing = Database.fetchone(
            "SELECT id FROM folders WHERE name = ? AND parent_id = ? AND deleted_at IS NULL",
            (part, current_parent_id)
        )
        if existing:
            current_parent_id = existing["id"]
        else:
            cursor = Database.execute(
                "INSERT INTO folders (name, parent_id) VALUES (?, ?)",
                (part, current_parent_id)
            )
            current_parent_id = cursor.lastrowid
            folders_created += 1
    
    return current_parent_id, folders_created


@api_bp.route("/commit-folders", methods=["POST"])
def commit_folders():
    """Commit staged folders to archive."""
    data = request.get_json()
    account_id = data.get("accountId")
    imap_folders = data.get("folders", [])
    dest_folder_id = data.get("destinationFolderId")
    
    if not account_id or not imap_folders or not dest_folder_id:
        return jsonify({"error": "Missing required fields"}), 400
    
    account = Database.fetchone(
        "SELECT id, credentials_encrypted FROM accounts WHERE id = ?",
        (account_id,)
    )
    if not account or not account["credentials_encrypted"]:
        return jsonify({"error": "Account not found or not configured"}), 404
    
    dest_folder = Database.fetchone(
        "SELECT id, name FROM folders WHERE id = ? AND deleted_at IS NULL",
        (dest_folder_id,)
    )
    if not dest_folder:
        return jsonify({"error": "Destination folder not found"}), 404

    results = {"success": 0, "failed": 0, "skipped": 0, "folders_created": 0}
    
    client = None
    try:
        client = IMAP.connect_with_credentials(account["credentials_encrypted"])
        all_folders = client.list_folders()
        delimiter = all_folders[0].get("delimiter", "/") if all_folders else "/"
        
        for imap_folder in imap_folders:
            try:
                archive_folder_id, created_count = _create_archive_folder_path(
                    imap_folder, delimiter, dest_folder_id
                )
                results["folders_created"] += created_count
                
                folder_info = client.select_folder(imap_folder)
                if folder_info.get("message_count", 0) == 0:
                    continue
                
                # Get all emails in this folder (no limit for archiving)
                uids = client.search(criteria="ALL", limit=10000)
                
                for uid in uids:
                    try:
                        email_data = client.fetch_full(uid)
                        raw_email = client.fetch_raw(uid)
                        
                        if not raw_email:
                            results["failed"] += 1
                            continue
                        
                        message_id = email_data.get("message_id", "")
                        if message_id:
                            existing = Database.fetchone(
                                "SELECT id FROM messages WHERE folder_id = ? AND message_id = ?",
                                (archive_folder_id, message_id)
                            )
                            if existing:
                                results["skipped"] += 1
                                continue
                        # Extract body text for search indexing
                        body_text = (email_data.get("text_body") or "")[:10000]
                        
                        archive_path = Config.get_base_path() / "archive" / str(archive_folder_id)
                        archive_path.mkdir(parents=True, exist_ok=True)

                        safe_id = f"{account_id}_{uid}"
                        encrypted_data = Encryption.encrypt(raw_email)
                        filepath = archive_path / f"{safe_id}.eml.enc"
                        filepath.write_bytes(encrypted_data)
                        
                        Database.execute(
                            """
                            INSERT INTO messages 
                            (folder_id, source_account_id, message_id, subject, sender, date, filepath, body_text)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                archive_folder_id,
                                account_id,
                                message_id,
                                email_data.get("subject", ""),
                                email_data.get("from", email_data.get("sender", "")),
                                email_data.get("date"),
                                str(filepath.relative_to(Config.get_base_path())),
                                body_text,
                            )
                        )
                        results["success"] += 1
                    except Exception:
                        results["failed"] += 1
            except IMAPError:
                results["failed"] += 1
        
        Database.commit()
    except Exception as e:
        return jsonify({"error": f"Failed to connect: {e}"}), 500
    finally:
        if client:
            client.disconnect()
    
    msg_parts = [f"{results['success']} emails archived"]
    if results["folders_created"]:
        msg_parts.append(f"{results['folders_created']} folders created")
    if results["skipped"]:
        msg_parts.append(f"{results['skipped']} skipped (duplicates)")
    if results["failed"]:
        msg_parts.append(f"{results['failed']} failed")
    
    return jsonify({"results": results, "message": ". ".join(msg_parts) + "."})
