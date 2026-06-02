"""
Tests for web/blueprints/api/accounts.py - IMAP account API.

Network-touching paths (test_connection, live fetch, live folder list)
are intentionally out of scope here per the coverage plan. What IS
covered without a network: account CRUD validation, the runtime
``is_gmail`` detection (derived by decrypting stored credentials and
inspecting the host), the no-password update path, the cached-folder
fast path that returns without connecting, deletion, and server
auto-detection from the email domain.
"""

import json

import pytest

from core import Database
from core import IMAP


def _make_account(name="Work", email="user@example.com", provider="imap",
                  host=None, password="secret", cached_folders=None):
    """Insert an account row; optionally attach encrypted credentials and/or
    a cached folder list."""
    cur = Database.execute(
        "INSERT INTO accounts (name, email, provider) VALUES (?, ?, ?)",
        (name, email, provider),
    )
    Database.commit()
    account_id = cur.lastrowid
    if host is not None:
        IMAP.save_credentials(account_id, email, password, host, 993, True)
    if cached_folders is not None:
        Database.execute(
            "UPDATE accounts SET cached_folders = ? WHERE id = ?",
            (json.dumps(cached_folders), account_id),
        )
        Database.commit()
    return account_id


# ---------------------------------------------------------------------------
# Listing + is_gmail detection
# ---------------------------------------------------------------------------

class TestListAccounts:
    def test_list_empty(self, authenticated_client, initialized_app):
        resp = authenticated_client.get("/api/accounts")
        assert resp.status_code == 200
        assert resp.get_json()["accounts"] == []

    def test_list_returns_accounts(self, authenticated_client, initialized_app):
        _make_account(name="Alpha", email="a@example.com")
        _make_account(name="Beta", email="b@example.com")
        resp = authenticated_client.get("/api/accounts")
        names = sorted(a["name"] for a in resp.get_json()["accounts"])
        assert names == ["Alpha", "Beta"]

    def test_is_gmail_true_for_gmail_host(self, authenticated_client, initialized_app):
        _make_account(email="me@gmail.com", host="imap.gmail.com")
        acct = authenticated_client.get("/api/accounts").get_json()["accounts"][0]
        assert acct["is_gmail"] is True

    def test_is_gmail_false_for_other_host(self, authenticated_client, initialized_app):
        _make_account(email="me@fastmail.com", host="imap.fastmail.com")
        acct = authenticated_client.get("/api/accounts").get_json()["accounts"][0]
        assert acct["is_gmail"] is False

    def test_is_gmail_false_without_credentials(self, authenticated_client, initialized_app):
        _make_account(email="me@example.com", host=None)
        acct = authenticated_client.get("/api/accounts").get_json()["accounts"][0]
        assert acct["is_gmail"] is False


# ---------------------------------------------------------------------------
# Create + update validation
# ---------------------------------------------------------------------------

class TestCreateAccountValidation:
    def test_create_requires_name(self, authenticated_client, initialized_app):
        resp = authenticated_client.post("/api/accounts", json={})
        assert resp.status_code == 400
        assert "name" in resp.get_json()["error"].lower()

    def test_create_requires_email(self, authenticated_client, initialized_app):
        resp = authenticated_client.post("/api/accounts", json={"name": "X"})
        assert resp.status_code == 400
        assert "email" in resp.get_json()["error"].lower()

    def test_create_requires_password(self, authenticated_client, initialized_app):
        resp = authenticated_client.post(
            "/api/accounts", json={"name": "X", "email": "x@example.com"}
        )
        assert resp.status_code == 400
        assert "password" in resp.get_json()["error"].lower()


class TestUpdateAccount:
    def test_update_not_found(self, authenticated_client, initialized_app):
        resp = authenticated_client.patch("/api/accounts/9999", json={"name": "X", "email": "x@e.com"})
        assert resp.status_code == 404

    def test_update_requires_name(self, authenticated_client, initialized_app):
        aid = _make_account()
        resp = authenticated_client.patch(f"/api/accounts/{aid}", json={"name": "", "email": "x@e.com"})
        assert resp.status_code == 400

    def test_update_requires_email(self, authenticated_client, initialized_app):
        aid = _make_account()
        resp = authenticated_client.patch(f"/api/accounts/{aid}", json={"name": "X", "email": ""})
        assert resp.status_code == 400

    def test_update_without_password_changes_name_and_email(self, authenticated_client, initialized_app):
        aid = _make_account(name="Old Name", email="old@example.com")
        resp = authenticated_client.patch(
            f"/api/accounts/{aid}", json={"name": "New Name", "email": "new@example.com"}
        )
        assert resp.status_code == 200
        assert "unchanged" in resp.get_json()["message"].lower()
        row = Database.fetchone("SELECT name, email FROM accounts WHERE id = ?", (aid,))
        assert row["name"] == "New Name"
        assert row["email"] == "new@example.com"


class TestTestConnectionGuards:
    def test_test_connection_not_found(self, authenticated_client, initialized_app):
        resp = authenticated_client.post("/api/accounts/9999/test")
        assert resp.status_code == 404

    def test_test_connection_no_credentials(self, authenticated_client, initialized_app):
        aid = _make_account(host=None)
        resp = authenticated_client.post(f"/api/accounts/{aid}/test")
        assert resp.status_code == 400
        assert "credentials" in resp.get_json()["error"].lower()


# ---------------------------------------------------------------------------
# Folder cache fast-path, email guards, delete, server detection
# ---------------------------------------------------------------------------

class TestAccountEmailGuards:
    def test_emails_account_not_found(self, authenticated_client, initialized_app):
        resp = authenticated_client.get("/api/accounts/9999/emails")
        assert resp.status_code == 404

    def test_emails_no_credentials(self, authenticated_client, initialized_app):
        aid = _make_account(host=None)
        resp = authenticated_client.get(f"/api/accounts/{aid}/emails")
        assert resp.status_code == 401


class TestFolderCache:
    def test_folders_not_found(self, authenticated_client, initialized_app):
        resp = authenticated_client.get("/api/accounts/9999/folders")
        assert resp.status_code == 404

    def test_folders_served_from_cache_without_imap(self, authenticated_client, initialized_app):
        # cached_folders present with the "noselect" field -> returned as-is,
        # no IMAP connection attempted.
        cached = [{"name": "INBOX", "noselect": False}, {"name": "Sent", "noselect": False}]
        aid = _make_account(host="imap.gmail.com", cached_folders=cached)
        resp = authenticated_client.get(f"/api/accounts/{aid}/folders")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["cached"] is True
        assert [f["name"] for f in data["folders"]] == ["INBOX", "Sent"]


class TestDeleteAccount:
    def test_delete_not_found(self, authenticated_client, initialized_app):
        resp = authenticated_client.delete("/api/accounts/9999")
        assert resp.status_code == 404

    def test_delete_removes_account(self, authenticated_client, initialized_app):
        aid = _make_account()
        resp = authenticated_client.delete(f"/api/accounts/{aid}")
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True
        assert Database.fetchone("SELECT id FROM accounts WHERE id = ?", (aid,)) is None


class TestDetectServer:
    def test_detect_requires_email(self, authenticated_client, initialized_app):
        resp = authenticated_client.post("/api/accounts/detect-server", json={"email": ""})
        assert resp.status_code == 400

    def test_detect_known_provider(self, authenticated_client, initialized_app):
        resp = authenticated_client.post(
            "/api/accounts/detect-server", json={"email": "someone@gmail.com"}
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["detected"] is True
        assert data["host"] == "imap.gmail.com"
        assert data["port"] == 993

    def test_detect_unknown_provider(self, authenticated_client, initialized_app):
        resp = authenticated_client.post(
            "/api/accounts/detect-server", json={"email": "someone@unknown-domain-xyz.test"}
        )
        assert resp.status_code == 200
        assert resp.get_json()["detected"] is False
