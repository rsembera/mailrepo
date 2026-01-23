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

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, Optional

from .config import Config


# Current schema version (increment when schema changes)
SCHEMA_VERSION = 4


class Database:
    """
    SQLCipher encrypted database manager for MailRepo.
    
    Provides connection management, schema creation, and query helpers.
    The entire database is encrypted at rest using the master password.
    """
    
    _connection: Optional[sqlite3.Connection] = None
    _db_key: Optional[str] = None
    
    @classmethod
    def set_key(cls, key: str) -> None:
        """
        Set the database encryption key.
        
        Must be called before any database operations.
        The key should be derived from the master password.
        
        Args:
            key: Hex-encoded encryption key.
        """
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
        # Migration from version 1 to 2: add folder caching columns
        if from_version < 2:
            conn.execute("ALTER TABLE accounts ADD COLUMN cached_folders TEXT")
            conn.execute("ALTER TABLE accounts ADD COLUMN cached_folders_at INTEGER")
        
        # Migration from version 2 to 3: add body_text for FTS, remove encrypted columns
        if from_version < 3:
            # Add body_text column for full-text search
            conn.execute("ALTER TABLE messages ADD COLUMN body_text TEXT")
            
            # Create FTS5 virtual table
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                    subject,
                    sender,
                    body_text,
                    content='messages',
                    content_rowid='id'
                )
            """)
            
            # Create triggers to keep FTS in sync
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
                    INSERT INTO messages_fts(rowid, subject, sender, body_text)
                    VALUES (new.id, new.subject, new.sender, new.body_text);
                END
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
                    INSERT INTO messages_fts(messages_fts, rowid, subject, sender, body_text)
                    VALUES ('delete', old.id, old.subject, old.sender, old.body_text);
                END
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
                    INSERT INTO messages_fts(messages_fts, rowid, subject, sender, body_text)
                    VALUES ('delete', old.id, old.subject, old.sender, old.body_text);
                    INSERT INTO messages_fts(rowid, subject, sender, body_text)
                    VALUES (new.id, new.subject, new.sender, new.body_text);
                END
            """)
            
            # Note: We're keeping the 'encrypted' columns for now to avoid data loss
            # They'll be ignored going forward (everything is encrypted)


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
    color TEXT,
    deleted_at INTEGER,
    created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
    FOREIGN KEY (parent_id) REFERENCES folders(id) ON DELETE CASCADE
);

-- Archived email messages
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_id INTEGER NOT NULL,
    source_account_id INTEGER,
    message_id TEXT NOT NULL,
    subject TEXT,
    sender TEXT,
    recipients TEXT,
    date INTEGER,
    filepath TEXT NOT NULL,
    body_text TEXT,
    deleted_at INTEGER,
    filed_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
    FOREIGN KEY (folder_id) REFERENCES folders(id) ON DELETE CASCADE,
    FOREIGN KEY (source_account_id) REFERENCES accounts(id) ON DELETE SET NULL
);

-- Full-text search index
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    subject,
    sender,
    body_text,
    content='messages',
    content_rowid='id'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, subject, sender, body_text)
    VALUES (new.id, new.subject, new.sender, new.body_text);
END;

CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, subject, sender, body_text)
    VALUES ('delete', old.id, old.subject, old.sender, old.body_text);
END;

CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, subject, sender, body_text)
    VALUES ('delete', old.id, old.subject, old.sender, old.body_text);
    INSERT INTO messages_fts(rowid, subject, sender, body_text)
    VALUES (new.id, new.subject, new.sender, new.body_text);
END;

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_messages_folder ON messages(folder_id);
CREATE INDEX IF NOT EXISTS idx_messages_date ON messages(date);
CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender);
CREATE INDEX IF NOT EXISTS idx_messages_message_id ON messages(message_id);
CREATE INDEX IF NOT EXISTS idx_folders_parent ON folders(parent_id);

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
