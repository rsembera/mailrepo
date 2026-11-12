"""
Code review 2026-11, findings 10 and 11.

10: the idle lock used to fire in the middle of a long job the user had
started (a commit, an export, a key rotation), closing the database and
the mail-server connection under it. It now waits for the job.

11: locking closed the database connection but kept its key, so the
next call from any thread reopened it.
"""

import time

import pytest

from core import Database, Encryption
from core.database import set_setting
from web import idle


@pytest.fixture
def unlocked(initialized_app):
    set_setting("session_timeout", "15")
    idle.touch()
    yield
    idle._busy.clear()


FAR_FUTURE = 10 * 365 * 86400


class TestIdleLockWaitsForWork:
    def test_idle_archive_locks(self, unlocked):
        assert idle.check_and_lock(now=time.time() + 3600) is True
        assert not Encryption.is_unlocked()

    def test_archive_does_not_lock_under_a_running_job(self, unlocked):
        with idle.busy("commit"):
            assert idle.is_busy()
            assert idle.check_and_lock(now=time.time() + 3600) is False
            assert Encryption.is_unlocked()
        assert not idle.is_busy()

    def test_the_idle_clock_restarts_when_the_job_ends(self, unlocked):
        idle.touch(time.time() - 3600)  # the user walked away an hour ago
        with idle.busy("export"):
            pass
        assert idle.seconds_idle() < 5
        assert idle.check_and_lock() is False
        # ...and it does lock once a full timeout has passed with no work.
        assert idle.check_and_lock(now=time.time() + 3600) is True

    def test_nested_and_concurrent_jobs_are_counted(self, unlocked):
        with idle.busy("commit"):
            with idle.busy("commit"):
                with idle.busy("export"):
                    assert idle.busy_with() == ["commit", "export"]
                assert idle.busy_with() == ["commit"]
            assert idle.is_busy()
        assert not idle.is_busy()

    def test_a_job_that_raises_is_still_cleared(self, unlocked):
        with pytest.raises(ValueError):
            with idle.busy("commit"):
                raise ValueError("boom")
        assert not idle.is_busy()

    def test_streaming_wrapper_holds_busy_until_the_stream_ends(self, unlocked):
        seen = []

        def events():
            seen.append(idle.is_busy())
            yield "a"
            seen.append(idle.is_busy())
            yield "b"

        stream = idle.stream_while_busy("commit", events())
        assert list(stream) == ["a", "b"]
        assert seen == [True, True]
        assert not idle.is_busy()

    def test_a_stream_the_client_abandons_is_cleared(self, unlocked):
        def events():
            yield "a"
            yield "b"

        stream = idle.stream_while_busy("commit", events())
        next(stream)
        assert idle.is_busy()
        stream.close()  # what the server does when the page goes away
        assert not idle.is_busy()

    def test_session_does_not_time_out_under_a_running_job(self, authenticated_client, unlocked):
        with authenticated_client._client.session_transaction() as sess:
            sess["last_activity"] = time.time() - 3600  # well past 15 minutes

        with idle.busy("commit"):
            resp = authenticated_client.get("/api/session-status")
            body = resp.get_json()
            assert resp.status_code == 200
            assert body["logged_in"] is True
            assert body["warning_needed"] is False
        assert Encryption.is_unlocked()

    def test_session_still_times_out_when_nothing_is_running(self, authenticated_client, unlocked):
        with authenticated_client._client.session_transaction() as sess:
            sess["last_activity"] = time.time() - 3600
        resp = authenticated_client.get("/api/session-status")
        assert resp.status_code == 401
        assert not Encryption.is_unlocked()


class TestLockDropsTheDatabaseKey:
    def test_database_does_not_reopen_after_a_lock(self, unlocked):
        Database.execute("INSERT INTO folders (name) VALUES ('Client: Smith')")
        Database.commit()

        Database.close()
        Encryption.lock()  # exactly what logout and the idle watchdog do

        assert Database._db_key is None
        with pytest.raises(RuntimeError, match="key not set"):
            Database.fetchone("SELECT name FROM folders")

    def test_idle_lock_drops_it_too(self, unlocked):
        assert idle.check_and_lock(now=time.time() + 3600) is True
        assert Database._db_key is None
        assert Database._connection is None

    def test_unlocking_again_works(self, initialized_app, unlocked):
        _app, password = initialized_app
        Database.execute("INSERT INTO folders (name) VALUES ('kept')")
        Database.commit()
        Database.close()
        Encryption.lock()

        Encryption.unlock(password)
        Database.set_key(Encryption.get_db_key())
        assert Database.fetchone("SELECT name FROM folders")["name"] == "kept"
