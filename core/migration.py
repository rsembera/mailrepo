"""
MailRepo - Crypto migration v1 -> v2.

Two-phase migration from the legacy v1 crypto (PBKDF2 + Fernet) to the v2
crypto (Argon2id + HKDF + AES-256-GCM). See docs/Crypto_Refactor_Plan.md
for the full design.

Phase 1 (file layer)
  - Walk every .eml.enc in the archive. For each: decrypt with v1 Fernet,
    encrypt with v2 AES-256-GCM, atomically replace via temp-file + fsync
    + os.replace + directory-fsync.
  - Re-encrypt stored IMAP credentials in the accounts table.
  - Verification: every archive file starts with 0x02; random-sample
    decrypt to confirm v2 keys produce sensible plaintext.
  - Write the durable .migration_phase_1_complete marker.

Phase 2 (database layer)
  - Re-check backup <= 24h (non-overridable).
  - Acquire exclusive DB access via Database.acquire_for_migration().
  - WAL checkpoint, then PRAGMA rekey to the v2 db_key.
  - Write the new v2 salt file (MRC2 magic) atomically.
  - Clear v1 in-memory keys; the session is now pure v2.
  - Delete the marker. Release exclusive DB access.

Halt-loud on corruption: if a v1 file fails to decrypt during Phase 1,
the migration raises MigrationCorruptionError naming the file. Never
silently skips.
"""

import base64
import json
import os
import random
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator, Optional

from .config import Config
from .database import Database
from .encryption import (
    ARGON2_KEY_LENGTH,
    ARGON2_MEMORY_COST,
    ARGON2_PARALLELISM,
    ARGON2_TIME_COST,
    Encryption,
    VERSION_BYTE_V2,
)


class MigrationError(Exception):
    """Raised when the migration encounters an unrecoverable error."""
    pass


class MigrationCorruptionError(MigrationError):
    """Raised when a v1 file fails to decrypt during the walk.

    The migration halts and reports the specific file rather than silently
    skipping. A v1 decrypt failure means real disk damage or a bug; the
    user wants to know loudly, not paper over.
    """
    def __init__(self, filepath: str, original_error: Exception):
        self.filepath = filepath
        self.original_error = original_error
        super().__init__(
            f"Corruption detected during migration: {filepath} failed to "
            f"decrypt with the v1 key ({type(original_error).__name__}: "
            f"{original_error}). Migration halted. Restore from backup or "
            f"investigate the specific file."
        )


class Migration:
    """Two-phase crypto migration from v1 to v2.

    Stateless: per-run state lives in the Encryption class (keys), in the
    database (credentials), and on disk (files + marker).
    """

    # Number of files to sample-decrypt during Phase 1 verification.
    VERIFICATION_SAMPLE_SIZE = 50

    # Phase 2's backup-age check is non-overridable.
    PHASE_2_MAX_BACKUP_AGE_HOURS = 24.0

    # ------------------------------------------------------------------
    # State detection
    # ------------------------------------------------------------------

    @classmethod
    def is_needed(cls) -> bool:
        """True if the archive is on v1 crypto and a migration is required."""
        try:
            return Encryption.get_crypto_version() == 1
        except Exception:
            return False

    @classmethod
    def has_marker(cls) -> bool:
        """True if the Phase 1 completion marker exists (Phase 2 pending)."""
        return Encryption.get_migration_marker_path().exists()

    @classmethod
    def has_v2_files(cls) -> bool:
        """True if any archive file starts with the v2 version byte.

        Used to detect a Phase 1 interruption. Short-circuits on the first
        hit so this is cheap even on large archives.
        """
        for path in cls._iter_archive_files():
            try:
                with open(path, "rb") as fh:
                    first = fh.read(1)
                if first and first[0] == VERSION_BYTE_V2:
                    return True
            except Exception:
                continue
        return False

    @classmethod
    def state(cls) -> str:
        """Return one of: not_needed, fresh, phase_1_interrupted, phase_2_pending."""
        if not cls.is_needed():
            return "not_needed"
        if cls.has_marker():
            return "phase_2_pending"
        if cls.has_v2_files():
            return "phase_1_interrupted"
        return "fresh"

    # ------------------------------------------------------------------
    # Pre-flight
    # ------------------------------------------------------------------

    @classmethod
    def run_preflight(cls, allow_stale_backup: bool = False) -> dict:
        """Run all pre-flight checks before starting Phase 1.

        Returns a dict with `ok` (overall pass/fail) and `checks` (per-check
        details). Caller decides whether to proceed; this method does not
        modify any state.

        allow_stale_backup: if True, the backup-age check is skipped (used
        when the user explicitly overrides for Phase 1 only -- Phase 2 has
        its own non-overridable check).
        """
        checks: dict = {}

        # 1. Encryption is unlocked.
        checks["unlocked"] = Encryption.is_unlocked()

        # 2. v1 key successfully decrypts a known-good file.
        sample = cls._find_any_v1_file()
        if sample is not None:
            try:
                with open(sample, "rb") as fh:
                    data = fh.read()
                if Encryption._fernet_v1 is None:
                    checks["v1_decrypt_sample"] = False
                    checks["v1_decrypt_error"] = "v1 Fernet not loaded"
                else:
                    Encryption._fernet_v1.decrypt(data)
                    checks["v1_decrypt_sample"] = True
            except Exception as e:
                checks["v1_decrypt_sample"] = False
                checks["v1_decrypt_error"] = f"{type(e).__name__}: {e}"
        else:
            checks["v1_decrypt_sample"] = True

        # 3. argon2-cffi imports and a live derivation succeeds.
        try:
            from argon2.low_level import Type as Argon2Type
            from argon2.low_level import hash_secret_raw
            hash_secret_raw(
                secret=b"preflight",
                salt=b"\x00" * 32,
                time_cost=ARGON2_TIME_COST,
                memory_cost=ARGON2_MEMORY_COST,
                parallelism=ARGON2_PARALLELISM,
                hash_len=ARGON2_KEY_LENGTH,
                type=Argon2Type.ID,
            )
            checks["argon2_works"] = True
        except Exception as e:
            checks["argon2_works"] = False
            checks["argon2_error"] = f"{type(e).__name__}: {e}"

        # 4. Disk space >= 2x archive size.
        archive_size = cls._total_archive_size()
        try:
            free = shutil.disk_usage(Config.get_data_path()).free
        except Exception:
            free = 0
        checks["disk_space_required"] = archive_size * 2
        checks["disk_space_available"] = free
        checks["disk_space_ok"] = free >= archive_size * 2

        # 5. Backup age. Skipped if allow_stale_backup is True.
        age = cls._latest_backup_age_hours()
        checks["backup_age_hours"] = age
        if allow_stale_backup:
            checks["backup_ok"] = True
            checks["backup_overridden"] = True
        else:
            checks["backup_ok"] = (
                age is not None and age <= cls.PHASE_2_MAX_BACKUP_AGE_HOURS
            )

        all_ok = all(
            checks.get(k) for k in (
                "unlocked", "v1_decrypt_sample", "argon2_works",
                "disk_space_ok", "backup_ok",
            )
        )
        return {"ok": all_ok, "checks": checks}

    # ------------------------------------------------------------------
    # Phase 1 -- file layer
    # ------------------------------------------------------------------

    @classmethod
    def run_phase_1(
        cls,
        password: str,
        progress_cb: Optional[Callable[[dict], None]] = None,
    ) -> dict:
        """Re-encrypt the file layer from v1 to v2, then verify, then write
        the Phase 1 completion marker.

        progress_cb stages:
          {"phase": 1, "stage": "cleanup", "stray_removed": int}
          {"phase": 1, "stage": "keys_derived"}
          {"phase": 1, "stage": "walking", "files_done": int, "files_total": int}
          {"phase": 1, "stage": "credentials_done", "count": int}
          {"phase": 1, "stage": "verifying", "samples_done": int, "samples_total": int}
          {"phase": 1, "stage": "complete"}

        Raises MigrationCorruptionError on a v1 decrypt failure.
        """
        stray = cls._clean_stray_tmp_files()
        if progress_cb:
            progress_cb({"phase": 1, "stage": "cleanup", "stray_removed": stray})

        Encryption._derive_and_set_v2_keys(password)
        if progress_cb:
            progress_cb({"phase": 1, "stage": "keys_derived"})

        files = list(cls._iter_archive_files())
        total = len(files)
        done = 0
        for path in files:
            cls._migrate_file(path)
            done += 1
            if done % 10 == 0 or done == total:
                if progress_cb:
                    progress_cb({
                        "phase": 1, "stage": "walking",
                        "files_done": done, "files_total": total,
                    })

        cred_count = cls._migrate_credentials()
        if progress_cb:
            progress_cb({
                "phase": 1, "stage": "credentials_done", "count": cred_count,
            })

        cls._verify_phase_1(progress_cb)

        marker = Encryption.get_migration_marker_path()
        cls._atomic_write_file(marker, json.dumps({
            "phase_1_complete_at": datetime.now().isoformat(),
            "files_migrated": total,
            "credentials_migrated": cred_count,
        }).encode("utf-8"))

        if progress_cb:
            progress_cb({"phase": 1, "stage": "complete"})
        return {"files": total, "credentials": cred_count}

    @classmethod
    def _migrate_file(cls, path: Path) -> bool:
        """Re-encrypt one file from v1 (Fernet) to v2 (AES-256-GCM).

        Returns True if migrated, False if skipped (already v2). Raises
        MigrationCorruptionError if v1 decryption fails -- never silently
        skips a bad file.
        """
        with open(path, "rb") as fh:
            data = fh.read()
        if data and data[0] == VERSION_BYTE_V2:
            return False  # already v2; resumability
        if Encryption._fernet_v1 is None:
            raise MigrationError(f"v1 Fernet not loaded; cannot migrate {path}")
        if Encryption._file_key_v2 is None:
            raise MigrationError(f"v2 file_key not derived; cannot migrate {path}")
        try:
            plaintext = Encryption._fernet_v1.decrypt(data)
        except Exception as e:
            raise MigrationCorruptionError(str(path), e)
        new_ct = Encryption._encrypt_v2_with_key(plaintext, Encryption._file_key_v2)
        cls._atomic_write_file(path, new_ct)
        return True

    @classmethod
    def _migrate_credentials(cls) -> int:
        """Re-encrypt every accounts.credentials_encrypted from v1 to v2.

        decrypt_string auto-detects v1 vs v2 (so this is resumable).
        encrypt_string now writes v2 because the v2 file_key is loaded.
        """
        rows = Database.fetchall(
            "SELECT id, credentials_encrypted FROM accounts "
            "WHERE credentials_encrypted IS NOT NULL"
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
            if raw and raw[0] == VERSION_BYTE_V2:
                continue  # already v2; skip
            try:
                plaintext = Encryption.decrypt_string(enc_str)
            except Exception as e:
                raise MigrationCorruptionError(
                    f"accounts.id={row['id']}/credentials", e
                )
            new_enc = Encryption.encrypt_string(plaintext)
            Database.execute(
                "UPDATE accounts SET credentials_encrypted = ? WHERE id = ?",
                (new_enc, row["id"]),
            )
            count += 1
        Database.commit()
        return count

    @classmethod
    def _verify_phase_1(
        cls, progress_cb: Optional[Callable[[dict], None]] = None
    ) -> None:
        """Confirm every archive file is v2 and a random sample decrypts.

        Raises MigrationError if any file is non-v2 or any sample fails
        to decrypt. This refuses Phase 2 if the file layer is in any way
        inconsistent.
        """
        files = list(cls._iter_archive_files())

        non_v2: list = []
        for path in files:
            try:
                with open(path, "rb") as fh:
                    first = fh.read(1)
                if not first or first[0] != VERSION_BYTE_V2:
                    non_v2.append(str(path))
            except Exception:
                non_v2.append(str(path))
        if non_v2:
            raise MigrationError(
                f"Phase 1 verification failed: {len(non_v2)} file(s) do not "
                f"start with 0x02. First few: {non_v2[:5]}"
            )

        sample_n = min(cls.VERIFICATION_SAMPLE_SIZE, len(files))
        if sample_n > 0:
            sample = random.sample(files, sample_n)
            for i, path in enumerate(sample, 1):
                with open(path, "rb") as fh:
                    data = fh.read()
                try:
                    Encryption._decrypt_v2_with_key(data, Encryption._file_key_v2)
                except Exception as e:
                    raise MigrationError(
                        f"Phase 1 verification: sample decrypt failed for "
                        f"{path}: {type(e).__name__}: {e}"
                    )
                if i % 10 == 0 and progress_cb:
                    progress_cb({
                        "phase": 1, "stage": "verifying",
                        "samples_done": i, "samples_total": sample_n,
                    })

    # ------------------------------------------------------------------
    # Phase 2 -- database layer
    # ------------------------------------------------------------------

    @classmethod
    def run_phase_2(
        cls, progress_cb: Optional[Callable[[dict], None]] = None
    ) -> dict:
        """Rekey SQLCipher to the v2 db_key, write the v2 salt file, clear
        v1 in-memory state, and delete the marker.

        Refuses to start if the most recent backup is older than 24 hours;
        this check is non-overridable because Phase 2 is not version-byte-
        resumable.

        progress_cb stages:
          {"phase": 2, "stage": "backup_check", "backup_age_hours": float}
          {"phase": 2, "stage": "acquiring"}
          {"phase": 2, "stage": "wal_checkpoint"}
          {"phase": 2, "stage": "rekey"}
          {"phase": 2, "stage": "salt_file"}
          {"phase": 2, "stage": "swap_keys"}
          {"phase": 2, "stage": "complete"}
        """
        age = cls._latest_backup_age_hours()
        if age is None or age > cls.PHASE_2_MAX_BACKUP_AGE_HOURS:
            age_repr = f"{age:.1f}h" if age is not None else "unknown"
            raise MigrationError(
                f"Phase 2 refused: most recent backup is {age_repr}. "
                f"Phase 2 is not resumable; the backup IS the recovery path. "
                f"Take a fresh backup and retry."
            )
        if progress_cb:
            progress_cb({
                "phase": 2, "stage": "backup_check",
                "backup_age_hours": age,
            })

        if not cls.has_marker():
            raise MigrationError(
                "Phase 2 refused: Phase 1 completion marker not found. "
                "Phase 1 must complete and write the marker before Phase 2 "
                "can begin."
            )

        if Encryption._db_key_v2 is None or Encryption._file_key_v2 is None:
            raise MigrationError(
                "Phase 2 refused: v2 keys are not loaded. Re-unlock the "
                "session and retry."
            )

        if progress_cb:
            progress_cb({"phase": 2, "stage": "acquiring"})

        Database.acquire_for_migration()
        try:
            if progress_cb:
                progress_cb({"phase": 2, "stage": "wal_checkpoint"})
            conn = Database.get_connection()
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

            if progress_cb:
                progress_cb({"phase": 2, "stage": "rekey"})
            new_db_key = Encryption.get_db_key_v2()
            conn.execute(f"PRAGMA rekey = \"x\'{new_db_key}\'\"")
            Database._db_key = new_db_key

            if progress_cb:
                progress_cb({"phase": 2, "stage": "salt_file"})
            Encryption.write_v2_salt_file()

            if progress_cb:
                progress_cb({"phase": 2, "stage": "swap_keys"})
            Encryption.swap_v1_to_v2()

            marker = Encryption.get_migration_marker_path()
            if marker.exists():
                marker.unlink()
        finally:
            Database.release_after_migration()

        if progress_cb:
            progress_cb({"phase": 2, "stage": "complete"})
        return {"crypto_version": Encryption.get_crypto_version()}

    # ------------------------------------------------------------------
    # File / archive helpers
    # ------------------------------------------------------------------

    @classmethod
    def _iter_archive_files(cls) -> Iterator[Path]:
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

    @classmethod
    def _find_any_v1_file(cls) -> Optional[Path]:
        """Return the first non-v2 file found, or None."""
        for path in cls._iter_archive_files():
            try:
                with open(path, "rb") as fh:
                    first = fh.read(1)
                if first and first[0] != VERSION_BYTE_V2:
                    return path
            except Exception:
                continue
        return None

    @classmethod
    def _total_archive_size(cls) -> int:
        """Sum of all .eml.enc file sizes in bytes."""
        total = 0
        for path in cls._iter_archive_files():
            try:
                total += path.stat().st_size
            except Exception:
                continue
        return total

    @classmethod
    def _clean_stray_tmp_files(cls) -> int:
        """Remove any .v2tmp files left behind by a previous interrupted run."""
        try:
            archive_root = Config.get_archive_path()
        except Exception:
            return 0
        if not archive_root.exists():
            return 0
        count = 0
        for path in archive_root.rglob("*.v2tmp"):
            try:
                path.unlink()
                count += 1
            except Exception:
                pass
        return count

    @classmethod
    def _latest_backup_age_hours(cls) -> Optional[float]:
        """Age of the most recent backup in hours, or None if no manifest."""
        try:
            manifest_path = Config.get_data_path().parent / "backups" / "manifest.json"
        except Exception:
            return None
        if not manifest_path.exists():
            return None
        try:
            manifest = json.loads(manifest_path.read_text())
            if not manifest.get("backups"):
                return None
            latest = max(manifest["backups"], key=lambda b: b["created_at"])
            created_str = latest["created_at"].rstrip("Z")
            created = datetime.fromisoformat(created_str)
            return (datetime.now() - created).total_seconds() / 3600.0
        except Exception:
            return None

    @staticmethod
    def _atomic_write_file(path: Path, content: bytes) -> None:
        """Crash-safe atomic file replacement.

        Pattern:
          1. Write to a temp file in the same directory (atomic rename on POSIX).
          2. fsync the temp file (durability of contents).
          3. os.replace (atomic rename).
          4. fsync the containing directory (durability of the rename itself).

        Step 4 is the textbook missing step. Without it, on power loss the
        rename can be lost even though contents were synced. With it, we
        never have a window where the rename can vanish.
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
