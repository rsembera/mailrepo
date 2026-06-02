"""
Tests for core/sync_cache.py and the pure IMAP.detect_server helper.

These are the cheap, connection-free pieces of the IMAP layer (the
connect/fetch machinery itself is Tier 4 / dogfooding territory). The
sync cache governs how often MailRepo re-hits an IMAP server, so its TTL
and state round-trip are worth pinning. detect_server is a pure
domain->server lookup.
"""

import time

import pytest

from core import sync_cache
from core.imap import IMAP


@pytest.fixture(autouse=True)
def _fresh_sync_cache():
    """The module keeps a global connection; drop it around each test so it
    rebuilds against the current temp data dir."""
    sync_cache.close()
    yield
    sync_cache.close()


class TestSyncCacheState:
    def test_unknown_folder_is_none(self, initialized_app):
        assert sync_cache.get_folder_sync_state(1, "INBOX") is None

    def test_update_then_read(self, initialized_app):
        sync_cache.update_folder_sync_state(1, "INBOX", uidvalidity=42, highestmodseq=100)
        state = sync_cache.get_folder_sync_state(1, "INBOX")
        assert state["uidvalidity"] == 42
        assert state["highestmodseq"] == 100
        assert isinstance(state["last_synced_at"], int)

    def test_update_replaces_existing(self, initialized_app):
        sync_cache.update_folder_sync_state(1, "INBOX", 1, 1)
        sync_cache.update_folder_sync_state(1, "INBOX", 2, 2)
        state = sync_cache.get_folder_sync_state(1, "INBOX")
        assert state["uidvalidity"] == 2 and state["highestmodseq"] == 2

    def test_clear_removes_state(self, initialized_app):
        sync_cache.update_folder_sync_state(1, "INBOX", 1, 1)
        sync_cache.clear_folder_sync_state(1, "INBOX")
        assert sync_cache.get_folder_sync_state(1, "INBOX") is None

    def test_state_is_per_account_and_folder(self, initialized_app):
        sync_cache.update_folder_sync_state(1, "INBOX", 11, 0)
        sync_cache.update_folder_sync_state(2, "INBOX", 22, 0)
        sync_cache.update_folder_sync_state(1, "Sent", 33, 0)
        assert sync_cache.get_folder_sync_state(1, "INBOX")["uidvalidity"] == 11
        assert sync_cache.get_folder_sync_state(2, "INBOX")["uidvalidity"] == 22
        assert sync_cache.get_folder_sync_state(1, "Sent")["uidvalidity"] == 33


class TestCacheFreshness:
    def test_ttl_constant(self):
        assert sync_cache.FOLDER_CACHE_TTL_SECONDS == 120

    def test_no_state_is_not_fresh(self, initialized_app):
        assert sync_cache.is_cache_fresh(1, "INBOX") is False

    def test_just_synced_is_fresh(self, initialized_app):
        sync_cache.update_folder_sync_state(1, "INBOX", 1, 1)
        assert sync_cache.is_cache_fresh(1, "INBOX") is True

    def test_old_sync_is_stale(self, initialized_app):
        sync_cache.update_folder_sync_state(1, "INBOX", 1, 1)
        # Backdate the sync well beyond the TTL window
        conn = sync_cache._get_connection()
        old = int(time.time()) - (sync_cache.FOLDER_CACHE_TTL_SECONDS + 60)
        conn.execute(
            "UPDATE folder_sync_state SET last_synced_at = ? WHERE account_id = 1 AND folder_name = 'INBOX'",
            (old,),
        )
        conn.commit()
        assert sync_cache.is_cache_fresh(1, "INBOX") is False


class TestDetectServer:
    def test_known_domain(self):
        assert IMAP.detect_server("user@gmail.com") == ("imap.gmail.com", 993)

    def test_case_insensitive(self):
        assert IMAP.detect_server("USER@GMAIL.COM") == ("imap.gmail.com", 993)

    def test_name_wrapped_address(self):
        assert IMAP.detect_server("Jane Doe <jane@fastmail.com>") == ("imap.fastmail.com", 993)

    def test_unknown_domain(self):
        assert IMAP.detect_server("user@unknown-provider-xyz.test") is None

    def test_malformed_address(self):
        assert IMAP.detect_server("not-an-email") is None
