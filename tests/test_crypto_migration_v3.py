"""
Tests for the v2 -> v3 crypto migration (envelope encryption).

The migration re-encrypts the whole archive under a new random master.
That is a lot of moving data, so these tests care mostly about one thing:
every byte that went in comes back out, readable, under both the password
and the new recovery key.
"""

import json
import zipfile
from datetime import datetime, timedelta

import pytest

from core.config import Config
from core.crypto_migration_v3 import (
    MigrationError,
    get_migration_state_path,
    migrate_to_v3,
    needs_v3_migration,
)
from core.encryption import Encryption, InvalidPasswordError
from core.password_change import (
    check_password_change_interrupted,
    describe_interrupted_password_change,
    get_interruption_marker_path,
)

PASSWORD = "TestPassword123!"


def write_backup_manifest(backups_dir, created, filename="full_test.zip"):
    """A real zip plus manifest entry — the gate opens the file, not the JSON."""
    zip_path = backups_dir / filename
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("data/placeholder.txt", "test backup content")

    (backups_dir / "manifest.json").write_text(
        json.dumps(
            {
                "current_chain_id": "testchain",
                "backups": [
                    {
                        "filename": filename,
                        "created_at": created.isoformat(),
                        "type": "full",
                        "chain_id": "testchain",
                        "backup_dir": str(backups_dir),
                    }
                ],
            }
        )
    )
    return zip_path


@pytest.fixture
def v2_archive(initialized_app):
    """A v2 archive with encrypted files and a fresh verified backup."""
    app, password = initialized_app
    tmp_path = Config.get_data_path().parent

    archive_root = Config.get_archive_path() / "1"
    archive_root.mkdir(parents=True, exist_ok=True)

    plaintexts = {
        "1/000.eml.enc": b"From: alice@example.com\r\nSubject: One\r\n\r\nFirst body.",
        "1/001.eml.enc": b"From: bob@example.com\r\nSubject: Two\r\n\r\nSecond body.",
        "1/002.eml.enc": b"From: carol@example.com\r\nSubject: Three\r\n\r\nThird.",
    }
    for rel, pt in plaintexts.items():
        (Config.get_archive_path() / rel).write_bytes(Encryption.encrypt(pt))

    backups_dir = tmp_path / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    write_backup_manifest(backups_dir, datetime.now())

    with app.app_context():
        yield {
            "app": app,
            "password": password,
            "plaintexts": plaintexts,
            "backups_dir": backups_dir,
        }


# ============================================================
# DETECTION
# ============================================================


class TestNeedsMigration:
    def test_v2_archive_needs_migration(self, v2_archive):
        assert needs_v3_migration()

    def test_v3_archive_does_not(self, v2_archive):
        migrate_to_v3(PASSWORD)
        assert not needs_v3_migration()


# ============================================================
# THE MIGRATION ITSELF
# ============================================================


class TestMigration:
    def test_returns_a_working_recovery_key(self, v2_archive):
        rk = migrate_to_v3(PASSWORD)
        Encryption.lock()
        assert Encryption.unlock_with_recovery_key(rk)

    def test_archive_content_survives(self, v2_archive):
        """The only claim that really matters."""
        migrate_to_v3(PASSWORD)

        for rel, expected in v2_archive["plaintexts"].items():
            data = (Config.get_archive_path() / rel).read_bytes()
            assert Encryption.decrypt(data) == expected

    def test_content_readable_after_unlocking_with_recovery_key(self, v2_archive):
        rk = migrate_to_v3(PASSWORD)
        Encryption.lock()
        Encryption.unlock_with_recovery_key(rk)

        for rel, expected in v2_archive["plaintexts"].items():
            data = (Config.get_archive_path() / rel).read_bytes()
            assert Encryption.decrypt(data) == expected

    def test_password_still_works_after_migration(self, v2_archive):
        migrate_to_v3(PASSWORD)
        Encryption.lock()
        assert Encryption.unlock(PASSWORD)

    def test_key_file_becomes_v3(self, v2_archive):
        migrate_to_v3(PASSWORD)
        assert Encryption.salt_file_version() == 3
        assert Encryption.has_recovery_key()

    def test_master_is_not_password_derived_afterwards(self, v2_archive):
        """The property the whole design exists to preserve.

        Under the cheap migration the new master would equal the value the
        password derives through the OLD salt, and this would fail.
        """
        old_derived = Encryption.derive_v2_file_key_for_password(PASSWORD)
        migrate_to_v3(PASSWORD)
        assert Encryption._file_key_v2 != old_derived

    def test_each_migration_produces_a_different_recovery_key(self, initialized_app):
        keys = set()
        for _ in range(3):
            Encryption.lock()
            keys.add(Encryption.generate_recovery_key())
        assert len(keys) == 3

    def test_progress_callback_reports_stages(self, v2_archive):
        seen = []
        migrate_to_v3(PASSWORD, progress_cb=lambda p: seen.append(p["status"]))
        assert "counting" in seen
        assert "encrypting" in seen
        assert "complete" in seen


# ============================================================
# REFUSALS
# ============================================================


class TestMigrationRefusals:
    def test_refuses_when_already_v3(self, v2_archive):
        migrate_to_v3(PASSWORD)
        with pytest.raises(MigrationError, match="already uses recovery keys"):
            migrate_to_v3(PASSWORD)

    def test_refuses_with_wrong_password(self, v2_archive):
        with pytest.raises(InvalidPasswordError):
            migrate_to_v3("WrongPassword!")

    def test_refuses_without_a_backup_file(self, v2_archive):
        (v2_archive["backups_dir"] / "full_test.zip").unlink()
        with pytest.raises(MigrationError, match="did not verify"):
            migrate_to_v3(PASSWORD)

    def test_refuses_with_a_stale_backup(self, v2_archive):
        (v2_archive["backups_dir"] / "full_test.zip").unlink()
        write_backup_manifest(
            v2_archive["backups_dir"],
            datetime.now() - timedelta(hours=48),
            filename="full_old.zip",
        )
        with pytest.raises(MigrationError, match="backup"):
            migrate_to_v3(PASSWORD)

    def test_refuses_when_locked(self, v2_archive):
        Encryption.lock()
        with pytest.raises(MigrationError, match="locked"):
            migrate_to_v3(PASSWORD)

    def test_a_refused_migration_leaves_the_archive_untouched(self, v2_archive):
        (v2_archive["backups_dir"] / "full_test.zip").unlink()
        with pytest.raises(MigrationError):
            migrate_to_v3(PASSWORD)

        assert Encryption.salt_file_version() == 2
        for rel, expected in v2_archive["plaintexts"].items():
            data = (Config.get_archive_path() / rel).read_bytes()
            assert Encryption.decrypt(data) == expected


# ============================================================
# INTERRUPTION
# ============================================================


class TestMigrationInterruption:
    def test_marker_cleared_after_success(self, v2_archive):
        migrate_to_v3(PASSWORD)
        assert check_password_change_interrupted() is None

    def test_crash_in_the_window_leaves_a_migration_marker(
        self, v2_archive, monkeypatch
    ):
        import core.crypto_migration_v3 as mig

        def boom(*args, **kwargs):
            raise RuntimeError("simulated crash mid-migration")

        monkeypatch.setattr(mig.Database, "acquire_for_migration", boom)

        with pytest.raises(RuntimeError, match="simulated crash"):
            migrate_to_v3(PASSWORD)

        marker = check_password_change_interrupted()
        assert marker is not None
        assert marker["phase"] == "v3_migration"

    def test_migration_marker_message_says_it_is_re_runnable(self):
        text = describe_interrupted_password_change(
            {
                "started_at": "2026-08-09T12:00:00",
                "phase": "v3_migration",
                "verified_backup": "full_test.zip",
            }
        )
        assert "recovery-key upgrade" in text
        assert "re-run" in text

    def test_an_interrupted_migration_can_simply_be_re_run(self, v2_archive):
        """The claim the interruption message makes to the user.

        The key file is written last, so a crash in the window leaves v2
        on disk with the archive files already converted to a master that
        nothing now knows. Re-running must recover from that: _rekey_file
        tries the old key, then the new one, and a file that decrypts
        under neither halts loudly rather than being skipped.
        """
        import core.crypto_migration_v3 as mig

        original = mig.Database.acquire_for_migration

        def boom(*args, **kwargs):
            raise RuntimeError("crash after the walk")

        mig.Database.acquire_for_migration = boom
        try:
            with pytest.raises(RuntimeError):
                migrate_to_v3(PASSWORD)
        finally:
            mig.Database.acquire_for_migration = original

        # Interrupted: marker present, key file still v2.
        assert get_interruption_marker_path().exists()
        assert Encryption.salt_file_version() == 2

        # Re-run. The password still unlocks the v2 key file, so the user
        # can log in and try again exactly as the message tells them to.
        recovery_key = migrate_to_v3(PASSWORD)

        assert Encryption.salt_file_version() == 3
        assert check_password_change_interrupted() is None

        for rel, expected in v2_archive["plaintexts"].items():
            data = (Config.get_archive_path() / rel).read_bytes()
            assert Encryption.decrypt(data) == expected

        Encryption.lock()
        Encryption.unlock_with_recovery_key(recovery_key)
        for rel, expected in v2_archive["plaintexts"].items():
            data = (Config.get_archive_path() / rel).read_bytes()
            assert Encryption.decrypt(data) == expected


# ============================================================
# RESUME STATE
# ============================================================


class TestMigrationResumeState:
    """The stored master is what makes a re-run possible at all."""

    def test_no_state_left_behind_after_success(self, v2_archive):
        migrate_to_v3(PASSWORD)
        assert not get_migration_state_path().exists()

    def test_state_written_before_the_walk(self, v2_archive):
        """Written early enough to survive a crash during the walk."""
        import core.crypto_migration_v3 as mig

        seen = {}
        original = mig._rekey_file

        def spy(path, old_key, new_key):
            seen.setdefault("state_exists", get_migration_state_path().exists())
            return original(path, old_key, new_key)

        mig._rekey_file = spy
        try:
            migrate_to_v3(PASSWORD)
        finally:
            mig._rekey_file = original

        assert seen["state_exists"] is True

    def test_a_re_run_reuses_the_same_master(self, v2_archive):
        """Two attempts must converge on one master, not two.

        This is the bug the interruption test caught: a fresh master per
        attempt strands every file the previous attempt converted.
        """
        import core.crypto_migration_v3 as mig

        original = mig.Database.acquire_for_migration

        def boom(*args, **kwargs):
            raise RuntimeError("crash")

        mig.Database.acquire_for_migration = boom
        try:
            with pytest.raises(RuntimeError):
                migrate_to_v3(PASSWORD)
        finally:
            mig.Database.acquire_for_migration = original

        # The archive files are now under the abandoned attempt's master.
        first_master = mig._load_migration_state(
            Encryption.derive_v2_file_key_for_password(PASSWORD)
        )
        assert first_master is not None

        migrate_to_v3(PASSWORD)
        assert Encryption._master == first_master

    def test_unreadable_state_halts_rather_than_starting_fresh(self, v2_archive):
        """Silently minting a new master here would destroy data."""
        get_migration_state_path().write_bytes(b"\x02" + b"\x00" * 60)
        with pytest.raises(MigrationError, match="cannot be read"):
            migrate_to_v3(PASSWORD)

    def test_malformed_state_length_is_rejected(self, v2_archive):
        old_key = Encryption.derive_v2_file_key_for_password(PASSWORD)
        short = Encryption._encrypt_v2_with_key(b"too-short", old_key)
        get_migration_state_path().write_bytes(short)
        with pytest.raises(MigrationError, match="malformed"):
            migrate_to_v3(PASSWORD)
