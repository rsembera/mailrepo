"""
MailRepo - Database management.

Handles SQLite database connection, schema creation, and migrations.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, Optional

from .config import Config


# Current schema version (increment when schema changes)
SCHEMA_VERSION = 1


class Database:
    """
    SQLite database manager for MailRepo.
    
    Provides connection management, schema creation, and query helpers.
    """
    
    _connection: Optional[sqlite3.Connection] = None
    
    @classmethod
    def get_connection(cls) -> sqlite3.Connection:
        """
        Get the database connection, creating it if necessary.
        
        Returns:
            SQLite connection with row factory set to sqlite3.Row.
        """
        if cls._connection is None:
            db_path = Config.get_database_path()
            db_path.parent.mkdir(parents=True, exist_ok=True)
            
            cls._connection = sqlite3.connect(
                db_path,
                check_same_thread=False,  # Flask uses multiple threads
                detect_types=sqlite3.PARSE_DECLTYPES,
            )
            cls._connection.row_factory = sqlite3.Row
            
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
        
        Usage:
            with Database.transaction() as conn:
                conn.execute("INSERT INTO ...")
        """
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
        return cls.get_connection().execute(sql, params)
    
    @classmethod
    def executemany(cls, sql: str, params_list: list[tuple]) -> sqlite3.Cursor:
        """Execute a SQL statement with multiple parameter sets."""
        return cls.get_connection().executemany(sql, params_list)
    
    @classmethod
    def fetchone(cls, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        """Execute a query and return the first row."""
        return cls.execute(sql, params).fetchone()
    
    @classmethod
    def fetchall(cls, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        """Execute a query and return all rows."""
        return cls.execute(sql, params).fetchall()
    
    @classmethod
    def commit(cls) -> None:
        """Commit the current transaction."""
        cls.get_connection().commit()
    
    @classmethod
    def close(cls) -> None:
        """Close the database connection."""
        if cls._connection is not None:
            cls._connection.close()
            cls._connection = None
    
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
            row = cls.fetchone(
                "SELECT value FROM settings WHERE key = 'schema_version'"
            )
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
        
        Args:
            conn: Database connection.
            from_version: Current schema version.
            to_version: Target schema version.
        """
        # Add migrations here as schema evolves
        # Example:
        # if from_version < 2:
        #     conn.execute("ALTER TABLE folders ADD COLUMN color TEXT")
        pass


# SQL schema definition
SCHEMA_SQL = """
-- Email accounts (Gmail, IMAP, etc.)
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,                    -- Display name: "Work Gmail", "Personal"
    email TEXT NOT NULL,                   -- Email address
    provider TEXT NOT NULL,                -- 'gmail' or 'imap'
    credentials_encrypted TEXT,            -- Encrypted OAuth tokens or IMAP credentials
    created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
    last_sync INTEGER,                     -- Last successful sync timestamp
    UNIQUE(email, provider)
);

-- Archive folders (unified across all accounts)
CREATE TABLE IF NOT EXISTS folders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,                    -- Folder name: "Client: John Smith"
    parent_id INTEGER,                     -- Parent folder ID (NULL for root folders)
    encrypted INTEGER NOT NULL DEFAULT 1,  -- 1 = encrypted, 0 = unencrypted
    retention_days INTEGER,                -- Auto-delete after N days (NULL = keep forever)
    created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
    FOREIGN KEY (parent_id) REFERENCES folders(id) ON DELETE CASCADE
);

-- Archived email messages
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_id INTEGER NOT NULL,            -- Archive folder
    source_account_id INTEGER,             -- Account message came from (NULL for imports)
    message_id TEXT NOT NULL,              -- Email Message-ID header
    subject TEXT,                          -- Email subject
    sender TEXT,                           -- From address
    recipients TEXT,                       -- JSON array of recipients
    date INTEGER,                          -- Email date timestamp
    filepath TEXT NOT NULL,                -- Path to .eml or .eml.enc file
    encrypted INTEGER NOT NULL DEFAULT 1,  -- 1 = encrypted, 0 = unencrypted
    filed_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
    FOREIGN KEY (folder_id) REFERENCES folders(id) ON DELETE CASCADE,
    FOREIGN KEY (source_account_id) REFERENCES accounts(id) ON DELETE SET NULL
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_messages_folder ON messages(folder_id);
CREATE INDEX IF NOT EXISTS idx_messages_date ON messages(date);
CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender);
CREATE INDEX IF NOT EXISTS idx_messages_message_id ON messages(message_id);
CREATE INDEX IF NOT EXISTS idx_folders_parent ON folders(parent_id);

-- Application settings (key-value store)
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
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
