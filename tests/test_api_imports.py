"""
Tests for web/blueprints/api/imports.py - import + export API.

Covers the route-level validation boundary (missing path / folder /
uid, nonexistent files and folders) plus real round-trips that don't
need a network: a single .eml import into the archive, fetching full
import-email content from a file on disk, and the unencrypted-ZIP
folder export (built from a genuinely encrypted message, then read back
and verified to decrypt to the original bytes).
"""

import io
import secrets
import zipfile

from core import Config, Database, Encryption


def _make_folder(name, parent_id=None):
    cur = Database.execute("INSERT INTO folders (name, parent_id) VALUES (?, ?)", (name, parent_id))
    Database.commit()
    return cur.lastrowid


def _eml_bytes(subject="Imported message", body="body text here", attachment=False):
    if attachment:
        boundary = "b0undary"
        return (
            f"From: sender@example.com\r\nTo: me@example.com\r\n"
            f"Subject: {subject}\r\nMessage-ID: <{secrets.token_hex(6)}@test>\r\n"
            f"MIME-Version: 1.0\r\n"
            f'Content-Type: multipart/mixed; boundary="{boundary}"\r\n\r\n'
            f'--{boundary}\r\nContent-Type: text/plain; charset="utf-8"\r\n\r\n'
            f"{body}\r\n"
            f"--{boundary}\r\nContent-Type: application/pdf\r\n"
            f'Content-Disposition: attachment; filename="doc.pdf"\r\n\r\n'
            f"%PDF-1.4 fake pdf bytes\r\n"
            f"--{boundary}--\r\n"
        ).encode()
    return (
        f"From: sender@example.com\r\nTo: me@example.com\r\n"
        f"Subject: {subject}\r\nMessage-ID: <{secrets.token_hex(6)}@test>\r\n"
        f'MIME-Version: 1.0\r\nContent-Type: text/plain; charset="utf-8"\r\n\r\n'
        f"{body}\r\n"
    ).encode()


def _seed_encrypted_message(folder_id, subject="Export me", body="secret contents 99"):
    raw = _eml_bytes(subject=subject, body=body)
    archive_path = Config.get_archive_path() / str(folder_id)
    archive_path.mkdir(parents=True, exist_ok=True)
    fp = archive_path / f"{secrets.token_hex(6)}.eml.enc"
    fp.write_bytes(Encryption.encrypt(raw))
    rel = str(fp.relative_to(Config.get_base_path()))
    Database.execute(
        """INSERT INTO messages (folder_id, message_id, subject, sender, date, filepath)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (folder_id, f"<{secrets.token_hex(6)}@t>", subject, "sender@example.com", 1739633400, rel),
    )
    Database.commit()
    return raw


# ---------------------------------------------------------------------------
# mbox / eml scan + import validation
# ---------------------------------------------------------------------------


class TestScanImportValidation:
    def test_scan_requires_path(self, authenticated_client, initialized_app):
        resp = authenticated_client.post("/api/import/mbox/scan", json={})
        assert resp.status_code == 400

    def test_scan_missing_file(self, authenticated_client, initialized_app):
        resp = authenticated_client.post(
            "/api/import/mbox/scan", json={"path": "/no/such/file.mbox"}
        )
        assert resp.status_code == 404

    def test_legacy_direct_import_routes_are_gone(self, authenticated_client, initialized_app):
        """The legacy /api/import/mbox and /api/import/eml routes (unreferenced
        by the UI; named archive files by Message-ID, leaking correspondent
        domains) were removed in the September 2026 review, #15."""
        assert authenticated_client.post("/api/import/mbox", json={}).status_code == 404
        assert authenticated_client.post("/api/import/eml", json={}).status_code == 404


class TestGetImportEmail:
    def test_requires_source(self, authenticated_client, initialized_app):
        resp = authenticated_client.post("/api/import/email", json={"uid": "eml-0"})
        assert resp.status_code == 400

    def test_requires_uid(self, authenticated_client, initialized_app, tmp_path):
        f = tmp_path / "m.eml"
        f.write_bytes(_eml_bytes())
        resp = authenticated_client.post("/api/import/email", json={"emailSourcePath": str(f)})
        assert resp.status_code == 400

    def test_source_not_found(self, authenticated_client, initialized_app):
        resp = authenticated_client.post(
            "/api/import/email", json={"sourcePath": "/no/file.mbox", "uid": "mbox-0"}
        )
        assert resp.status_code == 404

    def test_reads_eml_from_disk(self, authenticated_client, initialized_app, tmp_path):
        f = tmp_path / "view.eml"
        f.write_bytes(_eml_bytes(subject="Viewer subject", body="distinct body content"))
        resp = authenticated_client.post(
            "/api/import/email",
            json={"emailSourcePath": str(f), "uid": "eml-0", "importType": "eml"},
        )
        assert resp.status_code == 200
        email = resp.get_json()["email"]
        assert email["subject"] == "Viewer subject"
        assert "distinct body content" in email["text_body"]


class TestGetImportEmailSource:
    """View source for a mounted import (Session 88): the raw bytes, so
    headers can be inspected before an email is archived."""

    def test_requires_source(self, authenticated_client, initialized_app):
        resp = authenticated_client.post("/api/import/source", json={"uid": "eml-0"})
        assert resp.status_code == 400

    def test_source_not_found(self, authenticated_client, initialized_app):
        resp = authenticated_client.post(
            "/api/import/source", json={"sourcePath": "/no/file.mbox", "uid": "mbox-0"}
        )
        assert resp.status_code == 404

    def test_returns_raw_source_of_eml(self, authenticated_client, initialized_app, tmp_path):
        f = tmp_path / "src.eml"
        raw = _eml_bytes(subject="Source subject", body="raw body here")
        f.write_bytes(raw)
        resp = authenticated_client.post(
            "/api/import/source",
            json={"emailSourcePath": str(f), "uid": "eml-0", "importType": "eml"},
        )
        assert resp.status_code == 200
        source = resp.get_json()["source"]
        assert "Subject: Source subject" in source
        assert "raw body here" in source
        assert source == raw.decode("utf-8")

    def test_eml_directory_lookup_by_uid(self, authenticated_client, initialized_app, tmp_path):
        (tmp_path / "a.eml").write_bytes(_eml_bytes(subject="First"))
        resp = authenticated_client.post(
            "/api/import/source",
            json={"sourcePath": str(tmp_path), "uid": "eml-0", "importType": "eml"},
        )
        assert resp.status_code == 200
        assert "Subject: First" in resp.get_json()["source"]

    def test_unauthenticated_is_refused(self, client, initialized_app, tmp_path):
        f = tmp_path / "src.eml"
        f.write_bytes(_eml_bytes())
        resp = client.post(
            "/api/import/source", json={"emailSourcePath": str(f), "uid": "eml-0"}
        )
        assert resp.status_code in (401, 302)


class TestImportAttachment:
    def test_requires_source(self, authenticated_client, initialized_app):
        resp = authenticated_client.post(
            "/api/import/attachment", json={"uid": "eml-0", "index": 0}
        )
        assert resp.status_code == 400

    def test_downloads_attachment(self, authenticated_client, initialized_app, tmp_path):
        f = tmp_path / "att.eml"
        f.write_bytes(_eml_bytes(attachment=True))
        resp = authenticated_client.post(
            "/api/import/attachment",
            json={"emailSourcePath": str(f), "uid": "eml-0", "importType": "eml", "index": 0},
        )
        assert resp.status_code == 200
        assert b"fake pdf bytes" in resp.data

    def test_attachment_index_out_of_range(self, authenticated_client, initialized_app, tmp_path):
        f = tmp_path / "att.eml"
        f.write_bytes(_eml_bytes(attachment=True))
        resp = authenticated_client.post(
            "/api/import/attachment",
            json={"emailSourcePath": str(f), "uid": "eml-0", "importType": "eml", "index": 9},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Folder export (unencrypted ZIP round-trip)
# ---------------------------------------------------------------------------


class TestExportFolder:
    def test_export_folder_not_found(self, authenticated_client, initialized_app):
        resp = authenticated_client.post("/api/folders/9999/export", json={})
        assert resp.status_code == 404

    def test_export_round_trip_decrypts(self, authenticated_client, initialized_app):
        fid = _make_folder("Exports")
        original = _seed_encrypted_message(fid, subject="Export subject", body="zip body marker")
        resp = authenticated_client.post(f"/api/folders/{fid}/export", json={})
        assert resp.status_code == 200
        assert resp.mimetype == "application/zip"

        with zipfile.ZipFile(io.BytesIO(resp.data)) as zf:
            names = zf.namelist()
            assert len(names) == 1
            extracted = zf.read(names[0])
        # The ZIP holds the decrypted original .eml, not the ciphertext
        assert extracted == original
        assert b"zip body marker" in extracted

    def test_export_includes_subfolders(self, authenticated_client, initialized_app):
        parent = _make_folder("Parent")
        child = _make_folder("Child", parent_id=parent)
        _seed_encrypted_message(parent, subject="parent-msg")
        _seed_encrypted_message(child, subject="child-msg")
        resp = authenticated_client.post(
            f"/api/folders/{parent}/export", json={"include_subfolders": True}
        )
        assert resp.status_code == 200
        with zipfile.ZipFile(io.BytesIO(resp.data)) as zf:
            names = zf.namelist()
        assert len(names) == 2
        # Child folder's message is nested under the child path in the ZIP
        assert any("Child/" in n for n in names)
