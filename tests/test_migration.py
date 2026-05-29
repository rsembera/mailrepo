"""
Tests for the core/migration.py two-phase crypto v1 -> v2 migration.

These tests cover the critical paths only -- happy-path Phase 1, atomic
file write, halt-loud-on-corruption, and resumability via the per-file
version byte. Full interrupt/resume testing happens on Apollo per the
plan's Test 2 and Test 3 (which kill the process at random points).

The tests construct a v1 archive by hand because Encryption.initialize()
always creates v2 archives now. The construction mirrors what the live
v1 codebase produces: a v1 salt file (no MRC2 magic), Fernet-encrypted
.eml.enc files.
"""

import base64
import json
import secrets
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from core.config import Config
from core.database import Database
from core.encryption import (
    Encryption,
    PBKDF2_ITERATIONS_V1,
    DB_SALT_SUFFIX_V1,
    SALT_LENGTH,
    VERIFICATION_TOKEN,
    VERSION_BYTE_V2,
)
from core.migration import (
    Migration,
    MigrationError,
    MigrationCorruptionError,
)


TEST_PASSWORD = "MigrationTestPassword123!"


def _build_v1_archive(password: str, num_files: int = 5):
    """Construct a working v1 archive in the current test data dir.

    Writes a v1 salt file (no MRC2 magic) plus num_files .eml.enc files
    under a fake folder, each Fernet-encrypted under the password's v1
    file_key. Returns (file_paths, plaintexts).
    """
    salt = secrets.token_bytes(SALT_LENGTH)
    # v1 Fernet key derivation
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=32, salt=salt,
        iterations=PBKDF2_ITERATIONS_V1,
    )
    fernet_key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    fernet = Fernet(fernet_key)
    # Write the v1 salt file
    Config.get_data_path().mkdir(parents=True, exist_ok=True)
    salt_path = Config.get_salt_path()
    salt_path.write_bytes(salt + fernet.encrypt(VERIFICATION_TOKEN))
    # Write some v1 .eml.enc files
    archive_root = Config.get_archive_path()
    folder = archive_root / "1"
    folder.mkdir(parents=True, exist_ok=True)
    files = []
    plaintexts = []
    for i in range(num_files):
        pt = f"From: sender{i}@example.com\r\nSubject: Email {i}\r\n\r\nBody {i}".encode()
        path = folder / f"msg_{i}.eml.enc"
        path.write_bytes(fernet.encrypt(pt))
        files.append(path)
        plaintexts.append(pt)
    return files, plaintexts


# ============================================================
# STATE DETECTION
# ============================================================

class TestStateDetection:
    """Migration.state() classifies the archive correctly."""

    def test_state_not_needed_for_v2_archive(self):
        Encryption.initialize(TEST_PASSWORD)
        assert Migration.state() == "not_needed"
        assert Migration.is_needed() is False

    def test_state_fresh_for_pure_v1_archive(self):
        _build_v1_archive(TEST_PASSWORD, num_files=2)
        Encryption.unlock(TEST_PASSWORD)
        assert Migration.state() == "fresh"
        assert Migration.is_needed() is True
        assert Migration.has_marker() is False
        assert Migration.has_v2_files() is False

    def test_state_phase_1_interrupted_when_some_v2_files_exist(self):
        files, plaintexts = _build_v1_archive(TEST_PASSWORD, num_files=3)
        Encryption.unlock(TEST_PASSWORD)
        # Manually convert one file to v2 to simulate interruption
        Encryption._derive_and_set_v2_keys(TEST_PASSWORD)
        v2_data = Encryption._encrypt_v2_with_key(plaintexts[0], Encryption._file_key_v2)
        files[0].write_bytes(v2_data)
        # Clear v2 keys (so state checks see only the file artifact, not the in-memory keys)
        Encryption._file_key_v2 = None
        Encryption._db_key_v2 = None
        assert Migration.state() == "phase_1_interrupted"

    def test_state_phase_2_pending_when_marker_exists(self):
        _build_v1_archive(TEST_PASSWORD, num_files=2)
        Encryption.unlock(TEST_PASSWORD)
        # Write the marker
        marker = Encryption.get_migration_marker_path()
        marker.write_text("{}")
        assert Migration.state() == "phase_2_pending"


# ============================================================
# ATOMIC WRITE
# ============================================================

class TestAtomicWrite:
    """_atomic_write_file produces the right file with correct content."""

    def test_writes_content_correctly(self, tmp_path):
        target = tmp_path / "atomic_test.bin"
        content = b"hello world atomic"
        Migration._atomic_write_file(target, content)
        assert target.read_bytes() == content

    def test_replaces_existing_file(self, tmp_path):
        target = tmp_path / "atomic_test.bin"
        target.write_bytes(b"old content")
        Migration._atomic_write_file(target, b"new content")
        assert target.read_bytes() == b"new content"

    def test_no_stray_tmp_after_success(self, tmp_path):
        target = tmp_path / "atomic_test.bin"
        Migration._atomic_write_file(target, b"x")
        tmp = target.with_suffix(target.suffix + ".v2tmp")
        assert not tmp.exists()


# ============================================================
# FILE MIGRATION
# ============================================================

class TestMigrateFile:
    """_migrate_file converts v1 -> v2 cleanly, skips already-v2, halts on corruption."""

    def test_migrates_v1_to_v2(self):
        files, plaintexts = _build_v1_archive(TEST_PASSWORD, num_files=1)
        Encryption.unlock(TEST_PASSWORD)
        Encryption._derive_and_set_v2_keys(TEST_PASSWORD)

        result = Migration._migrate_file(files[0])
        assert result is True

        # File should now start with the v2 version byte.
        new_data = files[0].read_bytes()
        assert new_data[0] == VERSION_BYTE_V2

        # And it should decrypt back to the original plaintext via v2.
        decrypted = Encryption._decrypt_v2_with_key(new_data, Encryption._file_key_v2)
        assert decrypted == plaintexts[0]

    def test_skips_already_v2_file(self):
        files, plaintexts = _build_v1_archive(TEST_PASSWORD, num_files=1)
        Encryption.unlock(TEST_PASSWORD)
        Encryption._derive_and_set_v2_keys(TEST_PASSWORD)

        # First migration
        Migration._migrate_file(files[0])
        first_v2 = files[0].read_bytes()

        # Second call returns False and does not re-encrypt
        result = Migration._migrate_file(files[0])
        assert result is False
        assert files[0].read_bytes() == first_v2

    def test_halts_loud_on_corrupt_v1_file(self):
        files, plaintexts = _build_v1_archive(TEST_PASSWORD, num_files=1)
        Encryption.unlock(TEST_PASSWORD)
        Encryption._derive_and_set_v2_keys(TEST_PASSWORD)

        # Corrupt the v1 ciphertext by flipping bytes in the middle.
        data = files[0].read_bytes()
        corrupted = data[:len(data)//2] + bytes([b ^ 0xFF for b in data[len(data)//2:]])
        files[0].write_bytes(corrupted)

        with pytest.raises(MigrationCorruptionError) as exc_info:
            Migration._migrate_file(files[0])

        # The exception names the specific file
        assert str(files[0]) in str(exc_info.value)


# ============================================================
# END-TO-END PHASE 1
# ============================================================

class TestPhase1EndToEnd:
    """Full Phase 1 on a tiny v1 archive: every file migrated, content preserved,
    marker written, runtime decrypt still works."""

    def test_phase_1_happy_path(self):
        files, plaintexts = _build_v1_archive(TEST_PASSWORD, num_files=5)
        Encryption.unlock(TEST_PASSWORD)
        Database.set_key(Encryption.get_db_key())
        Database.initialize()

        progress_events = []
        result = Migration.run_phase_1(TEST_PASSWORD, progress_cb=progress_events.append)

        # Returned summary
        assert result["files"] == 5

        # Every file is now v2
        for path in files:
            assert path.read_bytes()[0] == VERSION_BYTE_V2

        # Plaintext survives round-trip via runtime decrypt() (which auto-detects v2)
        for path, pt in zip(files, plaintexts):
            decrypted = Encryption.decrypt(path.read_bytes())
            assert decrypted == pt

        # Marker was written
        assert Migration.has_marker() is True

        # Progress callback got the right stages
        stages = [e.get("stage") for e in progress_events]
        assert "cleanup" in stages
        assert "keys_derived" in stages
        assert "walking" in stages
        assert "complete" in stages

    def test_phase_1_resumable_after_partial_run(self):
        files, plaintexts = _build_v1_archive(TEST_PASSWORD, num_files=4)
        Encryption.unlock(TEST_PASSWORD)
        Database.set_key(Encryption.get_db_key())
        Database.initialize()

        # Manually migrate first 2 files (simulate partial Phase 1)
        Encryption._derive_and_set_v2_keys(TEST_PASSWORD)
        Migration._migrate_file(files[0])
        Migration._migrate_file(files[1])
        # Clear v2 keys, lock, then re-unlock (simulates app restart mid-migration)
        Encryption.lock()
        Encryption.unlock(TEST_PASSWORD)
        # Re-derive v2 keys for the resume
        # (the unlock-resume detection is the unlock layer's job; here we just
        # exercise run_phase_1's resumability via the version byte.)

        result = Migration.run_phase_1(TEST_PASSWORD)
        assert result["files"] == 4  # total found, regardless of how many needed migrating

        # All files end up v2 and content survives
        for path, pt in zip(files, plaintexts):
            assert path.read_bytes()[0] == VERSION_BYTE_V2
            assert Encryption.decrypt(path.read_bytes()) == pt
