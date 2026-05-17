"""
MailRepo API - Thread Discovery Routes

Handles thread-related endpoints, primarily POST /api/threads/find which
walks RFC 5322 In-Reply-To and References headers across live IMAP folders
to discover all messages in a conversation. Used by the "Stage thread to..."
button in the live email viewer.

See docs/Stage_Thread_Plan.md for the design rationale.
"""

from flask import request, jsonify
from core import Database
from core import IMAP, IMAPError
from utils.log import get_logger
from . import api_bp

log = get_logger()


@api_bp.route("/threads/find", methods=["POST"])
def find_thread():
    """Find all messages in the same thread as the given message.

    Body:
        {
            "account_id": int,
            "folder": str,         # IMAP folder containing the starting message
            "uid": str             # IMAP UID within that folder
        }

    Optional:
        "include_sent": bool       # default True; if False, only searches the
                                   # source folder (rare; mostly for debugging)

    Returns:
        {
            "thread": [
                {
                    "folder": "INBOX",
                    "uid": "12340",
                    "message_id": "<...>",
                    "subject": "Following up",
                    "from": "Jane <jane@example.com>",
                    "date": "Mon, 12 May 2026 10:30:00 +0000"
                },
                ...
            ],
            "truncated": false,
            "timed_out": false,
            "method": "header_walk",
            "sent_folder": "Sent"   # for the frontend's information
        }
    """
    body = request.get_json(silent=True) or {}

    # Validate required fields up front; bad payloads should fail fast and
    # clearly, not deep in the IMAP code.
    try:
        account_id = int(body.get("account_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "account_id is required and must be an integer"}), 400

    folder = body.get("folder")
    uid = body.get("uid")
    if not folder or not isinstance(folder, str):
        return jsonify({"error": "folder is required"}), 400
    if not uid or not isinstance(uid, (str, int)):
        return jsonify({"error": "uid is required"}), 400
    uid = str(uid)

    include_sent = body.get("include_sent")
    if include_sent is None:
        include_sent = True

    # Look up the account's stored credentials
    row = Database.fetchone(
        "SELECT email, credentials_encrypted FROM accounts WHERE id = ?",
        (account_id,),
    )
    if not row:
        return jsonify({"error": f"Account {account_id} not found"}), 404
    if not row["credentials_encrypted"]:
        return jsonify({"error": "Account has no stored credentials"}), 400

    # Connect and run the thread walk. Always disconnect on exit, even on error.
    client = None
    try:
        client = IMAP.connect_with_credentials(row["credentials_encrypted"])

        # Identify the Sent folder for cross-folder search (unless caller opted out).
        # Skip Sent if it IS the source folder (e.g. user clicked on a message
        # already in Sent — we'll find their replies in INBOX via header walk).
        sent_folder = None
        also_search = []
        if include_sent:
            sent_folder = client.get_special_folder("sent")
            if sent_folder and sent_folder != folder:
                also_search.append(sent_folder)

        # If the user clicked a message in the Sent folder, the corresponding
        # received messages are most likely in INBOX. Include it.
        if folder != "INBOX":
            also_search.append("INBOX")

        result = client.find_thread(
            source_folder=folder,
            source_uid=uid,
            also_search_folders=also_search,
        )
        # Surface the Sent folder name for the frontend's status text
        result["sent_folder"] = sent_folder
        return jsonify(result)

    except IMAPError as e:
        log.warning(f"find_thread IMAP error: {e}")
        return jsonify({"error": str(e)}), 502
    except Exception as e:
        log.exception("find_thread unexpected error")
        return jsonify({"error": f"Unexpected error: {type(e).__name__}: {e}"}), 500
    finally:
        if client:
            try:
                client.disconnect()
            except Exception:
                pass
