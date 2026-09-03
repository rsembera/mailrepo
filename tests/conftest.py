"""
Pytest configuration and fixtures for MailRepo tests.
"""

import secrets
import shutil
import tempfile
from pathlib import Path

import pytest

from web import idle


@pytest.fixture(scope="session")
def test_data_dir():
    """Create a temporary directory for test data that persists for the session."""
    tmpdir = tempfile.mkdtemp(prefix="mailrepo_test_")
    yield Path(tmpdir)
    # Cleanup after all tests
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def temp_data_dir(tmp_path):
    """Create a fresh temporary directory for each test."""
    data_dir = tmp_path / "mailrepo_data"
    data_dir.mkdir()
    return data_dir


@pytest.fixture(autouse=True)
def reset_singletons(temp_data_dir, tmp_path, monkeypatch):
    """Reset all singleton state before each test."""
    # Set environment variable BEFORE importing modules
    monkeypatch.setenv("MAILREPO_DATA_DIR", str(temp_data_dir))

    # Run Argon2id at the cheap work factor (ported from Daybook, Session
    # 81). Real algorithm, same call site, smaller cost — the suite's
    # runtime was almost entirely password hashing. The cheap path
    # requires BOTH this flag and the data-dir override above; a real
    # install has neither. test_kdf_cost.py pins the production numbers
    # and proves a full-cost round trip separately.
    monkeypatch.setenv("MAILREPO_FAST_KDF", "1")

    # This re-rooting is also what isolates the unverified-restore
    # marker (data/.restore_unverified): it is deleted on every
    # successful login, so an unisolated auth test would silently
    # unlink the real install's marker. EdgeCase needed a dedicated
    # fixture for this because its DATA_DIR was not per-test; here the
    # whole data directory already is. test_unverified_restore.py
    # carries a tripwire asserting the marker path lives under the
    # per-test temp dir, so moving the marker elsewhere (e.g. the state
    # dir) reopens this question loudly rather than quietly.

    # Keep the backup-locations record out of the real home directory,
    # and as a SIBLING of the app folder rather than a child. In
    # production it lives in the OS application-state directory
    # precisely so that losing the app folder does not lose it; nesting
    # it under temp_data_dir here would quietly void that property for
    # every test that depends on it.
    monkeypatch.setenv("MAILREPO_STATE_DIR", str(tmp_path / "mailrepo_state"))

    # Reset Config's cached path
    from core.config import Config

    Config._base_path = None

    # Force Config to use our temp dir
    Config.set_base_path(temp_data_dir)

    # Reset Encryption state
    from core.encryption import Encryption

    Encryption.lock()

    # Reset Database state
    from core.database import Database

    if Database._connection is not None:
        try:
            Database._connection.close()
        except Exception:
            pass
    Database._connection = None
    Database._db_key = None

    yield

    # Cleanup after test
    if Database._connection is not None:
        try:
            Database._connection.close()
        except Exception:
            pass
    Database._connection = None
    Database._db_key = None
    Encryption.lock()
    Config._base_path = None


@pytest.fixture
def app(temp_data_dir):
    """Create a test Flask application."""
    from web import create_app

    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    return app


@pytest.fixture
def client(app):
    """Create a test client."""
    return app.test_client()


@pytest.fixture
def initialized_app(app, temp_data_dir):
    """Create an app with encryption initialized and database set up."""
    from core.database import Database
    from core.encryption import Encryption

    test_password = "TestPassword123!"

    with app.app_context():
        # Initialize encryption
        Encryption.initialize(test_password)

        # Set database key and initialize
        Database.set_key(Encryption.get_db_key())
        Database.initialize()

        yield app, test_password


@pytest.fixture
def authenticated_client(initialized_app):
    """Create a test client that's already authenticated with CSRF token."""
    app, password = initialized_app

    # Create test client with session support
    client = app.test_client()

    # Generate a CSRF token
    csrf_token = secrets.token_hex(32)

    # Set up session with authentication and CSRF token
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["login_id"] = idle.new_login_id()
        sess["csrf_token"] = csrf_token

    # Create a wrapper that automatically adds CSRF header
    class AuthenticatedClient:
        def __init__(self, client, csrf_token):
            self._client = client
            self._csrf_token = csrf_token

        def get(self, *args, **kwargs):
            return self._client.get(*args, **kwargs)

        def post(self, *args, **kwargs):
            headers = kwargs.pop("headers", {})
            headers["X-CSRF-Token"] = self._csrf_token
            kwargs["headers"] = headers
            return self._client.post(*args, **kwargs)

        def put(self, *args, **kwargs):
            headers = kwargs.pop("headers", {})
            headers["X-CSRF-Token"] = self._csrf_token
            kwargs["headers"] = headers
            return self._client.put(*args, **kwargs)

        def patch(self, *args, **kwargs):
            headers = kwargs.pop("headers", {})
            headers["X-CSRF-Token"] = self._csrf_token
            kwargs["headers"] = headers
            return self._client.patch(*args, **kwargs)

        def delete(self, *args, **kwargs):
            headers = kwargs.pop("headers", {})
            headers["X-CSRF-Token"] = self._csrf_token
            kwargs["headers"] = headers
            return self._client.delete(*args, **kwargs)

        def session_transaction(self):
            return self._client.session_transaction()

    return AuthenticatedClient(client, csrf_token)


@pytest.fixture
def sample_email():
    """Return a sample RFC 2822 email for testing."""
    return b"""From: sender@example.com
To: recipient@example.com
Subject: Test Email
Date: Sat, 15 Feb 2026 10:30:00 -0500
Message-ID: <test-123@example.com>
MIME-Version: 1.0
Content-Type: text/plain; charset="utf-8"

This is a test email body.
It has multiple lines.
"""


@pytest.fixture
def sample_html_email():
    """Return a sample HTML email for testing."""
    return b"""From: sender@example.com
To: recipient@example.com
Subject: HTML Test Email
Date: Sat, 15 Feb 2026 10:30:00 -0500
Message-ID: <html-test-123@example.com>
MIME-Version: 1.0
Content-Type: multipart/alternative; boundary="boundary123"

--boundary123
Content-Type: text/plain; charset="utf-8"

Plain text version.

--boundary123
Content-Type: text/html; charset="utf-8"

<html><body><p>HTML version with <strong>formatting</strong>.</p></body></html>

--boundary123--
"""
