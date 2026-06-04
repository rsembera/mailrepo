"""
Tests for web/blueprints/api/threads.py - thread discovery API.

POST /api/threads/find connects to a live IMAP server to walk a
conversation, so the happy path is out of scope per the coverage plan.
What is covered is the request-validation boundary that runs *before*
any connection is attempted: required/typed fields, unknown account,
and an account with no stored credentials. These guard the IMAP layer
from malformed input.
"""

from core import Database


def _make_account(with_creds=False):
    cur = Database.execute(
        "INSERT INTO accounts (name, email, provider) VALUES (?, ?, ?)",
        ("Acct", "user@example.com", "imap"),
    )
    Database.commit()
    aid = cur.lastrowid
    if with_creds:
        Database.execute(
            "UPDATE accounts SET credentials_encrypted = ? WHERE id = ?",
            ("not-real-but-present", aid),
        )
        Database.commit()
    return aid


class TestFindThreadValidation:
    def test_account_id_required(self, authenticated_client, initialized_app):
        resp = authenticated_client.post("/api/threads/find", json={"folder": "INBOX", "uid": "5"})
        assert resp.status_code == 400
        assert "account_id" in resp.get_json()["error"]

    def test_account_id_must_be_int(self, authenticated_client, initialized_app):
        resp = authenticated_client.post(
            "/api/threads/find", json={"account_id": "abc", "folder": "INBOX", "uid": "5"}
        )
        assert resp.status_code == 400

    def test_folder_required(self, authenticated_client, initialized_app):
        resp = authenticated_client.post("/api/threads/find", json={"account_id": 1, "uid": "5"})
        assert resp.status_code == 400
        assert "folder" in resp.get_json()["error"]

    def test_uid_required(self, authenticated_client, initialized_app):
        resp = authenticated_client.post(
            "/api/threads/find", json={"account_id": 1, "folder": "INBOX"}
        )
        assert resp.status_code == 400
        assert "uid" in resp.get_json()["error"]

    def test_account_not_found(self, authenticated_client, initialized_app):
        resp = authenticated_client.post(
            "/api/threads/find", json={"account_id": 9999, "folder": "INBOX", "uid": "5"}
        )
        assert resp.status_code == 404

    def test_account_without_credentials(self, authenticated_client, initialized_app):
        aid = _make_account(with_creds=False)
        resp = authenticated_client.post(
            "/api/threads/find", json={"account_id": aid, "folder": "INBOX", "uid": "5"}
        )
        assert resp.status_code == 400
        assert "credentials" in resp.get_json()["error"].lower()
