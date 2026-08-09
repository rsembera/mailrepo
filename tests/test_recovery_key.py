"""
Tests for the v3 envelope: random master key wrapped under both a
password and a printable recovery key.

The property these tests exist to protect is the one that dictated the
migration design (Session 68): because the master is RANDOM rather than
password-derived, rewrapping under a new password genuinely revokes the
old one. If the master were derived from the password -- the cheap
migration we rejected -- the old password would remain a permanent path
to the master no matter how many times the wrapper changed.
"""

import secrets

import pytest

from core.config import Config
from core.encryption import (
    RECOVERY_KEY_BYTES,
    SALT_MAGIC_V3,
    V3_SALT_FILE_LENGTH,
    Encryption,
    EncryptionError,
    InvalidPasswordError,
)

PASSWORD = "TestPassword123!"
NEW_PASSWORD = "NewPassword456!"


@pytest.fixture
def envelope():
    """A master key plus a v3 blob wrapping it under password + recovery key."""
    master = secrets.token_bytes(32)
    recovery_key = Encryption.generate_recovery_key()
    blob = Encryption.build_v3_salt_blob(master, PASSWORD, recovery_key)
    return {"master": master, "recovery_key": recovery_key, "blob": blob}


# ============================================================
# RECOVERY KEY FORMAT
# ============================================================


class TestRecoveryKeyFormat:
    def test_generated_keys_are_unique(self):
        keys = {Encryption.generate_recovery_key() for _ in range(50)}
        assert len(keys) == 50

    def test_display_format_is_grouped_base32(self):
        key = Encryption.generate_recovery_key()
        groups = key.split("-")
        assert len(groups) == 8
        assert all(len(g) == 4 for g in groups)
        assert set("".join(groups)) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")

    def test_round_trips_through_parse(self):
        raw = secrets.token_bytes(RECOVERY_KEY_BYTES)
        assert Encryption.parse_recovery_key(Encryption.format_recovery_key(raw)) == raw

    @pytest.mark.parametrize(
        "mangle",
        [
            lambda k: k.lower(),
            lambda k: k.replace("-", ""),
            lambda k: k.replace("-", " "),
            lambda k: f"  {k}  ",
        ],
        ids=["lowercase", "no-hyphens", "spaces", "whitespace"],
    )
    def test_tolerates_how_people_actually_type(self, mangle):
        key = Encryption.generate_recovery_key()
        assert Encryption.parse_recovery_key(mangle(key)) == (
            Encryption.parse_recovery_key(key)
        )

    def test_maps_lookalike_digits(self):
        """0/1/8 are not in the base32 alphabet, so they can only be typos."""
        raw = Encryption.parse_recovery_key("OIBO-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA")
        typo = Encryption.parse_recovery_key("0180-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA")
        assert raw == typo

    def test_empty_key_is_rejected(self):
        with pytest.raises(EncryptionError, match="No recovery key"):
            Encryption.parse_recovery_key("")

    def test_wrong_length_is_rejected_with_a_length_message(self):
        with pytest.raises(EncryptionError, match="characters"):
            Encryption.parse_recovery_key("ABCD-EFGH")

    def test_alphabet_violation_is_rejected(self):
        with pytest.raises(EncryptionError, match="alphabet"):
            Encryption.parse_recovery_key("!!!!-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA")


# ============================================================
# ENVELOPE STRUCTURE
# ============================================================


class TestEnvelopeStructure:
    def test_blob_has_v3_magic_and_fixed_length(self, envelope):
        assert envelope["blob"][:4] == SALT_MAGIC_V3
        assert len(envelope["blob"]) == V3_SALT_FILE_LENGTH

    def test_master_never_appears_in_the_blob(self, envelope):
        """The blob is written to disk; the master must only exist wrapped."""
        assert envelope["master"] not in envelope["blob"]

    def test_two_archives_wrap_differently(self):
        """Same master, same password, same recovery key -- different bytes.

        Fresh salts and nonces per build, so identical inputs must not
        produce identical key files.
        """
        master = secrets.token_bytes(32)
        rk = Encryption.generate_recovery_key()
        a = Encryption.build_v3_salt_blob(master, PASSWORD, rk)
        b = Encryption.build_v3_salt_blob(master, PASSWORD, rk)
        assert a != b
        assert Encryption.unwrap_master_with_password(a, PASSWORD) == master
        assert Encryption.unwrap_master_with_password(b, PASSWORD) == master

    def test_rejects_a_wrong_size_master(self):
        with pytest.raises(EncryptionError, match="32 bytes"):
            Encryption.build_v3_salt_blob(
                b"tooshort", PASSWORD, Encryption.generate_recovery_key()
            )

    def test_parse_rejects_v2_key_file(self):
        with pytest.raises(EncryptionError, match="Not a v3"):
            Encryption.parse_v3_salt_blob(b"MRC2" + b"\x00" * 81)

    def test_parse_rejects_truncated_blob(self, envelope):
        with pytest.raises(EncryptionError, match="truncated"):
            Encryption.parse_v3_salt_blob(envelope["blob"][:-1])


# ============================================================
# UNWRAPPING
# ============================================================


class TestUnwrap:
    def test_password_recovers_the_master(self, envelope):
        assert (
            Encryption.unwrap_master_with_password(envelope["blob"], PASSWORD)
            == envelope["master"]
        )

    def test_recovery_key_recovers_the_same_master(self, envelope):
        """Both doors open onto the same room -- that is the whole design."""
        assert (
            Encryption.unwrap_master_with_recovery_key(
                envelope["blob"], envelope["recovery_key"]
            )
            == envelope["master"]
        )

    def test_wrong_password_raises_invalid_password(self, envelope):
        with pytest.raises(InvalidPasswordError):
            Encryption.unwrap_master_with_password(envelope["blob"], "WrongPassword!")

    def test_wrong_recovery_key_raises_invalid_password(self, envelope):
        other = Encryption.generate_recovery_key()
        with pytest.raises(InvalidPasswordError, match="does not open"):
            Encryption.unwrap_master_with_recovery_key(envelope["blob"], other)

    def test_malformed_recovery_key_is_distinguishable_from_a_wrong_one(self, envelope):
        """A typo should say 'that is not a key', not 'wrong key'."""
        with pytest.raises(EncryptionError) as exc:
            Encryption.unwrap_master_with_recovery_key(envelope["blob"], "NOPE")
        assert not isinstance(exc.value, InvalidPasswordError)

    def test_tampered_wrapper_fails_authentication(self, envelope):
        blob = bytearray(envelope["blob"])
        blob[60] ^= 0xFF  # inside wrapped_pw
        with pytest.raises(InvalidPasswordError):
            Encryption.unwrap_master_with_password(bytes(blob), PASSWORD)


# ============================================================
# REWRAPPING -- the property that decided the migration design
# ============================================================


class TestRewrapPassword:
    def test_new_password_opens_the_archive(self, envelope):
        blob = Encryption.rewrap_password(
            envelope["blob"], envelope["master"], NEW_PASSWORD
        )
        assert (
            Encryption.unwrap_master_with_password(blob, NEW_PASSWORD)
            == envelope["master"]
        )

    def test_old_password_is_genuinely_revoked(self, envelope):
        """The reason the master must be random.

        With a password-derived master, the old password would still
        reach the master directly and this test could not pass.
        """
        blob = Encryption.rewrap_password(
            envelope["blob"], envelope["master"], NEW_PASSWORD
        )
        with pytest.raises(InvalidPasswordError):
            Encryption.unwrap_master_with_password(blob, PASSWORD)

    def test_recovery_key_survives_a_password_change(self, envelope):
        blob = Encryption.rewrap_password(
            envelope["blob"], envelope["master"], NEW_PASSWORD
        )
        assert (
            Encryption.unwrap_master_with_recovery_key(blob, envelope["recovery_key"])
            == envelope["master"]
        )

    def test_password_change_touches_only_the_password_wrapper(self, envelope):
        """Byte-level proof that the recovery half is untouched."""
        before = Encryption.parse_v3_salt_blob(envelope["blob"])
        after = Encryption.parse_v3_salt_blob(
            Encryption.rewrap_password(
                envelope["blob"], envelope["master"], NEW_PASSWORD
            )
        )
        assert after["salt_rk"] == before["salt_rk"]
        assert after["wrapped_rk"] == before["wrapped_rk"]
        assert after["salt_pw"] != before["salt_pw"]
        assert after["wrapped_pw"] != before["wrapped_pw"]


class TestRewrapRecoveryKey:
    def test_new_recovery_key_opens_the_archive(self, envelope):
        new_rk = Encryption.generate_recovery_key()
        blob = Encryption.rewrap_recovery_key(
            envelope["blob"], envelope["master"], new_rk
        )
        assert (
            Encryption.unwrap_master_with_recovery_key(blob, new_rk)
            == envelope["master"]
        )

    def test_old_recovery_key_is_revoked(self, envelope):
        """A printed key that leaked has to be killable."""
        new_rk = Encryption.generate_recovery_key()
        blob = Encryption.rewrap_recovery_key(
            envelope["blob"], envelope["master"], new_rk
        )
        with pytest.raises(InvalidPasswordError):
            Encryption.unwrap_master_with_recovery_key(blob, envelope["recovery_key"])

    def test_password_survives_recovery_key_rotation(self, envelope):
        blob = Encryption.rewrap_recovery_key(
            envelope["blob"], envelope["master"], Encryption.generate_recovery_key()
        )
        assert (
            Encryption.unwrap_master_with_password(blob, PASSWORD) == envelope["master"]
        )


# ============================================================
# UNLOCK WIRING (v2 and v3 side by side)
# ============================================================


class TestUnlockWiring:
    """A v3 archive must be indistinguishable to everything below the master."""

    def test_v2_archive_reports_version_2(self, app):
        with app.app_context():
            Encryption.initialize(PASSWORD)
            assert Encryption.salt_file_version() == 2
            assert not Encryption.is_v3()
            assert not Encryption.has_recovery_key()

    def test_v3_archive_reports_version_3(self, app):
        with app.app_context():
            Encryption.initialize_v3(PASSWORD)
            assert Encryption.salt_file_version() == 3
            assert Encryption.is_v3()
            assert Encryption.has_recovery_key()

    def test_initialize_v3_returns_a_usable_recovery_key(self, app):
        with app.app_context():
            rk = Encryption.initialize_v3(PASSWORD)
            assert len(rk.split("-")) == 8
            Encryption.lock()
            assert Encryption.unlock_with_recovery_key(rk)

    def test_v3_unlock_by_password(self, app):
        with app.app_context():
            Encryption.initialize_v3(PASSWORD)
            master = Encryption._master
            Encryption.lock()

            assert Encryption.unlock(PASSWORD)
            assert Encryption._master == master
            assert Encryption._salt_version == 3

    def test_v3_unlock_by_recovery_key_yields_identical_keys(self, app):
        """Both doors must produce the same file_key and db_key.

        If they did not, data written after a recovery-key unlock would be
        unreadable after a password unlock -- a silent split-brain.
        """
        with app.app_context():
            rk = Encryption.initialize_v3(PASSWORD)

            Encryption.lock()
            Encryption.unlock(PASSWORD)
            by_password = (Encryption._file_key_v2, Encryption._db_key_v2)

            Encryption.lock()
            Encryption.unlock_with_recovery_key(rk)
            by_recovery = (Encryption._file_key_v2, Encryption._db_key_v2)

            assert by_password == by_recovery

    def test_v3_round_trips_ciphertext_across_unlock_methods(self, app):
        """Encrypt after a password unlock, decrypt after a recovery unlock."""
        with app.app_context():
            rk = Encryption.initialize_v3(PASSWORD)
            secret = b"From: alice@example.com\r\nSubject: Hi\r\n\r\nBody."
            ciphertext = Encryption.encrypt(secret)

            Encryption.lock()
            Encryption.unlock_with_recovery_key(rk)
            assert Encryption.decrypt(ciphertext) == secret

    def test_v3_wrong_password_still_raises_invalid_password(self, app):
        with app.app_context():
            Encryption.initialize_v3(PASSWORD)
            Encryption.lock()
            with pytest.raises(InvalidPasswordError):
                Encryption.unlock("WrongPassword!")

    def test_v2_archive_refuses_recovery_key_unlock_with_a_clear_reason(self, app):
        with app.app_context():
            Encryption.initialize(PASSWORD)
            Encryption.lock()
            with pytest.raises(EncryptionError, match="predates recovery keys"):
                Encryption.unlock_with_recovery_key(Encryption.generate_recovery_key())

    def test_lock_clears_the_master(self, app):
        with app.app_context():
            Encryption.initialize_v3(PASSWORD)
            Encryption.lock()
            assert Encryption._master is None
            assert Encryption._salt_version is None
            assert not Encryption.is_unlocked()

    def test_unrecognised_magic_is_reported(self, app):
        with app.app_context():
            Encryption.initialize_v3(PASSWORD)
            Config.get_salt_path().write_bytes(b"XXXX" + b"\x00" * 100)
            with pytest.raises(EncryptionError, match="recognised magic"):
                Encryption.salt_file_version()
