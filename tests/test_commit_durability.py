"""
Code review 2026-11, finding 3: nothing is removed from the server while
archive rows are still uncommitted.
"""

import json

from core import IMAP, Database, ImapPool


class _Client:
    host = "imap.example.com"

    def __init__(self, raws):
        self.raws = raws
        self.open_transaction_at_delete = []

    def select_folder(self, folder="INBOX"):
        return {"folder": folder, "message_count": len(self.raws), "uidvalidity": 7}

    def search(self, criteria="ALL", limit=0):
        return sorted(self.raws, key=int, reverse=True)

    def fetch_raw(self, uid):
        return self.raws[str(uid)]

    def delete_email(self, uid):
        self.open_transaction_at_delete.append(Database.get_connection().in_transaction)

    def release(self):
        pass


def test_folder_rows_are_committed_before_the_server_delete(
    authenticated_client, initialized_app, monkeypatch
):
    cur = Database.execute(
        "INSERT INTO accounts (name, email, provider) VALUES ('A', 'a@example.com', 'imap')"
    )
    account_id = cur.lastrowid
    Database.execute("INSERT INTO folders (id, name) VALUES (1, 'Dest')")
    Database.commit()
    IMAP.save_credentials(account_id, "a@example.com", "pw", "imap.example.com", 993, True)

    # Seven messages: commit_imap_folder only commits on every tenth.
    raws = {
        str(i): f"Message-ID: <{i}@x>\r\nSubject: s{i}\r\n\r\nbody {i}\r\n".encode()
        for i in range(1, 8)
    }
    client = _Client(raws)
    monkeypatch.setattr(ImapPool, "acquire", classmethod(lambda cls, a, c: client))

    resp = authenticated_client.post(
        "/api/commit/stream",
        data=json.dumps(
            {
                "staged": [],
                "folders": [
                    {
                        "sourceType": "imap",
                        "accountId": account_id,
                        "folder": "INBOX",
                        "archivePath": "Inbox",
                        "destinationFolderId": 1,
                    }
                ],
                "sourceActions": {f"account:{account_id}:1": "delete"},
            }
        ),
        content_type="application/json",
    )
    assert resp.status_code == 200
    resp.get_data()  # drain the stream

    assert len(client.open_transaction_at_delete) == 7, "post-action should have run"
    assert not any(client.open_transaction_at_delete), (
        "server deletes began with archive rows still uncommitted"
    )
    assert Database.fetchone("SELECT COUNT(*) AS c FROM messages")["c"] == 7
