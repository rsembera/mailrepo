"""
MailRepo - v2-native master password change.

Re-encrypts every .eml.enc file and every stored IMAP credential under
the new password\'s derived keys, then PRAGMA-rekeys the SQLCipher DB,
then writes a new v2 salt file with the new verification token. The
session\'s in-memory keys are swapped to the new values so the running
app keeps working without forcing a logout.

This is structurally similar to the v1->v2 crypto migration in
core/migration.py, with two differences:

1. No version-byte distinction between "old key" and "new key" output —
   both are 0x02-prefixed v2. To support resumability after an interrupted
   walk, the file step tries the OLD key first, then the NEW key as a
   fallback. A file decryptable only by NEW means it was already re-
   encrypted in a previous attempt and we skip it.

2. Phase split is implicit, not marker-based. The file walk + credentials
   re-encryption happens first; the DB rekey + salt file rewrite happen
   at the end. If a crash happens between the two, recovery is restore-
   from-backup. The backup <=24h check at the top is non-overridable, same
   policy as the migration\'s Phase 2.

Halt-loud on corruption: if a file decrypts cleanly with neither the old
nor the new file_key, the function raises PasswordChangeCorruptionError
naming the specific file. We do not silently skip.
"""

import base64
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator, Optional

from utils.backup import get_verified_latest_restore_point
from utils.log import get_logger

from .config import Config
from .database import Database
from .encryption import (
    Encryption,
    InvalidPasswordError,
)

log = get_logger(__name__)

# ============================================================
# EXCEPTIONS
# ============================================================


class PasswordChangeError(Exception):
    """Raised when password change cannot proceed or fails partway."""

    pass


class PasswordChangeCorruptionError(PasswordChangeError):
    """Raised when a file decrypts with neither the old nor the new key."""

    def __init__(self, filepath: str, original_error: Exception):
        self.filepath = filepath
        self.original_error = original_error
        super().__init__(
            f"Corruption detected during password change: {filepath} could "
            f"not be decrypted with either the old or the new file key. "
            f"({type(original_error).__name__}: {original_error}). Password "
            f"change halted. Restore from backup or investigate the file."
        )


# Backup-age threshold mirrors the migration\'s Phase 2 policy.
MAX_BACKUP_AGE_HOURS = 24.0


def change_master_password(
    old_password: str,
    new_password: str,
    progress_cb: Optional[Callable[[dict], None]] = None,
) -> dict:
    """Change the master password for a v2 archive.

    Walks every .eml.enc file decrypting with the old file_key and re-
    encrypting with the new one; does the same for stored credentials;
    then rekeys SQLCipher to the new db_key and rewrites the v2 salt file
    with a new verification token.

    progress_cb is called with status dicts matching the existing
    settings.js vocabulary so the frontend works without changes:
      {"status": "counting", "message": "Counting encrypted files..."}
      {"status": "counted", "total": int, "message": "Found N files"}
      {"status": "encrypting", "total": int, "current": int, "message": ...}
      {"status": "credentials", "message": "Re-encrypting credentials..."}
      {"status": "database", "message": "Rekeying database..."}
      {"status": "finalizing", "message": "Updating salt file..."}
      {"status": "complete", "message": "Password changed successfully"}

    Refuses to proceed if no backup is <=24h old (non-overridable). The
    DB rekey + salt file write window is not resumable; the backup is the
    recovery path.

    Returns a summary dict on success. Raises:
      PasswordChangeError: backup too old, wrong password, or db rekey fail.
      PasswordChangeCorruptionError: a file decrypted with neither key.
    """
    # 1. Non-overridable backup check: recent AND verified usable on disk.
    #
    #    The manifest is a claim, not evidence. Before opening the rekey
    #    window we open every file in the newest restore chain — that is
    #    what catches a deleted backup, a truncated write, or an
    #    iCloud-evicted placeholder that still looks present to exists().
    point, problems = get_verified_latest_restore_point()
    if problems:
        detail = "; ".join(problems)
        raise PasswordChangeError(
            f"Password change refused: the most recent backup did not "
            f"verify. {detail}. The DB rekey window is not resumable; the "
            f"backup is the recovery path. Take a fresh backup and retry."
        )

    age = _restore_point_age_hours(point)
    if age is None or age > MAX_BACKUP_AGE_HOURS:
        age_repr = f"{age:.1f}h" if age is not None else "unknown age"
        raise PasswordChangeError(
            f"Password change refused: most recent verified backup is {age_repr}. "
            f"The DB rekey window is not resumable; the backup is the "
            f"recovery path. Take a fresh backup and retry."
        )

    # 2. Encryption must be unlocked (it normally is — the user is logged in).
    if not Encryption.is_unlocked():
        raise PasswordChangeError("Encryption is locked. Log in and retry.")

    # 3. Verify the old password by deriving its v2 file_key and comparing
    #    against the in-memory current key. We don\'t re-derive via salt
    #    decrypt because that would be slow; instead we derive once and
    #    check equality against what\'s already loaded.
    try:
        old_file_key = Encryption.derive_v2_file_key_for_password(old_password)
    except Exception as e:
        raise PasswordChangeError(f"Failed to derive old keys: {e}")

    if old_file_key != Encryption._file_key_v2:
        raise InvalidPasswordError("Current password is incorrect.")

    # 4. Derive new keys.
    try:
        new_file_key = Encryption.derive_v2_file_key_for_password(new_password)
        new_db_key_hex = Encryption.derive_v2_db_key_for_password(new_password)
    except Exception as e:
        raise PasswordChangeError(f"Failed to derive new keys: {e}")

    if new_file_key == old_file_key:
        raise PasswordChangeError(
            "New password derives to the same keys as the old one. Choose a different password."
        )

    # 5. File walk: decrypt with old, encrypt with new, atomic replace.
    if progress_cb:
        progress_cb({"status": "counting", "message": "Counting encrypted files..."})

    files = list(_iter_archive_files())
    total = len(files)

    if progress_cb:
        progress_cb(
            {
                "status": "counted",
                "total": total,
                "message": f"Found {total} encrypted files",
            }
        )

    for i, path in enumerate(files):
        _rekey_file(path, old_file_key, new_file_key)
        if (i + 1) % 10 == 0 or (i + 1) == total:
            if progress_cb:
                progress_cb(
                    {
                        "status": "encrypting",
                        "total": total,
                        "current": i + 1,
                        "message": f"Re-encrypting {i + 1} of {total}...",
                    }
                )

    # 6. Stored credentials.
    if progress_cb:
        progress_cb(
            {
                "status": "credentials",
                "message": "Re-encrypting account credentials...",
            }
        )
    cred_count = _rekey_credentials(old_file_key, new_file_key)

    # 7. Database rekey + salt file rewrite. These two operations together
    #    form an irreversible commit point; if anything fails between them,
    #    recovery is restore-from-backup.
    #
    #    Write the interruption marker BEFORE entering the window. If we
    #    crash inside it, the next startup finds the marker and can say
    #    what actually happened. Without it, a half-rekeyed archive
    #    presents as "invalid master password" — the single most
    #    misleading message we could show someone whose password is
    #    correct and whose data is still recoverable.
    _write_interruption_marker(point)

    if progress_cb:
        progress_cb({"status": "database", "message": "Rekeying database..."})

    Database.acquire_for_migration()
    try:
        conn = Database.get_connection()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute(f"PRAGMA rekey = \"x'{new_db_key_hex}'\"")
        Database._db_key = new_db_key_hex

        if progress_cb:
            progress_cb({"status": "finalizing", "message": "Updating salt file..."})

        # Swap in-memory keys to new BEFORE writing salt file (write_v2_salt_file
        # uses the in-memory file_key to encrypt the verification token).
        Encryption._file_key_v2 = new_file_key
        Encryption._db_key_v2 = new_db_key_hex
        Encryption.write_v2_salt_file()
    finally:
        Database.release_after_migration()

    # Window closed successfully — the marker's job is done.
    clear_interruption_marker()

    if progress_cb:
        progress_cb(
            {
                "status": "complete",
                "message": "Password changed successfully.",
            }
        )

    return {"files": total, "credentials": cred_count}


# ============================================================
# FILE / CREDENTIAL REKEY HELPERS
# ============================================================


def _rekey_file(path: Path, old_key: bytes, new_key: bytes) -> bool:
    """Re-encrypt one file from old_key to new_key. Atomic replace.

    Returns True if re-encrypted, False if the file was already encrypted
    under new_key (already-migrated, skipped).

    Raises PasswordChangeCorruptionError if neither key decrypts.
    """
    with open(path, "rb") as fh:
        data = fh.read()

    # Try old key first (the common case).
    try:
        plaintext = Encryption._decrypt_v2_with_key(data, old_key)
    except Exception as old_err:
        # Fall back to new key — resumability for an interrupted previous run.
        try:
            Encryption._decrypt_v2_with_key(data, new_key)
            return False  # already migrated; skip
        except Exception:
            raise PasswordChangeCorruptionError(str(path), old_err)

    new_data = Encryption._encrypt_v2_with_key(plaintext, new_key)
    _atomic_write_file(path, new_data)
    return True


def _rekey_credentials(old_key: bytes, new_key: bytes) -> int:
    """Re-encrypt every accounts.credentials_encrypted from old_key to new_key.

    Uses the same try-old-then-new resumability pattern as _rekey_file.
    Returns the count of credentials successfully re-encrypted (skipped or
    already-new entries are excluded from the count).
    """
    rows = Database.fetchall(
        "SELECT id, credentials_encrypted FROM accounts WHERE credentials_encrypted IS NOT NULL"
    )
    count = 0
    for row in rows:
        enc_str = row["credentials_encrypted"]
        if not enc_str:
            continue
        try:
            raw = base64.urlsafe_b64decode(enc_str.encode("ascii"))
        except Exception:
            continue

        # Try old key, fall back to new key for resumability.
        try:
            plaintext = Encryption._decrypt_v2_with_key(raw, old_key)
        except Exception as old_err:
            try:
                Encryption._decrypt_v2_with_key(raw, new_key)
                continue  # already migrated
            except Exception:
                raise PasswordChangeCorruptionError(f"accounts.id={row['id']}/credentials", old_err)

        new_raw = Encryption._encrypt_v2_with_key(plaintext, new_key)
        new_enc = base64.urlsafe_b64encode(new_raw).decode("ascii")
        Database.execute(
            "UPDATE accounts SET credentials_encrypted = ? WHERE id = ?",
            (new_enc, row["id"]),
        )
        count += 1
    Database.commit()
    return count


# ============================================================
# FILE SYSTEM HELPERS
# ============================================================


def _iter_archive_files() -> Iterator[Path]:
    """Yield every .eml.enc file under the archive root."""
    try:
        archive_root = Config.get_archive_path()
    except Exception:
        return
    if not archive_root.exists():
        return
    for path in archive_root.rglob("*.eml.enc"):
        if path.is_file():
            yield path


# ============================================================
# INTERRUPTION MARKER
# ============================================================
#
# The DB rekey + salt file rewrite is a non-resumable window. If the
# process dies inside it, the archive may be half-rekeyed: the DB on the
# new key, the salt file still on the old one (or vice versa). Unlock
# then fails, and the honest-looking symptom is "invalid master
# password" — which sends the user hunting for a password problem that
# does not exist, and risks them concluding their data is lost.
#
# The marker turns that into a specific, actionable message naming the
# backup that was verified immediately beforehand.


def get_interruption_marker_path() -> Path:
    return Config.get_data_path() / ".password_change_in_progress"


def _write_interruption_marker(point, phase: str = "db_rekey_and_salt_write") -> None:
    """Record that the irreversible window is open. Best-effort by design.

    Marker-write failure must not abort a password change the user has
    already authorised and which has already re-encrypted the archive —
    that would leave a worse mess than the one the marker guards against.

    The phase argument lets the v3 migration reuse this mechanism rather
    than growing a second, subtly-different one: both operations open the
    same non-resumable window and both need the next launch to explain
    itself.
    """
    try:
        payload = {
            "started_at": datetime.now().isoformat(),
            "phase": phase,
            "verified_backup": (point or {}).get("filename"),
            "verified_backup_created_at": (point or {}).get("created_at"),
        }
        _atomic_write_file(
            get_interruption_marker_path(),
            json.dumps(payload, indent=2).encode("utf-8"),
        )
    except Exception as e:
        log.warning(f"Could not write password-change interruption marker: {e}")


def clear_interruption_marker() -> None:
    """Remove the marker after the window closes cleanly."""
    try:
        get_interruption_marker_path().unlink(missing_ok=True)
    except Exception as e:
        log.warning(f"Could not clear password-change interruption marker: {e}")


def check_password_change_interrupted() -> Optional[dict]:
    """Return marker contents if a previous password change was interrupted.

    Called at startup. Returns None in the normal case.
    """
    path = get_interruption_marker_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        # A corrupt marker still means a change was interrupted; that fact
        # matters more than the details we failed to parse.
        return {"started_at": None, "phase": "unknown", "verified_backup": None}


def describe_interrupted_password_change(marker: dict) -> str:
    """Human-readable guidance for an interrupted password change."""
    started = marker.get("started_at") or "an earlier session"
    backup = marker.get("verified_backup")

    if marker.get("phase") == "v3_migration":
        lines = [
            "A recovery-key upgrade was interrupted before it finished.",
            f"It began at {started} and stopped partway through re-encrypting",
            "the archive.",
            "",
            "What this means: some files may be encrypted under the new key and",
            "some under the old. MailRepo handles that automatically when you",
            "log in and re-run the upgrade — it detects already-converted files",
            "and skips them. Use your existing master password.",
            "",
            "If the archive will not open at all, restore from backup.",
        ]
    else:
        lines = [
            "A previous master password change was interrupted before it finished.",
            f"It began at {started} and stopped inside the database rekey step.",
            "",
            "What this means: the archive may be partly re-encrypted under the new",
            "password. If the app reports an invalid password, that is a symptom of",
            "the interruption, not necessarily a wrong password — try BOTH your old",
            "and your new password before assuming anything is lost.",
            "",
            "If neither password opens the archive, restore from backup.",
        ]

    if backup:
        lines.append(f"A backup was verified immediately beforehand: {backup}")
    return "\n".join(lines)


def _restore_point_age_hours(point) -> Optional[float]:
    """Age in hours of an already-verified restore point, or None if unparseable."""
    if not point:
        return None
    try:
        created_str = point["created_at"].rstrip("Z")
        created = datetime.fromisoformat(created_str)
        return (datetime.now() - created).total_seconds() / 3600.0
    except Exception:
        return None


def _atomic_write_file(path: Path, content: bytes) -> None:
    """Crash-safe atomic file replacement.

    Same pattern as Migration._atomic_write_file: temp + fsync(file) +
    os.replace + fsync(directory). The directory fsync is the textbook
    missing step that protects against rename loss on power failure.
    """
    path = Path(path)
    tmp_path = path.with_suffix(path.suffix + ".v2tmp")
    with open(tmp_path, "wb") as fh:
        fh.write(content)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, path)
    dir_fd = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
