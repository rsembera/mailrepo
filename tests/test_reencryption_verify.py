# ruff: noqa: F811 - the archive fixtures are imported from their home test modules
"""
Password change and key rotation check that the re-encryption worked.

Requested via the Hermanubis review; code review 2026-11, findings 5, 12
and 13. The three operations that re-encrypt the archive (master
rotation, the recovery-key upgrade, the v2 password change) share one
engine in core/password_change.py, and these tests pin what it checks:

  * a new ciphertext is proven to open before it replaces the original;
  * the archive is listed again and every file must open under the new
    key before the point of no return, which is what catches a message
    that arrived while the walk was running;
  * nothing new can be encrypted under the outgoing key meanwhile;
  * the database must open with its new key before a key file is written;
  * the key file is read back from disk;
  * a rotation that died after its key file landed neither locks the
    owner out nor blocks the next rotation.
"""

import pytest

import core.master_rotation as rot
import core.password_change as pc
from core import keyfile_binding
from core.config import Config
from core.crypto_migration_v3 import migrate_to_v3
from core.database import Database
from core.encryption import HKDF_INFO_FILE_V2, Encryption, EncryptionError
from core.master_rotation import (
    clear_finished_rotation_leftovers,
    get_rotation_state_path,
    rotate_master_key,
)
from core.password_change import (
    PasswordChangeCorruptionError,
    PasswordChangeError,
    change_master_password,
    check_password_change_interrupted,
)
from tests.test_crypto_migration_v3 import v2_archive  # noqa: F401 - fixture
from tests.test_master_rotation import PASSWORD, v4_archive  # noqa: F401 - fixture

LATE = b"Subject: late\r\n\r\narrived while the walk was running"


def _late_file():
    return Config.get_archive_path() / "1" / "late.eml.enc"


def _arrive_mid_walk(monkeypatch, seen=None):
    """Drop a file under the OUTGOING key after the walk has passed.

    Stands in for a commit on another thread whose encrypt() ran just
    before the walk began and whose write landed after it. The hook is
    the first credentials pass, which runs between the walk and the
    verification sweep.
    """
    real = pc._rekey_credentials
    state = {"done": False}

    def hook(old_key, new_key):
        if not state["done"]:
            state["done"] = True
            _late_file().write_bytes(Encryption._encrypt_v2_with_key(LATE, old_key))
            if seen is not None:
                try:
                    Encryption.encrypt(b"new mail")
                    seen["encrypt"] = "allowed"
                except EncryptionError as e:
                    seen["encrypt"] = str(e)
        return real(old_key, new_key)

    monkeypatch.setattr(pc, "_rekey_credentials", hook)


def _relogin(password=PASSWORD):
    Database.close()
    Database._db_key = None
    Encryption.lock()
    Encryption.unlock(password)
    Database.set_key(Encryption.get_db_key())
    Database.initialize()
    keyfile_binding.check_after_unlock()


class TestLateArrivals:
    def test_rotation_converts_a_file_that_arrived_mid_walk(self, v4_archive, monkeypatch):
        _arrive_mid_walk(monkeypatch)
        rotate_master_key(PASSWORD)
        assert Encryption.decrypt(_late_file().read_bytes()) == LATE

    def test_upgrade_converts_a_file_that_arrived_mid_walk(self, v2_archive, monkeypatch):
        _arrive_mid_walk(monkeypatch)
        migrate_to_v3(v2_archive["password"])
        assert Encryption.decrypt(_late_file().read_bytes()) == LATE

    def test_v2_password_change_converts_a_file_that_arrived_mid_walk(
        self, v2_archive, monkeypatch
    ):
        _arrive_mid_walk(monkeypatch)
        change_master_password(v2_archive["password"], "ADifferentPassword456!")
        assert Encryption.decrypt(_late_file().read_bytes()) == LATE

    def test_nothing_can_be_encrypted_while_keys_are_changing(self, v4_archive, monkeypatch):
        seen = {}
        _arrive_mid_walk(monkeypatch, seen)
        rotate_master_key(PASSWORD)
        assert "re-encrypted" in seen["encrypt"]
        # ...and the gate is lifted afterwards, on success
        assert Encryption.decrypt(Encryption.encrypt(b"after")) == b"after"

    def test_the_gate_is_lifted_after_a_failure_too(self, v4_archive):
        victim = Config.get_archive_path() / "1" / "000.eml.enc"
        victim.write_bytes(b"\x02" + b"garbage that is long enough to be a message" * 2)
        with pytest.raises(PasswordChangeCorruptionError):
            rotate_master_key(PASSWORD)
        assert Encryption.decrypt(Encryption.encrypt(b"after")) == b"after"

    def test_progress_reports_the_check(self, v4_archive):
        events = []
        rotate_master_key(PASSWORD, progress_cb=events.append)
        statuses = [e["status"] for e in events]
        assert "verifying" in statuses
        assert statuses.index("verifying") < statuses.index("database")


class TestSelfCheckBeforeReplace:
    def test_a_ciphertext_that_does_not_open_never_replaces_the_original(
        self, v4_archive, monkeypatch
    ):
        path = Config.get_archive_path() / "1" / "000.eml.enc"
        before = path.read_bytes()
        old_key = Encryption._file_key_v2
        new_key = b"\x11" * 32
        real = Encryption._encrypt_v2_with_key

        # An encryption that silently used the wrong key.
        monkeypatch.setattr(
            Encryption,
            "_encrypt_v2_with_key",
            classmethod(lambda cls, data, key: real(data, b"\x22" * 32)),
        )
        with pytest.raises(PasswordChangeError, match="self-check failed"):
            pc._rekey_file(path, old_key, new_key)
        assert path.read_bytes() == before

    def test_a_ciphertext_of_the_wrong_bytes_never_replaces_the_original(
        self, v4_archive, monkeypatch
    ):
        path = Config.get_archive_path() / "1" / "000.eml.enc"
        before = path.read_bytes()
        old_key = Encryption._file_key_v2
        new_key = b"\x11" * 32
        real = Encryption._encrypt_v2_with_key

        # Right key, wrong content: it opens, but not to the message.
        monkeypatch.setattr(
            Encryption,
            "_encrypt_v2_with_key",
            classmethod(lambda cls, data, key: real(data[:-1], key)),
        )
        with pytest.raises(PasswordChangeError, match="different bytes"):
            pc._rekey_file(path, old_key, new_key)
        assert path.read_bytes() == before


class TestStubs:
    def test_an_empty_leftover_does_not_block_rotation(self, v4_archive):
        stub = Config.get_archive_path() / "1" / "orphan.eml.enc"
        stub.write_bytes(b"")
        rotate_master_key(PASSWORD)
        for rel, expected in v4_archive["plaintexts"].items():
            assert Encryption.decrypt((Config.get_archive_path() / rel).read_bytes()) == expected

    def test_an_empty_file_the_archive_knows_about_still_halts(self, v4_archive):
        stub = Config.get_archive_path() / "1" / "known.eml.enc"
        stub.write_bytes(b"")
        Database.execute("INSERT INTO folders (id, name) VALUES (1, 'F')")
        Database.execute(
            "INSERT INTO messages (folder_id, message_id, filepath) VALUES (1, '<a@x>', ?)",
            (str(stub.relative_to(Config.get_base_path())),),
        )
        Database.commit()
        with pytest.raises(PasswordChangeCorruptionError):
            rotate_master_key(PASSWORD)

    def test_an_unreadable_file_long_enough_to_be_mail_still_halts(self, v4_archive):
        (Config.get_archive_path() / "1" / "orphan.eml.enc").write_bytes(b"\x02" + b"z" * 200)
        with pytest.raises(PasswordChangeCorruptionError):
            rotate_master_key(PASSWORD)


class _IgnoresRekey:
    """A connection on which PRAGMA rekey silently does nothing."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, *args):
        if sql.startswith("PRAGMA rekey"):
            return None
        return self._conn.execute(sql, *args)

    def __getattr__(self, name):
        return getattr(self._conn, name)


class TestDatabaseRekeyIsProven:
    def test_a_rekey_that_did_not_take_stops_before_the_key_file(self, v4_archive, monkeypatch):
        old_salt = v4_archive["old_salt"]
        old_db_key = Database._db_key
        real = Database.get_connection

        def wrapped(*a, **k):
            return _IgnoresRekey(real(*a, **k))

        monkeypatch.setattr(Database, "get_connection", wrapped)
        with pytest.raises(PasswordChangeError, match="did not accept its new key"):
            rotate_master_key(PASSWORD)
        monkeypatch.setattr(Database, "get_connection", real)

        # Nothing irreversible happened: same key file, same database key,
        # and the old password still opens everything.
        assert Config.get_salt_path().read_bytes() == old_salt
        assert Database._db_key == old_db_key
        _relogin()
        assert Database.fetchone("SELECT count(*) AS c FROM sqlite_master")["c"] > 0

        # ...and running it again finishes the job.
        rotate_master_key(PASSWORD)
        for rel, expected in v4_archive["plaintexts"].items():
            assert Encryption.decrypt((Config.get_archive_path() / rel).read_bytes()) == expected


class TestKeyFileReadBack:
    def test_a_key_file_that_lands_wrong_is_reported(self, v4_archive, monkeypatch):
        import core.encryption as enc

        def bad_replace(src, dst):
            with open(src, "rb") as fh:
                data = fh.read()
            with open(dst, "wb") as fh:
                fh.write(data[: len(data) // 2])  # a short write

        monkeypatch.setattr(enc.os, "replace", bad_replace)
        with pytest.raises(EncryptionError, match="does not match what was just written"):
            Encryption._atomic_write_salt_file(v4_archive["old_salt"])


class TestCrashAfterTheKeyFileLands:
    def _rotate_and_die_before_cleanup(self, monkeypatch):
        def die():
            raise KeyboardInterrupt("power loss")

        monkeypatch.setattr(rot, "clear_interruption_marker", die)
        with pytest.raises(KeyboardInterrupt):
            rotate_master_key(PASSWORD)
        monkeypatch.setattr(rot, "clear_interruption_marker", pc.clear_interruption_marker)

    def test_the_next_login_is_accepted(self, v4_archive, monkeypatch):
        """The tag is recorded before the key file lands, so the file that
        is on disk is always one the database knows."""
        self._rotate_and_die_before_cleanup(monkeypatch)
        _relogin()  # raised KeyFileRollbackError before the fix

    def test_leftovers_are_cleared_and_the_next_rotation_runs(self, v4_archive, monkeypatch):
        self._rotate_and_die_before_cleanup(monkeypatch)
        assert get_rotation_state_path().exists()
        assert check_password_change_interrupted() is not None

        _relogin()
        clear_finished_rotation_leftovers()
        assert not get_rotation_state_path().exists()
        assert check_password_change_interrupted() is None

        rotate_master_key(PASSWORD)  # refused with "state that cannot be read" before
        for rel, expected in v4_archive["plaintexts"].items():
            assert Encryption.decrypt((Config.get_archive_path() / rel).read_bytes()) == expected

    def test_state_from_a_rotation_still_in_progress_is_kept(self, v4_archive):
        """Wrapped under the key the archive opens with: needed to resume."""
        old_file_key = Encryption._derive_subkey_v2(Encryption._master, HKDF_INFO_FILE_V2)
        rot._save_state(b"\x33" * 32, old_file_key)
        clear_finished_rotation_leftovers()
        assert get_rotation_state_path().exists()
