"""
Tests for apply_email_action (web/blueprints/api/commit.py) — the single
shared dispatcher for post-commit server actions, called per message by the
live /api/commit/stream workflow (progress_commit.py).

Mocks the IMAP client at the boundary — no real server, no Argon2id.
Covers provider routing and, critically, the source re-select before each
Gmail delete (delete_email_via_trash changes the selected folder).

History note: a previous version of these tests drove a near-identical
dispatch loop in commit.py that nothing in the live app called, which let
the Gmail-aware delete sit unwired while appearing tested. These tests
target the helper the live workflow imports; if the import in
progress_commit.py disappears, ruff's unused-import check will flag it.
"""

from unittest.mock import MagicMock, call

from web.blueprints.api.commit import apply_email_action


def test_gmail_delete_reselects_source_before_each_uid():
    client = MagicMock()

    for uid in ("100", "101", "102"):
        apply_email_action(client, "delete", uid, "INBOX", is_gmail=True)

    # All three routed through the Gmail-aware path.
    assert client.delete_email_via_trash.call_count == 3
    client.delete_email.assert_not_called()
    # Source folder re-selected before EACH message, in order.
    expected = []
    for uid in ("100", "101", "102"):
        expected.append(call.select_folder("INBOX"))
        expected.append(call.delete_email_via_trash(uid, "INBOX"))
    assert client.mock_calls == expected


def test_non_gmail_delete_uses_standard_delete():
    client = MagicMock()

    for uid in ("100", "101"):
        apply_email_action(client, "delete", uid, "INBOX", is_gmail=False)

    assert client.delete_email.call_count == 2
    client.delete_email_via_trash.assert_not_called()
    # Standard path never re-selects; selection is the caller's business.
    client.select_folder.assert_not_called()


def test_archive_routes_to_archive_email_regardless_of_provider():
    for is_gmail in (True, False):
        client = MagicMock()
        apply_email_action(client, "archive", "7", "INBOX", is_gmail=is_gmail)
        client.archive_email.assert_called_once_with("7")
        client.delete_email.assert_not_called()
        client.delete_email_via_trash.assert_not_called()


def test_trash_routes_to_trash_email_regardless_of_provider():
    for is_gmail in (True, False):
        client = MagicMock()
        apply_email_action(client, "trash", "7", "INBOX", is_gmail=is_gmail)
        client.trash_email.assert_called_once_with("7")
        client.delete_email.assert_not_called()
        client.delete_email_via_trash.assert_not_called()
