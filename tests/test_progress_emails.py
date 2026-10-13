"""
Tests for the folder-listing stream (web/blueprints/api/progress_emails.py):
cache survival across refresh, incremental fetch, and the explicit rebuild.
"""

import json

import pytest

from core import Database, sync_cache
from web.blueprints.api.streaming import cache_email, get_cached_emails


def _parse_sse(text):
    events = []
    for block in text.strip().split("\n\n"):
        event = data = None
        for line in block.split("\n"):
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if event:
            events.append((event, data))
    return events


class _FakeImap:
    """Server with UIDs 1-4 present; 9 was cached earlier but is gone."""

    host = "imap.example.com"

    def __init__(self, modseq=7):
        self.modseq = modseq
        self.fetched = []

    def select_folder(self, name):
        return {"folder": name, "uidvalidity": 42, "highestmodseq": self.modseq}

    def search(self, criteria="ALL", limit=0):
        return ["4", "3", "2", "1"]

    def fetch_headers_batch(self, uids):
        self.fetched.append(list(uids))
        return [
            {"uid": u, "subject": f"s{u}", "from": "", "to": "", "date": "", "message_id": f"<{u}>"}
            for u in uids
        ]

    def disconnect(self):
        pass


@pytest.fixture
def account(initialized_app):
    Database.execute(
        "INSERT INTO accounts (name, email, provider, credentials_encrypted) VALUES (?, ?, ?, ?)",
        ("Acct", "a@example.com", "imap", "not-real"),
    )
    Database.commit()
    return Database.fetchone("SELECT id FROM accounts WHERE email = 'a@example.com'")["id"]


@pytest.fixture
def seeded(account):
    for uid in ("1", "2", "3", "9"):
        cache_email(account, "INBOX", 42, {"uid": uid, "subject": f"old{uid}"})
    Database.commit()
    sync_cache.update_folder_sync_state(account, "INBOX", 42, 7)
    return account


def _stream(client, monkeypatch, account, fake, query=""):
    from core.imap import IMAP

    monkeypatch.setattr(IMAP, "connect_with_credentials", classmethod(lambda cls, c: fake))
    resp = client.get(f"/api/accounts/{account}/emails/stream?folder=INBOX{query}")
    return _parse_sse(resp.get_data(as_text=True))


class TestRefreshIsIncremental:
    def test_fresh_ttl_serves_cache_without_network(
        self, authenticated_client, seeded, monkeypatch
    ):
        fake = _FakeImap()
        events = _stream(authenticated_client, monkeypatch, seeded, fake)
        assert events[-1][0] == "complete"
        assert events[-1][1]["fetched"] == 0 and fake.fetched == []

    def test_refresh_keeps_cache_and_fetches_only_new(
        self, authenticated_client, seeded, monkeypatch
    ):
        fake = _FakeImap()
        events = _stream(authenticated_client, monkeypatch, seeded, fake, "&refresh=true")
        done = events[-1][1]
        assert fake.fetched == [["4"]], "only the UID above the cached high-water mark"
        assert done["fetched"] == 1
        uids = sorted(e["uid"] for e in get_cached_emails(seeded, "INBOX", 42))
        assert uids == ["1", "2", "3", "4"], "stale 9 dropped, 1-3 kept, 4 added"
        assert [e["uid"] for e in done["emails"]] == ["4", "3", "2", "1"]

    def test_rebuild_discards_cache_and_refetches_all(
        self, authenticated_client, seeded, monkeypatch
    ):
        fake = _FakeImap()
        _stream(authenticated_client, monkeypatch, seeded, fake, "&rebuild=true")
        assert fake.fetched == [["4", "3", "2", "1"]]
        uids = sorted(e["uid"] for e in get_cached_emails(seeded, "INBOX", 42))
        assert uids == ["1", "2", "3", "4"]

    def test_unchanged_modseq_short_circuits_after_ttl(
        self, authenticated_client, seeded, monkeypatch
    ):
        sync_cache.update_folder_sync_state(seeded, "INBOX", 42, 7)
        # Expire the TTL without touching the server markers.
        conn = sync_cache._get_connection()
        conn.execute("UPDATE folder_sync_state SET last_synced_at = last_synced_at - 10000")
        conn.commit()
        fake = _FakeImap(modseq=7)
        events = _stream(authenticated_client, monkeypatch, seeded, fake)
        assert fake.fetched == [] and events[-1][1]["fetched"] == 0


class TestCacheFirst:
    def test_cached_event_precedes_server_check(self, authenticated_client, seeded, monkeypatch):
        fake = _FakeImap()
        events = _stream(authenticated_client, monkeypatch, seeded, fake, "&refresh=true")
        names = [e for e, _ in events]
        assert names[0] == "cached"
        assert names.index("cached") < names.index("status")
        assert sorted(x["uid"] for x in events[0][1]["emails"]) == ["1", "2", "3", "9"]
        assert names[-1] == "complete"

    def test_rebuild_skips_cached_event(self, authenticated_client, seeded, monkeypatch):
        fake = _FakeImap()
        events = _stream(authenticated_client, monkeypatch, seeded, fake, "&rebuild=true")
        assert "cached" not in [e for e, _ in events]

    def test_empty_cache_sends_no_cached_event(self, authenticated_client, account, monkeypatch):
        fake = _FakeImap()
        events = _stream(authenticated_client, monkeypatch, account, fake)
        names = [e for e, _ in events]
        assert "cached" not in names and names[-1] == "complete"
