"""
Tests for the threading lock and migration flag added to Database in the
crypto refactor (docs/Crypto_Refactor_Plan.md scope item 5).

These tests verify:
- Concurrent threads can use the Database without deadlock or corruption.
- acquire_for_migration() blocks other threads until release.
- The migration thread itself can still call Database methods during the
  exclusive window (thread-id bypass works).
- The reentrant lock allows nested calls (fetchone -> execute) on a
  single thread.
"""

import threading
import time

import pytest

from core.database import Database
from core.encryption import Encryption


@pytest.fixture(autouse=True)
def _initialized_db():
    """Bring up a working Database (encrypted, schema applied) for each test.

    Uses the new v2 Encryption.initialize() to get a db_key, hands it to
    Database, then calls Database.initialize() to create the schema. The
    autouse=True annotation means every test in this file runs in this state
    without having to ask for the fixture explicitly. Teardown clears the
    migration flag in case a test left it set (defensive).
    """
    Encryption.initialize("ThreadingTestPassword123!")
    Database.set_key(Encryption.get_db_key())
    Database.initialize()
    yield
    # Defensive cleanup: if any test forgot to release_after_migration,
    # don't let it poison the next test.
    if Database._migration_active:
        try:
            Database.release_after_migration()
        except Exception:
            pass


# ============================================================
# CONCURRENT NORMAL ACCESS
# ============================================================


class TestConcurrentNormalAccess:
    """Multiple threads doing ordinary queries should not deadlock or corrupt
    results. The lock serializes them but they all complete cleanly."""

    def test_two_threads_can_query_concurrently(self):
        # Make sure schema exists.
        Database.execute(
            "CREATE TABLE IF NOT EXISTS thread_test (id INTEGER PRIMARY KEY, val INTEGER)"
        )
        Database.execute("DELETE FROM thread_test")
        Database.commit()

        results = []
        errors = []

        def worker(start, end):
            try:
                for i in range(start, end):
                    Database.execute("INSERT INTO thread_test (val) VALUES (?)", (i,))
                Database.commit()
                rows = Database.fetchall("SELECT COUNT(*) AS c FROM thread_test")
                results.append(rows[0]["c"])
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=worker, args=(0, 50))
        t2 = threading.Thread(target=worker, args=(100, 150))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert errors == [], f"thread errors: {errors}"
        # Each thread saw at least its own 50 rows committed.
        assert all(r >= 50 for r in results)
        # Final state: exactly 100 rows.
        total = Database.fetchone("SELECT COUNT(*) AS c FROM thread_test")["c"]
        assert total == 100


# ============================================================
# MIGRATION LOCK BLOCKS OTHER THREADS
# ============================================================


class TestMigrationLock:
    """acquire_for_migration() must block other threads until release."""

    def test_acquire_blocks_other_thread_queries(self):
        Database.execute("CREATE TABLE IF NOT EXISTS lock_test (id INTEGER PRIMARY KEY)")
        Database.commit()

        other_thread_result = {"raised": None, "elapsed": None}

        def blocked_worker():
            t0 = time.perf_counter()
            try:
                Database.fetchone("SELECT 1")
                other_thread_result["raised"] = False
            except RuntimeError as e:
                other_thread_result["raised"] = True
                other_thread_result["error"] = str(e)
            other_thread_result["elapsed"] = time.perf_counter() - t0

        # Acquire migration exclusivity on the main thread.
        Database.acquire_for_migration()
        try:
            # Start a worker that tries to query; it should block on the lock.
            t = threading.Thread(target=blocked_worker)
            t.start()
            # Give it time to actually try the query.
            time.sleep(0.2)
            # While we hold the migration lock, the worker has not completed.
            assert t.is_alive(), "worker should still be blocked on the lock"
            assert other_thread_result["elapsed"] is None
        finally:
            Database.release_after_migration()

        # After release, the worker proceeds. Since we cleared the migration
        # flag before releasing, the worker should succeed (not raise).
        t.join(timeout=5.0)
        assert not t.is_alive(), "worker did not complete after release"
        assert other_thread_result["raised"] is False, (
            f"worker should have succeeded after release, got error: "
            f"{other_thread_result.get('error')}"
        )

    def test_migration_thread_can_still_query_during_window(self):
        """The migration's own thread bypasses the flag check, so it can do
        normal Database operations during Phase 2 (which it needs to: WAL
        checkpoint, credential re-encryption queries, etc.)."""
        Database.execute("CREATE TABLE IF NOT EXISTS migration_self_test (id INTEGER PRIMARY KEY)")
        Database.commit()

        Database.acquire_for_migration()
        try:
            # Same thread that acquired: should be able to query freely.
            row = Database.fetchone("SELECT 1 AS v")
            assert row["v"] == 1
            Database.execute("INSERT INTO migration_self_test DEFAULT VALUES")
            Database.commit()
        finally:
            Database.release_after_migration()

        # And after release, ordinary queries still work.
        assert Database.fetchone("SELECT COUNT(*) AS c FROM migration_self_test")["c"] >= 1

    def test_release_unblocks_waiting_threads(self):
        """A thread waiting on the lock should proceed promptly after
        release_after_migration() is called."""
        Database.execute("CREATE TABLE IF NOT EXISTS release_test (id INTEGER PRIMARY KEY)")
        Database.commit()

        worker_done = threading.Event()
        worker_error = {"err": None}

        def worker():
            try:
                Database.execute("INSERT INTO release_test DEFAULT VALUES")
                Database.commit()
            except Exception as e:
                worker_error["err"] = e
            worker_done.set()

        Database.acquire_for_migration()
        t = threading.Thread(target=worker)
        t.start()
        time.sleep(0.1)
        assert not worker_done.is_set(), "worker should be blocked"

        Database.release_after_migration()
        # Worker should complete promptly (well under a second).
        assert worker_done.wait(timeout=2.0), "worker did not complete after release"
        assert worker_error["err"] is None


# ============================================================
# REENTRANT LOCK
# ============================================================


class TestReentrantLock:
    """RLock allows the same thread to acquire the lock multiple times.
    Methods like fetchone() internally call execute(), both of which acquire
    the lock; this test ensures that nested call works without deadlock."""

    def test_fetchone_works(self):
        """fetchone() -> execute() is a nested acquisition on the same thread."""
        row = Database.fetchone("SELECT 1 AS v")
        assert row["v"] == 1

    def test_transaction_with_nested_calls_works(self):
        """transaction() holds the lock; calls inside it re-acquire."""
        with Database.transaction():
            # transaction holds the lock; these all re-acquire.
            Database.execute("CREATE TABLE IF NOT EXISTS rlock_test (id INTEGER PRIMARY KEY)")
            Database.execute("INSERT INTO rlock_test DEFAULT VALUES")
            row = Database.fetchone("SELECT COUNT(*) AS c FROM rlock_test")
            assert row["c"] >= 1
