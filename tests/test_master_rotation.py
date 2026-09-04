"""
Security review 2026-09, finding 8b: master-key rotation.

After rotation, every earlier key file, password, recovery key and
backup must open nothing current. Before it, the same old key file plus
old password DOES open the live archive offline — that is the gap.
"""

import json
import zipfile
from datetime import datetime

import pytest

from core.config import Config
from core.database import Database, get_setting
from core.encryption import (
    HKDF_INFO_DB_V2,
    HKDF_INFO_FILE_V2,
    SALT_MAGIC_V4,
    Encryption,
    InvalidPasswordError,
)
from core.keyfile_binding import record_current_tag
from core.master_rotation import RotationError, get_rotation_state_path, rotate_master_key
from core.password_change import check_password_change_interrupted, get_interruption_marker_path

PASSWORD = "TestPassword123!"
NEW_PASSWORD = "BrandNewPassword456!"


def _write_backup_manifest(backups_dir, created):
    zip_path = backups_dir / "full_test.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("data/placeholder.txt", "x")
    (backups_dir / "manifest.json").write_text(
        json.dumps(
            {
                "current_chain_id": "c",
                "backups": [
                    {
                        "filename": "full_test.zip",
                        "created_at": created.isoformat(),
                        "type": "full",
                        "chain_id": "c",
                        "backup_dir": str(backups_dir),
                    }
                ],
            }
        )
    )


@pytest.fixture
def v4_archive(app, temp_data_dir):
    """MRC4 archive, database open, three encrypted files, fresh verified backup."""
    with app.app_context():
        recovery_key = Encryption.initialize_v3(PASSWORD)
        Database.set_key(Encryption.get_db_key())
        Database.initialize()
        record_current_tag()

        root = Config.get_archive_path() / "1"
        root.mkdir(parents=True, exist_ok=True)
        plaintexts = {
            "1/000.eml.enc": b"Subject: One\r\n\r\nFirst.",
            "1/001.eml.enc": b"Subject: Two\r\n\r\nSecond.",
            "1/002.eml.enc": b"Subject: Three\r\n\r\nThird.",
        }
        for rel, pt in plaintexts.items():
            (Config.get_archive_path() / rel).write_bytes(Encryption.encrypt(pt))

        backups_dir = Config.get_data_path().parent / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        _write_backup_manifest(backups_dir, datetime.now())

        yield {
            "recovery_key": recovery_key,
            "plaintexts": plaintexts,
            "old_salt": Config.get_salt_path().read_bytes(),
            "old_master": Encryption._master,
        }
        Database.close()
        Encryption.lock()


class TestRotation:
    def test_before_rotation_the_gap_is_real(self, v4_archive):
        """Old key file + old password derives the live master offline."""
        master = Encryption.unwrap_master_with_password(v4_archive["old_salt"], PASSWORD)
        assert master == v4_archive["old_master"]
        fk = Encryption._derive_subkey_v2(master, HKDF_INFO_FILE_V2)
        data = (Config.get_archive_path() / "1/000.eml.enc").read_bytes()
        assert (
            Encryption._decrypt_v2_with_key(data, fk) == v4_archive["plaintexts"]["1/000.eml.enc"]
        )

    def test_rotation_closes_it(self, v4_archive):
        old_salt = v4_archive["old_salt"]
        old_key = v4_archive["recovery_key"]
        new_key = rotate_master_key(PASSWORD)

        # Live archive still opens, with the same password, and files decrypt.
        for rel, expected in v4_archive["plaintexts"].items():
            assert Encryption.decrypt((Config.get_archive_path() / rel).read_bytes()) == expected
        assert Encryption.unwrap_master_with_password(Config.get_salt_path().read_bytes(), PASSWORD)
        assert Encryption.unwrap_master_with_recovery_key(
            Config.get_salt_path().read_bytes(), new_key
        )

        # The old key file + old password derives the OLD master, which
        # opens nothing current.
        stale_master = Encryption.unwrap_master_with_password(old_salt, PASSWORD)
        assert stale_master != Encryption._master
        stale_fk = Encryption._derive_subkey_v2(stale_master, HKDF_INFO_FILE_V2)
        data = (Config.get_archive_path() / "1/000.eml.enc").read_bytes()
        with pytest.raises(Exception):
            Encryption._decrypt_v2_with_key(data, stale_fk)
        assert Encryption._derive_subkey_v2(stale_master, HKDF_INFO_DB_V2).hex() != Database._db_key

        # The old recovery key no longer opens the live key file.
        with pytest.raises(InvalidPasswordError):
            Encryption.unwrap_master_with_recovery_key(Config.get_salt_path().read_bytes(), old_key)

        # The old key file is refused at login as a rollback, too.
        from core.keyfile_binding import KeyFileRollbackError, check_after_unlock

        Config.get_salt_path().write_bytes(old_salt)
        Encryption._adopt_master(stale_master, version=3)
        with pytest.raises(KeyFileRollbackError):
            check_after_unlock()

    def test_rotation_can_change_the_password_too(self, v4_archive):
        rotate_master_key(PASSWORD, NEW_PASSWORD)
        blob = Config.get_salt_path().read_bytes()
        assert Encryption.unwrap_master_with_password(blob, NEW_PASSWORD)
        with pytest.raises(InvalidPasswordError):
            Encryption.unwrap_master_with_password(blob, PASSWORD)

    def test_archive_id_is_kept_and_tag_recorded(self, v4_archive):
        before = v4_archive["old_salt"]
        rotate_master_key(PASSWORD)
        after = Config.get_salt_path().read_bytes()
        assert after[:4] == SALT_MAGIC_V4
        assert Encryption.archive_id_hex(after) == Encryption.archive_id_hex(before)
        assert Encryption.key_file_tag_hex(after) == json.loads(get_setting("key_file_tags"))[0]

    def test_wrong_password_is_refused_untouched(self, v4_archive):
        with pytest.raises(InvalidPasswordError):
            rotate_master_key("wrong-password-here!")
        assert Config.get_salt_path().read_bytes() == v4_archive["old_salt"]
        assert not get_rotation_state_path().exists()

    def test_stale_backup_is_refused(self, v4_archive):
        from datetime import timedelta

        _write_backup_manifest(
            Config.get_data_path().parent / "backups", datetime.now() - timedelta(days=3)
        )
        with pytest.raises(RotationError, match="backup"):
            rotate_master_key(PASSWORD)
        assert Config.get_salt_path().read_bytes() == v4_archive["old_salt"]

    def test_interrupted_rotation_resumes(self, v4_archive):
        import core.master_rotation as rot

        original = rot.Database.acquire_for_migration
        rot.Database.acquire_for_migration = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("crash")
        )
        try:
            with pytest.raises(RuntimeError):
                rotate_master_key(PASSWORD)
        finally:
            rot.Database.acquire_for_migration = original

        assert get_interruption_marker_path().exists()
        assert get_rotation_state_path().exists()
        assert check_password_change_interrupted()["phase"] == "master_rotation"
        # Key file unchanged: the current password still opens it.
        assert Config.get_salt_path().read_bytes() == v4_archive["old_salt"]

        rotate_master_key(PASSWORD)  # re-run: converted files are skipped, not stranded
        assert check_password_change_interrupted() is None
        assert not get_rotation_state_path().exists()
        for rel, expected in v4_archive["plaintexts"].items():
            assert Encryption.decrypt((Config.get_archive_path() / rel).read_bytes()) == expected


class TestRoute:
    def test_page_requires_session(self, app, v4_archive):
        assert app.test_client().get("/auth/rotate-master-key").status_code == 302

    def test_page_renders_and_post_rotates(self, app, v4_archive):
        from web import idle

        client = app.test_client()
        with client.session_transaction() as sess:
            sess["authenticated"] = True
            sess["csrf_token"] = "tok"
            sess["login_id"] = idle.new_login_id()
        resp = client.get("/auth/rotate-master-key")
        assert resp.status_code == 200
        assert b"Rotate the master key" in resp.data

        before = Config.get_salt_path().read_bytes()
        resp = client.post(
            "/auth/rotate-master-key", data={"csrf_token": "tok", "password": PASSWORD}
        )
        assert resp.status_code == 200
        assert b"recovery-key-value" in resp.data
        assert Config.get_salt_path().read_bytes() != before

    def test_post_without_csrf_is_bounced(self, app, v4_archive):
        from web import idle

        client = app.test_client()
        with client.session_transaction() as sess:
            sess["authenticated"] = True
            sess["csrf_token"] = "tok"
            sess["login_id"] = idle.new_login_id()
        before = Config.get_salt_path().read_bytes()
        resp = client.post("/auth/rotate-master-key", data={"password": PASSWORD})
        assert resp.status_code == 302
        assert Config.get_salt_path().read_bytes() == before
