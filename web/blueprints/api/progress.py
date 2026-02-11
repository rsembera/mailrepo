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
import logging
from flask import request, Response, stream_with_context
from core import Database
from core import IMAP, IMAPError

logger = logging.getLogger(__name__)
from core.pending_commit import (
    create_commit_session,
    get_pending_items,
    get_committed_items_needing_post_action,
    mark_item_committed,
    mark_item_done,
    mark_all_committed_as_done,
    clear_commit_session,
)
from . import api_bp
from .streaming import (
    get_cached_emails,
    get_highest_cached_uid,
    clear_folder_cache,
    get_any_cached_emails,
    cache_email,
    remove_stale_cache_entries,
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


@api_bp.route("/commit/pending", methods=["GET"])
def check_pending_commit():
    """Check if there's an interrupted commit that can be resumed."""
    from core.pending_commit import get_pending_commit
    from flask import jsonify
    
    pending = get_pending_commit()
    if pending:
        return jsonify({
            "hasPending": True,
            "commitId": pending['commit_id'],
            "total": pending['total'],
            "pending": pending['pending'],
            "committed": pending['committed'],
            "createdAt": pending['created_at'],
        })
    return jsonify({"hasPending": False})


@api_bp.route("/commit/discard", methods=["POST"])
def discard_pending_commit():
    """Discard an interrupted commit (user chose not to resume)."""
    from core.pending_commit import discard_pending_commit as do_discard
    from flask import jsonify, request
    
    data = request.get_json() or {}
    commit_id = data.get("commitId")
    
    if not commit_id:
        return jsonify({"error": "commitId required"}), 400
    
    do_discard(commit_id)
    return jsonify({"success": True})


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
            
            # Remove cached emails that no longer exist on server
            stale_removed = 0
            if cache_valid and uidvalidity:
                stale_removed = remove_stale_cache_entries(account_id, folder, uidvalidity, all_uids)
                if stale_removed > 0:
                    # Refresh cached_emails after removing stale entries
                    cached_emails = get_cached_emails(account_id, folder, uidvalidity)
            
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
    
    All items are saved to pending_commit table before starting, allowing
    resume if interrupted.
    """
    data = request.get_json()
    staged = data.get("staged", [])
    staged_folders = data.get("folders", [])
    source_actions = data.get("sourceActions", {})
    resume_commit_id = data.get("resumeCommitId")  # If resuming interrupted commit
    
    if not staged and not staged_folders and not resume_commit_id:
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
            "post_actions": {"success": 0, "failed": 0, "by_action": {"archive": 0, "trash": 0, "delete": 0}}
        }
        
        # Either resume existing commit or create new one
        if resume_commit_id:
            commit_id = resume_commit_id
            yield sse_message("status", {"phase": "resuming", "message": "Resuming interrupted commit..."})
        else:
            # Save all items to pending_commit before starting
            commit_id = create_commit_session(staged, staged_folders, source_actions)
        
        # Get pending items from database
        pending_items = get_pending_items(commit_id, 'pending')
        pending_emails = [p for p in pending_items if p['item_type'] == 'email']
        pending_folders = [p for p in pending_items if p['item_type'] == 'folder']
        
        total = len(pending_emails) + len(pending_folders)
        
        if total == 0:
            # Check if we just need post-actions
            items_needing_post = get_committed_items_needing_post_action(commit_id)
            if items_needing_post:
                yield sse_message("status", {"phase": "post_actions", "message": "Updating server..."})
                yield from _apply_post_actions_from_pending(commit_id, items_needing_post, results)
            
            clear_commit_session(commit_id)
            yield sse_message("complete", {
                "results": results,
                "message": build_commit_summary(results) or "Nothing to commit.",
            })
            return
        
        yield sse_message("start", {"total": total, "type": "mixed" if pending_folders else "emails", "commitId": commit_id})
        
        # Separate imports from IMAP items
        import_emails = [p for p in pending_emails if p['item_data'].get('sourceType') == 'import']
        imap_emails = [p for p in pending_emails if p['item_data'].get('sourceType') != 'import']
        
        total_emails = len(pending_emails)
        processed = 0
        
        # Phase 1: Individual emails
        if total_emails > 0:
            yield sse_message("status", {
                "phase": "emails",
                "message": f"Committing {total_emails} email{'s' if total_emails != 1 else ''}",
            })
        
        # Process imports first (no IMAP connection needed)
        for pending_item in import_emails:
            processed += 1
            item = pending_item['item_data']
            result = commit_import_email(item, results)
            
            # Mark as committed in pending_commit table
            if result["status"] in ("success", "skipped"):
                mark_item_done(pending_item['id'])  # Imports don't need post-action
            else:
                mark_item_committed(pending_item['id'])  # Keep for retry visibility
            
            if processed % 10 == 0:
                Database.commit()
            
            yield sse_message("progress", {
                "current": processed,
                "total": total_emails,
                "percent": int(processed / total_emails * 100) if total_emails > 0 else 100,
                "status": result["status"],
                "subject": result["subject"],
                "commitPhase": "emails",
            })

        # Group IMAP items by account
        by_account = {}
        for pending_item in imap_emails:
            item = pending_item['item_data']
            acc_id = item.get("sourceAccountId")
            if acc_id not in by_account:
                by_account[acc_id] = []
            by_account[acc_id].append(pending_item)
        
        for account_id, account_pending_items in by_account.items():
            account = Database.fetchone(
                "SELECT id, credentials_encrypted FROM accounts WHERE id = ?",
                (account_id,)
            )
            
            if not account or not account["credentials_encrypted"]:
                for pending_item in account_pending_items:
                    processed += 1
                    item = pending_item['item_data']
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
                for pending_item in account_pending_items:
                    item = pending_item['item_data']
                    src_folder = item.get("sourceFolder", "INBOX")
                    if src_folder not in by_folder:
                        by_folder[src_folder] = []
                    by_folder[src_folder].append(pending_item)
                
                for source_folder, folder_pending_items in by_folder.items():
                    try:
                        client.select_folder(source_folder)
                    except IMAPError as e:
                        for pending_item in folder_pending_items:
                            processed += 1
                            item = pending_item['item_data']
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

                    for pending_item in folder_pending_items:
                        processed += 1
                        item = pending_item['item_data']
                        email_data = item.get("email", {})
                        folder_id = item.get("destinationFolderId")
                        
                        # We don't need committed_imap_emails dict anymore - 
                        # we track via pending_commit table
                        dummy_tracking = {}
                        result = commit_imap_email(
                            client, account_id, email_data, folder_id,
                            source_folder, results, dummy_tracking
                        )
                        
                        # Mark as committed (may need post-action)
                        if result["status"] in ("success", "skipped"):
                            mark_item_committed(pending_item['id'])
                        
                        if processed % 10 == 0:
                            Database.commit()
                        
                        yield sse_message("progress", {
                            "current": processed,
                            "total": total_emails,
                            "percent": int(processed / total_emails * 100) if total_emails > 0 else 100,
                            "status": result["status"],
                            "subject": result["subject"],
                            "commitPhase": "emails",
                        })
                
            except Exception as e:
                for pending_item in account_pending_items:
                    item = pending_item['item_data']
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

        Database.commit()
        
        # Post-commit actions from pending_commit table
        items_needing_post = get_committed_items_needing_post_action(commit_id)
        if items_needing_post:
            yield from _apply_post_actions_from_pending(commit_id, items_needing_post, results)
        
        # Mark remaining committed items as done
        mark_all_committed_as_done(commit_id)
        
        # Phase 2: Staged folders
        folder_count = len(pending_folders)
        
        if folder_count > 0:
            phase_label = "Phase 2" if total_emails > 0 else "Phase 1"
            yield sse_message("status", {
                "phase": "folders",
                "message": f"{phase_label}: Committing {folder_count} folder{'s' if folder_count != 1 else ''}",
            })
        
        for folder_idx, pending_item in enumerate(pending_folders):
            folder_item = pending_item['item_data']
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
                    
                    # Apply post-action for IMAP folder if set
                    folder_action = pending_item.get('source_action', 'leave')
                    if folder_action and folder_action != 'leave':
                        yield from _apply_folder_post_action(folder_item, folder_action, results)
                
                results["folders_success"] += 1
                mark_item_done(pending_item['id'])
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
        
        # All done - clear the commit session
        clear_commit_session(commit_id)
        
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


def _apply_post_actions_from_pending(commit_id: str, items: list, results: dict):
    """Apply post-commit actions using pending_commit tracking."""
    yield sse_message("status", {
        "phase": "post_actions",
        "message": "Updating server...",
    })
    
    # Group by account
    by_account = {}
    for item in items:
        item_data = item['item_data']
        acc_id = item_data.get('sourceAccountId')
        if acc_id not in by_account:
            by_account[acc_id] = []
        by_account[acc_id].append(item)
    
    for account_id, account_items in by_account.items():
        account = Database.fetchone(
            "SELECT id, credentials_encrypted FROM accounts WHERE id = ?",
            (account_id,)
        )
        if not account or not account["credentials_encrypted"]:
            results["post_actions"]["failed"] += len(account_items)
            continue
        
        client = None
        try:
            client = IMAP.connect_with_credentials(account["credentials_encrypted"])
            
            # Group by source folder
            by_folder = {}
            for item in account_items:
                item_data = item['item_data']
                src_folder = item_data.get("sourceFolder", "INBOX")
                if src_folder not in by_folder:
                    by_folder[src_folder] = []
                by_folder[src_folder].append(item)
            
            for source_folder, folder_items in by_folder.items():
                actions_applied = False
                try:
                    client.select_folder(source_folder)
                    
                    for item in folder_items:
                        item_data = item['item_data']
                        action = item['source_action']
                        uid = item_data['email'].get('uid')
                        
                        if not action or action == 'leave':
                            mark_item_done(item['id'])
                            continue
                        
                        try:
                            if action == 'archive':
                                client.archive_email(uid)
                            elif action == 'trash':
                                client.trash_email(uid)
                            elif action == 'delete':
                                client.delete_email(uid)
                            
                            results["post_actions"]["success"] += 1
                            results["post_actions"]["by_action"][action] = results["post_actions"]["by_action"].get(action, 0) + 1
                            mark_item_done(item['id'])
                            actions_applied = True
                        except IMAPError:
                            results["post_actions"]["failed"] += 1
                    
                    # Invalidate email cache so UI reflects changes
                    if actions_applied:
                        clear_folder_cache(int(account_id), source_folder)
                except IMAPError:
                    results["post_actions"]["failed"] += len(folder_items)
                    
        except Exception:
            results["post_actions"]["failed"] += len(account_items)
        finally:
            if client:
                try:
                    client.disconnect()
                except:
                    pass


def _apply_folder_post_action(folder_item: dict, action: str, results: dict):
    """Apply post-commit action to all emails in a committed IMAP folder.
    
    Args:
        folder_item: The folder item data (accountId, folder name, etc.)
        action: The action to apply ('archive', 'trash', 'delete')
        results: Results dict with post_actions counters
    
    Yields SSE status messages.
    """
    account_id = folder_item.get("accountId")
    imap_folder = folder_item.get("folder")
    folder_name = imap_folder.split('/')[-1] if imap_folder else "folder"
    
    account = Database.fetchone(
        "SELECT credentials_encrypted FROM accounts WHERE id = ?", (account_id,)
    )
    if not account or not account["credentials_encrypted"]:
        results["post_actions"]["failed"] += 1
        return
    
    action_verb = {"archive": "Archiving", "trash": "Trashing", "delete": "Deleting"}.get(action, "Processing")
    yield sse_message("status", {
        "phase": "post_actions",
        "message": f"{action_verb} emails in {folder_name}...",
    })
    
    client = None
    try:
        client = IMAP.connect_with_credentials(account["credentials_encrypted"])
        client.select_folder(imap_folder)
        uids = client.search(criteria="ALL", limit=0)
        
        for uid in uids:
            try:
                if action == 'archive':
                    client.archive_email(uid)
                elif action == 'trash':
                    client.trash_email(uid)
                elif action == 'delete':
                    client.delete_email(uid)
                results["post_actions"]["success"] += 1
                results["post_actions"]["by_action"][action] = results["post_actions"]["by_action"].get(action, 0) + 1
            except IMAPError:
                results["post_actions"]["failed"] += 1
        
        # Invalidate email cache for this folder so UI reflects changes
        clear_folder_cache(int(account_id), imap_folder)
                
    except Exception:
        results["post_actions"]["failed"] += 1
    finally:
        if client:
            try:
                client.disconnect()
            except:
                pass
