"""
MailRepo API - Progress streaming coordinator.

The two long-running SSE workflows live in sibling modules:
  - progress_emails.py: streaming emails from an IMAP account folder
  - progress_commit.py: streaming commit progress for staged items

This file holds:
  - sse_message(): the SSE event formatter helper used by all three
  - check_pending_commit(): GET /api/commit/pending
  - discard_pending_commit(): POST /api/commit/discard

Split done during the post-1.0 cleanup pass (May 30, 2026). The original
progress.py was ~770 lines with three concerns piled into one file; the
split gives each workflow its own focused file and keeps the coordinator
small enough to read in one screen.
"""

import json

from flask import jsonify, request

from . import api_bp


def sse_message(event: str, data: dict) -> str:
    """Format a Server-Sent Event message."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@api_bp.route("/commit/pending", methods=["GET"])
def check_pending_commit():
    """Check if there's an interrupted commit that can be resumed."""
    from core.pending_commit import get_pending_commit

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

    data = request.get_json() or {}
    commit_id = data.get("commitId")

    if not commit_id:
        return jsonify({"error": "commitId required"}), 400

    do_discard(commit_id)
    return jsonify({"success": True})
