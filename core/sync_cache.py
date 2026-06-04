"""
MailRepo - Sync Cache

Separate plain SQLite database for IMAP folder sync state.
Stored outside the main encrypted database so that frequent
timestamp updates don't trigger the backup system's change
detection. This is transient cache metadata — not user data.

File: data/.sync_cache.db (dot-prefixed, excluded from backups)
"""

import sqlite3
import time
from pathlib import Path
from typing import Optional

from .config import Config

_connection: Optional[sqlite3.Connection] = None


def _get_db_path() -> Path:
    return Config.get_data_path() / ".sync_cache.db"


def _get_connection() -> sqlite3.Connection:
    global _connection
    if _connection is None:
        db_path = _get_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _connection = sqlite3.connect(str(db_path), check_same_thread=False)
        _connection.row_factory = sqlite3.Row
        _connection.execute("PRAGMA journal_mode = WAL")
        _connection.executescript("""
            CREATE TABLE IF NOT EXISTS folder_sync_state (
                account_id INTEGER NOT NULL,
                folder_name TEXT NOT NULL,
                uidvalidity INTEGER,
                highestmodseq INTEGER,
                last_synced_at INTEGER NOT NULL,
                PRIMARY KEY (account_id, folder_name)
            );
        """)
    return _connection


def close():
    """Close the sync cache connection."""
    global _connection
    if _connection is not None:
        _connection.close()
        _connection = None


def get_folder_sync_state(account_id: int, folder: str) -> dict | None:
    """Get sync state for a folder."""
    conn = _get_connection()
    row = conn.execute(
        """SELECT uidvalidity, highestmodseq, last_synced_at
           FROM folder_sync_state
           WHERE account_id = ? AND folder_name = ?""",
        (account_id, folder),
    ).fetchone()
    if not row:
        return None
    return {
        "uidvalidity": row["uidvalidity"],
        "highestmodseq": row["highestmodseq"],
        "last_synced_at": row["last_synced_at"],
    }


def update_folder_sync_state(
    account_id: int,
    folder: str,
    uidvalidity: int | None,
    highestmodseq: int | None,
) -> None:
    """Record that we just synced a folder."""
    conn = _get_connection()
    now = int(time.time())
    conn.execute(
        """INSERT OR REPLACE INTO folder_sync_state
           (account_id, folder_name, uidvalidity, highestmodseq, last_synced_at)
           VALUES (?, ?, ?, ?, ?)""",
        (account_id, folder, uidvalidity, highestmodseq, now),
    )
    conn.commit()


def clear_folder_sync_state(account_id: int, folder: str) -> None:
    """Clear sync state for a folder (e.g. after cache clear)."""
    conn = _get_connection()
    conn.execute(
        "DELETE FROM folder_sync_state WHERE account_id = ? AND folder_name = ?",
        (account_id, folder),
    )
    conn.commit()


# How many seconds a cached folder is considered fresh.
FOLDER_CACHE_TTL_SECONDS = 120


def is_cache_fresh(account_id: int, folder: str) -> bool:
    """Check whether the cache for this folder is within the TTL window."""
    state = get_folder_sync_state(account_id, folder)
    if not state or not state["last_synced_at"]:
        return False
    age = int(time.time()) - state["last_synced_at"]
    return age < FOLDER_CACHE_TTL_SECONDS
