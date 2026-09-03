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
from datetime import datetime, timedelta

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


def _csrf(client):
    """The session's CSRF token, as the /auth/ form POSTs now require."""
    with client.session_transaction() as sess:
        return sess.get("csrf_token", "")


def _recovery_token(client, recovery_key):
    """Verify a recovery key and return the handoff token.

    The recovery flow is two steps by design: verify, then reset. Since
    Session 74 the verify step renders the reset form directly instead of
    redirecting, so the token arrives in a hidden field rather than a
    query string — it never enters browser history.
    """
    response = client.post(
        "/auth/login/recovery", data={"recovery_key": recovery_key}
    )
    assert response.status_code == 200, "recovery key did not verify"
    html = response.get_data(as_text=True)
    marker = 'name="token" value="'
    assert marker in html, "no handoff token in the rendered reset form"
    start = html.index(marker) + len(marker)
    return html[start : html.index('"', start)]


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
        with fresh_client.session_transaction() as sess:
            token = sess.get("csrf_token", "")
        fresh_client.post("/auth/logout", data={"csrf_token": token})
        return {"client": fresh_client, "key": key}

    def test_login_page_offers_the_recovery_link(self, archive):
        html = archive["client"].get("/auth/login").get_data(as_text=True)
        assert "/auth/login/recovery" in html

    def test_recovery_key_does_not_unlock_the_archive(self, archive):
        """The whole point of Session 71.

        The recovery key verifies and hands off to the password reset. It
        must NOT open the archive, or it is simply a second password and
        the user can skip the reset and keep using it forever.
        """
        response = archive["client"].post(
            "/auth/login/recovery",
            data={"recovery_key": archive["key"]},
        )
        assert response.status_code == 200
        assert b"Set a new master password" in response.data

        assert not Encryption.is_unlocked(), (
            "recovery key granted an unlocked archive"
        )
        with archive["client"].session_transaction() as sess:
            assert not sess.get("authenticated"), (
                "recovery key granted an authenticated session"
            )

    def test_handoff_token_is_not_the_recovery_key(self, archive):
        """The key must not travel in a URL, a page, or a cookie."""
        response = archive["client"].post(
            "/auth/login/recovery",
            data={"recovery_key": archive["key"]},
        )
        compact = archive["key"].replace("-", "")
        html = response.get_data(as_text=True)

        # The rendered reset form carries the handoff token, never the key.
        assert archive["key"] not in html
        assert compact not in html

        with archive["client"].session_transaction() as sess:
            for value in sess.values():
                assert compact not in str(value)

    def test_handoff_token_does_not_enter_browser_history(self, archive):
        """Suggestion 12.

        The verify step used to redirect with ?token=..., putting the
        token in history for its whole 5-minute life. It now renders the
        reset form directly, so the token exists only in a hidden field.
        """
        response = archive["client"].post(
            "/auth/login/recovery",
            data={"recovery_key": archive["key"]},
        )
        assert response.status_code == 200, "verify step still redirects"
        assert "Location" not in response.headers

    def test_formatting_variations_are_accepted(self, archive):
        mangled = archive["key"].lower().replace("-", " ")
        response = archive["client"].post(
            "/auth/login/recovery", data={"recovery_key": mangled}
        )
        assert response.status_code == 200
        assert b"Set a new master password" in response.data

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
        token = _recovery_token(client, archive["key"])

        response = client.post(
            "/auth/login/recovery/new-password",
            data={"token": token, "password": NEW_PASSWORD, "confirm": NEW_PASSWORD},
        )
        assert response.status_code == 200
        assert b"Password updated" in response.data

        Encryption.lock()
        assert Encryption.unlock(NEW_PASSWORD)

    def test_reset_does_not_log_the_user_in(self, archive):
        """They have typed the new password exactly twice.

        Using it once more now, while the recovery key is still in hand,
        is the cheapest confirmation it is what they think it is.
        """
        client = archive["client"]
        token = _recovery_token(client, archive["key"])
        client.post(
            "/auth/login/recovery/new-password",
            data={"token": token, "password": NEW_PASSWORD, "confirm": NEW_PASSWORD},
        )

        with client.session_transaction() as sess:
            assert not sess.get("authenticated")

    def test_old_password_stops_working_after_reset(self, archive):
        client = archive["client"]
        token = _recovery_token(client, archive["key"])
        client.post(
            "/auth/login/recovery/new-password",
            data={"token": token, "password": NEW_PASSWORD, "confirm": NEW_PASSWORD},
        )

        Encryption.lock()
        with pytest.raises(InvalidPasswordError):
            Encryption.unlock(PASSWORD)

    def test_token_is_single_use(self, archive):
        """Consumed on success, so a replay cannot reset again."""
        client = archive["client"]
        token = _recovery_token(client, archive["key"])
        client.post(
            "/auth/login/recovery/new-password",
            data={"token": token, "password": NEW_PASSWORD, "confirm": NEW_PASSWORD},
        )

        response = client.post(
            "/auth/login/recovery/new-password",
            data={"token": token, "password": "YetAnother12345!", "confirm": "YetAnother12345!"},
        )
        assert response.status_code == 302
        Encryption.lock()
        assert Encryption.unlock(NEW_PASSWORD)

    def test_recovery_key_survives_the_password_reset(self, archive):
        client = archive["client"]
        token = _recovery_token(client, archive["key"])
        client.post(
            "/auth/login/recovery/new-password",
            data={"token": token, "password": NEW_PASSWORD, "confirm": NEW_PASSWORD},
        )

        Encryption.lock()
        assert Encryption.unlock_with_recovery_key(archive["key"])

    def test_reset_page_needs_a_valid_token(self, archive):
        response = archive["client"].get("/auth/login/recovery/new-password")
        assert response.status_code == 302
        assert "recovery" in response.headers["Location"]

    def test_forged_token_is_rejected(self, archive):
        response = archive["client"].post(
            "/auth/login/recovery/new-password",
            data={"token": "not-a-real-token", "password": NEW_PASSWORD, "confirm": NEW_PASSWORD},
        )
        assert response.status_code == 302
        Encryption.lock()
        assert Encryption.unlock(PASSWORD), "password was changed without a valid token"

    def test_an_authenticated_session_cannot_reach_the_reset(self, archive):
        """A password login must not reach the no-old-password reset.

        The reset asks for no credential — the verified recovery key IS
        the credential. Without the token requirement, any logged-in
        session could replace the master password, the exact capability
        rotate_recovery_key withholds by demanding the password.
        """
        client = archive["client"]
        client.post("/auth/login", data={"password": PASSWORD})

        response = client.get("/auth/login/recovery/new-password")
        assert response.status_code == 302
        assert "recovery" in response.headers["Location"]
        assert "new-password" not in response.headers["Location"]

        response = client.post(
            "/auth/login/recovery/new-password",
            data={"csrf_token": _csrf(client), "password": NEW_PASSWORD, "confirm": NEW_PASSWORD},
        )
        assert response.status_code == 302

        Encryption.lock()
        with pytest.raises(InvalidPasswordError):
            Encryption.unlock(NEW_PASSWORD)
        assert Encryption.unlock(PASSWORD)

    def test_the_handoff_token_is_what_protects_this_route(self, archive):
        """No session CSRF token here, and none is needed.

        The reset is deliberately unauthenticated — a user who forgot
        their password has no session. What stops a forged cross-site
        POST is the handoff token: 32 bytes of urlsafe randomness, minted
        server-side only after a recovery key verified, and never sent
        anywhere an attacker's page could read it.
        """
        client = archive["client"]

        response = client.post(
            "/auth/login/recovery/new-password",
            data={"password": NEW_PASSWORD, "confirm": NEW_PASSWORD},
        )
        assert response.status_code == 302
        assert "recovery" in response.headers["Location"]

        Encryption.lock()
        with pytest.raises(InvalidPasswordError):
            Encryption.unlock(NEW_PASSWORD)
        assert Encryption.unlock(PASSWORD)


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
        response = v2_client.post(
            "/auth/upgrade",
            data={"csrf_token": _csrf(v2_client), "password": PASSWORD},
        )
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

        v2_client.post(
            "/auth/upgrade",
            data={"csrf_token": _csrf(v2_client), "password": PASSWORD},
        )

        assert Encryption.decrypt(path.read_bytes()) == expected

    def test_wrong_password_refused(self, v2_client):
        response = v2_client.post(
            "/auth/upgrade",
            data={"csrf_token": _csrf(v2_client), "password": "WrongOne!"},
        )
        assert b"not your current master password" in response.data
        assert Encryption.salt_file_version() == 2

    def test_upgrade_takes_a_backup_when_none_is_recent(self, v2_client):
        """The user asked to upgrade; make the backup rather than refusing."""
        from core.config import Config

        backups_dir = Config.get_data_path().parent / "backups"
        for leftover in backups_dir.glob("*.zip"):
            leftover.unlink()
        (backups_dir / "manifest.json").unlink()

        response = v2_client.post(
            "/auth/upgrade",
            data={"csrf_token": _csrf(v2_client), "password": PASSWORD},
        )

        assert "Save your recovery key" in response.get_data(as_text=True)
        assert Encryption.salt_file_version() == 3
        assert list(backups_dir.glob("*.zip")), "no backup was taken"

    def test_upgrade_succeeds_with_a_stale_backup_and_no_file_changes(
        self, v2_client
    ):
        """The case that actually bit Rick.

        A real backup exists but is older than the 24h gate, and nothing
        in the archive has changed since. create_backup() would decide
        'incremental', find no changes, and return None without writing
        anything — so the gate would still see the stale backup and refuse,
        after the page had promised a fresh one. Forcing a full backup is
        what makes this pass.
        """
        from datetime import datetime, timedelta

        from core.config import Config
        from utils.backup import create_full_backup

        backups_dir = Config.get_data_path().parent / "backups"

        # A genuine backup of the current archive, aged past the gate.
        create_full_backup()
        import json

        manifest_path = backups_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        stale = (datetime.now() - timedelta(hours=30)).isoformat()
        for entry in manifest["backups"]:
            entry["created_at"] = stale
        manifest_path.write_text(json.dumps(manifest))

        response = v2_client.post(
            "/auth/upgrade",
            data={"csrf_token": _csrf(v2_client), "password": PASSWORD},
        )

        assert "Save your recovery key" in response.get_data(as_text=True), (
            "upgrade refused despite promising to take a fresh backup"
        )
        assert Encryption.salt_file_version() == 3

        # Filenames are timestamped to the second, so counting files is
        # unreliable here. What matters is that a non-stale restore point
        # now exists: that is what the gate reads.
        manifest = json.loads(manifest_path.read_text())
        newest = max(b["created_at"] for b in manifest["backups"])
        age_hours = (
            datetime.now() - datetime.fromisoformat(newest)
        ).total_seconds() / 3600
        assert age_hours < 1, (
            f"newest backup is still {age_hours:.1f}h old — none was taken"
        )

    def test_upgrade_backup_goes_to_the_configured_location(self, v2_client):
        """Not the default repo backups/ dir.

        create_full_backup() with no argument writes to
        Config.get_backup_path(). Anyone using a cloud folder has their
        backups elsewhere, so the safety backup would land somewhere
        their off-machine sync never sees — leaving a full that exists
        only locally while the incrementals depending on it are the only
        things replicated. That happened to Rick's real archive.
        """
        from core.config import Config
        from core.database import set_setting

        custom = Config.get_base_path() / "custom_backups"
        custom.mkdir(parents=True, exist_ok=True)
        set_setting("backup_location", str(custom))

        # Make the existing backup stale so the upgrade takes a new one.
        backups_dir = Config.get_data_path().parent / "backups"
        manifest_path = backups_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        stale = (datetime.now() - timedelta(hours=30)).isoformat()
        for entry in manifest["backups"]:
            entry["created_at"] = stale
        manifest_path.write_text(json.dumps(manifest))

        v2_client.post(
            "/auth/upgrade",
            data={"csrf_token": _csrf(v2_client), "password": PASSWORD},
        )

        assert list(custom.glob("*.zip")), (
            "upgrade backup did not go to the configured location"
        )

    def test_already_upgraded_archive_redirects(self, v2_client):
        v2_client.post(
            "/auth/upgrade",
            data={"csrf_token": _csrf(v2_client), "password": PASSWORD},
        )
        response = v2_client.get("/auth/upgrade")
        assert response.status_code == 302

    def test_continue_after_migration_goes_to_the_archive(self, v2_client):
        """Not to "Create New Archive".

        After an upgrade the user already has an archive. Landing them on
        the create-archive screen reads like the upgrade wiped everything
        — which is exactly how it looked when Rick hit it.
        """
        v2_client.post(
            "/auth/upgrade",
            data={"csrf_token": _csrf(v2_client), "password": PASSWORD},
        )

        with v2_client.session_transaction() as sess:
            token = sess["csrf_token"]

        response = v2_client.post(
            "/auth/setup/recovery-key-saved",
            data={"csrf_token": token, "context": "migration"},
        )
        assert response.status_code == 302
        assert "create" not in response.headers["Location"]

    def test_continue_after_first_run_setup_goes_to_create_archive(self, app):
        """The other half: a brand-new install has nothing yet."""
        client = app.test_client()
        client.post("/auth/setup", data={"password": PASSWORD, "confirm": PASSWORD})

        with client.session_transaction() as sess:
            token = sess["csrf_token"]

        response = client.post(
            "/auth/setup/recovery-key-saved",
            data={"csrf_token": token, "context": "setup"},
        )
        assert response.status_code == 302
        assert "create" in response.headers["Location"]

    def test_upgrade_requires_a_session(self, app):
        with app.app_context():
            Encryption.initialize(PASSWORD)
        response = app.test_client().get("/auth/upgrade")
        assert response.status_code == 302
        assert "login" in response.headers["Location"]

    def test_upgrade_post_requires_csrf(self, v2_client):
        """The password already blocks a blind cross-site POST from
        succeeding, but the token check keeps every state-changing /auth/
        form on the same rule rather than each arguing its own exception.
        """
        response = v2_client.post("/auth/upgrade", data={"password": PASSWORD})
        assert response.status_code == 302
        assert "login" in response.headers["Location"]
        assert Encryption.salt_file_version() == 2


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


# ============================================================
# VERIFY API — check a key without using it
# ============================================================


class TestVerifyRecoveryKeyApi:
    """Testing a key must not cost you your password.

    The recovery flow always resets. Without this endpoint the only way
    to find out whether the key in the drawer works is to use it — which
    is why the Session 68 drill needed a CLI script written for it.
    """

    @pytest.fixture
    def v3_client(self, app):
        client = app.test_client()
        response = client.post(
            "/auth/setup", data={"password": PASSWORD, "confirm": PASSWORD}
        )
        key = extract_recovery_key(response.get_data(as_text=True))
        with client.session_transaction() as sess:
            token = sess["csrf_token"]
        return {"client": client, "key": key, "csrf": token}

    def _check(self, ctx, key):
        return ctx["client"].post(
            "/auth/api/verify-recovery-key",
            json={"recovery_key": key},
            headers={"X-CSRF-Token": ctx["csrf"]},
        )

    def test_correct_key_verifies(self, v3_client):
        response = self._check(v3_client, v3_client["key"])
        assert response.status_code == 200
        assert response.get_json()["verified"] is True

    def test_verification_changes_nothing(self, v3_client):
        """The whole point: no password change, no key rotation."""
        before = Encryption.read_salt_blob()

        self._check(v3_client, v3_client["key"])

        assert Encryption.read_salt_blob() == before, "key file was modified"
        Encryption.lock()
        assert Encryption.unlock(PASSWORD)
        Encryption.lock()
        assert Encryption.unlock_with_recovery_key(v3_client["key"])

    def test_verification_does_not_unlock(self, v3_client):
        """Verifying is not the same act as being let in."""
        Encryption.lock()
        self._check(v3_client, v3_client["key"])
        assert not Encryption.is_unlocked()

    def test_wrong_key_reports_not_verified(self, v3_client):
        response = self._check(v3_client, Encryption.generate_recovery_key())
        assert response.status_code == 200
        data = response.get_json()
        assert data["verified"] is False
        assert "does not open" in data["error"]

    def test_mistyped_key_says_so_rather_than_wrong_key(self, v3_client):
        """A typo and a wrong key are different problems."""
        response = self._check(v3_client, "TOO-SHORT")
        data = response.get_json()
        assert data["verified"] is False
        assert "characters" in data["error"]
        assert "does not open" not in data["error"]

    def test_formatting_variations_accepted(self, v3_client):
        mangled = v3_client["key"].lower().replace("-", " ")
        assert self._check(v3_client, mangled).get_json()["verified"] is True

    def test_requires_a_session(self, app):
        client = app.test_client()
        with app.app_context():
            Encryption.initialize_v3(PASSWORD)
        response = client.post(
            "/auth/api/verify-recovery-key", json={"recovery_key": "whatever"}
        )
        assert response.status_code in (401, 403)

    def test_does_not_require_the_master_password(self, v3_client):
        """Deliberate: an existing session already has the archive open.

        Demanding the password would only discourage the checking this
        endpoint exists to encourage.
        """
        response = self._check(v3_client, v3_client["key"])
        assert response.status_code == 200
        assert response.get_json()["verified"] is True


class TestCreateArchiveCsrf:
    """Finding 4. A state-changing form outside /api/ carried no token.

    The middleware in web/app.py only covers paths containing /api/, so
    this form needed the same explicit check the other /auth/ forms make.
    """

    @pytest.fixture
    def logged_in(self, app):
        client = app.test_client()
        client.post("/auth/setup", data={"password": PASSWORD, "confirm": PASSWORD})
        with client.session_transaction() as sess:
            token = sess["csrf_token"]
        return {"client": client, "csrf": token}

    def _folder_count(self):
        from core.database import Database

        row = Database.fetchone("SELECT count(*) AS n FROM folders")
        return row["n"]

    def test_creates_with_a_valid_token(self, logged_in):
        before = self._folder_count()
        response = logged_in["client"].post(
            "/archive/create",
            data={"name": "Client Files", "csrf_token": logged_in["csrf"]},
        )
        assert response.status_code == 302
        assert self._folder_count() == before + 1

    def test_refuses_without_a_token(self, logged_in):
        before = self._folder_count()
        response = logged_in["client"].post(
            "/archive/create", data={"name": "Forged"}
        )
        assert response.status_code == 302
        assert "login" in response.headers["Location"]
        assert self._folder_count() == before, "folder created without a CSRF token"

    def test_refuses_with_a_wrong_token(self, logged_in):
        before = self._folder_count()
        logged_in["client"].post(
            "/archive/create",
            data={"name": "Forged", "csrf_token": "not-the-token"},
        )
        assert self._folder_count() == before
