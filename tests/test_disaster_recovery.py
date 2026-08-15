"""
Tests for disaster recovery — restoring when there is no archive to log in to.

Session 77. The gap these cover: if the data directory was lost, MailRepo
redirected every route to /auth/setup, which offers only "create a new
master password". A user whose backups were sitting intact in iCloud was
walked past them into starting an empty archive.

Two things were broken, and fixing either alone leaves you stuck:
  - No route could reach the restore machinery without a session, and a
    session needs a key file that no longer exists.
  - The backup manifest lived only inside the application folder, so the
    disk loss that took the archive also took the index of the backups.
    Zips survived in the cloud folder and nothing could interpret them.
"""

import json
import zipfile
from pathlib import Path

import pytest

from core.config import Config
from core.encryption import Encryption
from utils.backup import (
    check_restore_pending,
    complete_restore,
    create_full_backup,
    create_incremental_backup,
    describe_restore_point_credentials,
    discover_restore_points_in,
    get_restore_points,
    load_manifest,
    reconstruct_manifest_entries,
    save_manifest,
)

PASSWORD = "TestPassword123!"


# ============================================================
# FIXTURES
# ============================================================


@pytest.fixture
def cloud_folder(tmp_path):
    """Stands in for iCloud Drive: a backup destination outside the app."""
    folder = tmp_path / "cloud_backups"
    folder.mkdir()
    return folder


@pytest.fixture
def archive_backed_up_offsite(initialized_app, cloud_folder):
    """A small archive with one full backup written to an external folder."""
    app, password = initialized_app

    archive_root = Config.get_archive_path() / "1"
    archive_root.mkdir(parents=True, exist_ok=True)

    plaintext = b"From: alice@example.com\r\nSubject: Retainer\r\n\r\nPrivileged."
    (archive_root / "000.eml.enc").write_bytes(Encryption.encrypt(plaintext))

    with app.app_context():
        create_full_backup(cloud_folder)

    return {
        "app": app,
        "password": password,
        "folder": cloud_folder,
        "plaintext": plaintext,
    }


def _wipe_local_data():
    """Simulate losing the machine's data: archive, database, key file, manifest."""
    import shutil

    for path in (
        Config.get_data_path(),
        Config.get_archive_path(),
        Config.get_backup_path(),
    ):
        shutil.rmtree(path, ignore_errors=True)
    Encryption.lock()


# ============================================================
# THE MANIFEST SIDECAR
# ============================================================


class TestManifestSidecar:
    """A backup folder must be able to describe itself."""

    def test_backup_writes_a_manifest_beside_the_zips(self, archive_backed_up_offsite):
        sidecar = archive_backed_up_offsite["folder"] / "manifest.json"
        assert sidecar.exists()

    def test_sidecar_lists_the_backup_that_is_there(self, archive_backed_up_offsite):
        sidecar = archive_backed_up_offsite["folder"] / "manifest.json"
        entries = json.loads(sidecar.read_text())["backups"]
        assert len(entries) == 1
        assert (archive_backed_up_offsite["folder"] / entries[0]["filename"]).exists()

    def test_sidecar_keeps_up_with_later_backups(self, archive_backed_up_offsite):
        folder = archive_backed_up_offsite["folder"]
        target = Config.get_archive_path() / "1" / "001.eml.enc"
        target.write_bytes(Encryption.encrypt(b"a second message"))

        create_incremental_backup(folder)

        entries = json.loads((folder / "manifest.json").read_text())["backups"]
        assert len(entries) == 2

    def test_local_only_backups_need_no_sidecar(self, initialized_app):
        """The canonical manifest is not duplicated onto itself."""
        create_full_backup()
        # One manifest, in the usual place, and no crash from trying to
        # write a sidecar over it.
        assert (Config.get_backup_path() / "manifest.json").exists()

    def test_unwritable_destination_does_not_fail_the_backup(
        self, archive_backed_up_offsite, monkeypatch
    ):
        """A backup that succeeded must not be reported as failed.

        The canonical manifest is already written by the time sidecars are
        attempted, so a cloud folder that went offline is a warning, not
        a failed backup.
        """
        import utils.backup as backup_module

        real_write = backup_module._atomic_write_text
        cloud = str(archive_backed_up_offsite["folder"])

        def fail_on_cloud(path, text):
            if str(path).startswith(cloud):
                raise OSError("cloud folder went away")
            return real_write(path, text)

        monkeypatch.setattr(backup_module, "_atomic_write_text", fail_on_cloud)

        save_manifest(load_manifest())  # must not raise

        assert (Config.get_backup_path() / "manifest.json").exists()


# ============================================================
# FINDING BACKUPS WITH NO LOCAL INDEX
# ============================================================


class TestDiscovery:
    """After total loss, the folder is the only thing left to go on."""

    def test_sidecar_is_used_when_present(self, archive_backed_up_offsite):
        folder = archive_backed_up_offsite["folder"]
        _wipe_local_data()

        points, source = discover_restore_points_in(folder)

        assert source == "manifest"
        assert len(points) == 1

    def test_local_manifest_is_gone_after_loss(self, archive_backed_up_offsite):
        """The premise: without discovery there is nothing to offer."""
        _wipe_local_data()
        assert get_restore_points() == []

    def test_reconstructs_from_filenames_without_a_sidecar(
        self, archive_backed_up_offsite
    ):
        folder = archive_backed_up_offsite["folder"]
        (folder / "manifest.json").unlink()
        _wipe_local_data()

        points, source = discover_restore_points_in(folder)

        assert source == "reconstructed"
        assert len(points) == 1
        assert points[0]["reconstructed"] is True

    def test_reconstruction_is_labelled_as_such(self, archive_backed_up_offsite):
        """A guess must not be presented as a record."""
        folder = archive_backed_up_offsite["folder"]
        (folder / "manifest.json").unlink()
        _wipe_local_data()

        points, _ = discover_restore_points_in(folder)
        assert all(p.get("reconstructed") for p in points)

    def test_sidecar_points_are_not_labelled_reconstructed(
        self, archive_backed_up_offsite
    ):
        folder = archive_backed_up_offsite["folder"]
        _wipe_local_data()

        points, _ = discover_restore_points_in(folder)
        assert not any(p.get("reconstructed") for p in points)

    def test_empty_folder_reports_empty(self, tmp_path):
        folder = tmp_path / "nothing"
        folder.mkdir()

        points, source = discover_restore_points_in(folder)

        assert points == []
        assert source == "empty"

    def test_missing_folder_raises(self, tmp_path):
        with pytest.raises(ValueError):
            discover_restore_points_in(tmp_path / "does_not_exist")

    def test_stale_sidecar_falls_through_to_reconstruction(
        self, archive_backed_up_offsite
    ):
        """A manifest naming files that aren't there is worse than none."""
        folder = archive_backed_up_offsite["folder"]
        manifest = json.loads((folder / "manifest.json").read_text())
        real_name = manifest["backups"][0]["filename"]
        manifest["backups"][0]["filename"] = "full_2020-01-01_000000.zip"
        (folder / "manifest.json").write_text(json.dumps(manifest))
        _wipe_local_data()

        points, source = discover_restore_points_in(folder)

        assert source == "reconstructed"
        assert points[0]["filename"] == real_name

    def test_corrupt_sidecar_falls_through_to_reconstruction(
        self, archive_backed_up_offsite
    ):
        folder = archive_backed_up_offsite["folder"]
        (folder / "manifest.json").write_text("{not json")
        _wipe_local_data()

        points, source = discover_restore_points_in(folder)

        assert source == "reconstructed"
        assert len(points) == 1


# ============================================================
# RECONSTRUCTION RULES
# ============================================================


class TestReconstruction:
    """Chain structure inferred from filenames, since that is all there is."""

    def _touch(self, folder, name):
        path = folder / name
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("data/placeholder", b"x")
        return path

    def test_incrementals_join_the_preceding_full(self, cloud_folder):
        self._touch(cloud_folder, "full_2026-01-01_120000.zip")
        self._touch(cloud_folder, "incr_2026-01-02_120000.zip")
        self._touch(cloud_folder, "incr_2026-01-03_120000.zip")

        entries = reconstruct_manifest_entries(cloud_folder)

        assert len(entries) == 3
        assert len({e["chain_id"] for e in entries}) == 1

    def test_a_new_full_starts_a_new_chain(self, cloud_folder):
        self._touch(cloud_folder, "full_2026-01-01_120000.zip")
        self._touch(cloud_folder, "incr_2026-01-02_120000.zip")
        self._touch(cloud_folder, "full_2026-02-01_120000.zip")
        self._touch(cloud_folder, "incr_2026-02-02_120000.zip")

        entries = reconstruct_manifest_entries(cloud_folder)
        chains = {}
        for entry in entries:
            chains.setdefault(entry["chain_id"], []).append(entry["filename"])

        assert len(chains) == 2
        assert all(len(members) == 2 for members in chains.values())

    def test_orphaned_incremental_is_dropped(self, cloud_folder):
        """An incremental with no full ahead of it cannot be restored."""
        self._touch(cloud_folder, "incr_2026-01-02_120000.zip")

        assert reconstruct_manifest_entries(cloud_folder) == []

    def test_safety_backups_stand_alone(self, cloud_folder):
        self._touch(cloud_folder, "full_2026-01-01_120000.zip")
        self._touch(cloud_folder, "pre_restore_2026-01-05_120000.zip")

        entries = reconstruct_manifest_entries(cloud_folder)
        safety = [e for e in entries if e["type"] == "pre_restore"]

        assert len(safety) == 1
        assert safety[0]["chain_id"] != entries[0]["chain_id"]

    def test_microsecond_suffixed_names_are_recognised(self, cloud_folder):
        self._touch(cloud_folder, "full_2026-01-01_120000_412773.zip")

        entries = reconstruct_manifest_entries(cloud_folder)

        assert len(entries) == 1
        assert entries[0]["type"] == "full"

    def test_unrelated_files_are_ignored(self, cloud_folder):
        self._touch(cloud_folder, "full_2026-01-01_120000.zip")
        (cloud_folder / "notes.txt").write_text("hello")
        (cloud_folder / "random.zip").write_bytes(b"PK")

        entries = reconstruct_manifest_entries(cloud_folder)

        assert len(entries) == 1

    def test_incrementals_are_ordered_by_time_not_readdir(self, cloud_folder):
        self._touch(cloud_folder, "full_2026-01-01_120000.zip")
        self._touch(cloud_folder, "incr_2026-01-09_120000.zip")
        self._touch(cloud_folder, "incr_2026-01-03_120000.zip")

        entries = reconstruct_manifest_entries(cloud_folder)
        incrementals = [e for e in entries if e["type"] == "incremental"]

        assert [e["created_at"] for e in incrementals] == sorted(
            e["created_at"] for e in incrementals
        )


# ============================================================
# WHICH PASSWORD OPENS IT
# ============================================================


class TestCredentialNoteAfterTotalLoss:
    """The disaster case is exactly when this note matters most."""

    def test_no_current_key_file_still_says_something_useful(
        self, archive_backed_up_offsite
    ):
        folder = archive_backed_up_offsite["folder"]
        _wipe_local_data()

        points, _ = discover_restore_points_in(folder)

        assert points[0]["credential_status"] == "no_current_key"
        assert points[0]["credential_note"]

    def test_note_names_the_password_as_the_one_from_then(
        self, archive_backed_up_offsite
    ):
        folder = archive_backed_up_offsite["folder"]
        _wipe_local_data()

        points, _ = discover_restore_points_in(folder)

        assert "password" in points[0]["credential_note"].lower()

    def test_comparison_still_works_when_a_key_file_exists(
        self, archive_backed_up_offsite
    ):
        """The no-key branch must not swallow the normal case."""
        points = get_restore_points()
        assert points[0]["credential_status"] != "no_current_key"


# ============================================================
# THE ROUTES
# ============================================================


class TestRecoveryRoutes:
    """Public, and dead the moment an archive exists."""

    def _token(self, client):
        response = client.get("/auth/restore")
        import re

        match = re.search(rb'name="csrf-token" content="([^"]*)"', response.data)
        return match.group(1).decode()

    def test_recovery_page_is_reachable_with_no_archive(self, client):
        assert client.get("/auth/restore").status_code == 200

    def test_setup_page_links_to_recovery(self, client):
        """The whole gap was that nothing pointed here."""
        assert b"/auth/restore" in client.get("/auth/setup").data

    def test_recovery_page_redirects_once_an_archive_exists(self, initialized_app):
        app, _ = initialized_app
        response = app.test_client().get("/auth/restore")

        assert response.status_code == 302
        assert "/auth/login" in response.headers["Location"]

    def test_scan_refuses_once_an_archive_exists(self, initialized_app):
        app, _ = initialized_app
        response = app.test_client().post("/auth/restore/scan", json={})

        assert response.status_code == 403

    def test_prepare_refuses_once_an_archive_exists(self, initialized_app):
        app, _ = initialized_app
        response = app.test_client().post(
            "/auth/restore/prepare", json={"restore_point_id": "anything"}
        )

        assert response.status_code == 403

    def test_scan_requires_the_page_token(self, client):
        """A page in another tab must not be able to drive this."""
        response = client.post("/auth/restore/scan", json={"folder": "/tmp"})

        assert response.status_code == 403

    def test_scan_finds_offsite_backups(self, archive_backed_up_offsite):
        app = archive_backed_up_offsite["app"]
        folder = archive_backed_up_offsite["folder"]
        _wipe_local_data()

        client = app.test_client()
        token = self._token(client)
        response = client.post(
            "/auth/restore/scan",
            json={"folder": str(folder), "csrf_token": token},
        )
        data = response.get_json()

        assert data["success"] is True
        assert len(data["restore_points"]) == 1

    def test_scan_rejects_a_path_that_is_not_a_folder(self, client, tmp_path):
        target = tmp_path / "afile.txt"
        target.write_text("x")
        token = self._token(client)

        response = client.post(
            "/auth/restore/scan",
            json={"folder": str(target), "csrf_token": token},
        )

        assert response.status_code == 400

    def test_scan_reports_a_missing_folder_plainly(self, client, tmp_path):
        token = self._token(client)

        response = client.post(
            "/auth/restore/scan",
            json={"folder": str(tmp_path / "nope"), "csrf_token": token},
        )

        assert response.status_code == 400
        assert "does not exist" in response.get_json()["error"]

    def test_prepare_rejects_an_unknown_restore_point(
        self, archive_backed_up_offsite
    ):
        app = archive_backed_up_offsite["app"]
        folder = archive_backed_up_offsite["folder"]
        _wipe_local_data()

        client = app.test_client()
        token = self._token(client)
        response = client.post(
            "/auth/restore/prepare",
            json={
                "folder": str(folder),
                "restore_point_id": "made_up",
                "csrf_token": token,
            },
        )

        assert response.status_code == 404


# ============================================================
# THE WHOLE LOOP
# ============================================================


class TestFullRecovery:
    """Total loss to readable mail, through the routes a user would use."""

    def test_data_comes_back_and_still_decrypts(self, archive_backed_up_offsite):
        app = archive_backed_up_offsite["app"]
        folder = archive_backed_up_offsite["folder"]
        password = archive_backed_up_offsite["password"]
        plaintext = archive_backed_up_offsite["plaintext"]

        _wipe_local_data()
        assert not Encryption.is_initialized()

        client = app.test_client()
        page = client.get("/auth/restore")
        import re

        token = re.search(
            rb'name="csrf-token" content="([^"]*)"', page.data
        ).group(1).decode()

        scan = client.post(
            "/auth/restore/scan",
            json={"folder": str(folder), "csrf_token": token},
        ).get_json()
        point_id = scan["restore_points"][0]["id"]

        prepared = client.post(
            "/auth/restore/prepare",
            json={
                "folder": str(folder),
                "restore_point_id": point_id,
                "csrf_token": token,
            },
        )
        assert prepared.get_json()["success"] is True

        # Restart: main.py completes staged restores before the DB opens.
        assert check_restore_pending() is not None
        assert complete_restore() is not None

        assert Encryption.is_initialized()
        Encryption.unlock(password)
        restored = Config.get_archive_path() / "1" / "000.eml.enc"
        assert Encryption.decrypt(restored.read_bytes()) == plaintext

    def test_recovery_routes_close_after_a_successful_restore(
        self, archive_backed_up_offsite
    ):
        app = archive_backed_up_offsite["app"]
        folder = archive_backed_up_offsite["folder"]

        _wipe_local_data()
        client = app.test_client()
        page = client.get("/auth/restore")
        import re

        token = re.search(
            rb'name="csrf-token" content="([^"]*)"', page.data
        ).group(1).decode()
        scan = client.post(
            "/auth/restore/scan",
            json={"folder": str(folder), "csrf_token": token},
        ).get_json()
        client.post(
            "/auth/restore/prepare",
            json={
                "folder": str(folder),
                "restore_point_id": scan["restore_points"][0]["id"],
                "csrf_token": token,
            },
        )
        complete_restore()

        assert app.test_client().get("/auth/restore").status_code == 302
