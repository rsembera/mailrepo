"""
Tests for core/pending_commit.py — the commit-resume state machine.

This module tracks staged items through pending -> committed ->
post_action_done so an interrupted commit can be resumed (or discarded)
without losing work or double-applying IMAP post-actions. Pure DB logic,
no external dependencies.

Setup note: pending_commit.destination_folder_id is NOT NULL with a foreign
key to folders(id) (and foreign_keys is ON), so each test first creates a
real destination folder via the `pc_env` fixture.
"""

import pytest

from core.database import Database
from core import pending_commit as pc


@pytest.fixture
def pc_env(initialized_app):
    """Initialized DB plus one destination folder. Yields (app, folder_id)."""
    app, _ = initialized_app
    cur = Database.execute("INSERT INTO folders (name) VALUES (?)", ("Dest",))
    Database.commit()
    return app, cur.lastrowid


# --- item builders matching the frontend's staged-item shape ---------------

def _email(dest, *, account_id=1, source_type="account", import_id=5, uid="100"):
    item = {"destinationFolderId": dest, "uid": uid, "subject": "S"}
    if source_type == "import":
        item["sourceType"] = "import"
        item["sourceImportId"] = import_id
    else:
        item["sourceType"] = "account"
        item["sourceAccountId"] = account_id
    return item


def _email_key(item):
    if item.get("sourceType") == "import":
        return f"import:{item['sourceImportId']}:{item['destinationFolderId']}"
    return f"account:{item['sourceAccountId']}:{item['destinationFolderId']}"


def _folder(dest, *, account_id=1, source_type="account", import_id=5):
    item = {"destinationFolderId": dest, "name": "F"}
    if source_type == "import":
        item["sourceType"] = "import"
        item["importId"] = import_id
    else:
        item["sourceType"] = "account"
        item["accountId"] = account_id
    return item


# ---------------------------------------------------------------------------

class TestCreateCommitSession:
    def test_returns_id_and_persists_items(self, pc_env):
        _, dest = pc_env
        cid = pc.create_commit_session([_email(dest)], [_folder(dest)], {})
        assert isinstance(cid, str) and cid
        pending = pc.get_pending_items(cid)
        assert len(pending) == 2
        assert sorted(p["item_type"] for p in pending) == ["email", "folder"]

    def test_source_action_resolved_from_key(self, pc_env):
        _, dest = pc_env
        item = _email(dest)
        cid = pc.create_commit_session([item], [], {_email_key(item): "archive"})
        assert pc.get_pending_items(cid)[0]["source_action"] == "archive"

    def test_source_action_defaults_to_leave(self, pc_env):
        _, dest = pc_env
        cid = pc.create_commit_session([_email(dest)], [], {})
        assert pc.get_pending_items(cid)[0]["source_action"] == "leave"

    def test_item_data_roundtrips(self, pc_env):
        _, dest = pc_env
        cid = pc.create_commit_session([_email(dest, uid="abc-123")], [], {})
        stored = pc.get_pending_items(cid)[0]["item_data"]
        assert stored["uid"] == "abc-123"
        assert stored["destinationFolderId"] == dest


class TestGetPendingCommit:
    def test_none_when_empty(self, pc_env):
        assert pc.get_pending_commit() is None

    def test_returns_counts(self, pc_env):
        _, dest = pc_env
        cid = pc.create_commit_session([_email(dest), _email(dest)], [], {})
        info = pc.get_pending_commit()
        assert info["commit_id"] == cid
        assert info["total"] == 2
        assert info["pending"] == 2

    def test_excludes_fully_done_session(self, pc_env):
        _, dest = pc_env
        cid = pc.create_commit_session([_email(dest)], [], {})
        pc.mark_item_committed(pc.get_pending_items(cid)[0]["id"])
        pc.mark_all_committed_as_done(cid)
        assert pc.get_pending_commit() is None

    def test_returns_session_with_committed_items(self, pc_env):
        _, dest = pc_env
        cid = pc.create_commit_session([_email(dest)], [], {})
        pc.mark_item_committed(pc.get_pending_items(cid)[0]["id"])
        info = pc.get_pending_commit()
        assert info is not None
        assert info["committed"] == 1
        assert info["pending"] == 0


class TestStatusTransitions:
    def test_mark_item_committed_moves_status(self, pc_env):
        _, dest = pc_env
        cid = pc.create_commit_session([_email(dest)], [], {})
        item = pc.get_pending_items(cid, "pending")[0]
        pc.mark_item_committed(item["id"])
        assert pc.get_pending_items(cid, "pending") == []
        assert len(pc.get_pending_items(cid, "committed")) == 1

    def test_mark_item_done_moves_status(self, pc_env):
        _, dest = pc_env
        cid = pc.create_commit_session([_email(dest)], [], {})
        item = pc.get_pending_items(cid, "pending")[0]
        pc.mark_item_committed(item["id"])
        pc.mark_item_done(item["id"])
        assert pc.get_pending_items(cid, "committed") == []
        assert len(pc.get_pending_items(cid, "post_action_done")) == 1


class TestPostActionFiltering:
    def _committed(self, item, action):
        cid = pc.create_commit_session([item], [], {_email_key(item): action})
        pc.mark_item_committed(pc.get_pending_items(cid, "pending")[0]["id"])
        return cid

    def test_excludes_leave_action(self, pc_env):
        _, dest = pc_env
        cid = self._committed(_email(dest), "leave")
        assert pc.get_committed_items_needing_post_action(cid) == []

    def test_excludes_import_items(self, pc_env):
        _, dest = pc_env
        cid = self._committed(_email(dest, source_type="import"), "trash")
        assert pc.get_committed_items_needing_post_action(cid) == []

    def test_includes_imap_nonleave(self, pc_env):
        _, dest = pc_env
        cid = self._committed(_email(dest, source_type="account"), "archive")
        result = pc.get_committed_items_needing_post_action(cid)
        assert len(result) == 1
        assert result[0]["source_action"] == "archive"


class TestClearAndDiscard:
    def test_clear_removes_everything(self, pc_env):
        _, dest = pc_env
        cid = pc.create_commit_session([_email(dest), _email(dest)], [], {})
        pc.clear_commit_session(cid)
        assert pc.get_pending_items(cid) == []
        assert pc.get_pending_commit() is None

    def test_discard_deletes_pending_keeps_committed_as_done(self, pc_env):
        _, dest = pc_env
        cid = pc.create_commit_session([_email(dest), _email(dest)], [], {})
        items = pc.get_pending_items(cid, "pending")
        pc.mark_item_committed(items[0]["id"])  # one committed, one still pending
        pc.discard_pending_commit(cid)
        assert pc.get_pending_items(cid, "pending") == []
        assert len(pc.get_pending_items(cid, "post_action_done")) == 1
        # No pending and no committed left -> nothing to resume.
        assert pc.get_pending_commit() is None


class TestSourceKeyHelpers:
    def test_email_key_account(self):
        item = {"sourceType": "account", "sourceAccountId": 7, "destinationFolderId": 3}
        assert pc._build_source_key(item) == "account:7:3"

    def test_email_key_import(self):
        item = {"sourceType": "import", "sourceImportId": 9, "destinationFolderId": 4}
        assert pc._build_source_key(item) == "import:9:4"

    def test_folder_key_account(self):
        item = {"sourceType": "account", "accountId": 2, "destinationFolderId": 5}
        assert pc._build_source_key_folder(item) == "account:2:5"

    def test_folder_key_import(self):
        item = {"sourceType": "import", "importId": 8, "destinationFolderId": 6}
        assert pc._build_source_key_folder(item) == "import:8:6"
