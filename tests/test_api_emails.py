"""
Tests for web/blueprints/api/emails.py - Archived email API.

Covers search (FTS, folder scoping, subfolder toggle), folder email
listing, the full-content viewer (real encrypted .eml round-trip),
soft-delete/restore/permanent-delete, flagging, move, and the trash
listing. Messages are seeded with genuine AES-256-GCM-encrypted files on
disk so the decrypt-and-parse path in the viewer is exercised for real,
not mocked.
"""

import secrets

import pytest

from core import Database, Config, Encryption


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------

def _make_folder(name, parent_id=None):
    cur = Database.execute(
        "INSERT INTO folders (name, parent_id) VALUES (?, ?)", (name, parent_id)
    )
    Database.commit()
    return cur.lastrowid


def _make_message(folder_id, subject="Quarterly Report", sender="alice@example.com",
                  recipients="bob@example.com", body="The widget revenue figures are attached.",
                  message_id=None, flagged_at=None):
    """Insert a message backed by a real encrypted .eml.enc file on disk."""
    mid = message_id or f"<{secrets.token_hex(8)}@test>"
    raw = (
        f"From: {sender}\r\n"
        f"To: {recipients}\r\n"
        f"Subject: {subject}\r\n"
        f"Message-ID: {mid}\r\n"
        f"Date: Sat, 15 Feb 2026 10:30:00 -0500\r\n"
        f'MIME-Version: 1.0\r\n'
        f'Content-Type: text/plain; charset="utf-8"\r\n\r\n'
        f"{body}\r\n"
    ).encode()

    archive_path = Config.get_archive_path() / str(folder_id)
    archive_path.mkdir(parents=True, exist_ok=True)
    fp = archive_path / f"{secrets.token_hex(6)}.eml.enc"
    fp.write_bytes(Encryption.encrypt(raw))
    rel = str(fp.relative_to(Config.get_base_path()))

    cur = Database.execute(
        """INSERT INTO messages
           (folder_id, message_id, subject, sender, recipients, date, filepath, body_text, flagged_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (folder_id, mid, subject, sender, recipients, 1739633400, rel, body, flagged_at),
    )
    Database.commit()
    return cur.lastrowid


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

class TestEmailSearch:
    def test_search_requires_query(self, authenticated_client, initialized_app):
        resp = authenticated_client.get("/api/search?q=")
        assert resp.status_code == 400
        assert "required" in resp.get_json()["error"].lower()

    def test_search_finds_by_subject(self, authenticated_client, initialized_app):
        fid = _make_folder("Clients")
        _make_message(fid, subject="Invoice for catering job")
        resp = authenticated_client.get("/api/search?q=catering")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] == 1
        assert "catering" in data["emails"][0]["subject"].lower()

    def test_search_finds_by_body(self, authenticated_client, initialized_app):
        fid = _make_folder("Clients")
        _make_message(fid, subject="Misc", body="discussion of the deposition schedule")
        resp = authenticated_client.get("/api/search?q=deposition")
        assert resp.status_code == 200
        assert resp.get_json()["count"] == 1

    def test_search_excludes_trashed(self, authenticated_client, initialized_app):
        fid = _make_folder("Clients")
        mid = _make_message(fid, subject="findme please")
        authenticated_client.delete(f"/api/messages/{mid}")
        resp = authenticated_client.get("/api/search?q=findme")
        assert resp.get_json()["count"] == 0

    def test_search_scoped_to_folder(self, authenticated_client, initialized_app):
        f1 = _make_folder("Folder One")
        f2 = _make_folder("Folder Two")
        _make_message(f1, subject="shared keyword alpha")
        _make_message(f2, subject="shared keyword beta")
        resp = authenticated_client.get(f"/api/search?q=keyword&folder_id={f1}")
        data = resp.get_json()
        assert data["count"] == 1
        assert data["emails"][0]["folder_id"] == f1

    def test_search_subfolder_toggle(self, authenticated_client, initialized_app):
        parent = _make_folder("Parent")
        child = _make_folder("Child", parent_id=parent)
        _make_message(parent, subject="topic in parent")
        _make_message(child, subject="topic in child")
        # Default includes descendants
        resp = authenticated_client.get(f"/api/search?q=topic&folder_id={parent}")
        assert resp.get_json()["count"] == 2
        # Excluding subfolders limits to the parent itself
        resp = authenticated_client.get(
            f"/api/search?q=topic&folder_id={parent}&include_subfolders=false"
        )
        assert resp.get_json()["count"] == 1


# ---------------------------------------------------------------------------
# Folder email listing + full-content viewer
# ---------------------------------------------------------------------------

class TestFolderEmails:
    def test_list_emails_folder_not_found(self, authenticated_client, initialized_app):
        resp = authenticated_client.get("/api/folders/9999/emails")
        assert resp.status_code == 404

    def test_list_emails_excludes_deleted(self, authenticated_client, initialized_app):
        fid = _make_folder("Clients")
        keep = _make_message(fid, subject="Keep me")
        gone = _make_message(fid, subject="Trash me")
        authenticated_client.delete(f"/api/messages/{gone}")
        resp = authenticated_client.get(f"/api/folders/{fid}/emails")
        ids = [e["id"] for e in resp.get_json()["emails"]]
        assert keep in ids and gone not in ids


class TestArchivedEmailView:
    def test_view_not_found(self, authenticated_client, initialized_app):
        fid = _make_folder("Clients")
        resp = authenticated_client.get(f"/api/folders/{fid}/emails/9999")
        assert resp.status_code == 404

    def test_view_decrypts_and_parses(self, authenticated_client, initialized_app):
        fid = _make_folder("Clients")
        mid = _make_message(
            fid, subject="Settlement terms", sender="lawyer@firm.example",
            recipients="client@example.com", body="Please review the attached terms.",
        )
        resp = authenticated_client.get(f"/api/folders/{fid}/emails/{mid}")
        assert resp.status_code == 200
        email = resp.get_json()["email"]
        assert email["subject"] == "Settlement terms"
        assert "lawyer@firm.example" in email["from"]
        assert "review the attached terms" in email["text_body"]

    def test_source_round_trip(self, authenticated_client, initialized_app):
        fid = _make_folder("Clients")
        mid = _make_message(fid, subject="Raw source check", body="unique-body-marker-42")
        resp = authenticated_client.get(f"/api/folders/{fid}/emails/{mid}/source")
        assert resp.status_code == 200
        assert "unique-body-marker-42" in resp.get_json()["source"]


# ---------------------------------------------------------------------------
# Soft delete / restore / permanent delete
# ---------------------------------------------------------------------------

class TestSoftDelete:
    def test_delete_not_found(self, authenticated_client, initialized_app):
        resp = authenticated_client.delete("/api/messages/9999")
        assert resp.status_code == 404

    def test_soft_delete_detaches_and_trashes(self, authenticated_client, initialized_app):
        fid = _make_folder("Clients")
        mid = _make_message(fid, subject="Bye")
        resp = authenticated_client.delete(f"/api/messages/{mid}")
        assert resp.status_code == 200 and resp.get_json()["success"] is True

        # folder_id detached -> NULL, original_folder_id preserved, deleted_at set
        row = Database.fetchone(
            "SELECT folder_id, original_folder_id, deleted_at FROM messages WHERE id = ?", (mid,)
        )
        assert row["folder_id"] is None
        assert row["original_folder_id"] == fid
        assert row["deleted_at"] is not None

        # Shows up in trash listing with the original location preserved
        trash = authenticated_client.get("/api/trash/emails").get_json()["emails"]
        entry = next(e for e in trash if e["id"] == mid)
        assert entry["folder_id"] == fid
        assert entry["original_folder_unavailable"] is False


class TestRestore:
    def test_restore_not_found(self, authenticated_client, initialized_app):
        resp = authenticated_client.post("/api/messages/9999/restore")
        assert resp.status_code == 404

    def test_restore_requires_trashed(self, authenticated_client, initialized_app):
        fid = _make_folder("Clients")
        mid = _make_message(fid)
        resp = authenticated_client.post(f"/api/messages/{mid}/restore")
        assert resp.status_code == 400

    def test_restore_to_original_folder(self, authenticated_client, initialized_app):
        fid = _make_folder("Clients")
        mid = _make_message(fid)
        authenticated_client.delete(f"/api/messages/{mid}")
        resp = authenticated_client.post(f"/api/messages/{mid}/restore")
        assert resp.status_code == 200
        assert resp.get_json()["folder_id"] == fid
        row = Database.fetchone(
            "SELECT folder_id, deleted_at, original_folder_id FROM messages WHERE id = ?", (mid,)
        )
        assert row["folder_id"] == fid
        assert row["deleted_at"] is None
        assert row["original_folder_id"] is None

    def test_restore_needs_destination_when_original_gone(self, authenticated_client, initialized_app):
        fid = _make_folder("Temp")
        mid = _make_message(fid)
        authenticated_client.delete(f"/api/messages/{mid}")
        # Permanently remove the original folder so restore has nowhere to go
        Database.execute("DELETE FROM folders WHERE id = ?", (fid,))
        Database.commit()
        resp = authenticated_client.post(f"/api/messages/{mid}/restore")
        assert resp.status_code == 409
        assert resp.get_json()["needs_destination"] is True

    def test_restore_to_chosen_destination(self, authenticated_client, initialized_app):
        src = _make_folder("Source")
        dest = _make_folder("Destination")
        mid = _make_message(src)
        authenticated_client.delete(f"/api/messages/{mid}")
        resp = authenticated_client.post(
            f"/api/messages/{mid}/restore", json={"folder_id": dest}
        )
        assert resp.status_code == 200
        assert resp.get_json()["folder_id"] == dest


class TestPermanentDelete:
    def test_permanent_delete_not_found(self, authenticated_client, initialized_app):
        resp = authenticated_client.delete("/api/messages/9999/permanent")
        assert resp.status_code == 404

    def test_permanent_delete_requires_trash(self, authenticated_client, initialized_app):
        fid = _make_folder("Clients")
        mid = _make_message(fid)
        resp = authenticated_client.delete(f"/api/messages/{mid}/permanent")
        assert resp.status_code == 400

    def test_permanent_delete_removes_row_and_file(self, authenticated_client, initialized_app):
        fid = _make_folder("Clients")
        mid = _make_message(fid)
        rel = Database.fetchone("SELECT filepath FROM messages WHERE id = ?", (mid,))["filepath"]
        fp = Config.get_base_path() / rel
        assert fp.exists()
        authenticated_client.delete(f"/api/messages/{mid}")
        resp = authenticated_client.delete(f"/api/messages/{mid}/permanent")
        assert resp.status_code == 200
        assert Database.fetchone("SELECT id FROM messages WHERE id = ?", (mid,)) is None
        assert not fp.exists()


# ---------------------------------------------------------------------------
# Flagging + move
# ---------------------------------------------------------------------------

class TestFlagging:
    def test_flag_not_found(self, authenticated_client, initialized_app):
        resp = authenticated_client.patch("/api/messages/9999/flag", json={"flagged": True})
        assert resp.status_code == 404

    def test_flag_requires_field(self, authenticated_client, initialized_app):
        fid = _make_folder("Clients")
        mid = _make_message(fid)
        resp = authenticated_client.patch(f"/api/messages/{mid}/flag", json={})
        assert resp.status_code == 400

    def test_flag_set_and_clear(self, authenticated_client, initialized_app):
        fid = _make_folder("Clients")
        mid = _make_message(fid)
        resp = authenticated_client.patch(f"/api/messages/{mid}/flag", json={"flagged": True})
        assert resp.status_code == 200
        assert resp.get_json()["flagged_at"] is not None
        resp = authenticated_client.patch(f"/api/messages/{mid}/flag", json={"flagged": False})
        assert resp.get_json()["flagged_at"] is None

    def test_flagged_list_excludes_trashed(self, authenticated_client, initialized_app):
        fid = _make_folder("Clients")
        keep = _make_message(fid, flagged_at=1739633400)
        gone = _make_message(fid, flagged_at=1739633400)
        authenticated_client.delete(f"/api/messages/{gone}")
        resp = authenticated_client.get("/api/messages/flagged")
        ids = [e["id"] for e in resp.get_json()["emails"]]
        assert keep in ids and gone not in ids


class TestMoveMessage:
    def test_move_message_not_found(self, authenticated_client, initialized_app):
        resp = authenticated_client.patch("/api/messages/9999", json={"folder_id": 1})
        assert resp.status_code == 404

    def test_move_to_missing_folder(self, authenticated_client, initialized_app):
        fid = _make_folder("Clients")
        mid = _make_message(fid)
        resp = authenticated_client.patch(f"/api/messages/{mid}", json={"folder_id": 9999})
        assert resp.status_code == 404

    def test_move_updates_folder(self, authenticated_client, initialized_app):
        src = _make_folder("Source")
        dest = _make_folder("Destination")
        mid = _make_message(src)
        resp = authenticated_client.patch(f"/api/messages/{mid}", json={"folder_id": dest})
        assert resp.status_code == 200
        row = Database.fetchone("SELECT folder_id FROM messages WHERE id = ?", (mid,))
        assert row["folder_id"] == dest
