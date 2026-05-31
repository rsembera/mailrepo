"""
Tests for utils/backup.py — change detection, the external state file, and
the full/incremental backup lifecycle.

These cover the subtle, interruption-sensitive paths flagged in the
May 31 2026 pre-1.0 code review (docs/Code_Review_Findings.md #5):

  * the external .backup_state.json round-trip and safe-degrade-on-corruption
  * the two-layer change detector (mtime/size quick check -> hash confirm)
  * the WAL-checkpoint case: a file whose mtime moved but whose content did
    NOT must not produce a spurious backup
  * the baseline-after-verify ordering: an interrupted backup must leave the
    previous baseline intact so the change is re-captured next run

The backup file operations don't touch Encryption or the Database, so these
tests run against plain dummy files placed in the temp data/archive dirs that
the autouse `reset_singletons` fixture points Config at.
"""

import os
import zipfile
from pathlib import Path

import pytest

from utils import backup


def _make_data_files(base: Path):
    """Create the minimal set of files get_all_backup_files() picks up:
    the DB, the two security files, and a couple of archived emails."""
    data = base / "data"
    arch = base / "archive" / "1"
    data.mkdir(parents=True, exist_ok=True)
    arch.mkdir(parents=True, exist_ok=True)
    (data / "mailrepo.db").write_bytes(b"DBDB" * 32)
    (data / ".salt").write_bytes(b"MRC2" + b"x" * 48)
    (data / ".secret_key").write_text("deadbeefcafe")
    (arch / "acct_1.eml.enc").write_bytes(b"\x02" + b"ciphertext-one")
    (arch / "acct_2.eml.enc").write_bytes(b"\x02" + b"ciphertext-two")
    return data, arch


# ---------------------------------------------------------------------------
# External state file
# ---------------------------------------------------------------------------

class TestBackupStateFile:
    def test_write_then_read_roundtrips(self, temp_data_dir):
        state = {"last_backup_hashes": {"a": "1"}, "file_info": {}}
        backup._write_backup_state(state)
        assert backup._read_backup_state() == state

    def test_write_leaves_no_temp_file(self, temp_data_dir):
        backup._write_backup_state({"x": 1})
        leftovers = list((temp_data_dir / "data").glob("*.tmp"))
        assert leftovers == []

    def test_missing_state_returns_empty(self, temp_data_dir):
        assert backup._read_backup_state() == {}

    def test_corrupt_state_returns_empty(self, temp_data_dir):
        state_file = backup._get_backup_state_file()
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text("{ this is not valid json")
        # Safe degrade: a corrupt baseline must not raise; it reads as empty,
        # which forces a full re-hash + backup that rebuilds a clean baseline.
        assert backup._read_backup_state() == {}


# ---------------------------------------------------------------------------
# Change detection (mtime/size quick check + hash layer)
# ---------------------------------------------------------------------------

class TestChangeDetection:
    def test_no_baseline_means_changed(self, temp_data_dir):
        _make_data_files(temp_data_dir)
        assert backup.has_file_changes() is True

    def test_matching_baseline_no_changes(self, temp_data_dir):
        _make_data_files(temp_data_dir)
        hashes, file_info = backup.get_file_hashes()
        backup._save_baseline_hashes(hashes, file_info)
        assert backup.has_file_changes() is False

    def test_modified_content_detected(self, temp_data_dir):
        _make_data_files(temp_data_dir)
        hashes, file_info = backup.get_file_hashes()
        backup._save_baseline_hashes(hashes, file_info)
        (temp_data_dir / "archive" / "1" / "acct_1.eml.enc").write_bytes(
            b"\x02" + b"a-clearly-different-and-longer-ciphertext"
        )
        assert backup.has_file_changes() is True

    def test_added_file_detected(self, temp_data_dir):
        _make_data_files(temp_data_dir)
        hashes, file_info = backup.get_file_hashes()
        backup._save_baseline_hashes(hashes, file_info)
        (temp_data_dir / "archive" / "1" / "acct_3.eml.enc").write_bytes(b"\x02new")
        assert backup.has_file_changes() is True

    def test_deleted_file_detected(self, temp_data_dir):
        _make_data_files(temp_data_dir)
        hashes, file_info = backup.get_file_hashes()
        backup._save_baseline_hashes(hashes, file_info)
        (temp_data_dir / "archive" / "1" / "acct_2.eml.enc").unlink()
        assert backup.has_file_changes() is True

    def test_mtime_only_change_trips_quick_check(self, temp_data_dir):
        # The quick check is intentionally conservative: an mtime bump with no
        # content change reports "maybe changed". The hash layer (exercised in
        # TestBackupLifecycle) is what resolves it to "actually no".
        _make_data_files(temp_data_dir)
        hashes, file_info = backup.get_file_hashes()
        backup._save_baseline_hashes(hashes, file_info)
        db = temp_data_dir / "data" / "mailrepo.db"
        st = db.stat()
        os.utime(db, (st.st_atime + 10, st.st_mtime + 10))
        assert backup.has_file_changes() is True

    def test_get_file_hashes_reuses_cached_hash(self, temp_data_dir):
        # When mtime AND size match the cached file_info, the cached hash is
        # reused without rehashing. Seed a sentinel hash with the file's
        # current metadata and confirm it comes back verbatim.
        _make_data_files(temp_data_dir)
        files = backup.get_all_backup_files()
        rel = "data/mailrepo.db"
        meta = backup.get_file_metadata(files[rel])
        sentinel = "0" * 64
        backup._write_backup_state(
            {"file_info": {rel: {"hash": sentinel, "mtime": meta["mtime"], "size": meta["size"]}}}
        )
        hashes, _ = backup.get_file_hashes()
        assert hashes[rel] == sentinel

    def test_get_file_hashes_recomputes_on_stale_mtime(self, temp_data_dir):
        # When the cached mtime is stale, the hash is recomputed for real.
        _make_data_files(temp_data_dir)
        files = backup.get_all_backup_files()
        rel = "data/mailrepo.db"
        meta = backup.get_file_metadata(files[rel])
        sentinel = "0" * 64
        backup._write_backup_state(
            {"file_info": {rel: {"hash": sentinel, "mtime": meta["mtime"] - 100, "size": meta["size"]}}}
        )
        hashes, _ = backup.get_file_hashes()
        assert hashes[rel] == backup.get_file_hash(files[rel])
        assert hashes[rel] != sentinel


# ---------------------------------------------------------------------------
# Full / incremental lifecycle, including the WAL-checkpoint case
# ---------------------------------------------------------------------------

class TestBackupLifecycle:
    def test_full_backup_creates_zip_manifest_and_baseline(self, temp_data_dir):
        _make_data_files(temp_data_dir)
        info = backup.create_full_backup()
        assert info["type"] == "full"
        assert (backup.get_backups_dir() / info["filename"]).exists()
        manifest = backup.load_manifest()
        assert any(b["filename"] == info["filename"] for b in manifest["backups"])
        assert backup._read_backup_state().get("last_backup_hashes")

    def test_incremental_no_changes_returns_none(self, temp_data_dir):
        _make_data_files(temp_data_dir)
        backup.create_full_backup()
        assert backup.create_incremental_backup() is None

    def test_incremental_after_change_creates_zip_with_changed_file(self, temp_data_dir):
        _make_data_files(temp_data_dir)
        backup.create_full_backup()
        (temp_data_dir / "archive" / "1" / "acct_1.eml.enc").write_bytes(
            b"\x02" + b"DIFFERENT-and-longer-content-than-before"
        )
        info = backup.create_incremental_backup()
        assert info is not None and info["type"] == "incremental"
        bp = backup.get_backups_dir() / info["filename"]
        assert bp.exists()
        with zipfile.ZipFile(bp) as zf:
            names = zf.namelist()
        assert "archive/1/acct_1.eml.enc" in names
        # Unchanged files must not be re-included in the incremental.
        assert "archive/1/acct_2.eml.enc" not in names

    def test_mtime_bump_without_content_change_no_spurious_backup(self, temp_data_dir):
        # The WAL-checkpoint case the review cared about: a checkpoint touches
        # the DB file's mtime without changing logical content. The quick
        # check trips, but the hash comparison finds nothing changed, so no
        # backup is produced AND the baseline mtime is refreshed so the next
        # quick check is clean (no perpetual false positive).
        _make_data_files(temp_data_dir)
        assert backup.create_full_backup()["type"] == "full"
        db = temp_data_dir / "data" / "mailrepo.db"
        st = db.stat()
        os.utime(db, (st.st_atime + 5, st.st_mtime + 5))
        assert backup.has_file_changes() is True
        assert backup.create_incremental_backup() is None
        assert backup.has_file_changes() is False


# ---------------------------------------------------------------------------
# Interrupted-backup safety: baseline is committed only after verify
# ---------------------------------------------------------------------------

class TestBaselineOrderingSafety:
    def test_baseline_unchanged_when_verification_fails(self, temp_data_dir, monkeypatch):
        # Simulate a crash/interruption during backup verification (after the
        # zip is written, before the baseline is saved). The baseline must be
        # left untouched so the change is re-detected and re-captured on the
        # next run -- redundant at worst, never a silent coverage gap.
        _make_data_files(temp_data_dir)
        backup.create_full_backup()
        baseline_before = dict(backup._get_baseline_hashes())

        (temp_data_dir / "archive" / "1" / "acct_1.eml.enc").write_bytes(
            b"\x02" + b"CHANGED-content-that-is-noticeably-longer"
        )

        def boom(_path):
            raise RuntimeError("simulated crash during verify")

        monkeypatch.setattr(backup, "verify_backup", boom)
        with pytest.raises(RuntimeError):
            backup.create_incremental_backup()

        assert backup._get_baseline_hashes() == baseline_before
