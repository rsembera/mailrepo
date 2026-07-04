"""
MailRepo API - Commit streaming (SSE).

POST /api/commit/stream consumes a staged email + folder set, writes a
pending_commit session, then walks each item: archive emails to disk +
DB, then apply optional post-commit IMAP actions (archive / trash /
delete on the source server). Resumable: if the SSE stream is
interrupted, the next call with resumeCommitId picks up from where the
pending_commit table left off.

Helpers:
  _apply_post_actions_from_pending(): post-action loop after per-email walk
  _apply_folder_post_action(): post-action for a whole IMAP folder

Split out of progress.py during the post-1.0 cleanup pass so each SSE
workflow lives in its own focused module. The sse_message() helper lives
in progress.py (the coordinator).
"""

import logging
import socket

from flask import Response, request, stream_with_context

from core import IMAP, Database, IMAPError
from core.account_utils import is_gmail_host
from core.pending_commit import (
    clear_commit_session,
    create_commit_session,
    get_committed_items_needing_post_action,
    get_pending_items,
    mark_all_committed_as_done,
    mark_item_committed,
    mark_item_done,
)

from . import api_bp
from .commit import (
    apply_email_action,
    build_commit_summary,
    commit_imap_email,
    commit_imap_folder,
    commit_import_email,
    commit_import_folder,
    create_archive_folder_from_path,
)
from .progress import sse_message
from .streaming import clear_folder_cache

logger = logging.getLogger(__name__)


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
            sse_message("error", {"error": "No items to commit"}), mimetype="text/event-stream"
        )

    def generate():
        results = {
            "success": [],
            "failed": [],
            "skipped": [],
            "folders_success": 0,
            "folders_failed": 0,
            "post_actions": {
                "success": 0,
                "failed": 0,
                "by_action": {"archive": 0, "trash": 0, "delete": 0},
            },
        }

        # Either resume existing commit or create new one
        if resume_commit_id:
            commit_id = resume_commit_id
            yield sse_message(
                "status", {"phase": "resuming", "message": "Resuming interrupted commit..."}
            )
        else:
            # Save all items to pending_commit before starting
            commit_id = create_commit_session(staged, staged_folders, source_actions)

        # Get pending items from database
        pending_items = get_pending_items(commit_id, "pending")
        pending_emails = [p for p in pending_items if p["item_type"] == "email"]
        pending_folders = [p for p in pending_items if p["item_type"] == "folder"]

        total = len(pending_emails) + len(pending_folders)

        if total == 0:
            # Check if we just need post-actions
            items_needing_post = get_committed_items_needing_post_action(commit_id)
            if items_needing_post:
                yield sse_message(
                    "status", {"phase": "post_actions", "message": "Updating server..."}
                )
                yield from _apply_post_actions_from_pending(commit_id, items_needing_post, results)

            clear_commit_session(commit_id)
            yield sse_message(
                "complete",
                {
                    "results": results,
                    "message": build_commit_summary(results) or "Nothing to commit.",
                },
            )
            return

        yield sse_message(
            "start",
            {
                "total": total,
                "type": "mixed" if pending_folders else "emails",
                "commitId": commit_id,
            },
        )

        # Separate imports from IMAP items
        import_emails = [p for p in pending_emails if p["item_data"].get("sourceType") == "import"]
        imap_emails = [p for p in pending_emails if p["item_data"].get("sourceType") != "import"]

        total_emails = len(pending_emails)
        processed = 0

        # Phase 1: Individual emails
        if total_emails > 0:
            yield sse_message(
                "status",
                {
                    "phase": "emails",
                    "message": f"Committing {total_emails} email{'s' if total_emails != 1 else ''}",
                },
            )

        # Process imports first (no IMAP connection needed)
        for pending_item in import_emails:
            processed += 1
            item = pending_item["item_data"]
            result = commit_import_email(item, results)

            # Mark as committed in pending_commit table
            if result["status"] in ("success", "skipped"):
                mark_item_done(pending_item["id"])  # Imports don't need post-action
            else:
                mark_item_committed(pending_item["id"])  # Keep for retry visibility

            if processed % 10 == 0:
                Database.commit()

            yield sse_message(
                "progress",
                {
                    "current": processed,
                    "total": total_emails,
                    "percent": int(processed / total_emails * 100) if total_emails > 0 else 100,
                    "status": result["status"],
                    "subject": result["subject"],
                    "commitPhase": "emails",
                },
            )

        # Group IMAP items by account
        by_account = {}
        for pending_item in imap_emails:
            item = pending_item["item_data"]
            acc_id = item.get("sourceAccountId")
            if acc_id not in by_account:
                by_account[acc_id] = []
            by_account[acc_id].append(pending_item)

        for account_id, account_pending_items in by_account.items():
            account = Database.fetchone(
                "SELECT id, credentials_encrypted FROM accounts WHERE id = ?", (account_id,)
            )

            if not account or not account["credentials_encrypted"]:
                for pending_item in account_pending_items:
                    processed += 1
                    item = pending_item["item_data"]
                    results["failed"].append(
                        {
                            "uid": item["email"].get("uid"),
                            "error": "Account not found or not configured",
                        }
                    )
                    yield sse_message(
                        "progress",
                        {
                            "current": processed,
                            "total": total,
                            "percent": int(processed / total * 100),
                            "status": "failed",
                            "subject": item["email"].get("subject", "")[:50],
                        },
                    )
                continue

            client = None
            try:
                yield sse_message(
                    "status",
                    {
                        "message": "Connecting to account...",
                        "current": processed,
                        "total": total,
                    },
                )

                client = IMAP.connect_with_credentials(account["credentials_encrypted"])

                # Group by source folder
                by_folder = {}
                for pending_item in account_pending_items:
                    item = pending_item["item_data"]
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
                            item = pending_item["item_data"]
                            results["failed"].append(
                                {
                                    "uid": item["email"].get("uid"),
                                    "error": f"Failed to select folder: {e}",
                                }
                            )
                            yield sse_message(
                                "progress",
                                {
                                    "current": processed,
                                    "total": total,
                                    "percent": int(processed / total * 100),
                                    "status": "failed",
                                },
                            )
                        continue

                    for pending_item in folder_pending_items:
                        processed += 1
                        item = pending_item["item_data"]
                        email_data = item.get("email", {})
                        folder_id = item.get("destinationFolderId")

                        # We don't need committed_imap_emails dict anymore --
                        # we track via pending_commit table
                        dummy_tracking = {}
                        result = commit_imap_email(
                            client,
                            account_id,
                            email_data,
                            folder_id,
                            source_folder,
                            results,
                            dummy_tracking,
                        )

                        # Mark as committed (may need post-action)
                        if result["status"] in ("success", "skipped"):
                            mark_item_committed(pending_item["id"])

                        if processed % 10 == 0:
                            Database.commit()

                        yield sse_message(
                            "progress",
                            {
                                "current": processed,
                                "total": total_emails,
                                "percent": int(processed / total_emails * 100)
                                if total_emails > 0
                                else 100,
                                "status": result["status"],
                                "subject": result["subject"],
                                "commitPhase": "emails",
                            },
                        )

            except Exception as e:
                for pending_item in account_pending_items:
                    item = pending_item["item_data"]
                    if not any(r.get("uid") == item["email"].get("uid") for r in results["failed"]):
                        processed += 1
                        results["failed"].append(
                            {
                                "uid": item["email"].get("uid"),
                                "error": f"Connection failed: {e}",
                            }
                        )
                        yield sse_message(
                            "progress",
                            {
                                "current": processed,
                                "total": total,
                                "percent": int(processed / total * 100),
                                "status": "failed",
                            },
                        )
            finally:
                if client:
                    try:
                        client.disconnect()
                    except Exception:
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
            yield sse_message(
                "status",
                {
                    "phase": "folders",
                    "message": f"{phase_label}: Committing {folder_count} folder{'s' if folder_count != 1 else ''}",
                },
            )

        for folder_idx, pending_item in enumerate(pending_folders):
            folder_item = pending_item["item_data"]
            source_type = folder_item.get("sourceType")
            archive_path = folder_item.get("archivePath", "")
            dest_folder_id = folder_item.get("destinationFolderId")
            folder_name = archive_path.split("/")[-1] if archive_path else "folder"

            try:
                target_folder_id = create_archive_folder_from_path(archive_path, dest_folder_id)

                if source_type == "import":
                    for event in commit_import_folder(
                        folder_item, target_folder_id, folder_idx, folder_count, results
                    ):
                        yield sse_message(
                            event["type"], {k: v for k, v in event.items() if k != "type"}
                        )
                else:
                    for event in commit_imap_folder(
                        folder_item, target_folder_id, folder_idx, folder_count, results
                    ):
                        yield sse_message(
                            event["type"], {k: v for k, v in event.items() if k != "type"}
                        )

                    # Apply post-action for IMAP folder if set
                    folder_action = pending_item.get("source_action", "leave")
                    if folder_action and folder_action != "leave":
                        yield from _apply_folder_post_action(folder_item, folder_action, results)

                results["folders_success"] += 1
                mark_item_done(pending_item["id"])
                Database.commit()

            except Exception as e:
                results["folders_failed"] += 1
                yield sse_message(
                    "progress",
                    {
                        "current": 0,
                        "total": 0,
                        "percent": 0,
                        "status": "folder_failed",
                        "folder": folder_name,
                        "error": str(e),
                    },
                )

        Database.commit()

        # All done - clear the commit session
        clear_commit_session(commit_id)

        yield sse_message(
            "complete",
            {
                "results": results,
                "message": build_commit_summary(results),
            },
        )

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _apply_post_actions_from_pending(commit_id: str, items: list, results: dict):
    """Apply post-commit actions using pending_commit tracking."""
    yield sse_message(
        "status",
        {
            "phase": "post_actions",
            "message": "Updating server...",
        },
    )

    # Group by account
    by_account = {}
    for item in items:
        item_data = item["item_data"]
        acc_id = item_data.get("sourceAccountId")
        if acc_id not in by_account:
            by_account[acc_id] = []
        by_account[acc_id].append(item)

    for account_id, account_items in by_account.items():
        account = Database.fetchone(
            "SELECT id, credentials_encrypted FROM accounts WHERE id = ?", (account_id,)
        )
        if not account or not account["credentials_encrypted"]:
            results["post_actions"]["failed"] += len(account_items)
            logger.warning(
                "Post-commit actions skipped for account %s (%d items): no stored credentials",
                account_id,
                len(account_items),
            )
            continue

        client = None
        try:
            client = IMAP.connect_with_credentials(account["credentials_encrypted"])
            # Gmail needs a provider-aware delete (its IMAP delete only
            # removes a label, not the message); detected from the host.
            is_gmail = is_gmail_host(client.host)

            # Group by source folder
            by_folder = {}
            for item in account_items:
                item_data = item["item_data"]
                src_folder = item_data.get("sourceFolder", "INBOX")
                if src_folder not in by_folder:
                    by_folder[src_folder] = []
                by_folder[src_folder].append(item)

            for source_folder, folder_items in by_folder.items():
                actions_applied = False
                handled_ids = set()
                try:
                    client.select_folder(source_folder)

                    # Batch Gmail permanent-deletes for this folder into a single
                    # pass (one UID-set MOVE + one EXPUNGE instead of ~7 commands
                    # per message). Gmail's per-command latency makes the
                    # per-message path slow for multi-deletes. Single deletes fall
                    # through to the per-item loop's proven path below.
                    if is_gmail:
                        delete_items = [
                            it
                            for it in folder_items
                            if it["source_action"] == "delete"
                            and it["item_data"]["email"].get("uid") is not None
                        ]
                        if len(delete_items) > 1:
                            by_uid = {
                                str(it["item_data"]["email"]["uid"]): it for it in delete_items
                            }
                            try:
                                outcome = client.delete_emails_via_trash(
                                    list(by_uid), source_folder
                                )
                            except IMAPError as e:
                                outcome = {u: False for u in by_uid}
                                logger.warning(
                                    "Post-commit batch delete failed for %d items in %s: %s",
                                    len(by_uid),
                                    source_folder,
                                    e,
                                )
                            for uid, ok in outcome.items():
                                item = by_uid[uid]
                                handled_ids.add(item["id"])
                                if ok:
                                    results["post_actions"]["success"] += 1
                                    results["post_actions"]["by_action"]["delete"] = (
                                        results["post_actions"]["by_action"].get("delete", 0) + 1
                                    )
                                    mark_item_done(item["id"])
                                    actions_applied = True
                                else:
                                    results["post_actions"]["failed"] += 1
                            # The batch leaves Trash selected; restore the source
                            # for the per-item loop (apply_email_action only
                            # re-selects on its Gmail-delete branch). Guarded so
                            # a failure here can't fall through to the folder
                            # handler and double-count the items the batch
                            # already accounted for.
                            try:
                                client.select_folder(source_folder)
                            except IMAPError as e:
                                remaining = [
                                    it for it in folder_items if it["id"] not in handled_ids
                                ]
                                results["post_actions"]["failed"] += len(remaining)
                                logger.warning(
                                    "Post-commit: re-select of %s failed after "
                                    "batch delete; %d remaining item(s) skipped: %s",
                                    source_folder,
                                    len(remaining),
                                    e,
                                )
                                if actions_applied:
                                    clear_folder_cache(int(account_id), source_folder)
                                continue

                    for item in folder_items:
                        if item["id"] in handled_ids:
                            continue
                        item_data = item["item_data"]
                        action = item["source_action"]
                        uid = item_data["email"].get("uid")

                        if not action or action == "leave":
                            mark_item_done(item["id"])
                            continue

                        try:
                            apply_email_action(client, action, uid, source_folder, is_gmail)

                            results["post_actions"]["success"] += 1
                            results["post_actions"]["by_action"][action] = (
                                results["post_actions"]["by_action"].get(action, 0) + 1
                            )
                            mark_item_done(item["id"])
                            actions_applied = True
                        except IMAPError as e:
                            results["post_actions"]["failed"] += 1
                            logger.warning(
                                "Post-commit %s failed for UID %s in %s: %s",
                                action,
                                uid,
                                source_folder,
                                e,
                            )

                    # Invalidate email cache so UI reflects changes
                    if actions_applied:
                        clear_folder_cache(int(account_id), source_folder)
                except IMAPError as e:
                    results["post_actions"]["failed"] += len(folder_items)
                    logger.warning(
                        "Post-commit actions failed for folder %s (%d items): %s",
                        source_folder,
                        len(folder_items),
                        e,
                    )

        except Exception as e:
            results["post_actions"]["failed"] += len(account_items)
            logger.warning(
                "Post-commit actions failed for account %s (%d items): %s",
                account_id,
                len(account_items),
                e,
            )
            # Report connection issues to the user via SSE. IMAPError wraps
            # the underlying socket error (see core/imap.py connect()), so
            # check the chained cause as well as the exception itself.
            if isinstance(e, (socket.timeout, OSError)) or isinstance(
                e.__cause__, (socket.timeout, OSError)
            ):
                yield sse_message(
                    "status",
                    {
                        "phase": "post_actions",
                        "message": "Server not responding -- skipping server updates. Your emails are safely archived.",
                    },
                )
        finally:
            if client:
                try:
                    client.disconnect()
                except Exception:
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
    folder_name = imap_folder.split("/")[-1] if imap_folder else "folder"

    account = Database.fetchone(
        "SELECT credentials_encrypted FROM accounts WHERE id = ?", (account_id,)
    )
    if not account or not account["credentials_encrypted"]:
        results["post_actions"]["failed"] += 1
        logger.warning(
            "Post-commit folder action skipped for account %s (%s): no stored credentials",
            account_id,
            imap_folder,
        )
        return

    action_verb = {"archive": "Archiving", "trash": "Trashing", "delete": "Deleting"}.get(
        action, "Processing"
    )
    yield sse_message(
        "status",
        {
            "phase": "post_actions",
            "message": f"{action_verb} emails in {folder_name}...",
        },
    )

    client = None
    try:
        client = IMAP.connect_with_credentials(account["credentials_encrypted"])
        # Gmail needs a provider-aware delete (its IMAP delete only removes
        # a label, not the message); detected from the connected host.
        is_gmail = is_gmail_host(client.host)
        client.select_folder(imap_folder)
        uids = client.search(criteria="ALL", limit=0)

        for uid in uids:
            try:
                apply_email_action(client, action, uid, imap_folder, is_gmail)
                results["post_actions"]["success"] += 1
                results["post_actions"]["by_action"][action] = (
                    results["post_actions"]["by_action"].get(action, 0) + 1
                )
            except IMAPError as e:
                results["post_actions"]["failed"] += 1
                logger.warning(
                    "Post-commit %s failed for UID %s in %s: %s",
                    action,
                    uid,
                    imap_folder,
                    e,
                )

        # Invalidate email cache for this folder so UI reflects changes
        clear_folder_cache(int(account_id), imap_folder)

    except Exception as e:
        results["post_actions"]["failed"] += 1
        logger.warning(
            "Post-commit folder action %s failed for %s: %s",
            action,
            imap_folder,
            e,
        )
    finally:
        if client:
            try:
                client.disconnect()
            except Exception:
                pass
