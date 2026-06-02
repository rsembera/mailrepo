"""
Tests for the commit workflow: web/blueprints/api/commit.py helpers and
the streaming endpoint in web/blueprints/api/progress_commit.py.

The pure helpers (archive-folder-from-path, duplicate detection, summary
building, post-action key parsing, and the atomic save-to-archive) are
unit-tested directly. The SSE endpoint is exercised end to end for the
import path (no IMAP): a staged import email backed by a real .eml on
disk is committed through /api/commit/stream, and we verify the archive
row + encrypted file land and the pending_commit session is cleared.
This complements the pending_commit state-machine unit tests from
Session 39.
"""

import json
import secrets

import pytest

from core import Database, Config, Encryption
from web.blueprints.api.commit import (
    create_archive_folder_from_path,
    _check_duplicate,
    build_commit_summary,
    _find_action_for_source,
    _save_email_to_archive,
)


def _make_folder(name, parent_id=None):
    cur = Database.execute(
        "INSERT INTO folders (name, parent_id) VALUES (?, ?)", (name, parent_id)
    )
    Database.commit()
    return cur.lastrowid


def _empty_results():
    return {
        "success": [], "failed": [], "skipped": [],
        "folders_success": 0, "folders_failed": 0,
        "post_actions": {"success": 0, "failed": 0, "by_action": {"archive": 0, "trash": 0, "delete": 0}},
    }


def _raw_eml(subject="Hi", body="hello body", message_id=None):
    mid = message_id or f"<{secrets.token_hex(6)}@test>"
    return (
        f"From: a@example.com\r\nTo: b@example.com\r\n"
        f"Subject: {subject}\r\nMessage-ID: {mid}\r\n"
        f'MIME-Version: 1.0\r\nContent-Type: text/plain; charset="utf-8"\r\n\r\n'
        f"{body}\r\n"
    ).encode()


# ---------------------------------------------------------------------------
# create_archive_folder_from_path
# ---------------------------------------------------------------------------

class TestArchiveFolderFromPath:
    def test_empty_path_returns_parent(self, initialized_app):
        parent = _make_folder("Root")
        assert create_archive_folder_from_path("", parent) == parent

    def test_single_segment(self, initialized_app):
        parent = _make_folder("Root")
        new_id = create_archive_folder_from_path("Clients", parent)
        row = Database.fetchone("SELECT name, parent_id FROM folders WHERE id = ?", (new_id,))
        assert row["name"] == "Clients"
        assert row["parent_id"] == parent

    def test_nested_chain(self, initialized_app):
        parent = _make_folder("Root")
        deepest = create_archive_folder_from_path("Fan Mail/2024/Q1", parent)
        row = Database.fetchone("SELECT name FROM folders WHERE id = ?", (deepest,))
        assert row["name"] == "Q1"
        # The whole chain exists: Root -> Fan Mail -> 2024 -> Q1
        names = {r["name"] for r in Database.fetchall("SELECT name FROM folders", ())}
        assert {"Root", "Fan Mail", "2024", "Q1"} <= names

    def test_reuses_existing_folder(self, initialized_app):
        parent = _make_folder("Root")
        first = create_archive_folder_from_path("Shared", parent)
        second = create_archive_folder_from_path("Shared", parent)
        assert first == second  # no duplicate created


# ---------------------------------------------------------------------------
# _check_duplicate
# ---------------------------------------------------------------------------

class TestCheckDuplicate:
    def _seed(self, folder_id, message_id, deleted=False):
        Database.execute(
            """INSERT INTO messages (folder_id, message_id, subject, filepath, deleted_at)
               VALUES (?, ?, ?, ?, ?)""",
            (folder_id, message_id, "S", "p.eml.enc", 123 if deleted else None),
        )
        Database.commit()

    def test_blank_message_id_is_never_duplicate(self, initialized_app):
        fid = _make_folder("F")
        assert _check_duplicate(fid, "") is False

    def test_existing_is_duplicate(self, initialized_app):
        fid = _make_folder("F")
        self._seed(fid, "<dup@test>")
        assert _check_duplicate(fid, "<dup@test>") is True

    def test_trashed_does_not_count(self, initialized_app):
        fid = _make_folder("F")
        self._seed(fid, "<gone@test>", deleted=True)
        assert _check_duplicate(fid, "<gone@test>") is False

    def test_other_folder_not_duplicate(self, initialized_app):
        f1 = _make_folder("F1")
        f2 = _make_folder("F2")
        self._seed(f1, "<x@test>")
        assert _check_duplicate(f2, "<x@test>") is False


# ---------------------------------------------------------------------------
# build_commit_summary
# ---------------------------------------------------------------------------

class TestBuildCommitSummary:
    def test_nothing_committed(self):
        assert build_commit_summary(_empty_results()) == "Nothing committed."

    def test_emails_filed(self):
        r = _empty_results()
        r["success"] = ["a", "b", "c"]
        assert "3 emails filed" in build_commit_summary(r)

    def test_folders_singular_plural(self):
        r = _empty_results()
        r["folders_success"] = 1
        assert "1 folder archived" in build_commit_summary(r)
        r["folders_success"] = 2
        assert "2 folders archived" in build_commit_summary(r)

    def test_skipped_duplicates(self):
        r = _empty_results()
        r["skipped"] = [{"uid": "1"}, {"uid": "2"}]
        assert "2 skipped (duplicates)" in build_commit_summary(r)

    def test_failures_counted(self):
        r = _empty_results()
        r["failed"] = [{"uid": "1"}]
        r["folders_failed"] = 1
        assert "2 failed" in build_commit_summary(r)

    def test_post_actions_by_action(self):
        r = _empty_results()
        r["post_actions"]["success"] = 3
        r["post_actions"]["by_action"] = {"archive": 2, "trash": 1, "delete": 0}
        summary = build_commit_summary(r)
        assert "2 archived" in summary and "1 trashed" in summary and "on server" in summary


# ---------------------------------------------------------------------------
# _find_action_for_source
# ---------------------------------------------------------------------------

class TestFindActionForSource:
    def test_three_part_key_applies_to_account(self):
        actions = {"account:1:5": "archive"}
        assert _find_action_for_source(actions, 1, "INBOX") == "archive"

    def test_four_part_key_matches_folder(self):
        actions = {"account:1:INBOX:5": "trash"}
        assert _find_action_for_source(actions, 1, "INBOX") == "trash"
        assert _find_action_for_source(actions, 1, "Sent") is None

    def test_folder_name_with_colon(self):
        actions = {"account:2:[Gmail]:All Mail:9": "delete"}
        assert _find_action_for_source(actions, 2, "[Gmail]:All Mail") == "delete"

    def test_wrong_account_returns_none(self):
        actions = {"account:1:5": "archive"}
        assert _find_action_for_source(actions, 2, "INBOX") is None


# ---------------------------------------------------------------------------
# _save_email_to_archive (atomic file + DB)
# ---------------------------------------------------------------------------

class TestSaveEmailToArchive:
    def test_happy_path_writes_file_and_row(self, initialized_app):
        fid = _make_folder("Archive")
        raw = _raw_eml(subject="Archived subject", body="archived body 77")
        _save_email_to_archive(raw, fid, None, "import_eml-0")

        row = Database.fetchone(
            "SELECT subject, filepath FROM messages WHERE folder_id = ?", (fid,)
        )
        assert row["subject"] == "Archived subject"
        fp = Config.get_base_path() / row["filepath"]
        assert fp.exists()
        # File on disk is ciphertext that decrypts back to the original bytes
        assert Encryption.decrypt(fp.read_bytes()) == raw

    def test_db_failure_removes_orphan_file(self, initialized_app, monkeypatch):
        fid = _make_folder("Archive")
        raw = _raw_eml()
        expected = Config.get_archive_path() / str(fid) / "import_fail-1.eml.enc"

        def boom(*args, **kwargs):
            raise RuntimeError("simulated insert failure")

        monkeypatch.setattr(Database, "execute", staticmethod(boom))
        with pytest.raises(RuntimeError):
            _save_email_to_archive(raw, fid, None, "import_fail-1")
        # The orphaned file must have been cleaned up
        assert not expected.exists()


# ---------------------------------------------------------------------------
# SSE endpoint: /api/commit/stream
# ---------------------------------------------------------------------------

def _parse_sse(text):
    """Parse an SSE stream into a list of (event, data_dict) tuples."""
    events = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        event = None
        data = None
        for line in block.split("\n"):
            if line.startswith("event: "):
                event = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        if event:
            events.append((event, data))
    return events


class TestCommitStream:
    def test_empty_payload_errors(self, authenticated_client, initialized_app):
        resp = authenticated_client.post("/api/commit/stream", json={})
        events = _parse_sse(resp.get_data(as_text=True))
        assert ("error", {"error": "No items to commit"}) in events

    def test_import_email_round_trip(self, authenticated_client, initialized_app, tmp_path):
        fid = _make_folder("Filed")
        eml = tmp_path / "msg.eml"
        eml.write_bytes(_raw_eml(subject="Committed via stream", body="stream body"))

        staged = [{
            "sourceType": "import",
            "destinationFolderId": fid,
            "email": {
                "uid": "eml-0",
                "subject": "Committed via stream",
                "message_id": "<stream@test>",
                "sourcePath": str(eml),
            },
        }]
        resp = authenticated_client.post("/api/commit/stream", json={"staged": staged})
        events = _parse_sse(resp.get_data(as_text=True))
        types = [e for e, _ in events]

        # A commit id was minted and the run completed
        assert "start" in types and "complete" in types
        start_data = next(d for e, d in events if e == "start")
        commit_id = start_data["commitId"]

        # The email landed in the archive with a real encrypted file
        row = Database.fetchone(
            "SELECT subject, filepath FROM messages WHERE folder_id = ?", (fid,)
        )
        assert row is not None and row["subject"] == "Committed via stream"
        assert (Config.get_base_path() / row["filepath"]).exists()

        # The pending_commit session was cleared on success
        remaining = Database.fetchone(
            "SELECT COUNT(*) AS c FROM pending_commit WHERE commit_id = ?", (commit_id,)
        )
        assert remaining["c"] == 0
