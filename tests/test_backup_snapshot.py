"""
Code review 2026-11, finding 1: a backup must hold a database that opens.

The backup functions used to zip the live database file. A checkpoint on
another thread rewrites pages in that file mid-read, and the copy came
out as a mix of old and new pages: the zip CRC and the MAC both passed,
and the damage showed only on restore. Two callers (the pre-rotation and
pre-upgrade backups) also skipped the WAL checkpoint, so their database
could be missing the most recent commits.
"""

import threading
import zipfile

from sqlcipher3 import dbapi2 as sqlcipher

from core.config import Config
from core.database import Database
from core.encryption import Encryption
from utils import backup


def _open_backed_up_db(zip_path, dest):
    with zipfile.ZipFile(zip_path) as zf:
        zf.extract(backup.DB_REL_PATH, dest)
    conn = sqlcipher.connect(str(dest / backup.DB_REL_PATH))
    conn.execute(f"PRAGMA key = \"x'{Encryption.get_db_key()}'\"")
    return conn


def _zip_path(info):
    return backup.get_backup_path_for_entry(info)


class TestSnapshot:
    def test_backup_under_concurrent_writes_holds_a_sound_database(self, initialized_app, tmp_path):
        blob = "x" * 8000
        for i in range(1500):
            Database.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (f"k{i}", blob))
        Database.commit()

        stop = threading.Event()

        def writer():  # a commit stream archiving mail on another thread
            n = 0
            while not stop.is_set():
                for _ in range(100):
                    Database.execute(
                        "UPDATE settings SET value = ? WHERE key = ?",
                        (str(n) + blob[: 7000 + (n % 900)], f"k{(n * 37) % 1500}"),
                    )
                    n += 1
                Database.commit()

        thread = threading.Thread(target=writer)
        thread.start()
        try:
            for round_no in range(4):
                info = backup.create_full_backup()
                dest = tmp_path / f"restore{round_no}"
                dest.mkdir()
                conn = _open_backed_up_db(_zip_path(info), dest)
                try:
                    assert conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
                finally:
                    conn.close()
        finally:
            stop.set()
            thread.join()

    def test_full_backup_includes_commits_still_in_the_wal(self, initialized_app, tmp_path):
        """No caller-side checkpoint: the backup must not depend on one."""
        Database.execute("INSERT INTO folders (name) VALUES ('Client: Smith')")
        Database.commit()  # in the WAL, not yet in the main file

        info = backup.create_full_backup()
        conn = _open_backed_up_db(_zip_path(info), tmp_path)
        try:
            names = [r[0] for r in conn.execute("SELECT name FROM folders")]
        finally:
            conn.close()
        assert names == ["Client: Smith"]

    def test_incremental_sees_a_change_that_is_only_in_the_wal(self, initialized_app, tmp_path):
        backup.create_full_backup()
        Database.execute("INSERT INTO folders (name) VALUES ('Added later')")
        Database.commit()

        info = backup.create_incremental_backup()
        assert info is not None, "an uncheckpointed commit must count as a change"
        conn = _open_backed_up_db(_zip_path(info), tmp_path)
        try:
            names = [r[0] for r in conn.execute("SELECT name FROM folders")]
        finally:
            conn.close()
        assert names == ["Added later"]

    def test_unchanged_archive_still_yields_no_incremental(self, initialized_app):
        backup.create_full_backup()
        assert backup.create_incremental_backup() is None

    def test_snapshot_file_is_removed(self, initialized_app):
        backup.create_full_backup()
        assert not (Config.get_data_path() / ".backup_snapshot.db").exists()

    def test_damaged_copy_is_refused(self, initialized_app, monkeypatch):
        """If the copy does not pass SQLite's own check, no backup is recorded."""
        import shutil

        import pytest

        real_copy = shutil.copyfile

        def torn_copy(src, dst):
            real_copy(src, dst)
            with open(dst, "r+b") as fh:  # scribble over a page in the middle
                fh.seek(4096 * 3)
                fh.write(b"\x00" * 4096)

        Database.execute("INSERT INTO folders (name) VALUES ('x')")
        Database.commit()
        monkeypatch.setattr(backup.shutil, "copyfile", torn_copy)
        with pytest.raises(ValueError, match="Backup refused"):
            backup.create_full_backup()
        assert backup.load_manifest()["backups"] == []
