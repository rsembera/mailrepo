"""
MailRepo API - Progress Streaming Routes (SSE)

Server-Sent Events endpoints for real-time progress updates during
long-running operations like email loading and committing.
"""

import json
import time
from flask import request, Response, stream_with_context
from core import Database
from core import IMAP, IMAPError
from core import Config
from core import Encryption
from . import api_bp


def sse_message(event: str, data: dict) -> str:
    """Format a Server-Sent Event message."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _get_cached_emails(account_id: int, folder: str, uidvalidity: int) -> list[dict]:
    """Get cached email headers for a folder."""
    rows = Database.fetchall(
        """SELECT uid, subject, sender, recipients, date, message_id
           FROM email_cache
           WHERE account_id = ? AND folder_name = ? AND uidvalidity = ?
           ORDER BY CAST(uid AS INTEGER) DESC""",
        (account_id, folder, uidvalidity)
    )
    return [
        {
            "uid": row["uid"],
            "subject": row["subject"],
            "from": row["sender"],
            "to": row["recipients"],
            "date": row["date"],
            "message_id": row["message_id"],
        }
        for row in rows
    ]


def _get_highest_cached_uid(account_id: int, folder: str, uidvalidity: int) -> int:
    """Get the highest UID in cache for incremental sync."""
    row = Database.fetchone(
        """SELECT MAX(CAST(uid AS INTEGER)) as max_uid
           FROM email_cache
           WHERE account_id = ? AND folder_name = ? AND uidvalidity = ?""",
        (account_id, folder, uidvalidity)
    )
    return row["max_uid"] if row and row["max_uid"] else 0


def _clear_folder_cache(account_id: int, folder: str):
    """Clear cache for a folder (when UIDVALIDITY changes)."""
    Database.execute(
        "DELETE FROM email_cache WHERE account_id = ? AND folder_name = ?",
        (account_id, folder)
    )
    Database.commit()


def _get_any_cached_emails(account_id: int, folder: str) -> list[dict]:
    """Get cached emails regardless of UIDVALIDITY (for offline mode)."""
    rows = Database.fetchall(
        """SELECT uid, subject, sender, recipients, date, message_id
           FROM email_cache
           WHERE account_id = ? AND folder_name = ?
           ORDER BY CAST(uid AS INTEGER) DESC""",
        (account_id, folder)
    )
    return [
        {
            "uid": row["uid"],
            "subject": row["subject"],
            "from": row["sender"],
            "to": row["recipients"],
            "date": row["date"],
            "message_id": row["message_id"],
        }
        for row in rows
    ]


def _cache_email(account_id: int, folder: str, uidvalidity: int, email: dict):
    """Cache a single email header."""
    Database.execute(
        """INSERT OR REPLACE INTO email_cache
           (account_id, folder_name, uid, uidvalidity, subject, sender, recipients, date, message_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            account_id,
            folder,
            email.get("uid"),
            uidvalidity,
            email.get("subject"),
            email.get("from"),
            email.get("to"),
            email.get("date"),
            email.get("message_id"),
        )
    )


# ============================================
# FOLDER COMMIT HELPERS
# ============================================

def _create_archive_folder_from_path(archive_path: str, parent_folder_id: int) -> int:
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
    
    return current_parent_id


def _get_emails_from_import_folder(source_path: str, folder_path: str, import_type: str) -> list:
    """
    Get emails belonging DIRECTLY to a specific folder in an import.
    
    IMPORTANT: Only returns emails that are direct children of the folder,
    NOT emails from nested subfolders. This ensures that staging a parent
    folder without its children only archives the parent's direct emails.
    
    Args:
        source_path: Path to the mbox file or Apple Mail export root
        folder_path: Full path to the specific folder (e.g., "/path/to/Parent.mbox/Child.mbox")
        import_type: 'mbox', 'apple-mbox', or 'eml'
        
    Returns:
        List of (uid, raw_email_bytes) tuples
    """
    import os
    import mailbox
    
    results = []
    
    if import_type == 'eml':
        # EML directory - each .eml file is an email
        if os.path.isdir(source_path):
            for i, filename in enumerate(sorted(os.listdir(source_path))):
                if filename.lower().endswith('.eml'):
                    filepath = os.path.join(source_path, filename)
                    try:
                        with open(filepath, 'rb') as f:
                            raw_email = f.read()
                        results.append((f"eml-{i}", raw_email))
                    except Exception:
                        pass  # Skip unreadable files
        return results
    
    if import_type == 'apple-mbox':
        # Apple Mail export - folder_path points to a .mbox directory
        # Each .mbox dir has its own mbox file or Messages folder with only
        # that folder's direct emails - child folders are separate .mbox dirs
        mbox_internal = os.path.join(folder_path, 'mbox')
        if os.path.exists(mbox_internal):
            # Standard mbox file inside the .mbox directory
            try:
                mbox = mailbox.mbox(mbox_internal)
                for i, message in enumerate(mbox):
                    results.append((f"apple-{i}", message.as_bytes()))
            except Exception:
                pass  # Skip unreadable mbox
        else:
            # Check for emlx files in Messages subdirectory
            messages_dir = os.path.join(folder_path, 'Messages')
            if os.path.isdir(messages_dir):
                for i, filename in enumerate(sorted(os.listdir(messages_dir))):
                    if filename.endswith('.emlx'):
                        filepath = os.path.join(messages_dir, filename)
                        try:
                            with open(filepath, 'rb') as f:
                                content = f.read()
                            # emlx format: first line is byte count, then email, then plist
                            first_newline = content.find(b'\n')
                            if first_newline > 0:
                                email_content = content[first_newline + 1:]
                                plist_marker = email_content.rfind(b'<?xml version=')
                                if plist_marker > 0:
                                    email_content = email_content[:plist_marker]
                                results.append((f"emlx-{filename}", email_content))
                        except Exception:
                            pass  # Skip unreadable emlx
        return results
    
    # Regular mbox file - filter by folder header for exact match only
    # (emails in child folders have different X-Folder values)
    if import_type == 'mbox' and os.path.isfile(source_path):
        try:
            mbox = mailbox.mbox(source_path)
            for i, message in enumerate(mbox):
                # Check if email belongs to this folder
                email_folder = message.get("X-Folder") or message.get("X-Gmail-Labels") or ""
                
                # If folder_path is empty/root, include emails without folder or match exactly
                if not folder_path or email_folder == folder_path:
                    results.append((f"mbox-{i}", message.as_bytes()))
        except Exception:
            pass  # Skip unreadable mbox
    
    return results


@api_bp.route("/accounts/<int:account_id>/emails/stream", methods=["GET"])
def stream_account_emails(account_id):
    """
    Stream emails from an IMAP account with progress updates.
    
    Uses Server-Sent Events to report progress as emails are fetched.
    Implements caching with UIDVALIDITY for incremental sync.
    """
    account = Database.fetchone(
        "SELECT id, credentials_encrypted FROM accounts WHERE id = ?",
        (account_id,)
    )
    
    if not account:
        return Response(
            sse_message("error", {"error": "Account not found"}),
            mimetype="text/event-stream"
        )
    
    if not account["credentials_encrypted"]:
        return Response(
            sse_message("error", {"error": "Account not configured"}),
            mimetype="text/event-stream"
        )
    
    folder = request.args.get("folder", "INBOX")
    force_refresh = request.args.get("refresh", "").lower() == "true"
    
    def generate():
        client = None
        connection_failed = False
        cached_emails = []
        
        try:
            # Connection phase
            yield sse_message("status", {"phase": "connecting", "message": "Connecting to server..."})
            
            try:
                client = IMAP.connect_with_credentials(account["credentials_encrypted"])
            except IMAPError as e:
                # Connection failed - try to use cache
                connection_failed = True
                cached_emails = _get_any_cached_emails(account_id, folder)
                if cached_emails:
                    yield sse_message("status", {
                        "phase": "offline",
                        "message": f"Server unavailable. Showing {len(cached_emails)} cached emails."
                    })
                    yield sse_message("complete", {
                        "emails": cached_emails,
                        "total": len(cached_emails),
                        "from_cache": len(cached_emails),
                        "fetched": 0,
                        "offline": True,
                    })
                    return
                else:
                    raise e  # No cache, propagate the error
            
            yield sse_message("status", {"phase": "selecting", "message": f"Opening {folder}..."})
            
            folder_info = client.select_folder(folder)
            uidvalidity = folder_info.get("uidvalidity")
            
            # Check cache validity
            highest_cached_uid = 0
            cache_valid = False
            
            if uidvalidity and not force_refresh:
                # Check if we have valid cache
                cached_emails = _get_cached_emails(account_id, folder, uidvalidity)
                if cached_emails:
                    cache_valid = True
                    highest_cached_uid = _get_highest_cached_uid(account_id, folder, uidvalidity)
                    yield sse_message("status", {
                        "phase": "cache",
                        "message": f"Found {len(cached_emails)} cached emails, checking for new..."
                    })
            
            if force_refresh and uidvalidity:
                _clear_folder_cache(account_id, folder)
                cached_emails = []
                cache_valid = False
            
            yield sse_message("status", {"phase": "searching", "message": "Finding emails..."})
            
            # Get all UIDs from server
            all_uids = client.search("ALL", limit=0)
            
            # Determine which UIDs are new (not in cache)
            if cache_valid and highest_cached_uid > 0:
                # Only fetch UIDs higher than our cached max
                new_uids = [uid for uid in all_uids if int(uid) > highest_cached_uid]
            else:
                # Fetch everything - either no cache or cache invalid
                new_uids = all_uids
                if uidvalidity:
                    # Clear any stale cache (different uidvalidity)
                    _clear_folder_cache(account_id, folder)
            
            total_new = len(new_uids)
            total_cached = len(cached_emails)
            total = total_cached + total_new
            
            yield sse_message("start", {
                "total": total,
                "folder": folder,
                "cached": total_cached,
                "new": total_new,
            })
            
            # Start with cached emails (already have them)
            emails = list(cached_emails)
            
            # Fetch new emails
            if total_new > 0:
                for i, uid in enumerate(new_uids):
                    headers = client.fetch_headers(uid)
                    emails.insert(0, headers)  # Insert at beginning (newest first)
                    
                    # Cache the new email
                    if uidvalidity:
                        _cache_email(account_id, folder, uidvalidity, headers)
                    
                    # Send progress
                    current = total_cached + i + 1
                    yield sse_message("progress", {
                        "current": current,
                        "total": total,
                        "percent": int(current / total * 100) if total > 0 else 100,
                        "subject": headers.get("subject", "")[:50],
                        "phase": "fetching",
                    })
                
                # Commit cache updates
                if uidvalidity:
                    Database.commit()
            
            # Sort by UID descending (newest first)
            emails.sort(key=lambda e: int(e.get("uid", 0)), reverse=True)
            
            # Complete
            yield sse_message("complete", {
                "emails": emails,
                "total": len(emails),
                "from_cache": total_cached,
                "fetched": total_new,
            })
            
        except IMAPError as e:
            yield sse_message("error", {"error": str(e)})
        except Exception as e:
            yield sse_message("error", {"error": f"Unexpected error: {str(e)}"})
        finally:
            if client:
                try:
                    client.disconnect()
                except:
                    pass
    
    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


@api_bp.route("/commit/stream", methods=["POST"])
def stream_commit():
    """
    Commit staged emails and folders with progress streaming.
    
    Uses Server-Sent Events to report progress as items are archived.
    Supports post-commit actions (archive, trash, delete) for IMAP emails.
    """
    data = request.get_json()
    staged = data.get("staged", [])
    staged_folders = data.get("folders", [])
    source_actions = data.get("sourceActions", {})  # e.g., {"account:1:INBOX:5": "archive"}
    
    if not staged and not staged_folders:
        return Response(
            sse_message("error", {"error": "No items to commit"}),
            mimetype="text/event-stream"
        )
    
    def generate():
        results = {"success": [], "failed": [], "skipped": [], "folders_success": 0, "folders_failed": 0, "post_actions": {"success": 0, "failed": 0}}
        total = len(staged) + len(staged_folders)
        
        yield sse_message("start", {"total": total, "type": "mixed" if staged_folders else "emails"})
        
        # Separate imports from IMAP items
        import_items = [item for item in staged if item.get("sourceType") == "import"]
        imap_items = [item for item in staged if item.get("sourceType") != "import"]
        
        total_individual_emails = len(staged)
        processed = 0
        
        # Track successfully committed IMAP emails for post-actions
        # Structure: {account_id: {folder: [(uid, dest_folder_id), ...]}}
        committed_imap_emails = {}
        
        # Send phase 1 status if we have individual emails
        if total_individual_emails > 0:
            yield sse_message("status", {
                "phase": "emails",
                "message": f"Phase 1: Committing {total_individual_emails} email{'s' if total_individual_emails != 1 else ''}",
            })
        
        # Process imports first (no IMAP connection needed)
        for item in import_items:
            processed += 1
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
                if message_id:
                    existing = Database.fetchone(
                        "SELECT id FROM messages WHERE folder_id = ? AND message_id = ?",
                        (folder_id, message_id)
                    )
                    if existing:
                        results["skipped"].append({
                            "uid": uid,
                            "reason": "duplicate",
                            "subject": subject,
                        })
                        yield sse_message("progress", {
                            "current": processed,
                            "total": total,
                            "percent": int(processed / total * 100),
                            "status": "skipped",
                            "subject": subject,
                        })
                        continue
                
                # Get raw email from source file
                source_path = email_data.get("sourcePath")
                if not source_path:
                    raise ValueError("No source path for imported email")
                
                raw_email = _get_raw_email_from_import(source_path, uid)
                if not raw_email:
                    raise ValueError("Could not retrieve email content")
                
                body_text = _extract_body_text(raw_email)
                
                archive_path = Config.get_archive_path() / str(folder_id)
                archive_path.mkdir(parents=True, exist_ok=True)
                
                safe_id = f"import_{uid.replace('/', '_').replace(':', '_')}"
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
                        None,  # No source account for imports
                        message_id,
                        email_data.get("subject", ""),
                        email_data.get("from", email_data.get("sender", "")),
                        email_data.get("date"),
                        str(filepath.relative_to(Config.get_base_path())),
                        body_text,
                    )
                )
                
                results["success"].append(uid)
                
                # Commit every 10 emails for durability
                if processed % 10 == 0:
                    Database.commit()
                
                yield sse_message("progress", {
                    "current": processed,
                    "total": total_individual_emails,
                    "percent": int(processed / total_individual_emails * 100) if total_individual_emails > 0 else 100,
                    "status": "success",
                    "subject": subject,
                    "commitPhase": "emails",
                })
                
            except Exception as e:
                results["failed"].append({"uid": uid, "error": str(e)})
                yield sse_message("progress", {
                    "current": processed,
                    "total": total_individual_emails,
                    "percent": int(processed / total_individual_emails * 100) if total_individual_emails > 0 else 100,
                    "status": "failed",
                    "subject": subject,
                    "error": str(e),
                    "commitPhase": "emails",
                })
        
        # Group IMAP items by account
        by_account = {}
        for item in imap_items:
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
                    processed += 1
                    results["failed"].append({
                        "uid": item["email"].get("uid"),
                        "error": "Account not found or not configured",
                    })
                    yield sse_message("progress", {
                        "current": processed,
                        "total": total,
                        "percent": int(processed / total * 100),
                        "status": "failed",
                        "subject": item["email"].get("subject", "")[:50],
                    })
                continue
            
            client = None
            try:
                yield sse_message("status", {
                    "message": f"Connecting to account...",
                    "current": processed,
                    "total": total,
                })
                
                client = IMAP.connect_with_credentials(account["credentials_encrypted"])
                
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
                            processed += 1
                            results["failed"].append({
                                "uid": item["email"].get("uid"),
                                "error": f"Failed to select folder: {e}",
                            })
                            yield sse_message("progress", {
                                "current": processed,
                                "total": total,
                                "percent": int(processed / total * 100),
                                "status": "failed",
                            })
                        continue
                    
                    for item in folder_items:
                        processed += 1
                        email_data = item.get("email", {})
                        folder_id = item.get("destinationFolderId")
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
                            if message_id:
                                existing = Database.fetchone(
                                    "SELECT id FROM messages WHERE folder_id = ? AND message_id = ?",
                                    (folder_id, message_id)
                                )
                                if existing:
                                    results["skipped"].append({
                                        "uid": uid,
                                        "reason": "duplicate",
                                        "subject": subject,
                                    })
                                    yield sse_message("progress", {
                                        "current": processed,
                                        "total": total,
                                        "percent": int(processed / total * 100),
                                        "status": "skipped",
                                        "subject": subject,
                                    })
                                    continue
                            
                            # Fetch and save email
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
                                    message_id,
                                    email_data.get("subject", ""),
                                    email_data.get("from", email_data.get("sender", "")),
                                    email_data.get("date"),
                                    str(filepath.relative_to(Config.get_base_path())),
                                    body_text,
                                )
                            )
                            
                            results["success"].append(uid)
                            
                            # Track for post-commit actions
                            if account_id not in committed_imap_emails:
                                committed_imap_emails[account_id] = {}
                            if source_folder not in committed_imap_emails[account_id]:
                                committed_imap_emails[account_id][source_folder] = []
                            committed_imap_emails[account_id][source_folder].append((uid, folder_id))
                            
                            # Commit every 10 emails for durability
                            if processed % 10 == 0:
                                Database.commit()
                            
                            yield sse_message("progress", {
                                "current": processed,
                                "total": total_individual_emails,
                                "percent": int(processed / total_individual_emails * 100) if total_individual_emails > 0 else 100,
                                "status": "success",
                                "subject": subject,
                                "commitPhase": "emails",
                            })
                            
                        except Exception as e:
                            results["failed"].append({"uid": uid, "error": str(e)})
                            yield sse_message("progress", {
                                "current": processed,
                                "total": total_individual_emails,
                                "percent": int(processed / total_individual_emails * 100) if total_individual_emails > 0 else 100,
                                "status": "failed",
                                "subject": subject,
                                "error": str(e),
                                "commitPhase": "emails",
                            })
                
            except Exception as e:
                # Handle connection failures
                for item in items:
                    if item not in [i for acc_items in by_account.values() for i in acc_items if i.get("_processed")]:
                        processed += 1
                        results["failed"].append({
                            "uid": item["email"].get("uid"),
                            "error": f"Connection failed: {e}",
                        })
                        yield sse_message("progress", {
                            "current": processed,
                            "total": total,
                            "percent": int(processed / total * 100),
                            "status": "failed",
                        })
            finally:
                if client:
                    try:
                        client.disconnect()
                    except:
                        pass
        
        # ============================================
        # POST-COMMIT ACTIONS (archive, trash, delete on server)
        # ============================================
        
        if committed_imap_emails and source_actions:
            yield sse_message("status", {
                "phase": "post_actions",
                "message": "Applying post-commit actions on server...",
            })
            
            for account_id, folders_data in committed_imap_emails.items():
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
                        # Find the action for this source folder
                        # Keys are like "account:1:INBOX:5" where 5 is the dest folder id
                        # Or "account:1:5" for grouped sources
                        action = None
                        for key, act in source_actions.items():
                            # Check various key formats
                            if key.startswith(f"account:{account_id}"):
                                # Could be "account:1:5" or "account:1:INBOX:5"
                                parts = key.split(':')
                                if len(parts) >= 3:
                                    # Check if this key matches our folder
                                    if len(parts) == 3:
                                        # "account:1:5" format - applies to all folders for this dest
                                        action = act
                                        break
                                    elif len(parts) >= 4 and parts[2] == source_folder:
                                        # "account:1:INBOX:5" format
                                        action = act
                                        break
                        
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
                    for folders_data in folders_data.values():
                        results["post_actions"]["failed"] += len(folders_data)
                finally:
                    if client:
                        try:
                            client.disconnect()
                        except:
                            pass
        
        # ============================================
        # PHASE 2: Process Staged Folders
        # ============================================
        
        folder_count = len(staged_folders)
        
        # Send phase 2 status if we have folders
        if folder_count > 0:
            phase_label = "Phase 2" if total_individual_emails > 0 else "Phase 1"
            yield sse_message("status", {
                "phase": "folders",
                "message": f"{phase_label}: Committing {folder_count} folder{'s' if folder_count != 1 else ''}",
            })
        
        for folder_idx, folder_item in enumerate(staged_folders):
            source_type = folder_item.get("sourceType")
            archive_path = folder_item.get("archivePath", "")
            dest_folder_id = folder_item.get("destinationFolderId")
            folder_name = archive_path.split('/')[-1] if archive_path else "folder"
            
            try:
                # Create archive folder structure from archivePath
                target_folder_id = _create_archive_folder_from_path(archive_path, dest_folder_id)
                
                if source_type == "import":
                    # Import folder commit
                    import_path = folder_item.get("importPath")
                    folder_path = folder_item.get("folder")
                    import_type = folder_item.get("importType", "apple-mbox")
                    
                    emails = _get_emails_from_import_folder(import_path, folder_path, import_type)
                    folder_email_count = len(emails)
                    
                    # Send status update for this folder
                    yield sse_message("status", {
                        "phase": "folder",
                        "message": f"Folder {folder_idx + 1} of {folder_count}: {folder_name} ({folder_email_count} emails)",
                        "folderIndex": folder_idx + 1,
                        "folderCount": folder_count,
                    })
                    
                    for i, (uid, raw_email) in enumerate(emails):
                        try:
                            # Parse email for metadata first (so we can show subject in progress)
                            import email as email_lib
                            from email.header import decode_header
                            from email.utils import parsedate_to_datetime
                            
                            msg = email_lib.message_from_bytes(raw_email)
                            
                            def decode_hdr(h):
                                if not h: return ""
                                try:
                                    parts = decode_header(h)
                                    return " ".join(
                                        p.decode(c or "utf-8", errors="replace") if isinstance(p, bytes) else p
                                        for p, c in parts
                                    )
                                except: return str(h)
                            
                            subject = decode_hdr(msg.get("Subject", ""))[:50] or "(no subject)"
                            sender = decode_hdr(msg.get("From", ""))
                            message_id = msg.get("Message-ID", "")
                            date_str = msg.get("Date", "")
                            try:
                                date_ts = parsedate_to_datetime(date_str).isoformat() if date_str else None
                            except:
                                date_ts = date_str
                            
                            body_text = _extract_body_text(raw_email)
                            
                            file_path = Config.get_archive_path() / str(target_folder_id)
                            file_path.mkdir(parents=True, exist_ok=True)
                            
                            safe_id = f"import_{uid.replace('/', '_').replace(':', '_')}"
                            encrypted_data = Encryption.encrypt(raw_email)
                            filepath = file_path / f"{safe_id}.eml.enc"
                            filepath.write_bytes(encrypted_data)
                            
                            Database.execute(
                                """INSERT INTO messages 
                                   (folder_id, source_account_id, message_id, subject, sender, date, filepath, body_text)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                                (target_folder_id, None, message_id, subject, sender, date_ts,
                                 str(filepath.relative_to(Config.get_base_path())), body_text)
                            )
                            results["success"].append(uid)
                            
                            # Commit every 10 emails for durability
                            if (i + 1) % 10 == 0:
                                Database.commit()
                            
                            # Send per-email progress
                            yield sse_message("progress", {
                                "current": i + 1,
                                "total": folder_email_count,
                                "percent": int((i + 1) / folder_email_count * 100) if folder_email_count > 0 else 100,
                                "status": "success",
                                "subject": subject,
                                "folder": folder_name,
                                "folderIndex": folder_idx + 1,
                                "folderCount": folder_count,
                                "commitPhase": "folders",
                            })
                        except Exception as e:
                            results["failed"].append({"uid": uid, "error": str(e)})
                            yield sse_message("progress", {
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
                            })
                else:
                    # IMAP folder commit
                    account_id = folder_item.get("accountId")
                    imap_folder = folder_item.get("folder")
                    
                    account = Database.fetchone(
                        "SELECT credentials_encrypted FROM accounts WHERE id = ?", (account_id,)
                    )
                    if not account:
                        raise ValueError(f"Account {account_id} not found")
                    
                    client = IMAP.connect_with_credentials(account["credentials_encrypted"])
                    try:
                        folder_info = client.select_folder(imap_folder)
                        if folder_info.get("message_count", 0) > 0:
                            uids = client.search(criteria="ALL", limit=0)
                            folder_email_count = len(uids)
                            
                            # Send status update for this folder
                            yield sse_message("status", {
                                "phase": "folder",
                                "message": f"Folder {folder_idx + 1} of {folder_count}: {folder_name} ({folder_email_count} emails)",
                                "folderIndex": folder_idx + 1,
                                "folderCount": folder_count,
                            })
                            
                            for i, uid in enumerate(uids):
                                try:
                                    email_data = client.fetch_full(uid)
                                    raw_email = client.fetch_raw(uid)
                                    subject = (email_data.get("subject", "") or "(no subject)")[:50]
                                    
                                    if not raw_email:
                                        results["failed"].append({"uid": uid, "error": "Empty"})
                                        yield sse_message("progress", {
                                            "current": i + 1,
                                            "total": folder_email_count,
                                            "percent": int((i + 1) / folder_email_count * 100),
                                            "status": "failed",
                                            "subject": subject,
                                            "folder": folder_name,
                                            "folderIndex": folder_idx + 1,
                                            "folderCount": folder_count,
                                            "commitPhase": "folders",
                                        })
                                        continue
                                    
                                    message_id = email_data.get("message_id", "")
                                    if message_id:
                                        existing = Database.fetchone(
                                            "SELECT id FROM messages WHERE folder_id = ? AND message_id = ?",
                                            (target_folder_id, message_id)
                                        )
                                        if existing:
                                            results["skipped"].append({"uid": uid})
                                            yield sse_message("progress", {
                                                "current": i + 1,
                                                "total": folder_email_count,
                                                "percent": int((i + 1) / folder_email_count * 100),
                                                "status": "skipped",
                                                "subject": subject,
                                                "folder": folder_name,
                                                "folderIndex": folder_idx + 1,
                                                "folderCount": folder_count,
                                                "commitPhase": "folders",
                                            })
                                            continue
                                    
                                    body_text = _extract_body_text(raw_email)
                                    file_path = Config.get_archive_path() / str(target_folder_id)
                                    file_path.mkdir(parents=True, exist_ok=True)
                                    
                                    safe_id = f"{account_id}_{uid}"
                                    encrypted_data = Encryption.encrypt(raw_email)
                                    filepath = file_path / f"{safe_id}.eml.enc"
                                    filepath.write_bytes(encrypted_data)
                                    
                                    Database.execute(
                                        """INSERT INTO messages 
                                           (folder_id, source_account_id, message_id, subject, sender, date, filepath, body_text)
                                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                                        (target_folder_id, account_id, message_id,
                                         email_data.get("subject", ""), email_data.get("from", ""),
                                         email_data.get("date"), str(filepath.relative_to(Config.get_base_path())), body_text)
                                    )
                                    results["success"].append(uid)
                                    
                                    # Commit every 10 emails for durability
                                    if (i + 1) % 10 == 0:
                                        Database.commit()
                                    
                                    # Send per-email progress
                                    yield sse_message("progress", {
                                        "current": i + 1,
                                        "total": folder_email_count,
                                        "percent": int((i + 1) / folder_email_count * 100),
                                        "status": "success",
                                        "subject": subject,
                                        "folder": folder_name,
                                        "folderIndex": folder_idx + 1,
                                        "folderCount": folder_count,
                                        "commitPhase": "folders",
                                    })
                                except Exception as e:
                                    results["failed"].append({"uid": uid, "error": str(e)})
                                    yield sse_message("progress", {
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
                                    })
                    finally:
                        client.disconnect()
                
                results["folders_success"] += 1
                # Commit after each folder completes
                Database.commit()
            except Exception as e:
                results["folders_failed"] += 1
                yield sse_message("progress", {
                    "current": 0,
                    "total": 0,
                    "percent": 0,
                    "status": "folder_failed", 
                    "folder": folder_name, 
                    "error": str(e),
                })
        
        # Increment processed for folder count tracking (after all folders done)
        processed += len(staged_folders)
        
        Database.commit()
        
        # Build summary message
        msg_parts = []
        if results["success"]:
            msg_parts.append(f"{len(results['success'])} emails filed")
        if results["folders_success"]:
            msg_parts.append(f"{results['folders_success']} folder{'s' if results['folders_success'] != 1 else ''} archived")
        if results["skipped"]:
            msg_parts.append(f"{len(results['skipped'])} skipped (duplicate{'s' if len(results['skipped']) != 1 else ''})")
        if results["failed"] or results["folders_failed"]:
            fail_count = len(results["failed"]) + results["folders_failed"]
            msg_parts.append(f"{fail_count} failed")
        if results["post_actions"]["success"]:
            msg_parts.append(f"{results['post_actions']['success']} server action{'s' if results['post_actions']['success'] != 1 else ''} applied")
        if results["post_actions"]["failed"]:
            msg_parts.append(f"{results['post_actions']['failed']} server action{'s' if results['post_actions']['failed'] != 1 else ''} failed")
        
        yield sse_message("complete", {
            "results": results,
            "message": ". ".join(msg_parts) + "." if msg_parts else "Nothing committed.",
        })
    
    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


def _get_raw_email_from_import(source_path: str, uid: str) -> bytes:
    """
    Get raw email content from an imported source.
    
    Args:
        source_path: Path to mbox file or emlx/eml file
        uid: Email UID (e.g., "mbox-5" or "emlx-12345.emlx")
        
    Returns:
        Raw email bytes
    """
    import os
    import mailbox
    
    if not source_path or not os.path.exists(source_path):
        return None
    
    # Handle .emlx files (Apple Mail format)
    if source_path.endswith('.emlx'):
        try:
            with open(source_path, 'rb') as f:
                content = f.read()
            # .emlx files start with a line containing the byte count, skip it
            first_newline = content.find(b'\n')
            if first_newline > 0:
                email_content = content[first_newline + 1:]
                # Find where the email ends (before Apple's plist metadata)
                plist_marker = email_content.rfind(b'<?xml version=')
                if plist_marker > 0:
                    email_content = email_content[:plist_marker]
                return email_content
        except Exception:
            return None
    
    # Handle mbox files
    if uid.startswith('mbox-') or uid.startswith('apple-'):
        try:
            # Extract index from uid (e.g., "mbox-5" -> 5)
            parts = uid.split('-')
            if len(parts) >= 2:
                # Could be "mbox-5" or "apple-filename.mbox-5"
                index = int(parts[-1])
                
                mbox = mailbox.mbox(source_path)
                for i, message in enumerate(mbox):
                    if i == index:
                        return message.as_bytes()
        except Exception:
            return None
    
    # Handle standalone .eml files
    if source_path.endswith('.eml'):
        try:
            with open(source_path, 'rb') as f:
                return f.read()
        except Exception:
            return None
    
    return None


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
