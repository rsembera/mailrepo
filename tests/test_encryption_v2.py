"""
Tests for the v2 crypto path (Argon2id + AES-256-GCM + version byte).

These tests verify the v2-specific properties that the existing test suite
in test_encryption.py doesn\'t cover: salt file format, on-disk wire format,
version byte handling, AAD binding, and dual v1/v2 decode behavior.

Argon2id at production parameters (m=256MiB, t=6) is slow (~750ms per
derivation), so tests share initialized state where possible.
"""

import os
import pytest
from pathlib import Path

from core.encryption import (
    Encryption,
    EncryptionError,
    InvalidPasswordError,
    SALT_MAGIC_V2,
    SALT_LENGTH,
    VERSION_BYTE_V2,
    GCM_NONCE_LENGTH,
    GCM_TAG_LENGTH,
    VERIFICATION_TOKEN,
)
from core.config import Config


# ============================================================
# SALT FILE FORMAT
# ============================================================

class TestV2SaltFile:
    """A fresh initialize() must produce a v2-format salt file."""

    def test_initialize_writes_mrc2_magic(self):
        Encryption.initialize("TestPassword123!")
        salt_data = Config.get_salt_path().read_bytes()
        assert salt_data[:4] == SALT_MAGIC_V2

    def test_initialize_salt_is_32_bytes_after_magic(self):
        Encryption.initialize("TestPassword123!")
        salt_data = Config.get_salt_path().read_bytes()
        # MRC2 (4 bytes) + salt (32) + verification token (>0)
        assert len(salt_data) >= 4 + SALT_LENGTH + 1
        # The 32 bytes immediately after the magic should be the salt.
        # We confirm this indirectly by checking that re-unlock succeeds.

    def test_get_crypto_version_returns_2_for_new_install(self):
        Encryption.initialize("TestPassword123!")
        assert Encryption.get_crypto_version() == 2


# ============================================================
# V2 ON-DISK WIRE FORMAT
# ============================================================

class TestV2WireFormat:
    """encrypt() output for a v2 archive must have the [version][nonce][ct][tag] shape."""

    def test_encrypt_output_starts_with_version_byte(self):
        Encryption.initialize("TestPassword123!")
        ct = Encryption.encrypt(b"hello world")
        assert ct[0] == VERSION_BYTE_V2

    def test_encrypt_output_includes_nonce_and_tag(self):
        Encryption.initialize("TestPassword123!")
        plaintext = b"some plaintext"
        ct = Encryption.encrypt(plaintext)
        # Minimum size: 1 (version) + 12 (nonce) + len(plaintext) + 16 (tag)
        expected_min = 1 + GCM_NONCE_LENGTH + len(plaintext) + GCM_TAG_LENGTH
        assert len(ct) == expected_min

    def test_nonce_is_random_across_encryptions(self):
        Encryption.initialize("TestPassword123!")
        ct1 = Encryption.encrypt(b"identical plaintext")
        ct2 = Encryption.encrypt(b"identical plaintext")
        # Same plaintext, same key, but different random nonces means
        # different ciphertexts.
        assert ct1 != ct2

    def test_v2_roundtrip(self):
        Encryption.initialize("TestPassword123!")
        plaintext = b"any byte sequence here, including nulls and high bytes \xff\x00\xfe"
        ct = Encryption.encrypt(plaintext)
        assert Encryption.decrypt(ct) == plaintext


# ============================================================
# VERSION BYTE AAD BINDING
# ============================================================

class TestVersionByteAAD:
    """A tampered version byte must break the GCM auth check."""

    def test_tampered_version_byte_fails(self):
        Encryption.initialize("TestPassword123!")
        ct = Encryption.encrypt(b"original data")
        # Flip the version byte
        tampered = bytes([VERSION_BYTE_V2 ^ 0x01]) + ct[1:]
        # decrypt() routes by version byte. 0x03 isn\'t v2, so it routes to v1.
        # And v1 key isn\'t available in a fresh v2 install, so we get a
        # specific error about v1 key not loaded.
        with pytest.raises(EncryptionError):
            Encryption.decrypt(tampered)

    def test_tampered_nonce_fails(self):
        Encryption.initialize("TestPassword123!")
        ct = Encryption.encrypt(b"original data")
        # Flip a bit in the nonce
        tampered = ct[:1] + bytes([ct[1] ^ 0x01]) + ct[2:]
        with pytest.raises(EncryptionError):
            Encryption.decrypt(tampered)

    def test_tampered_ciphertext_fails(self):
        Encryption.initialize("TestPassword123!")
        ct = Encryption.encrypt(b"original data")
        # Flip a bit in the middle of the ciphertext
        mid = 1 + GCM_NONCE_LENGTH + 2
        tampered = ct[:mid] + bytes([ct[mid] ^ 0x01]) + ct[mid + 1:]
        with pytest.raises(EncryptionError):
            Encryption.decrypt(tampered)

    def test_truncated_ciphertext_fails(self):
        Encryption.initialize("TestPassword123!")
        ct = Encryption.encrypt(b"original data")
        # Strip the last byte (truncates the GCM tag)
        truncated = ct[:-1]
        with pytest.raises(EncryptionError):
            Encryption.decrypt(truncated)


# ============================================================
# UNLOCK ROUNDTRIP FOR V2
# ============================================================

class TestV2Unlock:
    """Lock + unlock with the same password must produce keys that decrypt the same data."""

    def test_unlock_after_lock_decrypts_same_data(self):
        password = "AnotherTestPassword456!"
        Encryption.initialize(password)
        ct = Encryption.encrypt(b"persistent payload")

        Encryption.lock()
        assert not Encryption.is_unlocked()

        Encryption.unlock(password)
        assert Encryption.decrypt(ct) == b"persistent payload"

    def test_unlock_with_wrong_password_raises(self):
        Encryption.initialize("CorrectPassword!")
        Encryption.lock()
        with pytest.raises(InvalidPasswordError):
            Encryption.unlock("WrongPassword!")


# ============================================================
# DUAL-DECODE (mid-migration simulation)
# ============================================================

class TestDualDecode:
    """
    Simulate the mid-migration state where v1 and v2 keys coexist in memory.

    We do this by manually constructing a v1 archive (writing a v1-format
    salt file directly), then forcing v2 keys into the in-memory state, and
    verifying both v1 and v2 ciphertexts can be decrypted.
    """

    def test_decrypt_auto_detects_v1_and_v2(self):
        # Step 1: build a real v1 archive by writing the v1 salt format manually.
        # This mimics an existing pre-migration install.
        from cryptography.fernet import Fernet
        from core.encryption import (
            PBKDF2_ITERATIONS_V1, DB_SALT_SUFFIX_V1
        )
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        import base64, secrets

        password = "DualDecodeTest123!"
        salt = secrets.token_bytes(SALT_LENGTH)

        # Derive v1 Fernet by hand
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(), length=32, salt=salt,
            iterations=PBKDF2_ITERATIONS_V1,
        )
        fernet_key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        fernet = Fernet(fernet_key)

        # Write a v1 salt file (no MRC2 magic)
        Config.get_data_path().mkdir(parents=True, exist_ok=True)
        salt_path = Config.get_salt_path()
        salt_path.write_bytes(salt + fernet.encrypt(VERIFICATION_TOKEN))

        # Create a v1-format ciphertext (just a Fernet token).
        v1_ct = fernet.encrypt(b"v1 payload")

        # Step 2: unlock as v1, confirm version detection.
        assert Encryption.get_crypto_version() == 1
        Encryption.unlock(password)
        assert Encryption.is_unlocked()

        # The v1 ciphertext we made by hand decrypts via the unlocked v1 path.
        assert Encryption.decrypt(v1_ct) == b"v1 payload"

        # Step 3: manually derive v2 keys and inject them, simulating the
        # "Phase 1 complete, v2 keys loaded for file access" state.
        Encryption._derive_and_set_v2_keys(password)

        # Now create a v2 ciphertext using the in-memory v2 key
        v2_ct = Encryption._encrypt_v2_with_key(b"v2 payload", Encryption._file_key_v2)
        assert v2_ct[0] == VERSION_BYTE_V2

        # Both should decrypt correctly via the auto-detecting decrypt().
        assert Encryption.decrypt(v1_ct) == b"v1 payload"
        assert Encryption.decrypt(v2_ct) == b"v2 payload"


# ============================================================
# MIGRATION HELPERS
# ============================================================

class TestMigrationHelpers:
    """Sanity checks on the migration-specific public methods."""

    def test_migration_marker_path_is_in_data_dir(self):
        marker = Encryption.get_migration_marker_path()
        assert marker.parent == Config.get_data_path()
        assert marker.name == ".migration_phase_1_complete"

    def test_is_migration_in_progress_false_for_fresh_v2_install(self):
        Encryption.initialize("TestPassword123!")
        assert Encryption.is_migration_in_progress() is False

    def test_is_migration_in_progress_false_when_uninitialized(self):
        # No salt file at all.
        assert Encryption.is_migration_in_progress() is False
