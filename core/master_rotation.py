"""
Master-key rotation for v3/v4 archives (security review 2026-09, #8b).

A password change or recovery-key rotation replaces a *wrapper*; the
master underneath — and so every file key and the database key — never
changes. That is what makes those operations cheap, and it is also why
they do not help against someone who already holds an old key file and
the credential that opened it: with a copy of the ciphertext they can
derive the same master offline, forever.

Rotation is the remedy for that case: mint a fresh master, re-encrypt
every archive file and stored credential, rekey the database, and write
a new key file (new password wrapper, new recovery key) under it. After
this, every earlier key file and every earlier credential opens
nothing current — and, since backups carry the key file, every earlier
backup is a *snapshot* rather than a way in.

The walk is core.crypto_migration_v3's, generalised: resumable across
the file walk, with an interruption marker across the two-statement
window where the database is rekeyed and the key file replaced. It is
gated on a verified recent backup for the same reason that one is.
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
    SALT_MAGIC_V4,
    V4_OFF_ARCHIVE_ID,
    V4_OFF_BODY,
    Encryption,
    EncryptionError,
    InvalidPasswordError,
)
from .password_change import (
    MAX_BACKUP_AGE_HOURS,
    _atomic_write_file,
    _restore_point_age_hours,
    _write_interruption_marker,
    check_password_change_interrupted,
    clear_interruption_marker,
    reencrypt_archive,
    rekey_database,
)

log = get_logger(__name__)


class RotationError(EncryptionError):
    pass


def get_rotation_state_path() -> Path:
    return Config.get_data_path() / ".master_rotation_state"


def _save_state(new_master: bytes, old_file_key: bytes) -> None:
    _atomic_write_file(
        get_rotation_state_path(), Encryption._encrypt_v2_with_key(new_master, old_file_key)
    )


def _load_state(old_file_key: bytes) -> Optional[bytes]:
    path = get_rotation_state_path()
    if not path.exists():
        return None
    try:
        master = Encryption._decrypt_v2_with_key(path.read_bytes(), old_file_key)
    except Exception:
        raise RotationError(
            "An interrupted rotation left state that cannot be read with this "
            "password. Restore from backup rather than continuing."
        )
    if len(master) != MASTER_KEY_LENGTH:
        raise RotationError("Interrupted rotation state is malformed.")
    return master


def clear_rotation_state() -> None:
    try:
        get_rotation_state_path().unlink(missing_ok=True)
    except Exception as e:
        log.warning(f"Could not clear rotation state: {e}")


def clear_finished_rotation_leftovers() -> None:
    """Run after a successful unlock. Removes what a finished rotation left.

    The state file holds the NEW master wrapped under the OLD file key.
    If the process died after the new key file landed but before cleanup,
    the rotation is complete and the file is both useless and harmful:
    the next rotation cannot read it and refuses to start, and anyone
    holding the old credentials could use it to derive the current
    master, which is the one thing a rotation exists to prevent.

    The test is whether the key the archive just opened with can read
    it. If it can, a rotation really was interrupted mid-walk and the
    state is needed to resume. If it cannot, it belongs to a master this
    archive no longer uses.
    """
    path = get_rotation_state_path()
    if not path.exists() or Encryption._file_key_v2 is None:
        return
    try:
        Encryption._decrypt_v2_with_key(path.read_bytes(), Encryption._file_key_v2)
        return
    except Exception:
        pass
    log.warning("Removing state left by a master rotation that had already finished")
    clear_rotation_state()
    marker = check_password_change_interrupted()
    if marker and marker.get("phase") == "master_rotation":
        clear_interruption_marker()


def rotation_backup_gate():
    """(ok, point, age_hours, problems) for the UI and the gate."""
    point, problems = get_verified_latest_restore_point()
    age = _restore_point_age_hours(point) if point else None
    ok = not problems and age is not None and age <= MAX_BACKUP_AGE_HOURS
    return ok, point, age, problems


def rotate_master_key(
    password: str,
    new_password: Optional[str] = None,
    progress_cb: Optional[Callable[[dict], None]] = None,
) -> str:
    """Rotate the master key. Returns the NEW recovery key (display format).

    ``new_password`` defaults to ``password``. The old recovery key is
    dead after this regardless: it wrapped a master that no longer opens
    anything.

    Raises RotationError (not v3, locked, no verified recent backup),
    InvalidPasswordError, or PasswordChangeCorruptionError.
    """
    if not Encryption.is_initialized() or not Encryption.is_unlocked():
        raise RotationError("The archive must be unlocked to rotate its master key.")
    if Encryption.salt_file_version() != 3:
        raise RotationError("Upgrade to recovery keys first; rotation needs the v3 envelope.")

    ok, point, age, problems = rotation_backup_gate()
    if not ok:
        detail = (
            "; ".join(problems) if problems else (f"{age:.1f}h old" if age is not None else "none")
        )
        raise RotationError(
            f"Rotation refused: no verified backup from the last {MAX_BACKUP_AGE_HOURS} hours "
            f"({detail}). Take a fresh backup and retry."
        )

    # 1. The password must be the current one; it also yields the old master.
    blob = Encryption.read_salt_blob()
    old_master = Encryption.unwrap_master_with_password(blob, password)
    if not secrets.compare_digest(old_master, Encryption._master):
        raise InvalidPasswordError("Current password is incorrect.")
    old_file_key = Encryption._derive_subkey_v2(old_master, HKDF_INFO_FILE_V2)

    # 2. New master (resume an interrupted one rather than stranding its files).
    resumed = _load_state(old_file_key)
    new_master = resumed if resumed is not None else secrets.token_bytes(MASTER_KEY_LENGTH)
    new_file_key = Encryption._derive_subkey_v2(new_master, HKDF_INFO_FILE_V2)
    new_db_key_hex = Encryption._derive_subkey_v2(new_master, HKDF_INFO_DB_V2).hex()
    if new_file_key == old_file_key:
        raise RotationError("Generated master collided with the current key.")
    if resumed is None:
        _save_state(new_master, old_file_key)
    else:
        log.info("Resuming an interrupted master rotation with the stored master")

    recovery_key = Encryption.generate_recovery_key()
    pw = new_password if new_password else password

    from .keyfile_binding import record_current_tag

    with Encryption.rekeying():
        # 3. Re-encrypt files (resumable) and credentials, then check that
        #    everything on disk opens under the new key.
        summary = reencrypt_archive(old_file_key, new_file_key, progress_cb)

        # 4. The new key file, under the new master. Keep the archive_id: it
        #    names the archive, not the key.
        archive_id = blob[V4_OFF_ARCHIVE_ID:V4_OFF_BODY] if blob[:4] == SALT_MAGIC_V4 else None
        v3_blob = Encryption.build_v3_salt_blob(new_master, pw, recovery_key)
        new_blob = Encryption.build_v4_blob(
            new_master, Encryption.envelope_body(v3_blob), archive_id
        )
        # build_v3_salt_blob proved both doors of v3_blob. new_blob is a
        # different object (re-wrapped as MRC4), and it is the one going
        # to disk, so prove the printed recovery key opens IT, binding
        # tag included.
        Encryption._assert_recovery_wrapper_opens(new_blob, recovery_key, new_master)

        # 5. The irreversible window: database rekey, then the key file.
        _write_interruption_marker(point, phase="master_rotation")
        if progress_cb:
            progress_cb({"status": "database", "message": "Rekeying database..."})

        Database.acquire_for_migration()
        try:
            rekey_database(new_db_key_hex)
            # Record the new key file's tag BEFORE the file lands, as the
            # password-change paths do. The database is already on the
            # new key, so the old tags are dead either way; recording
            # afterwards left a gap in which a crash made the next login
            # refuse a perfectly good key file as "replaced".
            record_current_tag(new_blob, sole=True)
            if progress_cb:
                progress_cb({"status": "finalizing", "message": "Writing new key file..."})
            Encryption.write_v3_salt_file(new_blob)
            Encryption._adopt_master(new_master, version=3)
        finally:
            Database.release_after_migration()

    clear_interruption_marker()
    clear_rotation_state()

    if progress_cb:
        progress_cb({"status": "complete", "message": "Master key rotated."})
    log.info(
        f"Master key rotated: {summary['files']} files, {summary['credentials']} credentials "
        f"re-encrypted; {summary['verified']} files verified, {summary['late']} converted late"
    )
    return recovery_key
