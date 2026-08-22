"""
The unverified-restore marker: a restore is UNVERIFIED until someone
proves they can open it.

A backup carries its key file as it stood, so a restored archive opens
with the credentials of the moment it was taken. If those turn out to
be lost, login is a wall — and before this marker, the recovery routes
went dead the moment the restore landed (a key file now existed), so
there was no way back to a different backup, including the pre-restore
safety copy.

House rule, both ways: door open with the marker, closed after each
login path clears it, marker set by complete_restore, marker never
inside a backup zip. Sealing mutations run against each guard (see the
session log) so these tests are proved capable of going red.
"""

import zipfile

import pytest

from core.database import Database
from core.encryption import Encryption
from utils.backup import (
    _restore_unverified_marker,
    clear_restore_unverified,
    complete_restore,
    create_full_backup,
    create_pre_restore_backup,
    get_backups_dir,
    get_restore_points,
    prepare_restore,
    prepare_restore_from_point,
    restore_unverified,
    set_restore_unverified,
)

PASSWORD = "TestPassword123!"


@pytest.fixture(autouse=True)
def _reset_auth_state():
    """Same reasoning as test_auth.py: the rate limiter is module state."""
    from web.blueprints import auth

    auth._login_attempts.clear()
    yield
    auth._login_attempts.clear()


def _recovery_token(client):
    """Fetch the recovery page and pull its CSRF token out of the meta tag."""
    import re

    response = client.get("/auth/restore")
    match = re.search(rb'name="csrf-token" content="([^"]*)"', response.data)
    return match.group(1).decode() if match else ""


# ============================================================
# THE MARKER ITSELF
# ============================================================


class TestMarker:
    def test_roundtrip(self):
        assert not restore_unverified()
        set_restore_unverified()
        assert restore_unverified()
        clear_restore_unverified()
        assert not restore_unverified()

    def test_clear_is_safe_when_absent(self):
        clear_restore_unverified()  # must not raise
        assert not restore_unverified()

    def test_marker_path_is_isolated(self, temp_data_dir):
        """Tripwire: conftest's data-dir re-rooting is what keeps auth
        tests from unlinking the real install's marker. If the marker
        ever moves out of the data dir (e.g. to the state dir), this
        fails and the isolation question must be re-answered."""
        marker = _restore_unverified_marker()
        assert str(marker).startswith(str(temp_data_dir))


# ============================================================
# THE MARKER NEVER RIDES INTO A BACKUP
# ============================================================


class TestMarkerStaysOutOfBackups:
    def test_marker_never_in_a_full_backup_zip(self, initialized_app):
        app, _ = initialized_app
        set_restore_unverified()

        with app.app_context():
            info = create_full_backup()

        zip_path = get_backups_dir() / info["filename"]
        with zipfile.ZipFile(zip_path) as zf:
            assert not any(".restore_unverified" in n for n in zf.namelist())

    def test_marker_never_in_a_pre_restore_zip(self, initialized_app):
        app, _ = initialized_app
        set_restore_unverified()

        with app.app_context():
            path = create_pre_restore_backup()

        with zipfile.ZipFile(path) as zf:
            assert not any(".restore_unverified" in n for n in zf.namelist())


# ============================================================
# COMPLETE_RESTORE SETS IT
# ============================================================


class TestCompleteRestoreSetsMarker:
    def test_complete_restore_sets_marker_and_carries_note(self, initialized_app):
        app, _ = initialized_app

        with app.app_context():
            create_full_backup()
            point = get_restore_points()[0]
            prepare_restore(point["id"])

        assert not restore_unverified()  # staging alone proves nothing
        result = complete_restore()

        assert restore_unverified()
        assert "credential_note" in result
        assert "credential_status" in result

    def test_marker_survives_a_relaunch(self, initialized_app):
        """A crash between complete_restore and first login must not
        lose it — that is the point of it being a file."""
        app, _ = initialized_app

        with app.app_context():
            create_full_backup()
            point = get_restore_points()[0]
            prepare_restore(point["id"])

        complete_restore()

        from web import create_app

        create_app()  # a fresh app instance changes nothing on disk
        assert restore_unverified()


# ============================================================
# THE DOOR: OPEN WITH THE MARKER, CLOSED WITHOUT
# ============================================================


class TestRecoveryDoor:
    def test_door_open_while_restore_unverified(self, initialized_app):
        """An archive exists, but nobody has vouched for it: the
        recovery routes must stay reachable."""
        app, _ = initialized_app
        set_restore_unverified()

        client = app.test_client()
        assert client.get("/auth/restore").status_code == 200

    def test_json_routes_open_while_unverified(self, initialized_app):
        app, _ = initialized_app
        set_restore_unverified()

        client = app.test_client()
        token = _recovery_token(client)
        headers = {"X-CSRF-Token": token}

        assert (
            client.post("/auth/restore/search", json={}, headers=headers).status_code
            == 200
        )
        assert (
            client.post(
                "/auth/restore/browse", json={}, headers=headers
            ).status_code
            == 200
        )
        # Scan of an empty-but-real folder: open door, empty result.
        response = client.post(
            "/auth/restore/scan",
            json={"folder": str(get_backups_dir())},
            headers=headers,
        )
        assert response.status_code == 200

    def test_door_closed_without_the_marker(self, initialized_app):
        """The pre-existing rule still holds in normal use."""
        app, _ = initialized_app

        client = app.test_client()
        assert client.get("/auth/restore").status_code == 302
        assert client.post("/auth/restore/search", json={}).status_code == 403

    def test_door_closes_when_the_marker_clears(self, initialized_app):
        app, _ = initialized_app
        set_restore_unverified()
        clear_restore_unverified()

        client = app.test_client()
        assert client.get("/auth/restore").status_code == 302


# ============================================================
# THE VOUCH: EACH LOGIN PATH CLEARS IT
# ============================================================


class TestVouch:
    def test_successful_login_clears_marker(self, initialized_app):
        app, _ = initialized_app
        set_restore_unverified()

        client = app.test_client()
        response = client.post("/auth/login", data={"password": PASSWORD})

        assert response.status_code == 302  # in — index or the v3 upgrade offer
        assert not restore_unverified()

    def test_failed_login_leaves_marker(self, initialized_app):
        app, _ = initialized_app
        set_restore_unverified()

        client = app.test_client()
        response = client.post("/auth/login", data={"password": "not-the-password"})

        assert response.status_code == 200  # re-rendered with the error
        assert restore_unverified()

    def test_verified_recovery_key_clears_marker(self, app):
        """Daybook's Aug 16 ruling: only a DEMONSTRATED credential
        counts. verify_recovery_key performs the full recovery-side
        unwrap against the key file on disk — a demonstration, so it
        vouches exactly as a password login does."""
        recovery_key = Encryption.initialize_v3(PASSWORD)
        Database.set_key(Encryption.get_db_key())
        with app.app_context():
            Database.initialize()
        Encryption.lock()

        set_restore_unverified()

        client = app.test_client()
        response = client.post(
            "/auth/login/recovery", data={"recovery_key": recovery_key}
        )

        assert response.status_code == 200
        assert b"Set a new master password" in response.data
        assert not restore_unverified()

    def test_wrong_recovery_key_leaves_marker(self, app):
        Encryption.initialize_v3(PASSWORD)
        Database.set_key(Encryption.get_db_key())
        with app.app_context():
            Database.initialize()
        Encryption.lock()

        set_restore_unverified()

        client = app.test_client()
        wrong = "AAAA-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA"
        client.post("/auth/login/recovery", data={"recovery_key": wrong})

        assert restore_unverified()


# ============================================================
# THE LOGIN SCREEN SAYS SO
# ============================================================


class TestLoginBanner:
    def test_banner_names_the_password_after_restore(self, initialized_app):
        app, _ = initialized_app
        set_restore_unverified()
        app.config["RESTORE_COMPLETED"] = {
            "original_date": "2026-07-01T09:00:00",
            "credential_note": "Opens with the password you used then.",
        }

        html = app.test_client().get("/auth/login").get_data(as_text=True)

        assert "restored from a backup" in html
        assert "2026-07-01" in html
        assert "the password you used then" in html
        assert "Restore a different backup" in html
        assert "/auth/restore" in html

    def test_banner_survives_a_failed_attempt(self, initialized_app):
        """Precisely when it is needed: the user has just typed their
        current password and been refused."""
        app, _ = initialized_app
        set_restore_unverified()
        app.config["RESTORE_COMPLETED"] = {
            "original_date": "2026-07-01T09:00:00",
            "credential_note": "Opens with the password you used then.",
        }

        response = app.test_client().post(
            "/auth/login", data={"password": "not-the-password"}
        )
        html = response.get_data(as_text=True)

        assert "Invalid password" in html
        assert "restored from a backup" in html
        assert "Restore a different backup" in html

    def test_generic_note_when_only_the_marker_stands(self, initialized_app):
        """Crash before the config was set, or a relaunch since: the
        marker alone still produces a banner with the generic note."""
        app, _ = initialized_app
        set_restore_unverified()

        html = app.test_client().get("/auth/login").get_data(as_text=True)

        assert "restored from a backup" in html
        assert "not necessarily your current one" in html
        assert "Restore a different backup" in html

    def test_no_banner_in_normal_use(self, initialized_app):
        app, _ = initialized_app

        html = app.test_client().get("/auth/login").get_data(as_text=True)

        assert "restored from a backup" not in html
        assert "restored-notice" not in html

    def test_no_way_back_link_once_vouched(self, initialized_app):
        """RESTORE_COMPLETED alone (marker already cleared) still names
        the date, but no longer offers the recovery door — it is shut."""
        app, _ = initialized_app
        app.config["RESTORE_COMPLETED"] = {
            "original_date": "2026-07-01T09:00:00",
            "credential_note": "",
        }

        html = app.test_client().get("/auth/login").get_data(as_text=True)

        assert "restored from a backup" in html
        assert "Restore a different backup" not in html

    def test_recovery_login_screen_carries_the_banner(self, app):
        Encryption.initialize_v3(PASSWORD)
        Database.set_key(Encryption.get_db_key())
        with app.app_context():
            Database.initialize()
        Encryption.lock()

        set_restore_unverified()

        html = app.test_client().get("/auth/login/recovery").get_data(as_text=True)

        assert "restored from a backup" in html


# ============================================================
# A SECOND RESTORE FROM THE UNVERIFIED STATE
# ============================================================


class TestSecondRestoreFromUnverified:
    def test_second_restore_takes_its_safety_copy(self, initialized_app):
        """Restore A could not be opened; the user goes back through the
        door for restore B. Unlike the bare-metal case there is data on
        disk this time, so the pre-restore safety net must fire — and
        with the database locked, its location setting is unreadable, so
        the copy lands in the default backups folder. That fallback is
        the documented behaviour, not an accident."""
        app, _ = initialized_app

        with app.app_context():
            create_full_backup()
            point = get_restore_points()[0]

        # Enter the unverified state: restore A landed, nobody logged in.
        set_restore_unverified()
        Database.close()
        Encryption.lock()

        before = len(list(get_backups_dir().glob("pre_restore_*.zip")))
        prepare_restore_from_point(point)
        after = len(list(get_backups_dir().glob("pre_restore_*.zip")))

        assert after == before + 1
