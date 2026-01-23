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


@api_bp.route("/accounts/<int:account_id>/emails/stream", methods=["GET"])
def stream_account_emails(account_id):
    """
    Stream emails from an IMAP account with progress updates.
    
    Uses Server-Sent Events to report progress as emails are fetched.
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
    limit = int(request.args.get("limit", 50))
    
    def generate():
        client = None
        try:
            # Connection phase
            yield sse_message("status", {"phase": "connecting", "message": "Connecting to server..."})
            
            client = IMAP.connect_with_credentials(account["credentials_encrypted"])
            
            yield sse_message("status", {"phase": "selecting", "message": f"Opening {folder}..."})
            
            folder_info = client.select_folder(folder)
            
            yield sse_message("status", {"phase": "searching", "message": "Finding emails..."})
            
            uids = client.search("ALL", limit=limit)
            total = len(uids)
            
            yield sse_message("start", {"total": total, "folder": folder})
            
            # Fetch phase
            emails = []
            for i, uid in enumerate(uids):
                headers = client.fetch_headers(uid)
                emails.append(headers)
                
                # Send progress every email (or batch for very large sets)
                yield sse_message("progress", {
                    "current": i + 1,
                    "total": total,
                    "percent": int((i + 1) / total * 100) if total > 0 else 100,
                    "subject": headers.get("subject", "")[:50],
                })
            
            # Complete
            yield sse_message("complete", {"emails": emails, "total": total})
            
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
    Commit staged emails with progress streaming.
    
    Uses Server-Sent Events to report progress as emails are archived.
    """
    data = request.get_json()
    staged = data.get("staged", [])
    
    if not staged:
        return Response(
            sse_message("error", {"error": "No emails to commit"}),
            mimetype="text/event-stream"
        )
    
    def generate():
        results = {"success": [], "failed": [], "skipped": []}
        total = len(staged)
        
        yield sse_message("start", {"total": total, "type": "emails"})
        
        # Group by account
        by_account = {}
        for item in staged:
            acc_id = item.get("sourceAccountId")
            if acc_id not in by_account:
                by_account[acc_id] = []
            by_account[acc_id].append(item)
        
        processed = 0
        
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
                            yield sse_message("progress", {
                                "current": processed,
                                "total": total,
                                "percent": int(processed / total * 100),
                                "status": "success",
                                "subject": subject,
                            })
                            
                        except Exception as e:
                            results["failed"].append({"uid": uid, "error": str(e)})
                            yield sse_message("progress", {
                                "current": processed,
                                "total": total,
                                "percent": int(processed / total * 100),
                                "status": "failed",
                                "subject": subject,
                                "error": str(e),
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
        
        Database.commit()
        
        # Build summary message
        msg_parts = [f"{len(results['success'])} emails filed successfully"]
        if results["skipped"]:
            msg_parts.append(f"{len(results['skipped'])} skipped (already archived)")
        if results["failed"]:
            msg_parts.append(f"{len(results['failed'])} failed")
        
        yield sse_message("complete", {
            "results": results,
            "message": ". ".join(msg_parts) + ".",
        })
    
    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


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
