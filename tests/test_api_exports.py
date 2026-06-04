"""
Tests for web/blueprints/api/exports.py - bulk export pipeline.

Three areas per the coverage plan, all exercised without a network or
WeasyPrint (PDF rendering is Tier 4):

1. Selection scope resolution (_resolve_message_ids and friends) -
   folder/messages/search sources, subfolder collection, FTS scoping,
   path labels.
2. The in-memory job state machine (_new_job/_push_event/_fail_job/
   _finish_job/_gc_jobs) including saving to disk with filename
   disambiguation and TTL garbage collection.
3. The .eml ZIP builders - both the plain and the AES-256 encrypted
   variants - built from real encrypted message fixtures and read back
   to verify they decrypt to the original bytes (and reject a wrong
   password).
"""

import io
import secrets
import zipfile

import pytest
import pyzipper

from core import Config, Database, Encryption
from web.blueprints.api import exports as ex


@pytest.fixture(autouse=True)
def _clear_jobs():
    """Keep the process-global job registry isolated between tests."""
    with ex._JOBS_LOCK:
        ex._JOBS.clear()
    yield
    with ex._JOBS_LOCK:
        ex._JOBS.clear()


def _make_folder(name, parent_id=None):
    cur = Database.execute(
        "INSERT INTO folders (name, parent_id) VALUES (?, ?)", (name, parent_id)
    )
    Database.commit()
    return cur.lastrowid


def _make_message(folder_id, subject="Subject", body="body text", date=1739633400,
                  deleted=False, write_file=True):
    """Insert a message; optionally back it with a real encrypted .eml.enc."""
    mid = f"<{secrets.token_hex(8)}@test>"
    rel = None
    if write_file:
        raw = (
            f"From: a@example.com\r\nTo: b@example.com\r\n"
            f"Subject: {subject}\r\nMessage-ID: {mid}\r\n"
            f'MIME-Version: 1.0\r\nContent-Type: text/plain; charset="utf-8"\r\n\r\n'
            f"{body}\r\n"
        ).encode()
        archive_path = Config.get_archive_path() / str(folder_id)
        archive_path.mkdir(parents=True, exist_ok=True)
        fp = archive_path / f"{secrets.token_hex(6)}.eml.enc"
        fp.write_bytes(Encryption.encrypt(raw))
        rel = str(fp.relative_to(Config.get_base_path()))
    cur = Database.execute(
        """INSERT INTO messages
           (folder_id, message_id, subject, sender, date, filepath, body_text, deleted_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (folder_id, mid, subject, "a@example.com", date, rel or "missing.eml.enc",
         body, 999 if deleted else None),
    )
    Database.commit()
    return cur.lastrowid


# ---------------------------------------------------------------------------
# Scope resolution
# ---------------------------------------------------------------------------

class TestScopeResolution:
    def test_collect_folder_ids_root_only(self, initialized_app):
        parent = _make_folder("Parent")
        _make_folder("Child", parent_id=parent)
        assert ex._collect_folder_ids(parent, include_subs=False) == [parent]

    def test_collect_folder_ids_with_descendants(self, initialized_app):
        parent = _make_folder("Parent")
        child = _make_folder("Child", parent_id=parent)
        grandchild = _make_folder("Grandchild", parent_id=child)
        ids = ex._collect_folder_ids(parent, include_subs=True)
        assert set(ids) == {parent, child, grandchild}

    def test_message_ids_in_folders_excludes_deleted_and_orders(self, initialized_app):
        fid = _make_folder("F")
        older = _make_message(fid, date=100)
        newer = _make_message(fid, date=200)
        _make_message(fid, deleted=True)
        assert ex._message_ids_in_folders([fid]) == [older, newer]

    def test_message_ids_in_folders_empty(self, initialized_app):
        assert ex._message_ids_in_folders([]) == []

    def test_search_message_ids_scoped(self, initialized_app):
        f1 = _make_folder("F1")
        f2 = _make_folder("F2")
        hit = _make_message(f1, subject="needle in folder one")
        _make_message(f2, subject="needle in folder two")
        ids = ex._search_message_ids("needle", f1, include_subs=False)
        assert ids == [hit]

    def test_search_message_ids_global(self, initialized_app):
        f1 = _make_folder("F1")
        f2 = _make_folder("F2")
        _make_message(f1, subject="haystack alpha")
        _make_message(f2, subject="haystack beta")
        ids = ex._search_message_ids("haystack", None, include_subs=True)
        assert len(ids) == 2

    def test_folder_path_label_nested(self, initialized_app):
        clients = _make_folder("Clients")
        smith = _make_folder("Smith", parent_id=clients)
        assert ex._folder_path_label(smith) == "Clients/Smith"

    def test_resolve_folder_source_with_subfolder_label(self, initialized_app):
        parent = _make_folder("Matter")
        child = _make_folder("Sub", parent_id=parent)
        m1 = _make_message(parent)
        m2 = _make_message(child)
        ids, label = ex._resolve_message_ids(
            {"source": "folder", "folder_id": parent, "include_subfolders": True}
        )
        assert set(ids) == {m1, m2}
        assert label == "Matter (+ subfolders)"

    def test_resolve_messages_source(self, initialized_app):
        ids, label = ex._resolve_message_ids(
            {"source": "messages", "message_ids": ["3", "7", "9"]}
        )
        assert ids == [3, 7, 9]
        assert label == "3 selected emails"

    def test_resolve_search_empty_query(self, initialized_app):
        ids, label = ex._resolve_message_ids({"source": "search", "query": "   "})
        assert ids == [] and label == ""

    def test_resolve_unknown_source(self, initialized_app):
        with pytest.raises(ValueError):
            ex._resolve_message_ids({"source": "bogus"})


# ---------------------------------------------------------------------------
# Job state machine (in-memory; no DB needed)
# ---------------------------------------------------------------------------

class TestJobStateMachine:
    def test_new_job_is_running_and_retrievable(self):
        job_id = ex._new_job()
        job = ex._get_job(job_id)
        assert job is not None and job["status"] == "running"

    def test_get_unknown_job_is_none(self):
        assert ex._get_job("does-not-exist") is None

    def test_push_event_queues_and_signals(self):
        job_id = ex._new_job()
        ex._push_event(job_id, "progress", {"percent": 50})
        job = ex._get_job(job_id)
        assert job["events"][-1] == {"event": "progress", "data": {"percent": 50}}
        assert job["event_added"].is_set()

    def test_fail_job_sets_status_and_error_event(self):
        job_id = ex._new_job()
        ex._fail_job(job_id, "boom")
        job = ex._get_job(job_id)
        assert job["status"] == "failed"
        assert job["error"] == "boom"
        assert job["events"][-1]["event"] == "error"

    def test_finish_job_in_memory(self):
        job_id = ex._new_job()
        ex._finish_job(
            job_id, result_bytes=b"hello", result_mimetype="application/zip",
            result_filename="out.zip", summary={"format": "eml"},
        )
        job = ex._get_job(job_id)
        assert job["status"] == "done"
        assert job["result_bytes"] == b"hello"
        complete = job["events"][-1]
        assert complete["event"] == "complete"
        assert complete["data"]["size"] == 5
        assert complete["data"]["saved_path"] is None

    def test_finish_job_to_disk(self, tmp_path):
        job_id = ex._new_job()
        ex._finish_job(
            job_id, result_bytes=b"file-bytes", result_mimetype="application/zip",
            result_filename="export.zip", summary={}, output_dir=str(tmp_path),
        )
        job = ex._get_job(job_id)
        saved = job["saved_path"]
        assert saved is not None
        assert (tmp_path / "export.zip").read_bytes() == b"file-bytes"
        # Bytes are dropped from memory once written to disk
        assert job["result_bytes"] is None

    def test_finish_job_disambiguates_existing_filename(self, tmp_path):
        (tmp_path / "export.zip").write_bytes(b"existing")
        job_id = ex._new_job()
        ex._finish_job(
            job_id, result_bytes=b"new", result_mimetype="application/zip",
            result_filename="export.zip", summary={}, output_dir=str(tmp_path),
        )
        saved = ex._get_job(job_id)["saved_path"]
        assert saved.endswith("export (1).zip")
        assert (tmp_path / "export.zip").read_bytes() == b"existing"

    def test_finish_job_missing_destination_fails(self, tmp_path):
        job_id = ex._new_job()
        # Two levels below an existing parent -> refused (no mkdir -p)
        ex._finish_job(
            job_id, result_bytes=b"x", result_mimetype="application/zip",
            result_filename="export.zip", summary={},
            output_dir=str(tmp_path / "missing" / "deeper"),
        )
        job = ex._get_job(job_id)
        assert job["status"] == "failed"
        assert "not found" in job["error"].lower()

    def test_gc_purges_stale_jobs(self):
        from datetime import datetime, timedelta
        stale_id = ex._new_job()
        ex._get_job(stale_id)["created_at"] = datetime.now() - timedelta(hours=2)
        # Allocating a new job triggers _gc_jobs internally
        fresh_id = ex._new_job()
        assert ex._get_job(stale_id) is None
        assert ex._get_job(fresh_id) is not None


# ---------------------------------------------------------------------------
# .eml ZIP builders - plain and AES-256 encrypted round-trips
# ---------------------------------------------------------------------------

class TestEmlZipBuilders:
    def test_plain_zip_round_trip(self, initialized_app):
        fid = _make_folder("Clients")
        _make_message(fid, subject="First", body="content one")
        _make_message(fid, subject="Second", body="content two")
        ids = ex._message_ids_in_folders([fid])
        data, filename = ex._build_eml_zip(ids)
        assert filename.startswith("mailrepo_export_") and filename.endswith(".zip")
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            assert len(names) == 2
            assert all(n.startswith("Clients/") for n in names)
            joined = b"".join(zf.read(n) for n in names)
        assert b"content one" in joined and b"content two" in joined

    def test_empty_selection(self, initialized_app):
        data, filename = ex._build_eml_zip([])
        assert data == b"" and filename == "export.zip"

    def test_skips_missing_files(self, initialized_app):
        fid = _make_folder("Clients")
        present = _make_message(fid, subject="Here")
        missing = _make_message(fid, subject="Gone", write_file=False)
        data, _ = ex._build_eml_zip([present, missing])
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            assert len(zf.namelist()) == 1

    def test_duplicate_subjects_deduped(self, initialized_app):
        fid = _make_folder("Clients")
        a = _make_message(fid, subject="Same Subject")
        b = _make_message(fid, subject="Same Subject")
        data, _ = ex._build_eml_zip([a, b])
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
        assert len(names) == 2 and len(set(names)) == 2

    def test_encrypted_zip_decrypts_with_password(self, initialized_app):
        fid = _make_folder("Clients")
        _make_message(fid, subject="Confidential", body="privileged material")
        ids = ex._message_ids_in_folders([fid])
        data, _ = ex._build_encrypted_eml_zip(ids, "Corr3ctHorse!")
        with pyzipper.AESZipFile(io.BytesIO(data)) as zf:
            zf.setpassword(b"Corr3ctHorse!")
            name = zf.namelist()[0]
            assert b"privileged material" in zf.read(name)

    def test_encrypted_zip_rejects_wrong_password(self, initialized_app):
        fid = _make_folder("Clients")
        _make_message(fid, subject="Confidential", body="privileged material")
        ids = ex._message_ids_in_folders([fid])
        data, _ = ex._build_encrypted_eml_zip(ids, "RightPassword")
        with pyzipper.AESZipFile(io.BytesIO(data)) as zf:
            zf.setpassword(b"WrongPassword")
            with pytest.raises(Exception):
                zf.read(zf.namelist()[0])

    def test_encrypt_to_zip_wraps_bytes(self, initialized_app):
        data = ex._encrypt_to_zip(b"raw payload", "payload.bin", "zippw")
        with pyzipper.AESZipFile(io.BytesIO(data)) as zf:
            zf.setpassword(b"zippw")
            assert zf.read("payload.bin") == b"raw payload"


# ---------------------------------------------------------------------------
# Worker + HTTP endpoints
# ---------------------------------------------------------------------------

class TestRunExportJob:
    def test_eml_job_end_to_end(self, initialized_app):
        fid = _make_folder("Clients")
        _make_message(fid, subject="One", body="alpha body")
        _make_message(fid, subject="Two", body="beta body")
        job_id = ex._new_job()
        payload = {
            "selection": {"source": "folder", "folder_id": fid, "include_subfolders": True},
            "format": "eml",
        }
        ex._run_export_job(job_id, payload)
        job = ex._get_job(job_id)
        assert job["status"] == "done"
        with zipfile.ZipFile(io.BytesIO(job["result_bytes"])) as zf:
            assert len(zf.namelist()) == 2

    def test_empty_selection_fails_job(self, initialized_app):
        fid = _make_folder("Empty")
        job_id = ex._new_job()
        ex._run_export_job(job_id, {"selection": {"source": "folder", "folder_id": fid}, "format": "eml"})
        job = ex._get_job(job_id)
        assert job["status"] == "failed"
        assert "no emails" in job["error"].lower()

    def test_unknown_format_fails_job(self, initialized_app):
        fid = _make_folder("F")
        _make_message(fid)
        job_id = ex._new_job()
        ids_payload = {"selection": {"source": "folder", "folder_id": fid}, "format": "xml"}
        ex._run_export_job(job_id, ids_payload)
        assert ex._get_job(job_id)["status"] == "failed"


class TestExportEndpoints:
    def test_start_requires_selection(self, authenticated_client, initialized_app):
        resp = authenticated_client.post("/api/export/start", json={"format": "eml"})
        assert resp.status_code == 400

    def test_start_rejects_bad_format(self, authenticated_client, initialized_app):
        resp = authenticated_client.post(
            "/api/export/start",
            json={"selection": {"source": "messages", "message_ids": [1]}, "format": "xml"},
        )
        assert resp.status_code == 400

    def test_start_returns_job_id(self, authenticated_client, initialized_app, monkeypatch):
        # Stub the worker so no background thread does real work during the test
        monkeypatch.setattr(ex, "_run_export_job", lambda *a, **k: None)
        resp = authenticated_client.post(
            "/api/export/start",
            json={"selection": {"source": "messages", "message_ids": [1]}, "format": "eml"},
        )
        assert resp.status_code == 200
        assert "job_id" in resp.get_json()

    def test_download_unknown_job(self, authenticated_client, initialized_app):
        resp = authenticated_client.get("/api/export/download/nope")
        assert resp.status_code == 404

    def test_download_running_job_conflicts(self, authenticated_client, initialized_app):
        job_id = ex._new_job()  # status "running"
        resp = authenticated_client.get(f"/api/export/download/{job_id}")
        assert resp.status_code == 409

    def test_download_done_job_streams_bytes(self, authenticated_client, initialized_app):
        job_id = ex._new_job()
        ex._finish_job(job_id, result_bytes=b"the-zip-bytes",
                       result_mimetype="application/zip", result_filename="x.zip", summary={})
        resp = authenticated_client.get(f"/api/export/download/{job_id}")
        assert resp.status_code == 200
        assert resp.data == b"the-zip-bytes"

    def test_cancel_drops_job(self, authenticated_client, initialized_app):
        job_id = ex._new_job()
        resp = authenticated_client.post(f"/api/export/cancel/{job_id}")
        assert resp.status_code == 200
        assert ex._get_job(job_id) is None

    def test_reveal_requires_path(self, authenticated_client, initialized_app):
        resp = authenticated_client.post("/api/export/reveal", json={})
        assert resp.status_code == 400

    def test_reveal_rejects_unknown_path(self, authenticated_client, initialized_app):
        # A path not matching any job's saved_path must be refused (security)
        resp = authenticated_client.post(
            "/api/export/reveal", json={"path": "/etc/passwd"}
        )
        assert resp.status_code == 403
