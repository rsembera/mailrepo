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
from core.encryption import Encryption, EncryptionError, InvalidPasswordError
from core.password_change import (
    PasswordChangeError,
    change_master_password,
    check_password_change_interrupted,
    describe_interrupted_password_change,
    get_interruption_marker_path,
    rotate_recovery_key,
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


# ============================================================
# v3 PASSWORD CHANGE + RECOVERY KEY ROTATION
# ============================================================


@pytest.fixture
def v3_archive(v2_archive):
    """A migrated archive, plus its recovery key and original content."""
    recovery_key = migrate_to_v3(PASSWORD)
    return {**v2_archive, "recovery_key": recovery_key}


def _all_content_readable(plaintexts):
    for rel, expected in plaintexts.items():
        data = (Config.get_archive_path() / rel).read_bytes()
        if Encryption.decrypt(data) != expected:
            return False
    return True


class TestV3PasswordChange:
    """On v3 a password change is a rewrap: no file walk, no DB rekey."""

    NEW = "BrandNewPassword789!"

    def test_new_password_unlocks(self, v3_archive):
        change_master_password(PASSWORD, self.NEW)
        Encryption.lock()
        assert Encryption.unlock(self.NEW)

    def test_old_password_stops_working(self, v3_archive):
        change_master_password(PASSWORD, self.NEW)
        Encryption.lock()
        with pytest.raises(InvalidPasswordError):
            Encryption.unlock(PASSWORD)

    def test_no_files_were_re_encrypted(self, v3_archive):
        """The entire point: the archive is not touched."""
        before = {
            rel: (Config.get_archive_path() / rel).read_bytes()
            for rel in v3_archive["plaintexts"]
        }
        result = change_master_password(PASSWORD, self.NEW)

        assert result["files"] == 0
        assert result["rewrapped"] is True
        for rel, raw in before.items():
            assert (Config.get_archive_path() / rel).read_bytes() == raw

    def test_content_still_readable(self, v3_archive):
        change_master_password(PASSWORD, self.NEW)
        Encryption.lock()
        Encryption.unlock(self.NEW)
        assert _all_content_readable(v3_archive["plaintexts"])

    def test_recovery_key_survives(self, v3_archive):
        change_master_password(PASSWORD, self.NEW)
        Encryption.lock()
        Encryption.unlock_with_recovery_key(v3_archive["recovery_key"])
        assert _all_content_readable(v3_archive["plaintexts"])

    def test_no_backup_required(self, v3_archive):
        """Deliberate removal: the operation is one atomic file write.

        The v2 gate protects a non-resumable window that does not exist
        here, so requiring a fresh backup would be ceremony.
        """
        (v3_archive["backups_dir"] / "full_test.zip").unlink()
        (v3_archive["backups_dir"] / "manifest.json").unlink()

        change_master_password(PASSWORD, self.NEW)
        Encryption.lock()
        assert Encryption.unlock(self.NEW)

    def test_wrong_current_password_refused(self, v3_archive):
        with pytest.raises(InvalidPasswordError):
            change_master_password("NotThePassword!", self.NEW)

    def test_same_password_refused(self, v3_archive):
        with pytest.raises(PasswordChangeError, match="same as the current"):
            change_master_password(PASSWORD, PASSWORD)

    def test_failed_change_leaves_old_password_working(self, v3_archive):
        with pytest.raises(InvalidPasswordError):
            change_master_password("NotThePassword!", self.NEW)
        Encryption.lock()
        assert Encryption.unlock(PASSWORD)


class TestRecoveryKeyRotation:
    def test_new_key_works(self, v3_archive):
        new_rk = rotate_recovery_key(PASSWORD)
        Encryption.lock()
        Encryption.unlock_with_recovery_key(new_rk)
        assert _all_content_readable(v3_archive["plaintexts"])

    def test_old_key_is_revoked(self, v3_archive):
        rotate_recovery_key(PASSWORD)
        Encryption.lock()
        with pytest.raises(InvalidPasswordError):
            Encryption.unlock_with_recovery_key(v3_archive["recovery_key"])

    def test_password_still_works(self, v3_archive):
        rotate_recovery_key(PASSWORD)
        Encryption.lock()
        assert Encryption.unlock(PASSWORD)

    def test_requires_the_current_password(self, v3_archive):
        """An unlocked session alone must not mint a durable second key."""
        with pytest.raises(InvalidPasswordError):
            rotate_recovery_key("NotThePassword!")

    def test_refused_on_v2_archive(self, v2_archive):
        with pytest.raises(PasswordChangeError, match="predates recovery keys"):
            rotate_recovery_key(PASSWORD)

    def test_rotation_does_not_touch_archive_files(self, v3_archive):
        before = {
            rel: (Config.get_archive_path() / rel).read_bytes()
            for rel in v3_archive["plaintexts"]
        }
        rotate_recovery_key(PASSWORD)
        for rel, raw in before.items():
            assert (Config.get_archive_path() / rel).read_bytes() == raw


class TestWrapperVerifiedBeforeWrite:
    """A blob can be perfectly well-formed and still not open.

    Structural validation checks magic bytes and length; it cannot tell a
    working wrapper from a dead one. These tests corrupt the wrap step
    itself and assert the key file is never written -- a silently dead
    credential is discovered on the worst possible day.
    """

    NEW = "BrandNewPassword789!"

    @staticmethod
    def _junk_wrapper(data, key):
        """Right length, right shape, opens to nothing."""
        return b"\x02" + b"\x00" * 12 + b"\xff" * len(data) + b"\x00" * 16

    def test_password_rewrap_refuses_an_unopenable_wrapper(self, v3_archive, monkeypatch):
        monkeypatch.setattr(Encryption, "_encrypt_v2_with_key", self._junk_wrapper)
        with pytest.raises(EncryptionError, match="does not decrypt"):
            change_master_password(PASSWORD, self.NEW)

    def test_password_rewrap_refuses_a_wrapper_holding_the_wrong_key(
        self, v3_archive, monkeypatch
    ):
        """Decrypts cleanly, yields something that is not the master."""
        real = Encryption._encrypt_v2_with_key.__func__

        def wrong_payload(cls, data, key):
            return real(cls, b"\x00" * len(data), key)

        monkeypatch.setattr(Encryption, "_encrypt_v2_with_key", classmethod(wrong_payload))
        with pytest.raises(EncryptionError, match="wrong key"):
            change_master_password(PASSWORD, self.NEW)

    def test_a_refused_password_change_leaves_the_key_file_untouched(
        self, v3_archive, monkeypatch
    ):
        before = Encryption.read_salt_blob()
        monkeypatch.setattr(Encryption, "_encrypt_v2_with_key", self._junk_wrapper)
        with pytest.raises(EncryptionError):
            change_master_password(PASSWORD, self.NEW)
        monkeypatch.undo()
        assert Encryption.read_salt_blob() == before
        Encryption.lock()
        assert Encryption.unlock(PASSWORD)

    def test_rotation_refuses_a_broken_display_round_trip(self, v3_archive, monkeypatch):
        """The failure this exists for: the printed key is not the key.

        Simulates format/parse drift by having the second parse -- the one
        the verify performs on the display string -- return different
        bytes than the wrap used.
        """
        real_parse = Encryption.parse_recovery_key
        calls = {"n": 0}

        def drifting_parse(text):
            calls["n"] += 1
            raw = real_parse(text)
            return bytes(b ^ 0xFF for b in raw) if calls["n"] > 1 else raw

        monkeypatch.setattr(Encryption, "parse_recovery_key", staticmethod(drifting_parse))
        with pytest.raises(EncryptionError, match="does not open it"):
            rotate_recovery_key(PASSWORD)

    def test_a_refused_rotation_leaves_the_old_key_working(self, v3_archive, monkeypatch):
        before = Encryption.read_salt_blob()
        monkeypatch.setattr(Encryption, "_encrypt_v2_with_key", self._junk_wrapper)
        with pytest.raises(EncryptionError):
            rotate_recovery_key(PASSWORD)
        monkeypatch.undo()
        assert Encryption.read_salt_blob() == before
        Encryption.lock()
        assert Encryption.unlock_with_recovery_key(v3_archive["recovery_key"])

    def test_setup_refuses_to_build_an_unopenable_blob(self, monkeypatch):
        """build_v3_salt_blob guards the first key file an archive gets."""
        rk = Encryption.generate_recovery_key()
        monkeypatch.setattr(Encryption, "_encrypt_v2_with_key", self._junk_wrapper)
        with pytest.raises(EncryptionError, match="does not decrypt"):
            Encryption.build_v3_salt_blob(b"\x11" * 32, PASSWORD, rk)

    def test_the_guards_do_not_fire_in_normal_operation(self, v3_archive):
        """The whole point: identical output on the success path."""
        new_rk = rotate_recovery_key(PASSWORD)
        change_master_password(PASSWORD, self.NEW)
        Encryption.lock()
        assert Encryption.unlock(self.NEW)
        Encryption.lock()
        assert Encryption.unlock_with_recovery_key(new_rk)


class TestOrphanedMigrationState:
    """Finding 5. The state file wraps the CURRENT master under the OLD
    password's file key, and nothing removed it once the archive was v3."""

    def test_orphaned_state_is_cleared_on_a_v3_archive(self, v2_archive):
        from core.crypto_migration_v3 import (
            get_migration_state_path,
            needs_v3_migration,
        )

        migrate_to_v3(PASSWORD)
        assert not get_migration_state_path().exists()

        # Simulate the file surviving: a crash between the key-file write
        # and cleanup, or a data-dir restore carrying it back.
        get_migration_state_path().write_bytes(b"\x02" + b"\x00" * 60)

        assert needs_v3_migration() is False
        assert not get_migration_state_path().exists(), (
            "orphaned state survived — an old password plus any "
            "pre-migration backup could unwrap the live master from it"
        )

    def test_state_is_not_cleared_while_a_migration_is_pending(self, v2_archive):
        """The guard must not delete state a re-run still needs."""
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

        # Still v2, so the migration is genuinely unfinished.
        assert mig.needs_v3_migration() is True
        assert mig.get_migration_state_path().exists(), (
            "state needed to resume the migration was deleted"
        )
