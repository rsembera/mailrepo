"""
Tests for core/database.py - SQLCipher database operations.
"""

import pytest


class TestDatabaseConnection:
    """Tests for database connection and initialization."""

    def test_database_requires_key(self):
        """Database operations should fail without a key."""
        from core.database import Database

        with pytest.raises(RuntimeError, match="key not set"):
            Database.get_connection()

    def test_database_initializes_schema(self, initialized_app):
        """Database should create all required tables."""
        app, _ = initialized_app

        from core.database import Database

        with app.app_context():
            # Check core tables exist
            tables = Database.fetchall(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            table_names = [t["name"] for t in tables]

            assert "accounts" in table_names
            assert "folders" in table_names
            assert "messages" in table_names
            assert "settings" in table_names
            assert "email_cache" in table_names
            assert "messages_fts" in table_names


class TestDatabaseOperations:
    """Tests for basic database operations."""

    def test_insert_and_fetch_folder(self, initialized_app):
        """Should be able to insert and retrieve a folder."""
        app, _ = initialized_app

        from core.database import Database

        with app.app_context():
            cursor = Database.execute("INSERT INTO folders (name) VALUES (?)", ("Test Folder",))
            Database.commit()
            folder_id = cursor.lastrowid

            folder = Database.fetchone("SELECT id, name FROM folders WHERE id = ?", (folder_id,))

            assert folder is not None
            assert folder["name"] == "Test Folder"

    def test_settings_helper_functions(self, initialized_app):
        """Settings helper functions should work correctly."""
        app, _ = initialized_app

        from core.database import delete_setting, get_setting, set_setting

        with app.app_context():
            # Default value when not set
            assert get_setting("test_key") is None
            assert get_setting("test_key", "default") == "default"

            # Set and get
            set_setting("test_key", "test_value")
            assert get_setting("test_key") == "test_value"

            # Update
            set_setting("test_key", "new_value")
            assert get_setting("test_key") == "new_value"

            # Delete
            delete_setting("test_key")
            assert get_setting("test_key") is None

    def test_transaction_rollback(self, initialized_app):
        """Failed transactions should rollback."""
        app, _ = initialized_app

        from core.database import Database

        with app.app_context():
            # Insert a folder
            Database.execute("INSERT INTO folders (name) VALUES (?)", ("Rollback Test",))
            Database.commit()

            # Start transaction that will fail
            try:
                with Database.transaction():
                    Database.execute("INSERT INTO folders (name) VALUES (?)", ("Should Rollback",))
                    raise ValueError("Simulated error")
            except ValueError:
                pass

            # The failed insert should not exist
            result = Database.fetchone(
                "SELECT id FROM folders WHERE name = ?", ("Should Rollback",)
            )
            assert result is None

            # The first insert should still exist
            result = Database.fetchone("SELECT id FROM folders WHERE name = ?", ("Rollback Test",))
            assert result is not None


class TestFTSIndex:
    """Tests for full-text search functionality."""

    def test_fts_indexes_on_insert(self, initialized_app):
        """FTS index should be updated on message insert."""
        app, _ = initialized_app

        from core.database import Database

        with app.app_context():
            # Create a folder first
            cursor = Database.execute("INSERT INTO folders (name) VALUES (?)", ("FTS Test",))
            folder_id = cursor.lastrowid

            # Insert a message
            Database.execute(
                """INSERT INTO messages
                   (folder_id, message_id, subject, sender, recipients, body_text, filepath)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    folder_id,
                    "<test@example.com>",
                    "Important Meeting",
                    "boss@company.com",
                    "team@company.com",
                    "Please attend the quarterly review meeting.",
                    "/fake/path.eml",
                ),
            )
            Database.commit()

            # Search should find it
            results = Database.fetchall(
                """SELECT m.* FROM messages m
                   JOIN messages_fts ON m.id = messages_fts.rowid
                   WHERE messages_fts MATCH ?""",
                ("quarterly",),
            )

            assert len(results) == 1
            assert results[0]["subject"] == "Important Meeting"

    def test_fts_search_multiple_fields(self, initialized_app):
        """FTS should search across subject, sender, recipients, and body."""
        app, _ = initialized_app

        from core.database import Database

        with app.app_context():
            cursor = Database.execute("INSERT INTO folders (name) VALUES (?)", ("Search Test",))
            folder_id = cursor.lastrowid

            # Insert messages with different searchable content
            messages = [
                ("1", "Budget Report", "alice@example.com", "bob@example.com", "Q1 numbers"),
                (
                    "2",
                    "Lunch Plans",
                    "bob@example.com",
                    "alice@example.com",
                    "Budget friendly restaurant",
                ),
                ("3", "Project Update", "charlie@example.com", "team@example.com", "On track"),
            ]

            for msg_id, subject, sender, recipients, body in messages:
                Database.execute(
                    """INSERT INTO messages
                       (folder_id, message_id, subject, sender, recipients, body_text, filepath)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (folder_id, msg_id, subject, sender, recipients, body, f"/fake/{msg_id}.eml"),
                )
            Database.commit()

            # Search for "budget" should find 2 messages
            results = Database.fetchall(
                """SELECT m.subject FROM messages m
                   JOIN messages_fts ON m.id = messages_fts.rowid
                   WHERE messages_fts MATCH ?""",
                ("budget",),
            )

            assert len(results) == 2
            subjects = [r["subject"] for r in results]
            assert "Budget Report" in subjects
            assert "Lunch Plans" in subjects


class TestSQLCipherRequired:
    """The archive must never be created or opened unencrypted.

    Regression guard: core/database.py falls back to plain sqlite3 so the
    module stays importable, but that fallback must never reach the archive.
    Before this guard existed, a missing sqlcipher3 produced a silent
    plaintext database with an unchanged UI and no error.
    """

    def test_require_sqlcipher_passes_when_available(self):
        """With a real SQLCipher build loaded, the guard is a no-op."""
        from core.database import SQLCIPHER_AVAILABLE, require_sqlcipher

        assert SQLCIPHER_AVAILABLE, "test environment lacks sqlcipher3"
        require_sqlcipher()

    def test_require_sqlcipher_raises_when_missing(self, monkeypatch):
        """With SQLCipher absent, the guard refuses."""
        import core.database as db

        monkeypatch.setattr(db, "SQLCIPHER_AVAILABLE", False)

        with pytest.raises(db.SQLCipherUnavailableError, match="UNENCRYPTED"):
            db.require_sqlcipher()

    def test_no_database_file_created_without_sqlcipher(self, monkeypatch, temp_data_dir):
        """The guard must fire BEFORE any file is written to disk."""
        import core.database as db
        from core.config import Config

        monkeypatch.setattr(db, "SQLCIPHER_AVAILABLE", False)
        db.Database._db_key = "41" * 32

        with pytest.raises(db.SQLCipherUnavailableError):
            db.Database.get_connection()

        assert not Config.get_database_path().exists(), (
            "an unencrypted database file was created on disk"
        )

    def test_archive_is_actually_encrypted_on_disk(self, initialized_app):
        """End-to-end: the real archive is ciphertext, not readable SQLite."""
        from core.config import Config

        db_path = Config.get_database_path()
        assert db_path.exists()

        raw = db_path.read_bytes()
        assert not raw.startswith(b"SQLite format 3"), (
            "archive has a plaintext SQLite header -- it is not encrypted"
        )
