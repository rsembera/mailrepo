"""
Tests for the restore path — utils/backup.py's prepare/complete/cancel.

Restore had no automated coverage until Session 68. It had been exercised
by hand exactly twice: Session 34 (February 2026, against v1 crypto) and
the Session 67 drill (against v2). Between those two, the crypto stack was
replaced wholesale. A v2-breaks-restore regression would have gone
unnoticed until someone actually needed their data back — which is the
worst possible moment to discover it.

These tests are the Session 67 drill, automated: build a small v2 archive,
back it up, restore it, assert the restored bytes still decrypt under the
original password. The drill's one manual step (typing the master
password) is unnecessary here because the fixture knows it.
"""

import zipfile
from pathlib import Path

import pytest

from core.config import Config
from core.encryption import Encryption
from utils.backup import (
    cancel_restore,
    check_restore_pending,
    complete_restore,
    create_full_backup,
    create_incremental_backup,
    get_restore_points,
    get_verified_latest_restore_point,
    prepare_restore,
    verify_restore_point_files,
)

# ============================================================
# FIXTURES
# ============================================================


@pytest.fixture
def archive_with_backup(initialized_app):
    """A small v2 archive plus one full backup of it."""
    app, password = initialized_app

    archive_root = Config.get_archive_path() / "1"
    archive_root.mkdir(parents=True, exist_ok=True)

    plaintexts = {
        "1/000.eml.enc": b"From: alice@example.com\r\nSubject: One\r\n\r\nFirst body.",
        "1/001.eml.enc": b"From: bob@example.com\r\nSubject: Two\r\n\r\nSecond body.",
        "1/002.eml.enc": b"From: carol@example.com\r\nSubject: Three\r\n\r\nThird body.",
    }

    for rel, pt in plaintexts.items():
        path = Config.get_archive_path() / rel
        path.write_bytes(Encryption.encrypt(pt))

    with app.app_context():
        backup_info = create_full_backup()
        yield {
            "app": app,
            "password": password,
            "plaintexts": plaintexts,
            "backup_info": backup_info,
        }


def _decrypts_to(staging_dir, rel_path, expected):
    """True if the staged copy of rel_path decrypts to expected plaintext."""
    staged = staging_dir / "archive" / rel_path
    if not staged.exists():
        return False
    return Encryption.decrypt(staged.read_bytes()) == expected


# ============================================================
# THE DRILL: a backup must restore to decryptable content
# ============================================================


class TestRestoreRoundTrip:
    """The claim that matters: backed-up bytes come back and still decrypt."""

    def test_full_backup_creates_a_restore_point(self, archive_with_backup):
        points = get_restore_points()
        assert len(points) >= 1
        assert points[0]["type"] == "full"

    def test_prepare_restore_stages_decryptable_files(self, archive_with_backup):
        points = get_restore_points()
        staging = Path(prepare_restore(points[0]["id"]))

        for rel, expected in archive_with_backup["plaintexts"].items():
            assert _decrypts_to(staging, rel, expected), f"{rel} did not survive"

    def test_backup_carries_its_own_key_material(self, archive_with_backup):
        """A backup that cannot be opened on a fresh machine is not a backup.

        The salt file and the database must travel inside the archive;
        this is what the Session 67 drill confirmed by hand.
        """
        points = get_restore_points()
        staging = Path(prepare_restore(points[0]["id"]))

        salt = staging / "data" / ".salt"
        assert salt.exists(), "backup does not contain the salt file"
        assert salt.read_bytes()[:4] == b"MRC2", "salt file is not v2 format"
        assert (staging / "data" / "mailrepo.db").exists()

    def test_restored_database_is_not_plaintext(self, archive_with_backup):
        points = get_restore_points()
        staging = Path(prepare_restore(points[0]["id"]))
        header = (staging / "data" / "mailrepo.db").read_bytes()[:16]
        assert not header.startswith(b"SQLite format 3")


# ============================================================
# INCREMENTAL CHAINS
# ============================================================


class TestIncrementalChain:
    """Restoring an incremental means replaying full + incrementals in order."""

    def test_incremental_restore_includes_later_changes(self, archive_with_backup):
        new_rel = "1/003.eml.enc"
        new_plain = b"From: dave@example.com\r\nSubject: Four\r\n\r\nAdded later."
        (Config.get_archive_path() / new_rel).write_bytes(Encryption.encrypt(new_plain))

        assert create_incremental_backup() is not None

        points = get_restore_points()
        newest = points[0]
        assert newest["type"] == "incremental"
        assert len(newest["files_needed"]) == 2, "chain should be full + incremental"

        staging = Path(prepare_restore(newest["id"]))

        # Everything from the full...
        for rel, expected in archive_with_backup["plaintexts"].items():
            assert _decrypts_to(staging, rel, expected)
        # ...plus the file that only exists in the incremental.
        assert _decrypts_to(staging, new_rel, new_plain)

    def test_deletion_propagates_through_the_chain(self, archive_with_backup):
        """Deleted files must not reappear on restore.

        This exercises the _backup_metadata.json branch, which only fires
        when an incremental actually records a deletion.
        """
        doomed = "1/002.eml.enc"
        (Config.get_archive_path() / doomed).unlink()

        assert create_incremental_backup() is not None

        points = get_restore_points()
        staging = Path(prepare_restore(points[0]["id"]))

        assert not (staging / "archive" / doomed).exists(), (
            "a file deleted before the incremental came back on restore"
        )
        # The survivors are untouched.
        for rel in ("1/000.eml.enc", "1/001.eml.enc"):
            assert _decrypts_to(staging, rel, archive_with_backup["plaintexts"][rel])

    def test_restoring_an_older_point_does_not_include_newer_files(
        self, archive_with_backup
    ):
        new_rel = "1/003.eml.enc"
        (Config.get_archive_path() / new_rel).write_bytes(Encryption.encrypt(b"later"))
        create_incremental_backup()

        # Restore the FULL, not the incremental.
        full_point = next(p for p in get_restore_points() if p["type"] == "full")
        staging = Path(prepare_restore(full_point["id"]))

        assert not (staging / "archive" / new_rel).exists()


# ============================================================
# SAFETY: staging is not production
# ============================================================


class TestRestoreSafety:
    """prepare_restore must not touch live data until complete_restore runs."""

    def test_prepare_does_not_modify_production(self, archive_with_backup):
        live = Config.get_archive_path() / "1/000.eml.enc"
        before = live.read_bytes()

        prepare_restore(get_restore_points()[0]["id"])

        assert live.read_bytes() == before

    def test_prepare_creates_a_pre_restore_safety_backup(self, archive_with_backup):
        prepare_restore(get_restore_points()[0]["id"])
        assert any(p["type"] == "pre_restore" for p in get_restore_points()), (
            "no safety backup was taken before staging a restore"
        )

    def test_prepare_writes_a_pending_marker(self, archive_with_backup):
        prepare_restore(get_restore_points()[0]["id"])
        assert check_restore_pending()

    def test_cancel_clears_the_pending_restore(self, archive_with_backup):
        prepare_restore(get_restore_points()[0]["id"])
        cancel_restore()
        assert not check_restore_pending()

    def test_cancel_leaves_production_intact(self, archive_with_backup):
        live = Config.get_archive_path() / "1/000.eml.enc"
        before = live.read_bytes()

        prepare_restore(get_restore_points()[0]["id"])
        cancel_restore()

        assert live.read_bytes() == before
        assert Encryption.decrypt(live.read_bytes()) == (
            archive_with_backup["plaintexts"]["1/000.eml.enc"]
        )


# ============================================================
# COMPLETION
# ============================================================


class TestCompleteRestore:
    """complete_restore swaps staging into production at startup."""

    def test_complete_restores_a_deleted_file(self, archive_with_backup):
        victim = Config.get_archive_path() / "1/000.eml.enc"
        expected = archive_with_backup["plaintexts"]["1/000.eml.enc"]
        victim.unlink()

        prepare_restore(get_restore_points()[0]["id"])
        result = complete_restore()

        assert result is not None
        assert victim.exists(), "restore did not bring back the deleted file"
        assert Encryption.decrypt(victim.read_bytes()) == expected

    def test_complete_clears_the_pending_state(self, archive_with_backup):
        prepare_restore(get_restore_points()[0]["id"])
        complete_restore()
        assert not check_restore_pending()

    def test_complete_is_a_no_op_with_nothing_staged(self, archive_with_backup):
        assert complete_restore() is None


# ============================================================
# CHAIN VERIFICATION (the Session 67 gate, tested directly)
# ============================================================


class TestVerifyRestorePointFiles:
    """Previously only exercised indirectly through the password-change gate."""

    def test_healthy_chain_reports_no_problems(self, archive_with_backup):
        assert verify_restore_point_files(get_restore_points()[0]) == []

    def test_missing_file_is_reported(self, archive_with_backup):
        point = get_restore_points()[0]
        Path(point["files_needed"][0]).unlink()
        problems = verify_restore_point_files(point)
        assert len(problems) == 1
        assert "missing" in problems[0]

    def test_zero_byte_file_is_reported(self, archive_with_backup):
        point = get_restore_points()[0]
        Path(point["files_needed"][0]).write_bytes(b"")
        assert "zero bytes" in verify_restore_point_files(point)[0]

    def test_truncated_zip_is_reported(self, archive_with_backup):
        point = get_restore_points()[0]
        path = Path(point["files_needed"][0])
        path.write_bytes(path.read_bytes()[:20])
        assert "not a readable zip" in verify_restore_point_files(point)[0]

    def test_corrupt_entry_is_reported(self, archive_with_backup):
        """A zip whose central directory is fine but whose contents are not.

        This is the case testzip() exists to catch — the file opens, lists
        its entries, and only fails when you actually read the bytes.
        """
        point = get_restore_points()[0]
        path = Path(point["files_needed"][0])

        with zipfile.ZipFile(path) as zf:
            first = zf.infolist()[0]
            offset = first.header_offset + 128

        data = bytearray(path.read_bytes())
        for i in range(offset, min(offset + 64, len(data))):
            data[i] ^= 0xFF
        path.write_bytes(bytes(data))

        problems = verify_restore_point_files(point)
        assert problems, "corrupted payload passed verification"

    def test_verified_latest_refuses_a_broken_newest_point(self, archive_with_backup):
        """No silent fallback to an older backup.

        Someone who believes they have an hour-old backup must not be
        handed one from last week without being told.
        """
        point = get_restore_points()[0]
        Path(point["files_needed"][0]).unlink()

        found, problems = get_verified_latest_restore_point()
        assert found is None
        assert problems
