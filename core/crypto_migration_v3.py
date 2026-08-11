"""
MailRepo — v2 to v3 crypto migration (envelope encryption).

Converts an archive whose master key is derived from the password into one
whose master key is random and wrapped under both the password and a
printable recovery key.

WHY THIS RE-ENCRYPTS EVERYTHING

There is a much cheaper migration available: set the new master to the
value the current password already derives, wrap that, rewrite one file,
touch no data. It was considered and rejected.

If the master equals Argon2id(password, salt), then that password remains
a permanent path to the master no matter how many times the wrappers are
replaced. Password change would stop actually revoking the old password —
it would only stop advertising it. For an audience that changes passwords
precisely because one was compromised, that is a silent downgrade of the
guarantee they believe they are getting.

So: generate a genuinely random master, re-encrypt the archive under the
file key it derives, rekey the database, and write the MRC3 key file. The
cost is one password change, paid once. Every password change after this
is a 61-byte rewrap with no file walk at all.

RESUMABILITY

Each file is tried with the old key first, then the new one, so a file
that already carries the new key is skipped as already-converted. That
alone is not enough: the new master is random, so a second attempt that
generated a fresh master would find the already-converted files readable
under neither key and halt as corruption.

So the candidate master is persisted before the walk begins, wrapped
under the OLD password's file key. A re-run unwraps it and continues with
the same master. The state file adds no exposure — it is encrypted under
the key that already protects the archive — and is deleted once the
migration completes.

The database rekey plus key-file write at the end is NOT resumable — the
same window password_change has. It is guarded the same way: a verified
on-disk backup beforehand (non-overridable) and an interruption marker
that lets the next launch explain itself.
"""

import secrets
from pathlib import Path
from typing import Callable, Optional

from utils.backup import get_verified_latest_restore_point
from utils.log import get_logger

from .config import Config
from .database import Database
from .encryption import (
    HKDF_INFO_DB_V2,
    HKDF_INFO_FILE_V2,
    MASTER_KEY_LENGTH,
    Encryption,
    InvalidPasswordError,
)
from .password_change import (
    MAX_BACKUP_AGE_HOURS,
    _atomic_write_file,
    _iter_archive_files,
    _rekey_credentials,
    _rekey_file,
    _restore_point_age_hours,
    _write_interruption_marker,
    clear_interruption_marker,
)

log = get_logger(__name__)


class MigrationError(Exception):
    """Raised when the v3 migration cannot proceed or fails partway."""

    pass


# ============================================================
# RESUME STATE
# ============================================================


def get_migration_state_path() -> Path:
    return Config.get_data_path() / ".v3_migration_state"


def _save_migration_state(master: bytes, old_file_key: bytes) -> None:
    """Persist the candidate master, wrapped under the old file key.

    Without this the migration is not actually re-runnable: a second
    attempt would mint a different random master, and every file already
    converted by the first attempt would decrypt under neither key.
    """
    blob = Encryption._encrypt_v2_with_key(master, old_file_key)
    _atomic_write_file(get_migration_state_path(), blob)


def _load_migration_state(old_file_key: bytes) -> Optional[bytes]:
    """Recover an in-progress master, or None if there is no usable state."""
    path = get_migration_state_path()
    if not path.exists():
        return None
    try:
        master = Encryption._decrypt_v2_with_key(path.read_bytes(), old_file_key)
    except Exception:
        # State written under a different password, or corrupt. Starting
        # fresh is wrong -- it would strand any already-converted files --
        # so say so rather than quietly minting a new master.
        raise MigrationError(
            "An interrupted upgrade left state that cannot be read with this "
            "password. Restore from backup rather than continuing."
        )
    if len(master) != MASTER_KEY_LENGTH:
        raise MigrationError("Interrupted upgrade state is malformed.")
    return master


def _clear_migration_state() -> None:
    try:
        get_migration_state_path().unlink(missing_ok=True)
    except Exception as e:
        log.warning(f"Could not clear v3 migration state: {e}")


def needs_v3_migration() -> bool:
    """True if an initialized archive is still on the v2 key format.

    Also clears any orphaned migration state, because this is the one
    function guaranteed to run on a v3 archive at startup.

    The state file wraps the CURRENT master under the OLD password's file
    key. If it survives past a completed migration — a crash between the
    key-file write and cleanup, or a data-dir restore that carries it
    back — nothing else would ever remove it: _clear_migration_state() is
    reachable only from the success path, which a v3 archive never enters
    again.

    That matters. The documented residual risk of not re-encrypting old
    backups is "an old credential opens old data". An orphaned state file
    turns that into "an old credential opens everything current", since
    an attacker with the old password and any pre-migration backup (which
    carries the old MRC2 salt) could derive the old file key and unwrap
    the live master from it.
    """
    if not Encryption.is_initialized():
        return False
    try:
        version = Encryption.salt_file_version()
    except Exception:
        return False

    if version == 3:
        if get_migration_state_path().exists():
            log.warning(
                "Removing orphaned v3 migration state: the archive is already "
                "v3, so this file can only extend an old password's reach."
            )
            _clear_migration_state()
        return False

    return version == 2


def migrate_to_v3(
    password: str,
    progress_cb: Optional[Callable[[dict], None]] = None,
) -> str:
    """Migrate a v2 archive to the v3 envelope.

    Returns the new recovery key in display format. This is the only time
    it exists in plaintext; it is never stored. The caller MUST show it to
    the user.

    Raises:
      MigrationError: already v3, no verified recent backup, or locked.
      InvalidPasswordError: the supplied password is not the current one.
      PasswordChangeCorruptionError: a file decrypted with neither key.
    """
    if not Encryption.is_initialized():
        raise MigrationError("Encryption is not initialized; nothing to migrate.")

    if Encryption.salt_file_version() == 3:
        raise MigrationError("This archive already uses recovery keys.")

    if not Encryption.is_unlocked():
        raise MigrationError("Encryption is locked. Log in and retry.")

    # 1. Non-overridable backup check, verified on disk. Same gate as the
    #    password change: this operation ends in a non-resumable window,
    #    and the backup is the recovery path if it is interrupted there.
    point, problems = get_verified_latest_restore_point()
    if problems:
        raise MigrationError(
            f"Upgrade refused: the most recent backup did not verify. "
            f"{'; '.join(problems)}. Take a fresh backup and retry."
        )

    age = _restore_point_age_hours(point)
    if age is None or age > MAX_BACKUP_AGE_HOURS:
        age_repr = f"{age:.1f}h" if age is not None else "unknown age"
        raise MigrationError(
            f"Upgrade refused: most recent verified backup is {age_repr}. "
            f"Take a fresh backup and retry."
        )

    # 2. Confirm the password really is the current one before we touch
    #    anything. Comparing derived keys avoids a second Argon2id pass
    #    over the salt file.
    try:
        old_file_key = Encryption.derive_v2_file_key_for_password(password)
    except Exception as e:
        raise MigrationError(f"Failed to derive current keys: {e}")

    if old_file_key != Encryption._file_key_v2:
        raise InvalidPasswordError("Current password is incorrect.")

    # 3. The new random master and the keys below it.
    #
    #    If a previous attempt was interrupted, reuse the master it was
    #    already converting files to. Minting a fresh one here would
    #    strand every file the earlier attempt had converted.
    resumed_master = _load_migration_state(old_file_key)
    resuming = resumed_master is not None
    master = resumed_master if resuming else secrets.token_bytes(MASTER_KEY_LENGTH)

    new_file_key = Encryption._derive_subkey_v2(master, HKDF_INFO_FILE_V2)
    new_db_key_hex = Encryption._derive_subkey_v2(master, HKDF_INFO_DB_V2).hex()

    if new_file_key == old_file_key:
        # Astronomically improbable; if it ever happens, stop rather than
        # write a key file that claims a rotation that did not occur.
        raise MigrationError("Generated master collided with the current key.")

    if not resuming:
        _save_migration_state(master, old_file_key)
    else:
        log.info("Resuming an interrupted v3 migration with the stored master")

    # The recovery key is minted per attempt, not stored: only the final
    # attempt's key ends up in the key file, and it is returned to the
    # caller to show the user.
    recovery_key = Encryption.generate_recovery_key()

    # 4. Re-encrypt the archive. Resumable: already-converted files are
    #    detected and skipped, so an interrupted run can be re-run.
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

    # 5. Stored account credentials.
    if progress_cb:
        progress_cb(
            {
                "status": "credentials",
                "message": "Re-encrypting account credentials...",
            }
        )
    cred_count = _rekey_credentials(old_file_key, new_file_key)

    # 6. The irreversible window: database rekey, then the new key file.
    #    Marker first, so an interruption in here can explain itself.
    _write_interruption_marker(point, phase="v3_migration")

    if progress_cb:
        progress_cb({"status": "database", "message": "Rekeying database..."})

    blob = Encryption.build_v3_salt_blob(master, password, recovery_key)

    Database.acquire_for_migration()
    try:
        conn = Database.get_connection()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute(f"PRAGMA rekey = \"x'{new_db_key_hex}'\"")
        Database._db_key = new_db_key_hex

        if progress_cb:
            progress_cb({"status": "finalizing", "message": "Writing new key file..."})

        # The key file is written LAST, immediately after the DB rekey.
        #
        # Be precise about what that does and does not buy. A crash BEFORE
        # the rekey leaves a re-runnable migration: the archive is still
        # described by the v2 key file and the old password still opens
        # it. A crash BETWEEN the rekey and this write does NOT — the
        # database is on the new key while the key file still describes
        # the old one, and recovery is restore-from-backup, exactly as
        # the interruption marker tells the user. The window is two
        # statements wide, which is why the verified-backup gate above is
        # non-overridable.
        Encryption.write_v3_salt_file(blob)
        Encryption._adopt_master(master, version=3)
    finally:
        Database.release_after_migration()

    clear_interruption_marker()
    _clear_migration_state()

    if progress_cb:
        progress_cb(
            {
                "status": "complete",
                "message": "Recovery key created.",
            }
        )

    log.info(f"v3 migration complete: {total} files, {cred_count} credentials")
    return recovery_key
