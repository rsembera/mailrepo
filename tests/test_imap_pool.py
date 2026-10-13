"""Tests for core/imap_pool.py: reuse, reconnect, serialisation, teardown."""

import threading
import time

import pytest

from core.encryption import Encryption
from core.imap import IMAPError
from core.imap_pool import ImapPool, PooledConnection


class _Conn:
    def __init__(self, alive=True):
        self.alive = alive
        self.noops = 0

    def noop(self):
        self.noops += 1
        if not self.alive:
            raise OSError("socket closed")
        return "OK", [b"NOOP completed"]


class _Client:
    host = "imap.example.com"
    instances = []

    def __init__(self):
        self.connection = _Conn()
        self._folder_cache = ["stale"]
        self.disconnected = False
        _Client.instances.append(self)

    def select_folder(self, name):
        return {"folder": name}

    def disconnect(self):
        self.disconnected = True
        self.connection = None


@pytest.fixture(autouse=True)
def fake_connect(monkeypatch):
    _Client.instances = []
    monkeypatch.setattr(ImapPool, "_entries", {})
    from core import imap_pool

    monkeypatch.setattr(
        imap_pool.IMAP, "connect_with_credentials", classmethod(lambda cls, c: _Client())
    )
    yield
    ImapPool.close_all()


class TestReuse:
    def test_second_acquire_reuses_connection(self):
        a = ImapPool.acquire(1, "creds")
        a.release()
        b = ImapPool.acquire(1, "creds")
        b.release()
        assert len(_Client.instances) == 1
        assert isinstance(b, PooledConnection)

    def test_lease_proxies_client_and_clears_folder_cache(self):
        a = ImapPool.acquire(1, "creds")
        a.release()
        b = ImapPool.acquire(1, "creds")
        assert b.select_folder("INBOX") == {"folder": "INBOX"}
        assert b.host == "imap.example.com"
        assert b._folder_cache is None, "held connection must not serve last request's folder list"
        b.release()

    def test_different_accounts_get_different_connections(self):
        a = ImapPool.acquire(1, "c1")
        b = ImapPool.acquire(2, "c2")
        a.release()
        b.release()
        assert len(_Client.instances) == 2


class TestReconnect:
    def test_dead_connection_is_replaced_on_acquire(self):
        a = ImapPool.acquire(1, "creds")
        a.release()
        _Client.instances[0].connection.alive = False
        b = ImapPool.acquire(1, "creds")
        b.release()
        assert len(_Client.instances) == 2
        assert _Client.instances[0].disconnected is True

    def test_connect_failure_releases_lock(self, monkeypatch):
        from core import imap_pool

        def boom(cls, c):
            raise IMAPError("no route")

        monkeypatch.setattr(imap_pool.IMAP, "connect_with_credentials", classmethod(boom))
        with pytest.raises(IMAPError):
            ImapPool.acquire(1, "creds")
        # A second attempt must not deadlock on the lock left by the first.
        monkeypatch.setattr(
            imap_pool.IMAP, "connect_with_credentials", classmethod(lambda cls, c: _Client())
        )
        ImapPool.acquire(1, "creds").release()


class TestSerialisation:
    def test_same_account_requests_queue(self, monkeypatch):
        monkeypatch.setattr("core.imap_pool.ACQUIRE_TIMEOUT_SECONDS", 5)
        order = []
        first = ImapPool.acquire(1, "creds")

        def second():
            order.append("second-waiting")
            lease = ImapPool.acquire(1, "creds")
            order.append("second-got")
            lease.release()

        t = threading.Thread(target=second)
        t.start()
        time.sleep(0.1)
        order.append("first-release")
        first.release()
        t.join(timeout=5)
        assert order == ["second-waiting", "first-release", "second-got"]
        assert len(_Client.instances) == 1

    def test_acquire_times_out_instead_of_hanging(self, monkeypatch):
        monkeypatch.setattr("core.imap_pool.ACQUIRE_TIMEOUT_SECONDS", 0.05)
        first = ImapPool.acquire(1, "creds")
        try:
            with pytest.raises(IMAPError):
                ImapPool.acquire(1, "creds")
        finally:
            first.release()


class TestTeardown:
    def test_lock_closes_every_connection(self):
        ImapPool.acquire(1, "c1").release()
        ImapPool.acquire(2, "c2").release()
        assert sorted(ImapPool.held_accounts()) == [1, 2]
        Encryption.lock()
        assert ImapPool.held_accounts() == []
        assert all(c.disconnected for c in _Client.instances)

    def test_evict_closes_one_account(self):
        ImapPool.acquire(1, "c1").release()
        ImapPool.acquire(2, "c2").release()
        ImapPool.evict(1)
        assert ImapPool.held_accounts() == [2]
        assert _Client.instances[0].disconnected and not _Client.instances[1].disconnected

    def test_double_release_is_harmless(self):
        a = ImapPool.acquire(1, "c1")
        a.release()
        a.release()
        ImapPool.acquire(1, "c1").release()
