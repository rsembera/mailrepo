"""
End-to-end tests for the recovery-key web flow.

The crypto is covered elsewhere; these exercise the wiring — routes,
templates, sessions — because that is where this feature can fail in ways
the unit tests cannot see.

One thing worth stating explicitly, because it is a security property and
not a detail: the recovery key must never be placed in the Flask session.
Sessions are SIGNED, not encrypted, so anything put there is readable in
the browser's cookie jar. test_recovery_key_never_enters_the_session is
the guard.
"""

import json
import zipfile

import pytest

from core.encryption import Encryption, InvalidPasswordError

PASSWORD = "TestPassword123!"
NEW_PASSWORD = "BrandNewPassword789!"


def _write_backup_manifest(backups_dir, created, filename="full_test.zip"):
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


def extract_recovery_key(html):
    """Pull the key out of the rendered page."""
    marker = 'id="recovery-key-value">'
    start = html.index(marker) + len(marker)
    end = html.index("<", start)
    return html[start:end].strip()


@pytest.fixture
def fresh_client(app):
    """A client against an app with no archive set up yet."""
    return app.test_client()


class TestSetupFlow:
    def test_setup_creates_v3_and_shows_the_key(self, fresh_client):
        response = fresh_client.post(
            "/auth/setup",
            data={"password": PASSWORD, "confirm": PASSWORD},
        )
        assert response.status_code == 200
        html = response.get_data(as_text=True)

        assert "Save your recovery key" in html
        key = extract_recovery_key(html)
        assert len(key.split("-")) == 8

        assert Encryption.salt_file_version() == 3
        assert Encryption.unlock_with_recovery_key(key)

    def test_recovery_key_never_enters_the_session(self, fresh_client):
        """Flask sessions are signed, not encrypted.

        A recovery key in the session cookie would be readable by anything
        with access to the browser profile.
        """
        response = fresh_client.post(
            "/auth/setup",
            data={"password": PASSWORD, "confirm": PASSWORD},
        )
        key = extract_recovery_key(response.get_data(as_text=True))

        with fresh_client.session_transaction() as sess:
            for value in sess.values():
                assert key not in str(value)

        cookies = response.headers.getlist("Set-Cookie")
        for cookie in cookies:
            assert key not in cookie
            # base32 groups would survive urlencoding intact, so a naive
            # check on the whole key is sufficient here.

    def test_setup_still_rejects_short_and_mismatched_passwords(self, fresh_client):
        response = fresh_client.post(
            "/auth/setup", data={"password": "short", "confirm": "short"}
        )
        assert "at least 12 characters" in response.get_data(as_text=True)
        assert not Encryption.is_initialized()

        response = fresh_client.post(
            "/auth/setup", data={"password": PASSWORD, "confirm": "Different123!"}
        )
        assert "do not match" in response.get_data(as_text=True)
        assert not Encryption.is_initialized()


class TestRecoveryLogin:
    @pytest.fixture
    def archive(self, fresh_client):
        response = fresh_client.post(
            "/auth/setup", data={"password": PASSWORD, "confirm": PASSWORD}
        )
        key = extract_recovery_key(response.get_data(as_text=True))
        fresh_client.post("/auth/logout")
        return {"client": fresh_client, "key": key}

    def test_login_page_offers_the_recovery_link(self, archive):
        html = archive["client"].get("/auth/login").get_data(as_text=True)
        assert "/auth/login/recovery" in html

    def test_recovery_key_unlocks_and_redirects_to_password_reset(self, archive):
        response = archive["client"].post(
            "/auth/login/recovery",
            data={"recovery_key": archive["key"]},
        )
        assert response.status_code == 302
        assert "new-password" in response.headers["Location"]
        assert Encryption.is_unlocked()

    def test_formatting_variations_are_accepted(self, archive):
        mangled = archive["key"].lower().replace("-", " ")
        response = archive["client"].post(
            "/auth/login/recovery", data={"recovery_key": mangled}
        )
        assert response.status_code == 302

    def test_wrong_key_is_rejected(self, archive):
        response = archive["client"].post(
            "/auth/login/recovery",
            data={"recovery_key": Encryption.generate_recovery_key()},
        )
        assert response.status_code == 200
        assert "does not open this archive" in response.get_data(as_text=True)

    def test_mistyped_key_says_so_rather_than_wrong_key(self, archive):
        """A typo and a wrong key are different problems."""
        response = archive["client"].post(
            "/auth/login/recovery", data={"recovery_key": "TOO-SHORT"}
        )
        html = response.get_data(as_text=True)
        assert "characters" in html
        assert "does not open this archive" not in html

    def test_new_password_after_recovery_works(self, archive):
        client = archive["client"]
        client.post("/auth/login/recovery", data={"recovery_key": archive["key"]})

        response = client.post(
            "/auth/login/recovery/new-password",
            data={"password": NEW_PASSWORD, "confirm": NEW_PASSWORD},
        )
        assert response.status_code == 302

        Encryption.lock()
        assert Encryption.unlock(NEW_PASSWORD)

    def test_recovery_key_survives_the_password_reset(self, archive):
        client = archive["client"]
        client.post("/auth/login/recovery", data={"recovery_key": archive["key"]})
        client.post(
            "/auth/login/recovery/new-password",
            data={"password": NEW_PASSWORD, "confirm": NEW_PASSWORD},
        )

        Encryption.lock()
        assert Encryption.unlock_with_recovery_key(archive["key"])

    def test_password_reset_page_requires_a_session(self, archive):
        Encryption.lock()
        response = archive["client"].get("/auth/login/recovery/new-password")
        assert response.status_code == 302
        assert "login" in response.headers["Location"]


# ============================================================
# UPGRADE FLOW (v2 archive -> recovery keys)
# ============================================================


class TestUpgradeFlow:
    @pytest.fixture
    def v2_client(self, app):
        """A logged-in client on a v2 archive with a fresh verified backup."""
        from datetime import datetime

        from core.config import Config
        from core.database import Database

        with app.app_context():
            Encryption.initialize(PASSWORD)
            Database.set_key(Encryption.get_db_key())
            Database.initialize()

            archive_root = Config.get_archive_path() / "1"
            archive_root.mkdir(parents=True, exist_ok=True)
            (archive_root / "000.eml.enc").write_bytes(
                Encryption.encrypt(b"From: a@b.c\r\nSubject: Hi\r\n\r\nBody.")
            )

            backups_dir = Config.get_data_path().parent / "backups"
            backups_dir.mkdir(parents=True, exist_ok=True)
            _write_backup_manifest(backups_dir, datetime.now())

        client = app.test_client()
        client.post("/auth/login", data={"password": PASSWORD})
        return client

    def test_login_on_v2_archive_redirects_to_the_upgrade(self, v2_client, app):
        """The prompt has to find the user, not the other way round.

        A v2 archive works fine without a recovery key, so the only moment
        the offer is guaranteed to be seen is on the way in.
        """
        fresh = app.test_client()
        response = fresh.post(
            "/auth/login", data={"password": PASSWORD}, follow_redirects=False
        )
        assert response.status_code == 302
        assert "/auth/upgrade" in response.headers["Location"]

    def test_upgrade_page_renders(self, v2_client):
        page = v2_client.get("/auth/upgrade")
        assert page.status_code == 200
        assert b"Add a recovery key" in page.data

    def test_upgrade_produces_a_working_recovery_key(self, v2_client):
        response = v2_client.post("/auth/upgrade", data={"password": PASSWORD})
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "Save your recovery key" in html

        key = extract_recovery_key(html)
        assert Encryption.salt_file_version() == 3

        Encryption.lock()
        assert Encryption.unlock_with_recovery_key(key)

    def test_upgrade_preserves_content(self, v2_client):
        from core.config import Config

        path = Config.get_archive_path() / "1" / "000.eml.enc"
        expected = Encryption.decrypt(path.read_bytes())

        v2_client.post("/auth/upgrade", data={"password": PASSWORD})

        assert Encryption.decrypt(path.read_bytes()) == expected

    def test_wrong_password_refused(self, v2_client):
        response = v2_client.post("/auth/upgrade", data={"password": "WrongOne!"})
        assert b"not your current master password" in response.data
        assert Encryption.salt_file_version() == 2

    def test_upgrade_takes_a_backup_when_none_is_recent(self, v2_client):
        """The user asked to upgrade; make the backup rather than refusing."""
        from core.config import Config

        backups_dir = Config.get_data_path().parent / "backups"
        for leftover in backups_dir.glob("*.zip"):
            leftover.unlink()
        (backups_dir / "manifest.json").unlink()

        response = v2_client.post("/auth/upgrade", data={"password": PASSWORD})

        assert "Save your recovery key" in response.get_data(as_text=True)
        assert Encryption.salt_file_version() == 3
        assert list(backups_dir.glob("*.zip")), "no backup was taken"

    def test_already_upgraded_archive_redirects(self, v2_client):
        v2_client.post("/auth/upgrade", data={"password": PASSWORD})
        response = v2_client.get("/auth/upgrade")
        assert response.status_code == 302

    def test_upgrade_requires_a_session(self, app):
        with app.app_context():
            Encryption.initialize(PASSWORD)
        response = app.test_client().get("/auth/upgrade")
        assert response.status_code == 302
        assert "login" in response.headers["Location"]


# ============================================================
# ROTATION API
# ============================================================


class TestRotationApi:
    @pytest.fixture
    def v3_client(self, app):
        """Logged-in client on a migrated archive, with CSRF set up."""
        client = app.test_client()
        response = client.post(
            "/auth/setup", data={"password": PASSWORD, "confirm": PASSWORD}
        )
        key = extract_recovery_key(response.get_data(as_text=True))

        with client.session_transaction() as sess:
            token = sess["csrf_token"]

        return {"client": client, "key": key, "csrf": token}

    def test_status_reports_a_recovery_key(self, v3_client):
        response = v3_client["client"].get("/auth/api/recovery-key-status")
        data = response.get_json()
        assert data["has_recovery_key"] is True
        assert data["needs_upgrade"] is False

    def test_rotation_returns_a_new_working_key(self, v3_client):
        response = v3_client["client"].post(
            "/auth/api/rotate-recovery-key",
            json={"password": PASSWORD},
            headers={"X-CSRF-Token": v3_client["csrf"]},
        )
        assert response.status_code == 200
        new_key = response.get_json()["recovery_key"]
        assert new_key != v3_client["key"]

        Encryption.lock()
        assert Encryption.unlock_with_recovery_key(new_key)

    def test_rotation_revokes_the_old_key(self, v3_client):
        v3_client["client"].post(
            "/auth/api/rotate-recovery-key",
            json={"password": PASSWORD},
            headers={"X-CSRF-Token": v3_client["csrf"]},
        )
        Encryption.lock()
        with pytest.raises(InvalidPasswordError):
            Encryption.unlock_with_recovery_key(v3_client["key"])

    def test_rotation_requires_the_password(self, v3_client):
        response = v3_client["client"].post(
            "/auth/api/rotate-recovery-key",
            json={"password": "WrongPassword!"},
            headers={"X-CSRF-Token": v3_client["csrf"]},
        )
        assert response.status_code == 403
        Encryption.lock()
        assert Encryption.unlock_with_recovery_key(v3_client["key"])

    def test_rotation_requires_csrf(self, v3_client):
        """This endpoint sits under /api/, so app.py enforces the token.

        In the browser the global fetch interceptor in base.html supplies
        it automatically, which is why no call site sets it by hand. The
        test client does not run that script, so it must be explicit here.
        """
        response = v3_client["client"].post(
            "/auth/api/rotate-recovery-key",
            json={"password": PASSWORD},
        )
        assert response.status_code == 403
