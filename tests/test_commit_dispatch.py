"""
Dispatch-level tests for apply_post_commit_actions (web/blueprints/api/commit.py).

Mocks the IMAP client and DB at the boundary — no real server, no Argon2id.
These cover provider routing and, critically, the per-iteration source
re-select that single-call unit tests cannot catch.
"""

from unittest.mock import MagicMock, call

import web.blueprints.api.commit as commit_mod


def _run(committed, source_actions, client):
    """Drive apply_post_commit_actions to completion with a mocked client/DB."""
    results = {"post_actions": {"success": 0, "failed": 0}}
    orig_db = commit_mod.Database.fetchone
    orig_connect = commit_mod.IMAP.connect_with_credentials
    try:
        commit_mod.Database.fetchone = staticmethod(
            lambda *a, **k: {"id": 1, "credentials_encrypted": "enc"}
        )
        commit_mod.IMAP.connect_with_credentials = staticmethod(lambda creds: client)
        list(commit_mod.apply_post_commit_actions(committed, source_actions, results))
    finally:
        commit_mod.Database.fetchone = orig_db
        commit_mod.IMAP.connect_with_credentials = orig_connect
    return results


def test_gmail_delete_reselects_source_before_each_uid():
    client = MagicMock()
    client.host = "imap.gmail.com"
    committed = {1: {"INBOX": [("100", 5), ("101", 5), ("102", 5)]}}
    source_actions = {"account:1:5": "delete"}

    results = _run(committed, source_actions, client)

    # All three routed through the Gmail-aware path.
    assert client.delete_email_via_trash.call_count == 3
    client.delete_email.assert_not_called()
    # Source folder re-selected before EACH message (1 initial + 3 per-uid).
    select_calls = [c for c in client.select_folder.call_args_list if c == call("INBOX")]
    assert len(select_calls) == 4
    assert results["post_actions"]["success"] == 3


def test_non_gmail_delete_uses_standard_delete():
    client = MagicMock()
    client.host = "imap.fastmail.com"
    committed = {1: {"INBOX": [("100", 5), ("101", 5)]}}
    source_actions = {"account:1:5": "delete"}

    results = _run(committed, source_actions, client)

    assert client.delete_email.call_count == 2
    client.delete_email_via_trash.assert_not_called()
    # No extra per-iteration re-selects on the standard path (just the initial).
    select_calls = [c for c in client.select_folder.call_args_list if c == call("INBOX")]
    assert len(select_calls) == 1
    assert results["post_actions"]["success"] == 2
