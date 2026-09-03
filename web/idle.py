"""
Process-level idle tracking and the server-side idle-lock watchdog.

The session cookie's ``last_activity`` is per-request and is refreshed by
almost everything the browser does, including the 30-second status poll.
It cannot, on its own, tell whether the *person* has walked away. This
module keeps one process-wide timestamp that only real activity
advances, and runs a daemon thread that locks the archive when that
timestamp goes stale — independent of any request arriving, so a closed
tab or a dead webview still locks.

Only ``touch()`` moves the clock. The status poll and the client's
own housekeeping deliberately do not call it.
"""

import threading
import time

from core import Encryption
from core.database import Database, get_setting
from utils.log import get_logger

log = get_logger(__name__)

_lock = threading.Lock()
_last_activity: float = time.time()
_watchdog_started = False

# How often the watchdog wakes up. Granularity of the idle lock, not its
# length: a 15-minute timeout locks between 15:00 and 15:15 after the
# last real activity.
WATCHDOG_INTERVAL_SECONDS = 15


def touch(now: float | None = None) -> None:
    """Record real user activity."""
    global _last_activity
    with _lock:
        _last_activity = time.time() if now is None else now


def last_activity() -> float:
    """Timestamp of the most recent real activity."""
    with _lock:
        return _last_activity


def seconds_idle(now: float | None = None) -> float:
    """Seconds since the most recent real activity."""
    return (time.time() if now is None else now) - last_activity()


def configured_timeout_seconds() -> int:
    """The user's idle timeout in seconds; 0 means never.

    Reads the settings table, so only meaningful while unlocked.
    """
    try:
        minutes = int(get_setting("session_timeout", "30"))
    except (ValueError, TypeError):
        minutes = 30
    return max(0, minutes) * 60


def check_and_lock(now: float | None = None) -> bool:
    """Lock the archive if it is unlocked and idle past the timeout.

    Returns True if a lock happened. Safe to call from any thread and
    at any time; a no-op when locked or when the timeout is "Never".
    Split out from the thread loop so tests can drive it directly.
    """
    if not Encryption.is_unlocked():
        return False

    timeout = configured_timeout_seconds()
    if timeout == 0:
        return False

    if seconds_idle(now) <= timeout:
        return False

    log.info("Idle timeout reached; locking archive")
    try:
        Database.close()
    except Exception as e:  # noqa: BLE001
        log.warning(f"Database close during idle lock failed: {e}")
    Encryption.lock()
    return True


def _watchdog_loop() -> None:
    while True:
        time.sleep(WATCHDOG_INTERVAL_SECONDS)
        try:
            check_and_lock()
        except Exception as e:  # noqa: BLE001
            # The watchdog must never die; a lock that fails once will be
            # retried on the next tick.
            log.warning(f"Idle watchdog error: {e}")


def start_watchdog() -> None:
    """Start the idle-lock thread once per process."""
    global _watchdog_started
    with _lock:
        if _watchdog_started:
            return
        _watchdog_started = True
    threading.Thread(target=_watchdog_loop, name="idle-watchdog", daemon=True).start()
    log.debug("Idle watchdog started")
