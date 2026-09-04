"""
Security review 2026-09, finding 8: the MRC4 key file.

Two halves bound together by a keyed tag (splice detection), and the
database recording which key file is current (rollback detection).
"""

import json

import pytest

from core.config import Config
from core.database import Database, get_setting
from core.encryption import (
    SALT_MAGIC_V3,
    SALT_MAGIC_V4,
    V3_OFF_SALT_RK,
    V4_OFF_BODY,
    V4_SALT_FILE_LENGTH,
    Encryption,
    EncryptionError,
)
from core.keyfile_binding import KeyFileRollbackError, check_after_unlock, record_current_tag
from core.password_change import reset_password_with_recovery_key, rotate_recovery_key

PASSWORD = "TestPassword123!"


def _open_db():
    Database.set_key(Encryption.get_db_key())
    Database.initialize()


@pytest.fixture
def v4_archive(app, temp_data_dir):
    """A fresh archive: MRC4 key file, database open, tag recorded."""
    with app.app_context():
        key = Encryption.initialize_v3(PASSWORD)
        _open_db()
        record_current_tag()
        yield {"recovery_key": key, "salt": Config.get_salt_path()}
        Database.close()
        Encryption.lock()


class TestFormat:
    def test_new_archives_are_mrc4(self, v4_archive):
        blob = v4_archive["salt"].read_bytes()
        assert blob[:4] == SALT_MAGIC_V4
        assert len(blob) == V4_SALT_FILE_LENGTH
        assert Encryption.key_file_is_bound()
        assert Encryption.salt_file_version() == 3  # still "the envelope" to every caller

    def test_both_doors_open_and_verify(self, v4_archive):
        blob = v4_archive["salt"].read_bytes()
        m1 = Encryption.unwrap_master_with_password(blob, PASSWORD)
        m2 = Encryption.unwrap_master_with_recovery_key(blob, v4_archive["recovery_key"])
        assert m1 == m2

    def test_splice_is_refused(self, v4_archive):
        """Rotate the recovery key, then splice the OLD recovery half back
        into the live file. Both halves are individually valid; the tag
        says they were not written together."""
        salt = v4_archive["salt"]
        old_blob = salt.read_bytes()
        rotate_recovery_key(PASSWORD)
        new_blob = salt.read_bytes()
        assert new_blob != old_blob
        # Body offset of the recovery half, inside the MRC4 body.
        rk_off = V4_OFF_BODY + (V3_OFF_SALT_RK - 4)
        body_end = V4_OFF_BODY + 186
        spliced = new_blob[:rk_off] + old_blob[rk_off:body_end] + new_blob[body_end:]
        assert len(spliced) == V4_SALT_FILE_LENGTH
        with pytest.raises(EncryptionError, match="integrity"):
            Encryption.unwrap_master_with_password(spliced, PASSWORD)
        with pytest.raises(EncryptionError, match="integrity"):
            Encryption.unwrap_master_with_recovery_key(spliced, v4_archive["recovery_key"])

    def test_tag_is_keyed(self, v4_archive):
        """Flipping a body byte breaks the tag; re-tagging needs the master."""
        blob = bytearray(v4_archive["salt"].read_bytes())
        blob[V4_OFF_BODY + 5] ^= 0x01
        with pytest.raises((EncryptionError, Exception)):
            Encryption.unwrap_master_with_password(bytes(blob), PASSWORD)


class TestRollback:
    def _relogin(self, password=PASSWORD):
        Database.close()
        Encryption.lock()
        Encryption.unlock(password)
        _open_db()
        check_after_unlock()

    def test_normal_relogin_passes(self, v4_archive):
        self._relogin()
        assert Encryption.is_unlocked()

    def test_rolled_back_key_file_is_refused(self, v4_archive):
        salt = v4_archive["salt"]
        gen0 = salt.read_bytes()
        rotate_recovery_key(PASSWORD)  # gen1 (previous = gen0)
        rotate_recovery_key(PASSWORD)  # gen2 (previous = gen1)
        salt.write_bytes(gen0)  # attacker restores the two-generations-old file
        with pytest.raises(KeyFileRollbackError):
            self._relogin()

    def test_previous_generation_is_tolerated(self, v4_archive):
        """A crash between the database write and the file write leaves the
        previous file on disk with the new tag recorded; must still log in."""
        salt = v4_archive["salt"]
        gen0 = salt.read_bytes()
        rotate_recovery_key(PASSWORD)
        salt.write_bytes(gen0)
        self._relogin()
        assert json.loads(get_setting("key_file_tags"))[0] == Encryption.key_file_tag_hex()

    def test_reset_via_recovery_key_records_tag_without_session(self, v4_archive):
        key = v4_archive["recovery_key"]
        Database.close()
        Encryption.lock()
        reset_password_with_recovery_key(key, "AnotherPassword456!")
        Encryption.unlock("AnotherPassword456!")
        _open_db()
        check_after_unlock()  # would raise if the reset had not recorded its tag
        assert Encryption.is_unlocked()


class TestUpgrade:
    def test_mrc3_is_upgraded_on_login(self, v4_archive):
        salt = v4_archive["salt"]
        blob = salt.read_bytes()
        # Downgrade on disk to what a 1.0 install has.
        v3 = SALT_MAGIC_V3 + blob[V4_OFF_BODY : V4_OFF_BODY + 186]
        salt.write_bytes(v3)
        Database.close()
        Encryption.lock()
        Encryption.unlock(PASSWORD)
        _open_db()
        check_after_unlock()
        after = salt.read_bytes()
        assert after[:4] == SALT_MAGIC_V4
        assert after[V4_OFF_BODY : V4_OFF_BODY + 186] == v3[4:]  # wrappers untouched
        assert Encryption.key_file_tag_hex() in json.loads(get_setting("key_file_tags"))

    def test_backup_fingerprint_reads_mrc4(self, v4_archive):
        from utils.backup import key_file_fingerprint

        fp = key_file_fingerprint(v4_archive["salt"].read_bytes())
        assert fp["version"] == 3 and fp["password_id"] and fp["recovery_id"]
