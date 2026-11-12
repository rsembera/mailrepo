"""
Code review 2026-11, findings 2 and 4: a message leaves the mail server
only once that exact message is safely in the archive.

Finding 2: a duplicate used to mean "same Message-ID". The sender picks
the Message-ID, so a different message could be skipped as a duplicate
and then removed from the server by the post-commit action.

Finding 4: the archive file was written with a single unchecked
os.write, never flushed, never read back, and a failed write left an
empty file behind.
"""

import errno
import os

import pytest

import web.blueprints.api.commit as commit
from core import Config, Database, Encryption
from web.blueprints.api.commit import (
    _check_duplicate,
    _save_email_to_archive,
    commit_imap_email,
)

ORIGINAL = b"Message-ID: <same@x>\r\nSubject: original\r\n\r\nthe original text\r\n"
IMPOSTOR = b"Message-ID: <same@x>\r\nSubject: other\r\n\r\nA DIFFERENT MESSAGE\r\n"


@pytest.fixture
def folder(initialized_app):
    cur = Database.execute("INSERT INTO folders (name) VALUES ('F')")
    Database.commit()
    return cur.lastrowid


@pytest.fixture
def account(initialized_app):
    cur = Database.execute(
        "INSERT INTO accounts (name, email, provider) VALUES ('A', 'a@example.com', 'imap')"
    )
    Database.commit()
    return cur.lastrowid


class _Client:
    def __init__(self, raws):
        self.raws = raws
        self.fetched = []

    def fetch_raw(self, uid):
        self.fetched.append(uid)
        return self.raws[uid]


def _results():
    return {"success": [], "failed": [], "skipped": []}


def _archive_files(folder_id):
    return sorted(p.name for p in (Config.get_archive_path() / str(folder_id)).glob("*"))


class TestDuplicateMeansSameMessage:
    def test_same_id_same_content_is_a_duplicate(self, folder):
        _save_email_to_archive(ORIGINAL, folder, None, "import_a")
        assert _check_duplicate(folder, "<same@x>", ORIGINAL) is True

    def test_same_id_different_content_is_not(self, folder):
        _save_email_to_archive(ORIGINAL, folder, None, "import_a")
        assert _check_duplicate(folder, "<same@x>", IMPOSTOR) is False

    def test_line_endings_do_not_make_a_message_different(self, folder):
        _save_email_to_archive(ORIGINAL, folder, None, "import_a")
        assert _check_duplicate(folder, "<same@x>", ORIGINAL.replace(b"\r\n", b"\n")) is True

    def test_an_unreadable_archived_copy_is_not_trusted_as_a_duplicate(self, folder):
        _save_email_to_archive(ORIGINAL, folder, None, "import_a")
        row = Database.fetchone("SELECT filepath FROM messages")
        (Config.get_base_path() / row["filepath"]).write_bytes(b"\x02" + b"damaged" * 10)
        assert _check_duplicate(folder, "<same@x>", ORIGINAL) is False

    def test_a_different_message_reusing_an_id_is_archived_not_skipped(self, folder, account):
        client = _Client({"1": ORIGINAL, "2": IMPOSTOR})
        res = _results()
        first = commit_imap_email(
            client, account, {"uid": "1", "message_id": "<same@x>"}, folder, "INBOX", res, {}
        )
        second = commit_imap_email(
            client, account, {"uid": "2", "message_id": "<same@x>"}, folder, "INBOX", res, {}
        )
        assert (first["status"], second["status"]) == ("success", "success")
        assert Database.fetchone("SELECT COUNT(*) AS c FROM messages")["c"] == 2
        stored = {
            Encryption.decrypt((Config.get_base_path() / r["filepath"]).read_bytes())
            for r in Database.fetchall("SELECT filepath FROM messages")
        }
        assert stored == {ORIGINAL, IMPOSTOR}

    def test_a_true_duplicate_is_still_skipped(self, folder, account):
        client = _Client({"1": ORIGINAL, "2": ORIGINAL})
        res = _results()
        commit_imap_email(
            client, account, {"uid": "1", "message_id": "<same@x>"}, folder, "INBOX", res, {}
        )
        again = commit_imap_email(
            client, account, {"uid": "2", "message_id": "<same@x>"}, folder, "INBOX", res, {}
        )
        assert again["status"] == "skipped"
        assert Database.fetchone("SELECT COUNT(*) AS c FROM messages")["c"] == 1

    def test_a_new_message_id_costs_one_fetch(self, folder, account):
        client = _Client({"1": ORIGINAL})
        commit_imap_email(
            client, account, {"uid": "1", "message_id": "<same@x>"}, folder, "INBOX", _results(), {}
        )
        assert client.fetched == ["1"]


class TestArchiveWrite:
    def test_short_writes_are_completed(self, folder, account, monkeypatch):
        real = os.write
        monkeypatch.setattr(commit.os, "write", lambda fd, data: real(fd, bytes(data[:7])))
        _save_email_to_archive(ORIGINAL, folder, account, "7_1")
        row = Database.fetchone("SELECT filepath FROM messages")
        assert (
            Encryption.decrypt((Config.get_base_path() / row["filepath"]).read_bytes()) == ORIGINAL
        )

    def test_a_failed_write_leaves_no_file_and_no_row(self, folder, account, monkeypatch):
        real = os.write
        calls = {"n": 0}

        def disk_fills(fd, data):
            calls["n"] += 1
            if calls["n"] > 1:
                raise OSError(errno.ENOSPC, "No space left on device")
            return real(fd, bytes(data[:5]))

        monkeypatch.setattr(commit.os, "write", disk_fills)
        with pytest.raises(OSError):
            _save_email_to_archive(ORIGINAL, folder, account, "7_1")
        assert _archive_files(folder) == []
        assert Database.fetchone("SELECT COUNT(*) AS c FROM messages")["c"] == 0

    def test_a_file_that_does_not_read_back_is_rejected(self, folder, account, monkeypatch):
        real = commit._write_new_file

        def truncating(path, data, durable):
            return real(path, data[:-4], durable)  # the tail never reached the disk

        monkeypatch.setattr(commit, "_write_new_file", truncating)
        with pytest.raises(OSError, match="read-back"):
            _save_email_to_archive(ORIGINAL, folder, account, "7_1")
        assert _archive_files(folder) == []
        assert Database.fetchone("SELECT COUNT(*) AS c FROM messages")["c"] == 0

    def test_mail_from_a_server_is_flushed_to_disk_and_imports_are_not(
        self, folder, account, monkeypatch
    ):
        synced = []
        real = os.fsync
        monkeypatch.setattr(commit.os, "fsync", lambda fd: (synced.append(fd), real(fd))[1])

        _save_email_to_archive(ORIGINAL, folder, None, "import_a")
        assert synced == []
        _save_email_to_archive(IMPOSTOR, folder, account, "7_1")
        assert len(synced) == 2  # the file, then its directory entry
