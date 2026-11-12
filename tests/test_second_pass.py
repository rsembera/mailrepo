# ruff: noqa: F811 - archive fixtures are imported from their home test modules
"""
Code review 2026-11, second pass: restore completion, launch-time
notices, database reset, PDF export, and mbox folder names.
"""

from email.message import EmailMessage

import pytest
from flask import get_flashed_messages

import core.pdf_export as pdf
from core import Config, Database, Encryption, ImapPool
from core.password_change import _write_interruption_marker, get_interruption_marker_path
from tests.test_restore import archive_with_backup  # noqa: F401 - fixture
from utils import backup
from utils.backup import complete_restore, create_full_backup, get_restore_points, prepare_restore
from web.blueprints.api import email_parser as ep


def _data(name):
    return Config.get_data_path() / name


# ---------------------------------------------------------------------------
# Restore completion
# ---------------------------------------------------------------------------


class TestRestoreCompletion:
    def _stage(self):
        point = next(p for p in get_restore_points() if p["type"] == "full")
        prepare_restore(point["id"])
        Database.close()

    def test_restored_files_are_moved_not_copied(self, archive_with_backup, monkeypatch):
        """A move cannot run out of disk halfway and needs no second copy."""
        self._stage()

        def no_copying(*a, **k):
            raise AssertionError("restore copied instead of moving")

        monkeypatch.setattr(backup.shutil, "copytree", no_copying)
        monkeypatch.setattr(backup.shutil, "copy2", no_copying)
        assert complete_restore() is not None
        for rel, expected in archive_with_backup["plaintexts"].items():
            assert Encryption.decrypt((Config.get_archive_path() / rel).read_bytes()) == expected
        assert not backup.get_restore_staging_dir().exists()
        assert not (Config.get_archive_path().parent / "archive.replaced").exists()

    def test_state_belonging_to_the_replaced_archive_is_cleared(self, archive_with_backup):
        _write_interruption_marker(None, phase="master_rotation")
        for name in (".sync_cache.db", ".master_rotation_state", ".v3_migration_state"):
            _data(name).write_bytes(b"stale")
        self._stage()

        complete_restore()

        assert not get_interruption_marker_path().exists()
        for name in (".sync_cache.db", ".master_rotation_state", ".v3_migration_state"):
            assert not _data(name).exists(), name

    def test_mail_archived_after_the_backup_does_not_survive_the_restore(self, archive_with_backup):
        later = Config.get_archive_path() / "1" / "later.eml.enc"
        later.write_bytes(Encryption.encrypt(b"archived after the backup"))
        self._stage()
        complete_restore()
        assert not later.exists()

    def test_restoring_a_point_with_no_mail_empties_the_archive(self, initialized_app):
        create_full_backup()  # database and key file only
        stray = Config.get_archive_path() / "1" / "a.eml.enc"
        stray.parent.mkdir(parents=True, exist_ok=True)
        stray.write_bytes(Encryption.encrypt(b"archived later"))
        self._stage()

        complete_restore()

        assert not stray.exists()
        assert Config.get_archive_path().is_dir()

    def test_an_interrupted_completion_finishes_on_the_next_launch(self, archive_with_backup):
        self._stage()
        # Died after setting the old archive aside, before the new one landed.
        archive = Config.get_archive_path()
        archive.rename(archive.with_name("archive.replaced"))

        assert complete_restore() is not None
        for rel, expected in archive_with_backup["plaintexts"].items():
            assert Encryption.decrypt((archive / rel).read_bytes()) == expected
        assert not archive.with_name("archive.replaced").exists()

    def test_a_set_aside_folder_from_an_earlier_attempt_does_not_block(self, archive_with_backup):
        self._stage()
        leftover = Config.get_archive_path().with_name("archive.replaced")
        leftover.mkdir()
        (leftover / "old.eml.enc").write_bytes(b"from an attempt that died")

        assert complete_restore() is not None
        assert not leftover.exists()
        for rel, expected in archive_with_backup["plaintexts"].items():
            assert Encryption.decrypt((Config.get_archive_path() / rel).read_bytes()) == expected


# ---------------------------------------------------------------------------
# Launch-time notices reach the login screen
# ---------------------------------------------------------------------------


class TestStartupNotices:
    def _login_page(self, app):
        return app.test_client().get("/auth/login").get_data(as_text=True)

    def test_an_ordinary_launch_shows_none(self, initialized_app):
        app, _pw = initialized_app
        Database.close()
        Encryption.lock()
        assert "startup-notice" not in self._login_page(app)

    def test_an_interrupted_key_change_is_explained(self, initialized_app):
        app, _pw = initialized_app
        _write_interruption_marker({"filename": "full_x.zip"}, phase="master_rotation")
        Database.close()
        Encryption.lock()
        page = self._login_page(app)
        assert "startup-notice" in page
        assert "master-key rotation was interrupted" in page
        assert "full_x.zip" in page

    def test_terminal_line_breaks_are_unwrapped_for_the_page(self):
        from web.blueprints.auth import _reflow

        text = "First line of a\nparagraph that was\nwrapped.\n\nSecond paragraph.\nA backup was verified immediately beforehand: full_x.zip"
        assert _reflow(text) == (
            "First line of a paragraph that was wrapped.\n\n"
            "Second paragraph.\n\n"
            "A backup was verified immediately beforehand: full_x.zip"
        )

    def test_a_missing_database_is_explained(self, initialized_app):
        app, _pw = initialized_app
        Database.close()
        Encryption.lock()
        Config.get_database_path().unlink()
        assert "no database" in self._login_page(app)

    def test_a_failed_restore_is_explained(self, initialized_app):
        app, _pw = initialized_app
        Database.close()
        Encryption.lock()
        app.config["RESTORE_FAILED"] = "No space left on device"
        page = self._login_page(app)
        assert "could not be completed" in page
        assert "No space left on device" in page

    def test_the_notice_goes_when_its_cause_does(self, initialized_app):
        from core.password_change import clear_interruption_marker

        app, _pw = initialized_app
        _write_interruption_marker(None)
        Database.close()
        Encryption.lock()
        assert "startup-notice" in self._login_page(app)
        clear_interruption_marker()
        assert "startup-notice" not in self._login_page(app)


class TestRestoredDatabaseIsChecked:
    def _vouch(self, app):
        from web.blueprints.auth import _vouch_for_restored_data

        with app.test_request_context("/"):
            _vouch_for_restored_data()
            return get_flashed_messages(with_categories=True)

    def test_a_sound_restored_database_raises_nothing(self, initialized_app):
        app, _pw = initialized_app
        backup.set_restore_unverified()
        assert [m for c, m in self._vouch(app) if c == "error"] == []
        assert not backup.restore_unverified()

    def test_a_damaged_restored_database_is_reported(self, initialized_app, monkeypatch):
        app, _pw = initialized_app
        backup.set_restore_unverified()
        real = Database.fetchall

        def fetchall(sql, params=()):
            if "quick_check" in sql:
                return [("*** in database main ***\nPage 12: btreeInitPage() returns error",)]
            return real(sql, params)

        monkeypatch.setattr(Database, "fetchall", staticmethod(fetchall))
        errors = [m for c, m in self._vouch(app) if c == "error"]
        assert len(errors) == 1 and "integrity check" in errors[0]

    def test_the_check_only_runs_after_a_restore(self, initialized_app, monkeypatch):
        app, _pw = initialized_app
        asked = []
        real = Database.fetchall
        monkeypatch.setattr(
            Database,
            "fetchall",
            staticmethod(lambda sql, params=(): (asked.append(sql), real(sql, params))[1]),
        )
        self._vouch(app)
        assert not any("quick_check" in sql for sql in asked)


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


def test_reset_leaves_nothing_of_the_old_archive_in_the_process(
    authenticated_client, initialized_app, monkeypatch
):
    _app, password = initialized_app
    closed = []
    monkeypatch.setattr(ImapPool, "close_all", classmethod(lambda cls: closed.append(True)))
    _write_interruption_marker(None, phase="master_rotation")
    _data(".master_rotation_state").write_bytes(b"x")

    resp = authenticated_client.post(
        "/api/reset_database", json={"password": password, "confirmation": "RESET"}
    )

    assert resp.get_json()["success"] is True
    assert closed == [True], "pooled mail-server connections must not outlive the accounts"
    assert Database._db_key is None
    assert not get_interruption_marker_path().exists()
    assert not _data(".master_rotation_state").exists()


# ---------------------------------------------------------------------------
# PDF export
# ---------------------------------------------------------------------------


def _archive(folder_id, name, raw, date=None):
    directory = Config.get_archive_path() / str(folder_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.eml.enc"
    path.write_bytes(Encryption.encrypt(raw))
    cur = Database.execute(
        "INSERT INTO messages (folder_id, message_id, subject, date, filepath) VALUES (?, ?, ?, ?, ?)",
        (folder_id, f"<{name}@x>", name, date, str(path.relative_to(Config.get_base_path()))),
    )
    return cur.lastrowid


def _mail(subject, date):
    m = EmailMessage()
    m["Subject"] = subject
    m["From"] = "a@b.c"
    m["Date"] = date
    m.set_content(f"body of {subject}")
    return m


class TestPdfExport:
    def test_export_lists_the_attachments_the_viewer_shows(self, initialized_app):
        Database.execute("INSERT INTO folders (id, name) VALUES (1, 'F')")
        m = _mail("pics", "Mon, 05 Jan 2026 10:00:00 +0000")
        m.add_alternative("<p>see attached</p>", subtype="html")
        m.add_attachment(
            b"\x89PNG-bytes", maintype="image", subtype="png", filename="photo.png", cid="<c1>"
        )
        m.add_attachment(b"%PDF-bytes", maintype="application", subtype="pdf", filename="r.pdf")
        mid = _archive(1, "pics", m.as_bytes())
        Database.commit()

        loaded = pdf._load_email(mid)
        # photo.png carries a Content-ID the HTML never uses; the export's
        # own copy of the rules used to leave it out.
        assert [a["filename"] for a in loaded["attachments"]] == ["photo.png", "r.pdf"]
        assert [a["is_pdf"] for a in loaded["attachments"]] == [False, True]

    def test_messages_are_ordered_by_when_they_were_sent(self, initialized_app):
        Database.execute("INSERT INTO folders (id, name) VALUES (1, 'F')")
        # 10:00 +05:00 is 05:00 UTC; 08:00 -05:00 is 13:00 UTC.
        early = _archive(1, "early", _mail("early", "Mon, 05 Jan 2026 10:00:00 +0500").as_bytes())
        late = _archive(1, "late", _mail("late", "Mon, 05 Jan 2026 08:00:00 -0500").as_bytes())
        Database.commit()

        a, b = pdf._load_email(early), pdf._load_email(late)
        assert a["date_ts"] < b["date_ts"]
        assert a["date_iso"] > b["date_iso"]  # which is why the text could not be the sort key

    def test_export_says_how_many_it_left_out(self, initialized_app):
        Database.execute("INSERT INTO folders (id, name) VALUES (1, 'F')")
        good = _archive(1, "good", _mail("good", "Mon, 05 Jan 2026 10:00:00 +0000").as_bytes())
        gone = _archive(1, "gone", b"x")
        (Config.get_archive_path() / "1" / "gone.eml.enc").unlink()
        Database.commit()

        events = list(pdf.build_combined_pdf([good, gone], include_cover=False))
        done = [e for e in events if e["event"] == "complete"][0]["data"]
        assert (done["email_count"], done["skipped_count"]) == (1, 1)


# ---------------------------------------------------------------------------
# mbox folder names
# ---------------------------------------------------------------------------


@pytest.fixture
def labelled_mbox(tmp_path):
    path = tmp_path / "labels.mbox"
    path.write_bytes(
        b"From a@b Mon Jan  5 00:00:00 2026\n"
        b"Subject: one\nX-Folder: =?UTF-8?Q?S=C3=A9ance?=\n\nbody\n\n"
        b"From a@b Mon Jan  5 00:00:01 2026\n"
        b"Subject: two\nX-Folder: Other\n\nbody\n\n"
    )
    ep._mbox_cache.clear()
    return str(path)


def test_a_folder_with_an_accented_name_commits_its_mail(labelled_mbox):
    """The import list showed "Séance"; the commit compared it with the
    undecoded header and found nothing."""
    assert ep.count_emails_in_import_folder(labelled_mbox, "Séance", "mbox") == 1
    assert [u for u, _ in ep.iter_emails_from_import_folder(labelled_mbox, "Séance", "mbox")] == [
        "mbox-0"
    ]


def test_scan_and_commit_agree_on_folders_and_ids(
    authenticated_client, initialized_app, labelled_mbox
):
    resp = authenticated_client.post("/api/filesystem/parse-mbox", json={"path": labelled_mbox})
    body = resp.get_json()
    assert [e["uid"] for e in body["emails"]] == ["mbox-0", "mbox-1"]
    assert [e["subject"] for e in body["emails"]] == ["one", "two"]
    for folder in body["folders"]:
        listed = sorted(folder["emailUids"])
        committed = sorted(
            u
            for u, _ in ep.iter_emails_from_import_folder(labelled_mbox, folder["fullPath"], "mbox")
        )
        assert listed == committed, folder["fullPath"]
