"""
MailRepo - IMAP connection pool

One held, authenticated IMAP connection per account, reused across
requests the way a mail client reuses its socket. Before this, every
folder click opened a fresh TLS connection and logged in again, which
is where the "Connecting to server..." pause came from.

Design:

- ``ImapPool.acquire(account_id, encrypted_creds)`` returns a lease. The
  lease proxies every attribute of the underlying ``IMAP`` client, so
  call sites use it exactly as they used a fresh client. Call
  ``release()`` (in a ``finally``) instead of ``disconnect()``; the
  connection stays open for the next request.
- IMAP is one command at a time and waitress serves requests on several
  threads, so each account's connection is guarded by a lock. A second
  request for the same account waits for the first to release.
- Lazy reconnect, no keepalives. Gmail drops a silent connection after
  roughly ten minutes, and sleep/wake or a network change will kill one
  too. On acquire the held connection is probed with NOOP; if the probe
  fails it is dropped and a fresh one is opened. A failure in the middle
  of a request surfaces as IMAPError exactly as before, and the next
  acquire reconnects.
- The pool holds authenticated sessions derived from credentials in the
  encrypted database, so it must never outlive the unlocked state.
  ``close_all`` is registered as an ``Encryption.on_lock`` hook, which
  covers logout, idle lock, and session timeout; ``main._cleanup`` calls
  it at exit; account edit/delete evicts that account.
"""

import threading
from typing import Optional

from utils.log import get_logger

from .encryption import Encryption
from .imap import IMAP, IMAPError

log = get_logger()

# How long a request waits for another request on the same account to
# finish before giving up. A commit can legitimately hold the connection
# for minutes; a folder click behind it just waits.
ACQUIRE_TIMEOUT_SECONDS = 300


class _Entry:
    __slots__ = ("client", "lock")

    def __init__(self) -> None:
        self.client: Optional[IMAP] = None
        self.lock = threading.Lock()


class PooledConnection:
    """A leased IMAP client. Proxies the client; ``release()`` returns it."""

    def __init__(self, pool: "type[ImapPool]", account_id: int, entry: _Entry) -> None:
        self._pool = pool
        self._account_id = account_id
        self._entry = entry
        self._released = False

    def __getattr__(self, name):
        client = self._entry.client
        if client is None:
            raise IMAPError("Not connected")
        return getattr(client, name)

    def release(self) -> None:
        """Hand the connection back to the pool (keeps it open)."""
        if self._released:
            return
        self._released = True
        self._entry.lock.release()

    def disconnect(self) -> None:
        """Compatibility alias: a lease is released, not closed."""
        self.release()

    def __enter__(self) -> "PooledConnection":
        return self

    def __exit__(self, *exc) -> None:
        self.release()


class ImapPool:
    _entries: dict[int, _Entry] = {}
    _registry_lock = threading.Lock()
    _hooked = False

    @classmethod
    def _entry_for(cls, account_id: int) -> _Entry:
        with cls._registry_lock:
            if not cls._hooked:
                Encryption.on_lock(cls.close_all)
                cls._hooked = True
            entry = cls._entries.get(account_id)
            if entry is None:
                entry = _Entry()
                cls._entries[account_id] = entry
            return entry

    @classmethod
    def acquire(cls, account_id: int, encrypted_creds: str) -> PooledConnection:
        """
        Lease the account's connection, opening or reopening it as needed.

        Raises IMAPError if the credentials cannot be loaded, the server
        cannot be reached, or another request holds the account for longer
        than ACQUIRE_TIMEOUT_SECONDS.
        """
        account_id = int(account_id)
        entry = cls._entry_for(account_id)
        if not entry.lock.acquire(timeout=ACQUIRE_TIMEOUT_SECONDS):
            raise IMAPError("Another operation on this account is still running; try again.")
        try:
            client = entry.client
            if client is not None and not cls._alive(client):
                log.debug(f"IMAP pool: connection for account {account_id} is dead; reconnecting")
                cls._drop(entry)
                client = None
            if client is None:
                entry.client = IMAP.connect_with_credentials(encrypted_creds)
            else:
                # A fresh client has no folder-list cache; a held one must
                # not serve last request's listing either.
                client._folder_cache = None
        except BaseException:
            entry.lock.release()
            raise
        return PooledConnection(cls, account_id, entry)

    @staticmethod
    def _alive(client: IMAP) -> bool:
        try:
            conn = client.connection
            if conn is None:
                return False
            status, _ = conn.noop()
            return status == "OK"
        except Exception:
            return False

    @staticmethod
    def _drop(entry: _Entry) -> None:
        client, entry.client = entry.client, None
        if client is not None:
            try:
                client.disconnect()
            except Exception:
                pass

    @classmethod
    def evict(cls, account_id: int) -> None:
        """Close and forget one account's connection (credentials changed, account deleted)."""
        with cls._registry_lock:
            entry = cls._entries.pop(int(account_id), None)
        if entry is None:
            return
        # If a request is mid-flight the drop waits for it; the lease then
        # releases a lock nobody else can see, which is harmless.
        with entry.lock:
            cls._drop(entry)

    @classmethod
    def close_all(cls) -> None:
        """Close every held connection. Runs on lock, logout, and exit."""
        with cls._registry_lock:
            entries = list(cls._entries.items())
            cls._entries.clear()
        for _account_id, entry in entries:
            got = entry.lock.acquire(timeout=5)
            try:
                cls._drop(entry)
            finally:
                if got:
                    entry.lock.release()

    @classmethod
    def held_accounts(cls) -> list[int]:
        with cls._registry_lock:
            return [a for a, e in cls._entries.items() if e.client is not None]
