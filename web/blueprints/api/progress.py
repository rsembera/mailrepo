"""
MailRepo API - Progress Streaming Routes (SSE)

Server-Sent Events endpoints for real-time progress updates during
long-running operations like email loading and committing.

This module serves as the coordinator, delegating to:
- streaming.py: Email cache management
- commit.py: Commit workflow logic
- email_parser.py: Email parsing utilities
"""

import json
from flask import request, Response, stream_with_context
from core import Database
from core import IMAP, IMAPError
from . import api_bp
from .streaming import (
    get_cached_emails,
    get_highest_cached_uid,
    clear_folder_cache,
    get_any_cached_emails,
    cache_email,
)
from .commit import (
    create_archive_folder_from_path,
    commit_import_email,
    commit_imap_email,
    commit_import_folder,
    commit_imap_folder,
    apply_post_commit_actions,
    build_commit_summary,
)


def sse_message(event: str, data: dict) -> str:
    """Format a Server-Sent Event message."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


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
        cached_emails = []
        
        try:
            # Connection phase
            yield sse_message("status", {"phase": "connecting", "message": "Connecting to server..."})
            
            try:
                client = IMAP.connect_with_credentials(account["credentials_encrypted"])
            except IMAPError as e:
                # Connection failed - try to use cache
                cached_emails = get_any_cached_emails(account_id, folder)
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
                    raise e

            yield sse_message("status", {"phase": "selecting", "message": f"Opening {folder}..."})
            
            folder_info = client.select_folder(folder)
            uidvalidity = folder_info.get("uidvalidity")
            
            # Check cache validity
            highest_cached_uid = 0
            cache_valid = False
            
            if uidvalidity and not force_refresh:
                cached_emails = get_cached_emails(account_id, folder, uidvalidity)
                if cached_emails:
                    cache_valid = True
                    highest_cached_uid = get_highest_cached_uid(account_id, folder, uidvalidity)
                    yield sse_message("status", {
                        "phase": "cache",
                        "message": f"Found {len(cached_emails)} cached emails, checking for new..."
                    })
            
            if force_refresh and uidvalidity:
                clear_folder_cache(account_id, folder)
                cached_emails = []
                cache_valid = False
            
            yield sse_message("status", {"phase": "searching", "message": "Finding emails..."})
            
            # Get all UIDs from server
            all_uids = client.search("ALL", limit=0)
            
            # Determine which UIDs are new (not in cache)
            if cache_valid and highest_cached_uid > 0:
                new_uids = [uid for uid in all_uids if int(uid) > highest_cached_uid]
            else:
                new_uids = all_uids
                if uidvalidity:
                    clear_folder_cache(account_id, folder)
            
            total_new = len(new_uids)
            total_cached = len(cached_emails)
            total = total_cached + total_new
            
            yield sse_message("start", {
                "total": total,
                "folder": folder,
                "cached": total_cached,
                "new": total_new,
            })
            
            # Start with cached emails
            emails = list(cached_emails)

            # Fetch new emails
            if total_new > 0:
                for i, uid in enumerate(new_uids):
                    headers = client.fetch_headers(uid)
                    emails.insert(0, headers)
                    
                    if uidvalidity:
                        cache_email(account_id, folder, uidvalidity, headers)
                    
                    current = total_cached + i + 1
                    yield sse_message("progress", {
                        "current": current,
                        "total": total,
                        "percent": int(current / total * 100) if total > 0 else 100,
                        "subject": headers.get("subject", "")[:50],
                        "phase": "fetching",
                    })
                
                if uidvalidity:
                    Database.commit()
            
            # Sort by UID descending (newest first)
            emails.sort(key=lambda e: int(e.get("uid", 0)), reverse=True)
            
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
            "X-Accel-Buffering": "no",
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
    source_actions = data.get("sourceActions", {})
    
    if not staged and not staged_folders:
        return Response(
            sse_message("error", {"error": "No items to commit"}),
            mimetype="text/event-stream"
        )
    
    def generate():
        results = {
            "success": [], 
            "failed": [], 
            "skipped": [], 
            "folders_success": 0, 
            "folders_failed": 0, 
            "post_actions": {"success": 0, "failed": 0}
        }
        total = len(staged) + len(staged_folders)
        
        yield sse_message("start", {"total": total, "type": "mixed" if staged_folders else "emails"})
        
        # Separate imports from IMAP items
        import_items = [item for item in staged if item.get("sourceType") == "import"]
        imap_items = [item for item in staged if item.get("sourceType") != "import"]
        
        total_individual_emails = len(staged)
        processed = 0
        committed_imap_emails = {}  # Track for post-actions
        
        # Phase 1: Individual emails
        if total_individual_emails > 0:
            yield sse_message("status", {
                "phase": "emails",
                "message": f"Phase 1: Committing {total_individual_emails} email{'s' if total_individual_emails != 1 else ''}",
            })
        
        # Process imports first (no IMAP connection needed)
        for item in import_items:
            processed += 1
            result = commit_import_email(item, results)
            
            if processed % 10 == 0:
                Database.commit()
            
            yield sse_message("progress", {
                "current": processed,
                "total": total_individual_emails,
                "percent": int(processed / total_individual_emails * 100) if total_individual_emails > 0 else 100,
                "status": result["status"],
                "subject": result["subject"],
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
                    "message": "Connecting to account...",
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
                        
                        result = commit_imap_email(
                            client, account_id, email_data, folder_id,
                            source_folder, results, committed_imap_emails
                        )
                        
                        if processed % 10 == 0:
                            Database.commit()
                        
                        yield sse_message("progress", {
                            "current": processed,
                            "total": total_individual_emails,
                            "percent": int(processed / total_individual_emails * 100) if total_individual_emails > 0 else 100,
                            "status": result["status"],
                            "subject": result["subject"],
                            "commitPhase": "emails",
                        })
                
            except Exception as e:
                for item in items:
                    if not any(r.get("uid") == item["email"].get("uid") for r in results["failed"]):
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

        # Post-commit actions
        for event in apply_post_commit_actions(committed_imap_emails, source_actions, results):
            yield sse_message(event["type"], {k: v for k, v in event.items() if k != "type"})
        
        # Phase 2: Staged folders
        folder_count = len(staged_folders)
        
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
                target_folder_id = create_archive_folder_from_path(archive_path, dest_folder_id)
                
                if source_type == "import":
                    for event in commit_import_folder(folder_item, target_folder_id, folder_idx, folder_count, results):
                        yield sse_message(event["type"], {k: v for k, v in event.items() if k != "type"})
                else:
                    for event in commit_imap_folder(folder_item, target_folder_id, folder_idx, folder_count, results):
                        yield sse_message(event["type"], {k: v for k, v in event.items() if k != "type"})
                
                results["folders_success"] += 1
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
        
        Database.commit()
        
        yield sse_message("complete", {
            "results": results,
            "message": build_commit_summary(results),
        })
    
    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )
