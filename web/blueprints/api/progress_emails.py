"""
MailRepo API - Email streaming (SSE).

Single endpoint that streams emails from an IMAP account folder with
progress updates. Implements layered caching:

  1. TTL short-circuit (data/.sync_cache.db is_cache_fresh check)
  2. CONDSTORE / HIGHESTMODSEQ short-circuit (no network if server unchanged)
  3. Full incremental sync (fetch only UIDs higher than highest_cached_uid)
  4. Offline fallback (use stale cache if server unreachable)

Split out of progress.py during the post-1.0 cleanup pass so each SSE
workflow lives in its own focused module. The sse_message() helper lives
in progress.py (the coordinator).
"""

from flask import Response, request, stream_with_context

from core import IMAP, Database, IMAPError, ImapPool
from core.sync_cache import (
    get_folder_sync_state,
    is_cache_fresh,
    update_folder_sync_state,
)

from . import api_bp
from .progress import sse_message
from .streaming import (
    cache_email,
    clear_folder_cache,
    get_any_cached_emails,
    get_cached_emails,
    get_highest_cached_uid,
    remove_stale_cache_entries,
)


@api_bp.route("/accounts/<int:account_id>/emails/stream", methods=["GET"])
def stream_account_emails(account_id):
    """
    Stream emails from an IMAP account with progress updates.

    Uses Server-Sent Events to report progress as emails are fetched.
    Implements caching with UIDVALIDITY for incremental sync.
    """
    account = Database.fetchone(
        "SELECT id, credentials_encrypted FROM accounts WHERE id = ?", (account_id,)
    )

    if not account:
        return Response(
            sse_message("error", {"error": "Account not found"}), mimetype="text/event-stream"
        )

    if not account["credentials_encrypted"]:
        return Response(
            sse_message("error", {"error": "Account not configured"}), mimetype="text/event-stream"
        )

    folder = request.args.get("folder", "INBOX")
    # refresh=true: skip the TTL and CONDSTORE short-circuits and reconcile
    # against the server, keeping the cache (fetch only what is new, drop
    # what is gone). rebuild=true: additionally discard the folder cache
    # and re-download every header -- the escape hatch for the rare case
    # incremental sync cannot see (a message reappearing with a lower
    # UID without a UIDVALIDITY change).
    rebuild = request.args.get("rebuild", "").lower() == "true"
    force_refresh = rebuild or request.args.get("refresh", "").lower() == "true"

    def generate():
        client = None
        cached_emails = []

        try:
            # ----- Option A: TTL short-circuit ----------------------------
            # If we synced this folder recently and user isn't forcing refresh,
            # return the cache immediately without touching the network.
            if not force_refresh and is_cache_fresh(account_id, folder):
                sync_state = get_folder_sync_state(account_id, folder)
                if sync_state and sync_state["uidvalidity"]:
                    cached_emails = get_cached_emails(account_id, folder, sync_state["uidvalidity"])
                    if cached_emails:
                        yield sse_message(
                            "complete",
                            {
                                "emails": cached_emails,
                                "total": len(cached_emails),
                                "from_cache": len(cached_emails),
                                "fetched": 0,
                            },
                        )
                        return

            # ----- Cache first -------------------------------------------
            # Whatever we hold for this folder goes out immediately so the
            # list renders while the server check runs. "complete" below
            # still carries the authoritative list. A rebuild shows the
            # full progress panel instead, since the cache is being thrown
            # away.
            if not rebuild:
                known = get_any_cached_emails(account_id, folder)
                if known:
                    yield sse_message("cached", {"emails": known, "total": len(known)})

            # ----- Connect to server -------------------------------------
            yield sse_message(
                "status",
                {
                    "phase": "connecting",
                    "message": "Connecting to server...",
                },
            )

            try:
                client = ImapPool.acquire(account_id, account["credentials_encrypted"])
            except IMAPError as e:
                # Connection failed -- try to use cache
                cached_emails = get_any_cached_emails(account_id, folder)
                if cached_emails:
                    yield sse_message(
                        "status",
                        {
                            "phase": "offline",
                            "message": f"Server unavailable. Showing {len(cached_emails)} cached emails.",
                        },
                    )
                    yield sse_message(
                        "complete",
                        {
                            "emails": cached_emails,
                            "total": len(cached_emails),
                            "from_cache": len(cached_emails),
                            "fetched": 0,
                            "offline": True,
                        },
                    )
                    return
                else:
                    raise e

            yield sse_message(
                "status",
                {
                    "phase": "selecting",
                    "message": f"Opening {folder}...",
                },
            )

            folder_info = client.select_folder(folder)
            uidvalidity = folder_info.get("uidvalidity")
            highestmodseq = folder_info.get("highestmodseq")

            # ----- Option B: CONDSTORE short-circuit ----------------------
            # If the server supports HIGHESTMODSEQ and it hasn't changed
            # since last sync, nothing in the folder has changed -- return cache.
            if not force_refresh and uidvalidity and highestmodseq:
                sync_state = get_folder_sync_state(account_id, folder)
                if (
                    sync_state
                    and sync_state["uidvalidity"] == uidvalidity
                    and sync_state["highestmodseq"] == highestmodseq
                ):
                    cached_emails = get_cached_emails(account_id, folder, uidvalidity)
                    if cached_emails:
                        # Update last_synced_at so TTL resets
                        update_folder_sync_state(account_id, folder, uidvalidity, highestmodseq)
                        yield sse_message(
                            "complete",
                            {
                                "emails": cached_emails,
                                "total": len(cached_emails),
                                "from_cache": len(cached_emails),
                                "fetched": 0,
                            },
                        )
                        return

            # ----- Full incremental sync ----------------------------------
            # Check cache validity
            highest_cached_uid = 0
            cache_valid = False

            if uidvalidity and not rebuild:
                cached_emails = get_cached_emails(account_id, folder, uidvalidity)
                if cached_emails:
                    cache_valid = True
                    highest_cached_uid = get_highest_cached_uid(account_id, folder, uidvalidity)
                    yield sse_message(
                        "status",
                        {
                            "phase": "cache",
                            "message": f"Found {len(cached_emails)} cached emails, checking for new...",
                        },
                    )

            if rebuild and uidvalidity:
                clear_folder_cache(account_id, folder)
                cached_emails = []
                cache_valid = False

            yield sse_message(
                "status",
                {
                    "phase": "searching",
                    "message": "Finding emails...",
                },
            )

            # Get all UIDs from server
            all_uids = client.search("ALL", limit=0)

            # Remove cached emails that no longer exist on server
            stale_removed = 0
            if cache_valid and uidvalidity:
                stale_removed = remove_stale_cache_entries(
                    account_id, folder, uidvalidity, all_uids
                )
                if stale_removed > 0:
                    cached_emails = get_cached_emails(account_id, folder, uidvalidity)
                    highest_cached_uid = get_highest_cached_uid(account_id, folder, uidvalidity)

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

            yield sse_message(
                "start",
                {
                    "total": total,
                    "folder": folder,
                    "cached": total_cached,
                    "new": total_new,
                },
            )

            # Start with cached emails
            emails = list(cached_emails)

            # Fetch new emails, one FETCH per chunk rather than per message
            if total_new > 0:
                fetched = 0
                chunk_size = IMAP.HEADER_FETCH_CHUNK
                for start in range(0, total_new, chunk_size):
                    chunk = new_uids[start : start + chunk_size]
                    batch = client.fetch_headers_batch(chunk)
                    for headers in batch:
                        emails.append(headers)
                        if uidvalidity:
                            cache_email(account_id, folder, uidvalidity, headers)
                    fetched += len(chunk)

                    current = total_cached + fetched
                    yield sse_message(
                        "progress",
                        {
                            "current": current,
                            "total": total,
                            "percent": int(current / total * 100) if total > 0 else 100,
                            "subject": batch[-1].get("subject", "")[:50] if batch else "",
                            "phase": "fetching",
                        },
                    )

                if uidvalidity:
                    Database.commit()

            # Sort by UID descending (newest first)
            emails.sort(key=lambda e: int(e.get("uid", 0)), reverse=True)

            # Record successful sync with server-side markers
            update_folder_sync_state(account_id, folder, uidvalidity, highestmodseq)

            yield sse_message(
                "complete",
                {
                    "emails": emails,
                    "total": len(emails),
                    "from_cache": total_cached,
                    "fetched": total_new,
                },
            )

        except IMAPError as e:
            yield sse_message("error", {"error": str(e)})
        except Exception as e:
            yield sse_message("error", {"error": f"Unexpected error: {str(e)}"})
        finally:
            if client:
                try:
                    client.release()
                except Exception:
                    pass

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
