"""
Code review 2026-11: the IMAP folder listing must match the server.

Finding 8: a folder emptied on the server kept showing its cached
messages, because stale-entry removal returned early on an empty list.
"""

import json

from core import IMAP, Database, ImapPool
from web.blueprints.api.streaming import cache_email, remove_stale_cache_entries


class _Client:
    host = "imap.example.com"

    def __init__(self, uids):
        self.uids = uids

    def select_folder(self, folder="INBOX"):
        return {
            "folder": folder,
            "message_count": len(self.uids),
            "uidvalidity": 7,
            "highestmodseq": None,
        }

    def search(self, criteria="ALL", limit=0):
        return list(self.uids)

    def fetch_headers_batch(self, chunk):
        return [
            {"uid": u, "subject": f"s{u}", "from": "", "to": "", "date": "", "message_id": ""}
            for u in chunk
        ]

    def release(self):
        pass


def _account():
    cur = Database.execute(
        "INSERT INTO accounts (name, email, provider) VALUES ('A', 'a@example.com', 'imap')"
    )
    Database.commit()
    IMAP.save_credentials(cur.lastrowid, "a@example.com", "pw", "imap.example.com", 993, True)
    return cur.lastrowid


def _cache(account_id, uids):
    for u in uids:
        cache_email(
            account_id,
            "INBOX",
            7,
            {"uid": u, "subject": "s", "from": "", "to": "", "date": "", "message_id": ""},
        )
    Database.commit()


def _final_listing(client, account_id):
    resp = client.get(f"/api/accounts/{account_id}/emails/stream?folder=INBOX&refresh=true")
    events = [
        json.loads(line[5:]) for line in resp.data.decode().split("\n") if line[:5] == "data:"
    ]
    return [e for e in events if "emails" in e and "fetched" in e][-1]


def test_folder_emptied_on_the_server_shows_empty(
    authenticated_client, initialized_app, monkeypatch
):
    account_id = _account()
    _cache(account_id, ["1", "2", "3"])
    monkeypatch.setattr(ImapPool, "acquire", classmethod(lambda cls, a, c: _Client([])))

    final = _final_listing(authenticated_client, account_id)
    assert final["total"] == 0
    assert Database.fetchone("SELECT COUNT(*) AS c FROM email_cache")["c"] == 0


def test_stale_removal_handles_many_uids(initialized_app):
    account_id = _account()
    _cache(account_id, [str(i) for i in range(1, 1301)])
    removed = remove_stale_cache_entries(account_id, "INBOX", 7, ["1", "2"])
    assert removed == 1298
    assert Database.fetchone("SELECT COUNT(*) AS c FROM email_cache")["c"] == 2
