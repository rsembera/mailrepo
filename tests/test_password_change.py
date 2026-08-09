"""
Tests for core/password_change.py — the v2-native master password change.

The function structure mirrors core/migration.py's run_phase_1 (which had
unit tests before it was deleted), so this test file follows the same
pattern: build a small v2 archive in a temp dir, exercise change_master_password,
verify the outcome.

Argon2id at production parameters is slow (~750ms per derivation), so each
test that calls change_master_password takes 2-4 seconds. Shared fixtures
where possible. Whole module runs in ~30-60s.
"""

import json
import os
import zipfile
from datetime import datetime, timedelta

import pytest

from core.config import Config
from core.encryption import (
    VERSION_BYTE_V2,
    Encryption,
    InvalidPasswordError,
)
from core.password_change import (
    PasswordChangeCorruptionError,
    PasswordChangeError,
    _atomic_write_file,
    _rekey_file,
    change_master_password,
    check_password_change_interrupted,
    describe_interrupted_password_change,
    get_interruption_marker_path,
)

# ============================================================
# HELPERS
# ============================================================


def write_backup_manifest(backups_dir, created, filename="full_test.zip"):
    """Write a real backup zip plus a matching manifest entry.

    The password-change gate opens every file in the newest restore chain,
    so tests must put an actual readable zip on disk. Writing only a
    manifest entry describes a backup that does not exist — which is
    precisely the condition the gate exists to catch.
    """
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


# ============================================================
# FIXTURES
# ============================================================


@pytest.fixture
def v2_archive(initialized_app, tmp_path):
    """
    Initialized app + encryption + database, plus a small v2 archive of
    encrypted .eml.enc files on disk, plus a fresh backup manifest so the
    backup-<=24h check passes.

    Yields a dict with: tmp_path, password, file_paths (list of Paths),
    plaintexts (list of bytes — the original content before encryption).
    """
    app, password = initialized_app
    tmp_path = Config.get_data_path().parent

    # Create a handful of archive files
    archive_root = Config.get_archive_path() / "1"
    archive_root.mkdir(parents=True, exist_ok=True)

    plaintexts = [
        b"From: alice@example.com\r\nSubject: Test 1\r\n\r\nFirst email body.",
        b"From: bob@example.com\r\nSubject: Test 2\r\n\r\nSecond email body.",
        b"From: carol@example.com\r\nSubject: Test 3\r\n\r\nThird email body.",
    ]
    file_paths = []
    for i, pt in enumerate(plaintexts):
        ciphertext = Encryption.encrypt(pt)
        path = archive_root / f"{i:03d}.eml.enc"
        path.write_bytes(ciphertext)
        file_paths.append(path)

    # Write a fresh backup so the backup gate passes. The gate verifies the
    # file on disk (opens the zip), not just the manifest entry, so a real
    # zip has to exist — a manifest entry alone is not a backup.
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    write_backup_manifest(backups_dir, datetime.now())

    with app.app_context():
        yield {
            "tmp_path": tmp_path,
            "password": password,
            "file_paths": file_paths,
            "plaintexts": plaintexts,
        }


# ============================================================
# HAPPY PATH
# ============================================================


class TestChangeMasterPasswordHappyPath:
    """The end-to-end success case: password actually changes."""

    def test_new_password_unlocks_after_change(self, v2_archive):
        change_master_password(v2_archive["password"], "NewPassword456!")
        Encryption.lock()
        assert Encryption.unlock("NewPassword456!") is True

    def test_old_password_no_longer_unlocks(self, v2_archive):
        change_master_password(v2_archive["password"], "NewPassword456!")
        Encryption.lock()
        with pytest.raises(InvalidPasswordError):
            Encryption.unlock(v2_archive["password"])

    def test_archive_content_survives_unchanged(self, v2_archive):
        change_master_password(v2_archive["password"], "NewPassword456!")
        Encryption.lock()
        Encryption.unlock("NewPassword456!")
        for path, original_pt in zip(v2_archive["file_paths"], v2_archive["plaintexts"]):
            decrypted = Encryption.decrypt(path.read_bytes())
            assert decrypted == original_pt

    def test_progress_callback_receives_expected_stages(self, v2_archive):
        events = []
        change_master_password(
            v2_archive["password"],
            "NewPassword456!",
            progress_cb=lambda ev: events.append(ev),
        )
        statuses = [e.get("status") for e in events]
        # Must include the canonical sequence (matches settings.js vocabulary)
        for expected in (
            "counting",
            "counted",
            "encrypting",
            "credentials",
            "database",
            "finalizing",
            "complete",
        ):
            assert expected in statuses, f"Missing status '{expected}' in {statuses}"

    def test_returns_summary_with_file_count(self, v2_archive):
        result = change_master_password(
            v2_archive["password"],
            "NewPassword456!",
        )
        assert result["files"] == len(v2_archive["file_paths"])
        assert "credentials" in result


# ============================================================
# REFUSAL CASES — backup, password, same-key
# ============================================================


class TestChangeMasterPasswordBackupCheck:
    """Backup <=24h check is non-overridable."""

    def test_refuses_with_no_manifest(self, v2_archive):
        # Delete the manifest we wrote in the fixture
        (v2_archive["tmp_path"] / "backups" / "manifest.json").unlink()
        with pytest.raises(PasswordChangeError, match="backup"):
            change_master_password(v2_archive["password"], "NewPassword456!")

    def test_refuses_with_stale_backup(self, v2_archive):
        # Replace with a real but 48h-old backup: verifiable, just too old.
        backups_dir = v2_archive["tmp_path"] / "backups"
        (backups_dir / "full_test.zip").unlink()
        write_backup_manifest(
            backups_dir,
            datetime.now() - timedelta(hours=48),
            filename="full_old.zip",
        )
        with pytest.raises(PasswordChangeError, match="backup"):
            change_master_password(v2_archive["password"], "NewPassword456!")

    def test_accepts_with_recent_backup(self, v2_archive):
        # Fixture already wrote a now-dated manifest; this should succeed.
        result = change_master_password(
            v2_archive["password"],
            "NewPassword456!",
        )
        assert "files" in result

    def test_refuses_when_backup_file_is_missing(self, v2_archive):
        """A manifest entry is a claim; the file is the evidence.

        Before the gate verified files on disk, this passed — the rekey
        window opened against a backup that did not exist.
        """
        (v2_archive["tmp_path"] / "backups" / "full_test.zip").unlink()
        with pytest.raises(PasswordChangeError, match="did not verify"):
            change_master_password(v2_archive["password"], "NewPassword456!")

    def test_refuses_when_backup_file_is_truncated(self, v2_archive):
        """A half-written zip is not a recovery path."""
        zip_path = v2_archive["tmp_path"] / "backups" / "full_test.zip"
        zip_path.write_bytes(zip_path.read_bytes()[:20])
        with pytest.raises(PasswordChangeError, match="did not verify"):
            change_master_password(v2_archive["password"], "NewPassword456!")

    def test_refuses_when_backup_file_is_zero_bytes(self, v2_archive):
        """Matches the iCloud-eviction shape: present, but no content."""
        (v2_archive["tmp_path"] / "backups" / "full_test.zip").write_bytes(b"")
        with pytest.raises(PasswordChangeError, match="did not verify"):
            change_master_password(v2_archive["password"], "NewPassword456!")


class TestInterruptionMarker:
    """The marker converts a half-rekeyed archive from 'invalid password'
    into a specific, actionable message."""

    def test_no_marker_when_idle(self, v2_archive):
        assert check_password_change_interrupted() is None

    def test_marker_cleared_after_successful_change(self, v2_archive):
        change_master_password(v2_archive["password"], "NewPassword456!")
        assert not get_interruption_marker_path().exists()
        assert check_password_change_interrupted() is None

    def test_marker_survives_a_crash_in_the_rekey_window(self, v2_archive, monkeypatch):
        """Kill the process inside the irreversible window; marker must remain."""
        import core.password_change as pc

        def boom(*args, **kwargs):
            raise RuntimeError("simulated crash mid-rekey")

        monkeypatch.setattr(pc.Database, "acquire_for_migration", boom)

        with pytest.raises(RuntimeError, match="simulated crash"):
            change_master_password(v2_archive["password"], "NewPassword456!")

        marker = check_password_change_interrupted()
        assert marker is not None
        assert marker["phase"] == "db_rekey_and_salt_write"
        # The verified backup is named so the user knows their recovery point.
        assert marker["verified_backup"] == "full_test.zip"

    def test_description_mentions_trying_both_passwords(self):
        text = describe_interrupted_password_change(
            {
                "started_at": "2026-08-09T12:00:00",
                "phase": "db_rekey_and_salt_write",
                "verified_backup": "full_test.zip",
            }
        )
        assert "old" in text and "new" in text
        assert "full_test.zip" in text

    def test_corrupt_marker_still_reports_interruption(self, v2_archive):
        get_interruption_marker_path().write_text("{not json")
        marker = check_password_change_interrupted()
        assert marker is not None
        assert marker["phase"] == "unknown"


class TestChangeMasterPasswordWrongOldPassword:
    """Old password must match in-memory current keys."""

    def test_raises_invalid_password_error(self, v2_archive):
        with pytest.raises(InvalidPasswordError):
            change_master_password("WrongPassword", "NewPassword456!")


class TestChangeMasterPasswordSamePassword:
    """New password equal to old derives identical keys -- refuse."""

    def test_refuses_when_new_equals_old(self, v2_archive):
        with pytest.raises(PasswordChangeError, match="same"):
            change_master_password(
                v2_archive["password"],
                v2_archive["password"],
            )


# ============================================================
# RESUMABILITY AND CORRUPTION (low-level _rekey_file tests)
# ============================================================


class TestRekeyFileResumability:
    """
    Files already encrypted under NEW key (from a previous interrupted run)
    should be skipped, not failed. This is the try-old-then-new fallback.
    """

    def test_already_new_key_file_returns_false(self, v2_archive, tmp_path):
        # Derive both keys
        old_key = Encryption.derive_v2_file_key_for_password(v2_archive["password"])
        new_key = Encryption.derive_v2_file_key_for_password("NewPassword456!")

        # Write a file already encrypted under NEW key
        plaintext = b"already migrated content"
        new_ct = Encryption._encrypt_v2_with_key(plaintext, new_key)
        test_file = tmp_path / "already_new.eml.enc"
        test_file.write_bytes(new_ct)

        # _rekey_file should detect this and skip
        result = _rekey_file(test_file, old_key, new_key)
        assert result is False  # False = skipped (already migrated)

        # File should be unchanged
        still_decrypts_with_new = Encryption._decrypt_v2_with_key(test_file.read_bytes(), new_key)
        assert still_decrypts_with_new == plaintext


class TestRekeyFileCorruption:
    """
    File that decrypts with neither old nor new key raises
    PasswordChangeCorruptionError naming the path.
    """

    def test_corrupted_file_halts_loud(self, v2_archive, tmp_path):
        old_key = Encryption.derive_v2_file_key_for_password(v2_archive["password"])
        new_key = Encryption.derive_v2_file_key_for_password("NewPassword456!")

        # Garbage that can't be decrypted with either key
        corrupt_file = tmp_path / "corrupt.eml.enc"
        corrupt_file.write_bytes(bytes([VERSION_BYTE_V2]) + os.urandom(64))

        with pytest.raises(PasswordChangeCorruptionError) as exc_info:
            _rekey_file(corrupt_file, old_key, new_key)
        assert str(corrupt_file) in exc_info.value.filepath


# ============================================================
# ATOMIC WRITE PRIMITIVE
# ============================================================


class TestAtomicWriteFile:
    """The _atomic_write_file helper is small but safety-critical."""

    def test_writes_content_correctly(self, tmp_path):
        target = tmp_path / "test.bin"
        content = b"\x00\x01\x02\x03test content"
        _atomic_write_file(target, content)
        assert target.read_bytes() == content

    def test_replaces_existing_file(self, tmp_path):
        target = tmp_path / "test.bin"
        target.write_bytes(b"old content")
        _atomic_write_file(target, b"new content")
        assert target.read_bytes() == b"new content"

    def test_leaves_no_stray_temp_after_success(self, tmp_path):
        target = tmp_path / "test.bin"
        _atomic_write_file(target, b"content")
        strays = list(tmp_path.glob("*.v2tmp"))
        assert strays == []
