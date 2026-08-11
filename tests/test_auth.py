"""
Tests for web/blueprints/auth.py — the authentication boundary.

Covers setup, login (incl. rate-limit lockout), logout, CSRF enforcement on
the auth API endpoints, and the password-change job-id handoff. The handoff
test validates the Session 39 #1 fix end to end (passwords held server-side,
never in the session cookie), which previously relied on a manual test.

Module-level state (_login_attempts, _pw_change_jobs) is global, so it is
cleared around every test.
"""

import pytest

from core.encryption import Encryption, InvalidPasswordError
from web.blueprints import auth


@pytest.fixture(autouse=True)
def _reset_auth_state():
    auth._login_attempts.clear()
    auth._pw_change_jobs.clear()
    yield
    auth._login_attempts.clear()
    auth._pw_change_jobs.clear()


INIT_PW = "TestPassword123!"  # matches conftest.initialized_app


# ---------------------------------------------------------------------------


class TestSetup:
    def test_get_renders_when_uninitialized(self, client):
        resp = client.get("/auth/setup")
        assert resp.status_code == 200

    def test_get_redirects_to_login_when_initialized(self, initialized_app):
        app, _ = initialized_app
        resp = app.test_client().get("/auth/setup")
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]

    def test_post_short_password_shows_error(self, client):
        resp = client.post("/auth/setup", data={"password": "short", "confirm": "short"})
        assert resp.status_code == 200
        assert b"at least 12 characters" in resp.data
        assert not Encryption.is_initialized()

    def test_post_mismatched_confirm_shows_error(self, client):
        resp = client.post(
            "/auth/setup",
            data={"password": "longenoughpassword", "confirm": "differentpassword"},
        )
        assert resp.status_code == 200
        assert b"do not match" in resp.data
        assert not Encryption.is_initialized()

    def test_post_valid_initializes_and_shows_recovery_key(self, client):
        """Setup now ends on the recovery-key screen, not a redirect.

        The key is rendered into this one response and stored nowhere, so
        setup cannot redirect past it (Session 68).
        """
        resp = client.post(
            "/auth/setup",
            data={"password": "averylongpassword", "confirm": "averylongpassword"},
        )
        assert resp.status_code == 200
        assert b"Save your recovery key" in resp.data
        assert Encryption.is_initialized()
        with client.session_transaction() as sess:
            assert sess.get("authenticated") is True


class TestLogin:
    def test_get_redirects_to_setup_when_uninitialized(self, client):
        resp = client.get("/auth/login")
        assert resp.status_code == 302
        assert "/auth/setup" in resp.headers["Location"]

    def test_get_renders_when_initialized(self, initialized_app):
        app, _ = initialized_app
        resp = app.test_client().get("/auth/login")
        assert resp.status_code == 200

    def test_post_correct_password_redirects_and_authenticates(self, initialized_app):
        app, password = initialized_app
        client = app.test_client()
        resp = client.post("/auth/login", data={"password": password})
        assert resp.status_code == 302
        with client.session_transaction() as sess:
            assert sess.get("authenticated") is True

    def test_post_wrong_password_errors_and_records_attempt(self, initialized_app):
        app, _ = initialized_app
        client = app.test_client()
        resp = client.post("/auth/login", data={"password": "wrong-password"})
        assert resp.status_code == 200
        assert b"Invalid password" in resp.data
        # A failed attempt was recorded against the client IP.
        assert sum(len(v) for v in auth._login_attempts.values()) == 1

    def test_already_authenticated_redirects_to_index(self, initialized_app):
        app, _ = initialized_app
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["authenticated"] = True
        resp = client.get("/auth/login")  # Encryption is unlocked via fixture
        assert resp.status_code == 302


class TestLogout:
    def test_logout_locks_and_clears_session(self, authenticated_client, monkeypatch):
        # Isolate logout's contract (lock + clear + redirect) from the
        # auto-backup side effect, which is covered by test_backup.
        monkeypatch.setattr(auth, "_run_auto_backup_check", lambda: None)
        resp = authenticated_client.post("/auth/logout")
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]
        assert Encryption.is_unlocked() is False
        with authenticated_client.session_transaction() as sess:
            assert "authenticated" not in sess

    def test_logout_rejects_get(self, authenticated_client, monkeypatch):
        """POST-only: a cross-site <img src> must not be able to force it.

        Logout clears the session, locks the archive and triggers a backup
        check — all state-changing.
        """
        monkeypatch.setattr(auth, "_run_auto_backup_check", lambda: None)
        resp = authenticated_client.get("/auth/logout")
        assert resp.status_code == 405
        assert Encryption.is_unlocked() is True


class TestRateLimit:
    def test_helper_allows_under_max(self):
        for _ in range(auth._MAX_ATTEMPTS - 1):
            auth._record_failed_attempt("1.2.3.4")
        allowed, remaining = auth._check_rate_limit("1.2.3.4")
        assert allowed is True
        assert remaining == 0

    def test_helper_locks_at_max(self):
        for _ in range(auth._MAX_ATTEMPTS):
            auth._record_failed_attempt("1.2.3.4")
        allowed, remaining = auth._check_rate_limit("1.2.3.4")
        assert allowed is False
        assert remaining > 0

    def test_clear_attempts_resets(self):
        for _ in range(auth._MAX_ATTEMPTS):
            auth._record_failed_attempt("1.2.3.4")
        auth._clear_attempts("1.2.3.4")
        allowed, _ = auth._check_rate_limit("1.2.3.4")
        assert allowed is True

    def test_login_endpoint_locks_out_after_max_failures(self, initialized_app):
        app, _ = initialized_app
        client = app.test_client()
        for _ in range(auth._MAX_ATTEMPTS):
            client.post("/auth/login", data={"password": "wrong-password"})
        resp = client.get("/auth/login")
        assert b"Too many failed attempts" in resp.data


class TestCSRF:
    def test_api_post_without_token_rejected(self, initialized_app):
        app, password = initialized_app
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["authenticated"] = True
            sess["csrf_token"] = "tok-123"
        resp = client.post("/auth/api/verify-password", json={"current_password": password})
        assert resp.status_code == 403

    def test_api_post_with_token_accepted(self, initialized_app):
        app, password = initialized_app
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["authenticated"] = True
            sess["csrf_token"] = "tok-123"
        resp = client.post(
            "/auth/api/verify-password",
            json={"current_password": password},
            headers={"X-CSRF-Token": "tok-123"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["valid"] is True


class TestPasswordChangeHandoff:
    def test_start_returns_job_and_keeps_passwords_off_cookie(self, authenticated_client):
        resp = authenticated_client.post(
            "/auth/api/change-password",
            json={"current_password": INIT_PW, "new_password": "BrandNewPass789!"},
        )
        assert resp.status_code == 200
        job_id = resp.get_json()["job_id"]
        # Passwords live in server memory, keyed by the opaque job id...
        assert job_id in auth._pw_change_jobs
        assert auth._pw_change_jobs[job_id]["new"] == "BrandNewPass789!"
        # ...and NOT in the session cookie.
        with authenticated_client.session_transaction() as sess:
            assert "password_change_current" not in sess
            assert "password_change_new" not in sess

    def test_start_wrong_current_rejected(self, authenticated_client):
        resp = authenticated_client.post(
            "/auth/api/change-password",
            json={"current_password": "not-the-password", "new_password": "BrandNewPass789!"},
        )
        assert resp.status_code == 400
        assert auth._pw_change_jobs == {}

    def test_start_short_new_password_rejected(self, authenticated_client):
        resp = authenticated_client.post(
            "/auth/api/change-password",
            json={"current_password": INIT_PW, "new_password": "short"},
        )
        assert resp.status_code == 400
        assert auth._pw_change_jobs == {}

    def test_progress_unknown_job_emits_expired(self, authenticated_client):
        resp = authenticated_client.get("/auth/api/change-password-progress/does-not-exist")
        text = resp.get_data(as_text=True)
        assert "expired" in text.lower()

    def test_full_change_via_job_id(self, authenticated_client):
        # End-to-end validation of the #1 fix: start -> consume the SSE job ->
        # password is actually changed, and the job is consumed exactly once.
        #
        # change_master_password has a non-overridable guard requiring a
        # backup <=24h old (the DB rekey window isn't resumable, so the backup
        # is the recovery path). Create one first, as the app requires.
        from utils import backup

        backup.create_full_backup()

        start = authenticated_client.post(
            "/auth/api/change-password",
            json={"current_password": INIT_PW, "new_password": "BrandNewPass789!"},
        )
        job_id = start.get_json()["job_id"]

        resp = authenticated_client.get(f"/auth/api/change-password-progress/{job_id}")
        text = resp.get_data(as_text=True)
        assert "complete" in text
        # Job consumed (single use).
        assert job_id not in auth._pw_change_jobs
        # The master password was actually rotated.
        Encryption.unlock("BrandNewPass789!")  # must not raise
        with pytest.raises(InvalidPasswordError):
            Encryption.unlock(INIT_PW)
