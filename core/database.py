"""
MailRepo - Database management.

Handles SQLCipher encrypted database connection, schema creation, and migrations.
"""

try:
    from sqlcipher3 import dbapi2 as sqlite3

    SQLCIPHER_AVAILABLE = True
except ImportError:
    import sqlite3

    SQLCIPHER_AVAILABLE = False

import threading
from contextlib import contextmanager
from typing import Generator, Optional

from .config import Config

# Current schema version (increment when schema changes)
SCHEMA_VERSION = 5


class Database:
    """
    SQLCipher encrypted database manager for MailRepo.

    Provides connection management, schema creation, and query helpers.
    The entire database is encrypted at rest using the master password.

    Thread safety: every public method acquires _lock (an RLock, so a
    single thread can re-acquire across nested calls). During the crypto
    migration's Phase 2, the migration thread acquires the lock once,
    sets _migration_active with its thread id, performs the rekey, then
    releases. Concurrent calls from other threads block on the lock; on
    acquiring, they see the flag set by a different thread and raise
    immediately. The migration's own DB calls bypass the flag check by
    matching thread id.
    """

    _connection: Optional[sqlite3.Connection] = None
    _db_key: Optional[str] = None

    # Threading primitives (added in the crypto refactor; see
    # docs/Crypto_Refactor_Plan.md scope item 5).
    _lock: threading.RLock = threading.RLock()
    _migration_active: bool = False
    _migration_thread_id: Optional[int] = None

    @classmethod
    def _check_migration(cls) -> None:
        """Raise if Phase 2 of the crypto migration is active in a different
        thread. The migration thread itself bypasses this check, so it can
        still perform DB operations during the rekey window."""
        if cls._migration_active and threading.get_ident() != cls._migration_thread_id:
            raise RuntimeError(
                "Database access blocked: crypto migration Phase 2 in progress. "
                "All other DB operations are paused until the rekey completes."
            )

    @classmethod
    def acquire_for_migration(cls) -> None:
        """Take exclusive ownership of the database for Phase 2 of the crypto
        migration. Acquires the lock and sets the migration flag with the
        caller's thread id. Must be paired with release_after_migration()."""
        cls._lock.acquire()
        cls._migration_active = True
        cls._migration_thread_id = threading.get_ident()

    @classmethod
    def release_after_migration(cls) -> None:
        """Release exclusive ownership taken by acquire_for_migration(). Clears
        the flag and releases the lock so other threads can proceed."""
        cls._migration_thread_id = None
        cls._migration_active = False
        cls._lock.release()

    @classmethod
    def set_key(cls, key: str) -> None:
        """
        Set the database encryption key.

        Must be called before any database operations.
        The key should be derived from the master password.

        Args:
            key: Hex-encoded encryption key.
        """
        with cls._lock:
            cls._check_migration()
            cls._db_key = key
            # Close existing connection if key changes
            if cls._connection is not None:
                cls.close()

    @classmethod
    def get_connection(cls) -> sqlite3.Connection:
        """
        Get the database connection, creating it if necessary.

        Returns:
            SQLite/SQLCipher connection with row factory set.
        """
        with cls._lock:
            cls._check_migration()
            if cls._connection is None:
                if cls._db_key is None:
                    raise RuntimeError("Database key not set. Call set_key() first.")

                db_path = Config.get_database_path()
                db_path.parent.mkdir(parents=True, exist_ok=True)

                cls._connection = sqlite3.connect(
                    str(db_path),
                    check_same_thread=False,
                )
                cls._connection.row_factory = sqlite3.Row

                # Set encryption key (SQLCipher)
                if SQLCIPHER_AVAILABLE:
                    cls._connection.execute(f"PRAGMA key = \"x'{cls._db_key}'\"")

                # Enable foreign keys
                cls._connection.execute("PRAGMA foreign_keys = ON")

                # Enable WAL mode for better concurrency
                cls._connection.execute("PRAGMA journal_mode = WAL")

            return cls._connection

    @classmethod
    @contextmanager
    def transaction(cls) -> Generator[sqlite3.Connection, None, None]:
        """
        Context manager for database transactions.

        Automatically commits on success, rolls back on exception.
        Holds the database lock for the full transaction so nested DB
        operations all execute under the same critical section.
        """
        with cls._lock:
            cls._check_migration()
            conn = cls.get_connection()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    @classmethod
    def execute(cls, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute a SQL statement and return the cursor."""
        with cls._lock:
            cls._check_migration()
            return cls.get_connection().execute(sql, params)

    @classmethod
    def executemany(cls, sql: str, params_list: list[tuple]) -> sqlite3.Cursor:
        """Execute a SQL statement with multiple parameter sets."""
        with cls._lock:
            cls._check_migration()
            return cls.get_connection().executemany(sql, params_list)

    @classmethod
    def fetchone(cls, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        """Execute a query and return the first row."""
        with cls._lock:
            cls._check_migration()
            return cls.execute(sql, params).fetchone()

    @classmethod
    def fetchall(cls, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        """Execute a query and return all rows."""
        with cls._lock:
            cls._check_migration()
            return cls.execute(sql, params).fetchall()

    @classmethod
    def commit(cls) -> None:
        """Commit the current transaction."""
        with cls._lock:
            cls._check_migration()
            cls.get_connection().commit()

    @classmethod
    def close(cls) -> None:
        """Close the database connection."""
        with cls._lock:
            # No _check_migration here: close() is part of the migration's own
            # teardown path and must always be allowed to run.
            if cls._connection is not None:
                cls._connection.close()
                cls._connection = None

    @classmethod
    def checkpoint(cls) -> None:
        """
        Checkpoint the WAL file to ensure all changes are in main database.

        Important to call before backup to ensure backup includes all data.
        """
        with cls._lock:
            cls._check_migration()
            conn = cls.get_connection()
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    @classmethod
    def initialize(cls) -> None:
        """
        Initialize the database schema.

        Creates tables if they don't exist, runs migrations if needed.
        """
        conn = cls.get_connection()

        # Check current schema version
        current_version = cls._get_schema_version()

        if current_version == 0:
            # Fresh install - create all tables
            cls._create_schema(conn)
            cls._set_schema_version(SCHEMA_VERSION)
        elif current_version < SCHEMA_VERSION:
            # Need to migrate
            cls._migrate(conn, current_version, SCHEMA_VERSION)
            cls._set_schema_version(SCHEMA_VERSION)

        conn.commit()

    @classmethod
    def _get_schema_version(cls) -> int:
        """Get the current schema version from the database."""
        try:
            row = cls.fetchone("SELECT value FROM settings WHERE key = 'schema_version'")
            return int(row["value"]) if row else 0
        except sqlite3.OperationalError:
            # Settings table doesn't exist yet
            return 0

    @classmethod
    def _set_schema_version(cls, version: int) -> None:
        """Set the schema version in the database."""
        cls.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            ("schema_version", str(version)),
        )

    @classmethod
    def _create_schema(cls, conn: sqlite3.Connection) -> None:
        """Create the initial database schema."""
        conn.executescript(SCHEMA_SQL)

    @classmethod
    def _migrate(cls, conn: sqlite3.Connection, from_version: int, to_version: int) -> None:
        """
        Run database migrations.

        Each migration is a function that takes a connection and applies changes
        for that version. Migrations run sequentially from from_version+1 to to_version.

        Args:
            conn: Database connection.
            from_version: Current schema version.
            to_version: Target schema version.
        """
        migrations = {
            # Add migrations here when needed post-release:
            # 6: cls._migrate_to_v6,
        }

        for version in range(from_version + 1, to_version + 1):
            if version in migrations:
                migrations[version](conn)

    # Migration functions — add new ones here post-release
    # @classmethod
    # def _migrate_to_v6(cls, conn: sqlite3.Connection) -> None:
    #     """Migration to schema version 6."""
    #     conn.execute("ALTER TABLE ...")


# SQL schema definition
SCHEMA_SQL = """
-- Email accounts (Gmail, IMAP, etc.)
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    provider TEXT NOT NULL,
    credentials_encrypted TEXT,
    cached_folders TEXT,
    cached_folders_at INTEGER,
    created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
    last_sync INTEGER,
    UNIQUE(email, provider)
);

-- Archive folders (unified across all accounts)
CREATE TABLE IF NOT EXISTS folders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    parent_id INTEGER,
    retention_days INTEGER,
    retention_date INTEGER,
    color TEXT,
    deleted_at INTEGER,
    created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
    FOREIGN KEY (parent_id) REFERENCES folders(id) ON DELETE CASCADE
);

-- Archived email messages
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_id INTEGER,
    original_folder_id INTEGER,
    source_account_id INTEGER,
    message_id TEXT NOT NULL,
    subject TEXT,
    sender TEXT,
    recipients TEXT,
    date INTEGER,
    filepath TEXT NOT NULL,
    body_text TEXT,
    deleted_at INTEGER,
    flagged_at INTEGER,
    filed_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
    FOREIGN KEY (folder_id) REFERENCES folders(id) ON DELETE CASCADE,
    FOREIGN KEY (original_folder_id) REFERENCES folders(id) ON DELETE SET NULL,
    FOREIGN KEY (source_account_id) REFERENCES accounts(id) ON DELETE SET NULL
);

-- Full-text search index
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    subject,
    sender,
    recipients,
    body_text,
    content='messages',
    content_rowid='id'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, subject, sender, recipients, body_text)
    VALUES (new.id, new.subject, new.sender, new.recipients, new.body_text);
END;

CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, subject, sender, recipients, body_text)
    VALUES ('delete', old.id, old.subject, old.sender, old.recipients, old.body_text);
END;

CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, subject, sender, recipients, body_text)
    VALUES ('delete', old.id, old.subject, old.sender, old.recipients, old.body_text);
    INSERT INTO messages_fts(rowid, subject, sender, recipients, body_text)
    VALUES (new.id, new.subject, new.sender, new.recipients, new.body_text);
END;

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_messages_folder ON messages(folder_id);
CREATE INDEX IF NOT EXISTS idx_messages_date ON messages(date);
CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender);
CREATE INDEX IF NOT EXISTS idx_messages_message_id ON messages(message_id);
CREATE INDEX IF NOT EXISTS idx_folders_parent ON folders(parent_id);
CREATE INDEX IF NOT EXISTS idx_folders_retention ON folders(retention_date);

-- Email header cache (for IMAP folder browsing)
CREATE TABLE IF NOT EXISTS email_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    folder_name TEXT NOT NULL,
    uid TEXT NOT NULL,
    uidvalidity INTEGER NOT NULL,
    subject TEXT,
    sender TEXT,
    recipients TEXT,
    date TEXT,
    message_id TEXT,
    cached_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
    UNIQUE(account_id, folder_name, uid, uidvalidity)
);
CREATE INDEX IF NOT EXISTS idx_email_cache_folder ON email_cache(account_id, folder_name, uidvalidity);

-- Application settings (key-value store)
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Pending commit tracking for resume after interruption
CREATE TABLE IF NOT EXISTS pending_commit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    commit_id TEXT NOT NULL,
    item_type TEXT NOT NULL,              -- 'email' or 'folder'
    item_data TEXT NOT NULL,              -- JSON blob with all item details
    destination_folder_id INTEGER NOT NULL,
    source_action TEXT,                   -- 'leave', 'archive', 'trash', 'delete'
    status TEXT NOT NULL DEFAULT 'pending', -- 'pending', 'committed', 'post_action_done'
    created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
    updated_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
    FOREIGN KEY (destination_folder_id) REFERENCES folders(id)
);
CREATE INDEX IF NOT EXISTS idx_pending_commit_id ON pending_commit(commit_id);
CREATE INDEX IF NOT EXISTS idx_pending_commit_status ON pending_commit(status);
"""


# Convenience functions for settings
def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    """Get a setting value by key."""
    row = Database.fetchone("SELECT value FROM settings WHERE key = ?", (key,))
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    """Set a setting value."""
    Database.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (key, value),
    )
    Database.commit()


def delete_setting(key: str) -> None:
    """Delete a setting."""
    Database.execute("DELETE FROM settings WHERE key = ?", (key,))
    Database.commit()
