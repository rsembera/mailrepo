"""
Tests for web/blueprints/backups.py — the password gate on the
dangerous backup settings (security review 2026-09, finding 6).

The post-backup command is arbitrary shell; the backup location is
where the key file gets copied; prepare-restore rolls the archive back
at next launch. None of these may be changed with a CSRF token alone.
"""

from core.database import get_setting
from core.encryption import Encryption

PASSWORD = "TestPassword123!"  # matches conftest.initialized_app


class TestSettingsGate:
    def test_frequency_and_retention_need_no_password(self, authenticated_client):
        resp = authenticated_client.post(
            "/api/backup/settings", json={"frequency": "weekly", "retention": "30"}
        )
        assert resp.status_code == 200, resp.get_json()
        assert get_setting("backup_frequency") == "weekly"

    def test_command_change_without_password_is_refused(self, authenticated_client):
        resp = authenticated_client.post(
            "/api/backup/settings", json={"post_backup_command": "rm -rf ~"}
        )
        assert resp.status_code == 401
        assert get_setting("post_backup_command", "") == ""

    def test_command_change_with_wrong_password_is_refused(self, authenticated_client):
        resp = authenticated_client.post(
            "/api/backup/settings",
            json={"post_backup_command": "rm -rf ~", "password": "nope"},
        )
        assert resp.status_code == 401
        assert get_setting("post_backup_command", "") == ""
        assert Encryption.is_unlocked()  # a failed check must not lock the archive

    def test_command_change_with_password_succeeds(self, authenticated_client):
        resp = authenticated_client.post(
            "/api/backup/settings",
            json={"post_backup_command": "echo ok", "password": PASSWORD},
        )
        assert resp.status_code == 200, resp.get_json()
        assert get_setting("post_backup_command") == "echo ok"

    def test_unchanged_command_needs_no_password(self, authenticated_client):
        # Re-submitting the current value (the settings form always sends
        # every field) must not demand a password.
        resp = authenticated_client.post(
            "/api/backup/settings",
            json={"frequency": "daily", "post_backup_command": "", "location": ""},
        )
        assert resp.status_code == 200, resp.get_json()

    def test_location_change_without_password_is_refused(self, authenticated_client, tmp_path):
        resp = authenticated_client.post(
            "/api/backup/settings", json={"location": str(tmp_path / "elsewhere")}
        )
        assert resp.status_code == 401
        assert get_setting("backup_location", "") == ""
        assert not (tmp_path / "elsewhere").exists()

    def test_location_change_with_password_succeeds(self, authenticated_client, tmp_path):
        target = tmp_path / "elsewhere"
        resp = authenticated_client.post(
            "/api/backup/settings",
            json={"location": str(target), "password": PASSWORD},
        )
        assert resp.status_code == 200, resp.get_json()
        assert get_setting("backup_location") == str(target)


class TestPrepareRestoreGate:
    def test_without_password_is_refused(self, authenticated_client):
        resp = authenticated_client.post(
            "/api/backup/prepare-restore", json={"restore_point": "anything"}
        )
        assert resp.status_code == 401

    def test_with_password_reaches_restore(self, authenticated_client):
        # No restore points exist, so the underlying call fails — but it
        # fails past the gate, which is what this checks.
        resp = authenticated_client.post(
            "/api/backup/prepare-restore",
            json={"restore_point": "does-not-exist", "password": PASSWORD},
        )
        assert resp.status_code != 401
