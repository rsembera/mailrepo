"""
Backup concurrency and chain_id audit, ported from EdgeCase (2026-09-23).

EdgeCase (595081e, c451766) and Hermanubis (0096407) fixed a family of
backup bugs. MailRepo had already fixed the sequential filename
collision its own way, but four related problems were still open:

1. A full's chain_id was stamped to the second independently of its
   (microsecond-suffixed) filename, so two fulls in one second shared a
   chain and the first vanished from restore points. Needs no concurrency.
2. Filename claiming was check-then-act, and the failure cleanup
   unlinked whatever was at the path — possibly another backup's zip.
3. Nothing serialized backup creation or manifest read-modify-write, so
   concurrent backups dropped each other's manifest entries.
4. Two overlapping /auth/logout requests each ran a backup check; the
   idle watchdog could lock the archive in the middle of one.

Every test here was run red against the pre-fix code first.
"""

import hashlib
import threading
from datetime import datetime, timedelta

import pytest

from core.config import Config
from core.encryption import Encryption
from utils import backup
from web import idle
from web.blueprints import auth

PINNED = datetime(2026, 9, 23, 14, 25, 1, 100)


def _pin_clock(monkeypatch):
    """Pin utils.backup's clock to one second.

    Microseconds still advance by one per call, so the microsecond
    suffix can disambiguate while every second-resolution stamp — the
    plain filename and the old chain_id — is identical.
    """
    ticks = iter(range(1, 900_000))

    class _Pinned(datetime):
        @classmethod
        def now(cls, tz=None):
            return PINNED + timedelta(microseconds=next(ticks))

    monkeypatch.setattr(backup, "datetime", _Pinned)


def _add_message(name, body=b"x"):
    path = Config.get_archive_path() / "1" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(Encryption.encrypt(body))


def _zips_on_disk():
    return {p.name for p in Config.get_backup_path().glob("*.zip")}


def _zips_in_manifest():
    return {b["filename"] for b in backup.load_manifest()["backups"]}


def _block_first_call(monkeypatch, target, name):
    """Make the first call to target.name block until released.

    Returns (entered, release) events. Later calls pass straight through.
    """
    original = getattr(target, name)
    entered = threading.Event()
    release = threading.Event()
    calls = {"n": 0}
    lock = threading.Lock()

    def wrapper(*args, **kwargs):
        with lock:
            calls["n"] += 1
            first = calls["n"] == 1
        if first:
            entered.set()
            release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(target, name, wrapper)
    return entered, release, calls


@pytest.fixture
def archive(initialized_app):
    """A small archive and an unlocked app context; no backups yet."""
    app, password = initialized_app
    _add_message("000.eml.enc", b"one")
    _add_message("001.eml.enc", b"two")
    with app.app_context():
        yield app


# ---------------------------------------------------------------------------
# 1. chain_id for two fulls in one second
# ---------------------------------------------------------------------------


class TestSameSecondFullChains:
    def test_two_fulls_in_one_second_are_two_chains(self, archive, monkeypatch):
        _pin_clock(monkeypatch)
        first = backup.create_full_backup()
        second = backup.create_full_backup()

        assert first["filename"] != second["filename"]
        assert first["chain_id"] != second["chain_id"]

        full_chains = {p["chain_id"] for p in backup.get_restore_points() if p["type"] == "full"}
        assert first["chain_id"] in full_chains, "first full vanished from restore points"
        assert second["chain_id"] in full_chains

    def test_incremental_joins_the_newer_full(self, archive, monkeypatch):
        _pin_clock(monkeypatch)
        backup.create_full_backup()
        second = backup.create_full_backup()
        _add_message("002.eml.enc", b"three")
        incr = backup.create_incremental_backup()

        assert incr["chain_id"] == second["chain_id"]

    def test_reconstruction_agrees_with_the_manifest(self, archive, monkeypatch):
        _pin_clock(monkeypatch)
        a = backup.create_full_backup()
        b = backup.create_full_backup()
        _add_message("002.eml.enc", b"three")
        c = backup.create_incremental_backup()

        rebuilt = {
            e["filename"]: e["chain_id"]
            for e in backup.reconstruct_manifest_entries(Config.get_backup_path())
        }
        for info in (a, b, c):
            assert rebuilt[info["filename"]] == info["chain_id"], info["filename"]

    def test_unsuffixed_name_keeps_the_legacy_chain_id(self):
        """Existing manifests must stay valid without migration."""
        assert backup.chain_id_from_filename("full_2026-09-23_142501.zip") == "20260923_142501"
        assert (
            backup.chain_id_from_filename("full_2026-09-23_142501_000123.zip")
            == "20260923_142501_000123"
        )


# ---------------------------------------------------------------------------
# 2. Atomic name claiming; cleanup only ever removes the caller's own file
# ---------------------------------------------------------------------------


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestAtomicNameClaim:
    def test_reservation_creates_the_file_and_names_are_distinct(self, archive):
        d = Config.get_backup_path()
        d.mkdir(parents=True, exist_ok=True)
        first = backup.reserve_backup_path(d, "full")
        second = backup.reserve_backup_path(d, "full")
        assert first != second
        assert first.exists() and second.exists()
        assert (first.stat().st_mode & 0o777) == 0o600

    def test_failed_backup_never_touches_a_colliding_zip(self, archive, monkeypatch):
        """Simulate the race: a name check that says 'free' for a name
        another backup has already written. The loser must fail without
        truncating or deleting the winner's zip."""
        _pin_clock(monkeypatch)
        winner = backup.create_full_backup()
        winner_path = Config.get_backup_path() / winner["filename"]
        before = _sha(winner_path)

        real_exists = type(winner_path).exists

        def lying_exists(self, *a, **kw):
            if self.parent == winner_path.parent and self.suffix == ".zip":
                return False
            return real_exists(self, *a, **kw)

        monkeypatch.setattr(type(winner_path), "exists", lying_exists)

        def disk_full(*a, **kw):
            raise OSError("No space left on device")

        monkeypatch.setattr(backup, "get_file_hash", disk_full)

        with pytest.raises(ValueError):
            backup.create_full_backup()

        monkeypatch.setattr(type(winner_path), "exists", real_exists)
        assert winner_path.exists(), "the loser's cleanup deleted the winner's zip"
        assert _sha(winner_path) == before, "the loser overwrote the winner's zip"
        assert _zips_on_disk() == {winner["filename"]}

    def test_non_oserror_failure_leaves_no_partial_zip(self, archive, monkeypatch):
        backup.create_full_backup()
        before = _zips_on_disk()

        def boom(*a, **kw):
            raise RuntimeError("unexpected")

        monkeypatch.setattr(backup, "get_file_hash", boom)
        with pytest.raises(RuntimeError):
            backup.create_full_backup()

        assert _zips_on_disk() == before

    def test_pre_restore_with_nothing_to_back_up_reserves_nothing(self, archive, monkeypatch):
        backup.create_full_backup()
        before = _zips_on_disk()
        monkeypatch.setattr(backup, "get_all_backup_files", lambda: {})
        assert backup.create_pre_restore_backup() is None
        assert _zips_on_disk() == before


# ---------------------------------------------------------------------------
# 3. Backups and manifest read-modify-writes are serialized
# ---------------------------------------------------------------------------


class TestSerializedBackups:
    def test_second_backup_waits_and_nothing_is_orphaned(self, archive, monkeypatch):
        backup.create_full_backup()
        _add_message("002.eml.enc", b"three")

        entered, release, _ = _block_first_call(monkeypatch, backup, "verify_backup")
        results = {}

        def run(key, fn):
            try:
                results[key] = fn()
            except Exception as e:  # noqa: BLE001
                results[key] = e

        a = threading.Thread(target=run, args=("a", backup.create_incremental_backup))
        b = threading.Thread(target=run, args=("b", backup.create_backup))
        a.start()
        assert entered.wait(10), "thread A never reached verify_backup"
        b.start()
        b.join(timeout=1.0)  # unserialized, B finishes here
        release.set()
        a.join(10)
        b.join(10)

        assert not isinstance(results["a"], Exception), results["a"]
        assert results["a"] is not None
        assert results["b"] is None, "second backup should have found A's baseline: no changes"
        assert _zips_on_disk() == _zips_in_manifest(), "a zip on disk is missing from the manifest"


# ---------------------------------------------------------------------------
# 4. Duplicate /auth/logout; watchdog mid-backup
# ---------------------------------------------------------------------------


def _logged_in_client(app, token):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["login_id"] = idle.current_login_id()
        sess["csrf_token"] = token
    return client


class TestDuplicateLogout:
    def test_second_logout_skips_the_backup_check(self, initialized_app, monkeypatch):
        app, _ = initialized_app
        idle.new_login_id()
        entered, release, calls = _block_first_call(monkeypatch, auth, "_run_auto_backup_check")
        first = _logged_in_client(app, "tok1")
        second = _logged_in_client(app, "tok2")

        responses = {}
        t = threading.Thread(
            target=lambda: responses.setdefault(
                "first", first.post("/auth/logout", data={"csrf_token": "tok1"})
            )
        )
        t.start()
        assert entered.wait(10)
        responses["second"] = second.post(
            "/auth/logout", data={"csrf_token": "tok2", "reason": "timeout"}
        )
        release.set()
        t.join(10)

        assert calls["n"] == 1, "the duplicate logout ran a second backup check"
        assert responses["first"].status_code == 302
        assert responses["second"].status_code == 302
        assert Encryption.is_unlocked() is False

    def test_logout_after_lock_skips_the_backup_check(self, initialized_app, monkeypatch):
        app, _ = initialized_app
        idle.new_login_id()
        calls = {"n": 0}
        monkeypatch.setattr(
            auth, "_run_auto_backup_check", lambda: calls.__setitem__("n", calls["n"] + 1)
        )
        client = _logged_in_client(app, "tok")
        Encryption.lock()
        client.post("/auth/logout", data={"csrf_token": "tok"})
        assert calls["n"] == 0


class TestWatchdogDuringBackup:
    def test_watchdog_does_not_lock_mid_backup(self, archive, monkeypatch):
        from core.database import set_setting

        set_setting("session_timeout", "15")
        backup.create_full_backup()
        _add_message("002.eml.enc", b"three")
        entered, release, _ = _block_first_call(monkeypatch, backup, "verify_backup")

        result = {}
        t = threading.Thread(target=lambda: result.setdefault("r", backup.create_backup()))
        t.start()
        assert entered.wait(10)

        idle.touch(now=1_000_000.0)
        locked = idle.check_and_lock(now=1_000_000.0 + 60 * 60)
        release.set()
        t.join(10)

        assert locked is False, "watchdog locked the archive in the middle of a backup"
        assert result["r"]["mac"], "backup lost its integrity tag to a mid-backup lock"
        # Once the backup is done, the next tick locks.
        assert idle.check_and_lock(now=1_000_000.0 + 60 * 60) is True

    def test_watchdog_does_not_lock_during_a_logout(self, initialized_app, monkeypatch):
        from core.database import set_setting

        app, _ = initialized_app
        set_setting("session_timeout", "15")
        idle.new_login_id()
        entered, release, _ = _block_first_call(monkeypatch, auth, "_run_auto_backup_check")
        client = _logged_in_client(app, "tok")
        t = threading.Thread(target=lambda: client.post("/auth/logout", data={"csrf_token": "tok"}))
        t.start()
        assert entered.wait(10)

        idle.touch(now=1_000_000.0)
        locked = idle.check_and_lock(now=1_000_000.0 + 60 * 60)
        release.set()
        t.join(10)

        assert locked is False, "watchdog locked the archive under a running logout"
        assert Encryption.is_unlocked() is False  # the logout itself locked
