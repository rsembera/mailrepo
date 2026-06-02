"""
Tests for web/blueprints/api/settings.py - application settings API.

Covers the validated settings endpoints (trash retention, session
timeout, thread-max-messages) including their GET defaults and the
allow-list rejection of out-of-range values, the session-status report
(including the "Never" timeout), keepalive, and the reset-database
guards (confirmation text + password) without performing the
destructive reset itself.
"""

import pytest

from core import Database
from core.database import set_setting


class TestTrashRetention:
    def test_default(self, authenticated_client, initialized_app):
        resp = authenticated_client.get("/api/settings/trash-retention")
        assert resp.status_code == 200
        assert resp.get_json()["value"] == "0"

    def test_set_valid(self, authenticated_client, initialized_app):
        resp = authenticated_client.post(
            "/api/settings/trash-retention", json={"value": "30"}
        )
        assert resp.status_code == 200
        assert resp.get_json()["value"] == "30"
        # Persisted
        assert authenticated_client.get(
            "/api/settings/trash-retention"
        ).get_json()["value"] == "30"

    def test_reject_invalid(self, authenticated_client, initialized_app):
        resp = authenticated_client.post(
            "/api/settings/trash-retention", json={"value": "999"}
        )
        assert resp.status_code == 400


class TestSessionTimeout:
    def test_default(self, authenticated_client, initialized_app):
        resp = authenticated_client.get("/api/settings/session-timeout")
        assert resp.get_json()["value"] == "30"

    def test_set_valid(self, authenticated_client, initialized_app):
        resp = authenticated_client.post(
            "/api/settings/session-timeout", json={"value": "60"}
        )
        assert resp.status_code == 200
        assert resp.get_json()["value"] == "60"

    def test_reject_invalid(self, authenticated_client, initialized_app):
        resp = authenticated_client.post(
            "/api/settings/session-timeout", json={"value": "7"}
        )
        assert resp.status_code == 400


class TestThreadMaxMessages:
    def test_default(self, authenticated_client, initialized_app):
        resp = authenticated_client.get("/api/settings/thread-max-messages")
        assert resp.get_json()["value"] == "500"

    def test_set_valid(self, authenticated_client, initialized_app):
        resp = authenticated_client.post(
            "/api/settings/thread-max-messages", json={"value": "1000"}
        )
        assert resp.status_code == 200
        assert resp.get_json()["value"] == "1000"

    def test_reject_invalid(self, authenticated_client, initialized_app):
        resp = authenticated_client.post(
            "/api/settings/thread-max-messages", json={"value": "5"}
        )
        assert resp.status_code == 400


class TestSessionStatus:
    def test_authenticated_reports_logged_in(self, authenticated_client, initialized_app):
        resp = authenticated_client.get("/api/session-status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["logged_in"] is True
        assert data["timeout_minutes"] == 30

    def test_never_timeout(self, authenticated_client, initialized_app):
        set_setting("session_timeout", "0")
        Database.commit()
        resp = authenticated_client.get("/api/session-status")
        data = resp.get_json()
        assert data["logged_in"] is True
        assert data["timeout_minutes"] == 0
        assert data["warning_needed"] is False
        assert data["seconds_remaining"] is None


class TestKeepalive:
    def test_authenticated_keepalive(self, authenticated_client, initialized_app):
        resp = authenticated_client.post("/api/keepalive")
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True


class TestResetDatabaseGuards:
    def test_wrong_confirmation_text(self, authenticated_client, initialized_app):
        _, password = initialized_app
        resp = authenticated_client.post(
            "/api/reset_database", json={"password": password, "confirmation": "nope"}
        )
        assert resp.status_code == 400
        # Nothing was torn down: the database still answers queries
        assert Database.fetchone("SELECT 1 AS ok", ())["ok"] == 1

    def test_wrong_password(self, authenticated_client, initialized_app):
        resp = authenticated_client.post(
            "/api/reset_database",
            json={"password": "WrongPassword!", "confirmation": "RESET"},
        )
        assert resp.status_code == 401
        assert Database.fetchone("SELECT 1 AS ok", ())["ok"] == 1
