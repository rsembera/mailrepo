"""
MailRepo - Backup System
Handles full and incremental backups with encryption support.

User-facing simplification:
- Single "Backup Now" button (system auto-decides full vs incremental)
- All backups are valid restore points
- No exposed complexity about backup chains
"""

import hashlib
import json
import os
import re
import shutil
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from core.config import Config
from utils.log import get_logger

log = get_logger(__name__)


def _atomic_write_text(path, text):
    """Write text to `path` atomically.

    Temp file in the same directory -> fsync -> os.replace (atomic on POSIX)
    -> fsync the containing directory so the rename itself survives power
    loss. Same crash-safe pattern as core/encryption.py's salt writer. Used
    for the manifest and the external backup-state file, both of which are
    sources of truth for change detection and restore.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)
    dir_fd = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def get_data_root():
    """Get data root directory from Config."""
    return Config.get_base_path()


def get_data_dir():
    return Config.get_data_path()


def get_archive_dir():
    return Config.get_archive_path()


def get_backups_dir():
    return Config.get_backup_path()


class UnsafeBackupPathError(ValueError):
    """A path read from a backup or manifest points outside where it may."""


# Top-level folders a backup may contain, and therefore the only ones a
# restore may delete under. Matches what get_all_backup_files() produces.
_BACKUP_ROOTS = ("data", "archive")


def safe_backup_relpath(rel_path) -> str:
    """Validate a relative path read from backup metadata.

    Backups carry no integrity protection, so anything in
    ``_backup_metadata.json`` is attacker-controlled once someone can
    write to the backup folder. This accepts only a plain relative path
    under ``data/`` or ``archive/`` — no absolute paths, no ``..``, no
    backslashes, no empty components — and returns it normalised with
    forward slashes. Raises UnsafeBackupPathError otherwise.
    """
    if not isinstance(rel_path, str) or not rel_path:
        raise UnsafeBackupPathError("empty path in backup metadata")
    if "\\" in rel_path or "\x00" in rel_path:
        raise UnsafeBackupPathError(f"unsafe characters in backup path: {rel_path!r}")
    if rel_path.startswith("/"):
        raise UnsafeBackupPathError(f"absolute path in backup metadata: {rel_path!r}")
    parts = rel_path.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise UnsafeBackupPathError(f"path traversal in backup metadata: {rel_path!r}")
    if parts[0] not in _BACKUP_ROOTS or len(parts) < 2:
        raise UnsafeBackupPathError(f"path outside backup roots: {rel_path!r}")
    return "/".join(parts)


def safe_backup_filename(filename) -> str:
    """Validate a zip filename read from a manifest.

    Manifest entries are joined onto a directory; a bare filename is all
    that is ever legitimate there. Raises UnsafeBackupPathError otherwise.
    """
    if not isinstance(filename, str) or not filename:
        raise UnsafeBackupPathError("empty filename in manifest")
    if filename in (".", "..") or "/" in filename or "\\" in filename or "\x00" in filename:
        raise UnsafeBackupPathError(f"unsafe filename in manifest: {filename!r}")
    return filename


def get_backup_path_for_entry(backup_entry: dict) -> Path:
    """Get the path where a backup file should be located based on its manifest entry."""
    backup_dir = (
        Path(backup_entry.get("backup_dir", ""))
        if backup_entry.get("backup_dir")
        else get_backups_dir()
    )
    return backup_dir / safe_backup_filename(backup_entry["filename"])


def get_restore_staging_dir():
    return get_data_root() / ".restore_staging"


def get_manifest_file():
    return get_backups_dir() / "manifest.json"


def ensure_backup_dir():
    """Create backups directory if it doesn't exist."""
    get_backups_dir().mkdir(parents=True, exist_ok=True)


def get_file_hash(filepath):
    """Calculate SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def get_file_metadata(filepath):
    """Get file metadata (mtime, size) for quick change detection."""
    stat = filepath.stat()
    return {"mtime": stat.st_mtime, "size": stat.st_size}


def get_all_backup_files():
    """
    Get list of all files that should be backed up.
    Returns dict: {relative_path: absolute_path}
    """
    data_root = get_data_root()
    data_dir = get_data_dir()
    archive_dir = get_archive_dir()
    files = {}

    # Database
    db_path = data_dir / "mailrepo.db"
    if db_path.exists():
        files["data/mailrepo.db"] = db_path

    # Security files (salt and secret key - essential for decryption)
    salt_path = data_dir / ".salt"
    if salt_path.exists():
        files["data/.salt"] = salt_path

    # Archive folder (all email files - encrypted and unencrypted)
    if archive_dir.exists():
        for filepath in archive_dir.rglob("*"):
            if filepath.is_file() and not filepath.name.startswith("."):
                rel_path = filepath.relative_to(data_root)
                files[str(rel_path)] = filepath

    return files


def get_file_hashes():
    """
    Calculate hashes for all backup files.
    Returns tuple: (hashes_dict, file_info_dict)

    Uses smart change detection: only rehashes files where mtime/size changed.
    """
    files = get_all_backup_files()
    state = _read_backup_state()
    previous_file_info = state.get("file_info", {})

    hashes = {}
    new_file_info = {}

    for rel_path, abs_path in files.items():
        current_meta = get_file_metadata(abs_path)
        prev_info = previous_file_info.get(rel_path, {})

        # Check if file might have changed (mtime or size different)
        if (
            prev_info.get("mtime") == current_meta["mtime"]
            and prev_info.get("size") == current_meta["size"]
            and prev_info.get("hash")
        ):
            # File unchanged - reuse cached hash
            file_hash = prev_info["hash"]
        else:
            # File changed or new - compute hash
            file_hash = get_file_hash(abs_path)

        hashes[rel_path] = file_hash
        new_file_info[rel_path] = {
            "hash": file_hash,
            "mtime": current_meta["mtime"],
            "size": current_meta["size"],
        }

    return hashes, new_file_info


def has_file_changes():
    """
    Quick check if any files have changed since last backup.

    Uses mtime/size comparison only - no hashing required.
    Returns True if any file appears changed or is new/deleted.
    """
    files = get_all_backup_files()
    state = _read_backup_state()
    previous_file_info = state.get("file_info", {})

    # No cached info means we need to do a full check
    if not previous_file_info:
        return True

    # Check for new or deleted files
    current_paths = set(files.keys())
    cached_paths = set(previous_file_info.keys())

    if current_paths != cached_paths:
        return True  # Files added or removed

    # Check for modified files (mtime or size changed)
    for rel_path, abs_path in files.items():
        current_meta = get_file_metadata(abs_path)
        prev_info = previous_file_info.get(rel_path, {})

        if (
            prev_info.get("mtime") != current_meta["mtime"]
            or prev_info.get("size") != current_meta["size"]
        ):
            return True  # File modified

    return False  # No changes detected


def load_manifest():
    """Load backup manifest from disk."""
    manifest_file = get_manifest_file()
    if manifest_file.exists():
        try:
            with open(manifest_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            # Manifest corrupted - backup the bad file and start fresh
            corrupted_path = manifest_file.with_suffix(".json.corrupted")
            shutil.copy(manifest_file, corrupted_path)
            log.warning(f"manifest.json was corrupted, backed up to {corrupted_path.name}")
    return {
        "backups": [],
        "last_full_hashes": {},
        "current_chain_id": None,
        "last_backup_check": None,
    }


# Identity stamped into every backup folder MailRepo writes to.
#
# Needed because filenames do not identify an application. EdgeCase
# writes `full_<date>_<time>.zip` containing `data/.salt` and
# `data/.secret_key` at exactly the same paths — the two are
# indistinguishable by name and by key material. Verified on a real pair:
#
#     EdgeCase: data/edgecase.db, data/.salt, data/.secret_key, ...
#     MailRepo: data/mailrepo.db, data/.salt, data/.secret_key, ...
#
# Restoring one into the other would find no database to copy and would
# overwrite this archive's key file with the other application's. So
# MailRepo marks what is its own rather than inferring it later.
APP_ID = "mailrepo"


def read_folder_stamp(folder):
    """Read the application stamp from a backup folder, or None."""
    sidecar = Path(folder) / "manifest.json"
    if not sidecar.exists():
        return None
    try:
        with open(sidecar, "r") as f:
            manifest = json.load(f)
    except (json.JSONDecodeError, ValueError, OSError):
        return None

    if not isinstance(manifest, dict) or "app" not in manifest:
        return None

    return {"app": manifest.get("app"), "app_version": manifest.get("app_version")}


def get_known_locations():
    """Folders MailRepo has recorded sending backups to.

    Read on recovery BEFORE any filesystem search. Searching is guessing;
    this is the record. Entries that no longer exist are dropped from the
    result but left in the file — an external drive that is merely
    unplugged should not be forgotten.
    """
    path = Config.get_backup_locations_file()
    if not path.exists():
        return []

    try:
        with open(path, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, ValueError, OSError) as e:
        log.warning(f"Could not read backup locations file: {e}")
        return []

    locations = []
    for entry in data.get("locations", []):
        raw = entry.get("path")
        if not raw:
            continue
        try:
            if Path(raw).is_dir():
                locations.append(entry)
        except OSError:
            continue

    locations.sort(key=lambda e: e.get("last_written", ""), reverse=True)
    return locations


def record_backup_location(folder):
    """Remember that backups were written here.

    Stored outside the application directory and outside the database,
    because both are gone in the situation this exists for. This is the
    difference between MailRepo knowing where its backups are and
    scanning the disk hoping to recognise them.
    """
    folder = Path(folder)
    path = Config.get_backup_locations_file()

    try:
        existing = {}
        if path.exists():
            with open(path, "r") as f:
                data = json.load(f)
            for entry in data.get("locations", []):
                if entry.get("path"):
                    existing[entry["path"]] = entry

        existing[str(folder)] = {
            "path": str(folder),
            "last_written": datetime.now().isoformat(),
            "app": APP_ID,
        }

        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(
            path,
            json.dumps({"app": APP_ID, "locations": list(existing.values())}, indent=2),
        )
    except Exception as e:
        # Never fail a backup over bookkeeping.
        log.warning(f"Could not record backup location {folder}: {e}")


def manifest_destinations(manifest):
    """Every distinct directory this manifest's backups actually live in.

    Excludes the canonical location, which save_manifest writes anyway.
    """
    canonical = get_backups_dir().resolve()
    destinations = {}

    for entry in manifest.get("backups", []):
        raw = entry.get("backup_dir")
        if not raw:
            continue
        try:
            resolved = Path(raw).resolve()
        except Exception:
            continue
        if resolved == canonical:
            continue
        destinations[resolved] = True

    return list(destinations)


def save_manifest(manifest):
    """Save backup manifest to disk (atomic, crash-safe write).

    Also drops a copy into every directory the manifest's backups live
    in. The canonical manifest sits inside the application folder, so a
    disk loss that takes the app takes the index with it — leaving the
    zips intact in iCloud and completely undiscoverable, because nothing
    remaining on disk knows which zip belongs to which chain.

    A sidecar makes each backup destination a self-describing unit: the
    folder plus its manifest is everything needed to rebuild. Written
    here rather than at each call site so that anything mutating the
    manifest — new backup, retention pruning — keeps the copies current
    without having to remember to.

    Sidecar failures are logged, never raised. A backup that succeeded
    must not be reported as failed because a cloud folder was briefly
    unwritable, and the canonical manifest is already safely written by
    the time we get here.
    """
    ensure_backup_dir()

    # Stamp the manifest with this application's identity before it is
    # written anywhere, so every folder MailRepo touches says whose it
    # is. Recognition then needs no inference about zip contents.
    manifest = dict(manifest)
    manifest["app"] = APP_ID
    manifest["app_version"] = Config.VERSION

    payload = json.dumps(manifest, indent=2)
    _atomic_write_text(get_manifest_file(), payload)
    record_backup_location(get_backups_dir())

    for destination in manifest_destinations(manifest):
        # manifest_destinations walks the whole backup history, so it can
        # name a folder that no longer exists — an old install path, a
        # deleted cloud folder. Do not recreate it: its zips are gone, and
        # a manifest there would describe nothing while making the folder
        # look like a recovery location. Real destinations always exist,
        # because the zip was written into them before we got here.
        if not destination.is_dir():
            continue
        try:
            _atomic_write_text(destination / "manifest.json", payload)
            record_backup_location(destination)
        except Exception as e:
            log.warning(f"Could not write manifest sidecar to {destination}: {e}")


# ============================================================================
# External Backup State File (Libram-style)
#
# Hash baseline is stored in .backup_state.json, NOT in the manifest.
# This avoids the circular modification problem where checking database
# state requires modifying the database.
# ============================================================================


def _get_backup_state_file():
    """Get path to backup state file (stored in data dir, not backups)."""
    return get_data_dir() / ".backup_state.json"


def _read_backup_state():
    """Read backup state from external JSON file."""
    state_file = _get_backup_state_file()
    if state_file.exists():
        try:
            with open(state_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _write_backup_state(state):
    """Write backup state to external JSON file (atomic, crash-safe write)."""
    state_file = _get_backup_state_file()
    _atomic_write_text(state_file, json.dumps(state, indent=2))


def _get_baseline_hashes():
    """
    Get hash baseline from external state file.
    Falls back to manifest for migration from old system.
    """
    state = _read_backup_state()
    if "last_backup_hashes" in state:
        return state["last_backup_hashes"]

    # Migration: check manifest for old-style hashes
    manifest = load_manifest()
    if manifest.get("last_full_hashes"):
        # Migrate to new system
        _write_backup_state(
            {
                "last_backup_hashes": manifest["last_full_hashes"],
                "last_backup_check": manifest.get("last_backup_check"),
            }
        )
        return manifest["last_full_hashes"]

    return {}


def _save_baseline_hashes(hashes, file_info=None):
    """
    Save hash baseline to external state file.

    Args:
        hashes: Dict of {relative_path: hash}
        file_info: Optional dict of {relative_path: {hash, mtime, size}}
                   If not provided, builds from hashes and current file state.
    """
    state = _read_backup_state()
    state["last_backup_hashes"] = hashes

    # Update file_info for smart change detection
    if file_info:
        state["file_info"] = file_info
    elif "file_info" not in state:
        # Build file_info from current state if not present
        files = get_all_backup_files()
        state["file_info"] = {}
        for rel_path, abs_path in files.items():
            if rel_path in hashes:
                meta = get_file_metadata(abs_path)
                state["file_info"][rel_path] = {
                    "hash": hashes[rel_path],
                    "mtime": meta["mtime"],
                    "size": meta["size"],
                }

    _write_backup_state(state)


def generate_backup_filename(backup_type, backup_dir=None):
    """Generate a backup filename that does not already exist.

    Second resolution alone is not enough. Two backups inside the same
    second produced the same name: the second zip overwrote the first
    while BOTH manifest entries survived, pointing at one file. Restoring
    the older point then silently applied the newer one's content, and
    the older one's deletion metadata was destroyed outright. This is not
    theoretical — it happened unprompted on the first run of the script
    written to reproduce the other restore bugs, and it corrupted that
    run's results.

    Interactive use makes it rare; scripted flows and the automatic
    backup path make it plausible.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    name = f"{backup_type}_{timestamp}.zip"

    if backup_dir is None:
        return name

    directory = Path(backup_dir)
    if not (directory / name).exists():
        return name

    # Collision: disambiguate rather than overwrite. Microseconds are
    # enough and keep the name sortable and human-readable.
    for _ in range(100):
        micro = datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")
        name = f"{backup_type}_{micro}.zip"
        if not (directory / name).exists():
            return name

    raise RuntimeError(f"Could not generate a unique backup filename in {directory}")


def validate_backup_location(backup_dir):
    """
    Validate that backup location is accessible and writable.
    Returns (success, error_message) tuple.
    """
    backup_dir = Path(backup_dir)

    # Check if it's a cloud folder
    cloud_indicators = [
        "iCloud",
        "CloudDocs",
        "Dropbox",
        "Google Drive",
        "OneDrive",
        "CloudStorage",
    ]
    is_cloud = any(indicator in str(backup_dir) for indicator in cloud_indicators)

    try:
        # Try to create directory
        backup_dir.mkdir(parents=True, exist_ok=True)

        # Try to write a test file
        test_file = backup_dir / ".write_test"
        try:
            test_file.write_text("test")
            test_file.unlink()
        except PermissionError:
            if is_cloud:
                return (
                    False,
                    "Cannot write to cloud folder. Please check that the cloud service is running and you're signed in.",
                )
            return False, "Permission denied. Cannot write to this location."
        except OSError as e:
            if is_cloud:
                return (
                    False,
                    "Cloud folder not accessible. Please check your internet connection and that the cloud service is online.",
                )
            return False, f"Cannot write to backup location: {e}"

        return True, None

    except PermissionError:
        if is_cloud:
            return (
                False,
                "Cannot access cloud folder. Please check that the cloud service is running and you're signed in.",
            )
        return False, "Permission denied. Cannot access this location."
    except OSError as e:
        if is_cloud:
            return False, "Cloud folder not accessible. Please check your internet connection."
        return False, f"Cannot access backup location: {e}"


def create_backup(backup_dir=None):
    """
    Create a backup, automatically deciding between full and incremental.

    Decision logic:
    - No previous backups → full
    - Last full backup > 7 days old → full
    - Otherwise → incremental (only changed files)

    Args:
        backup_dir: Optional custom backup directory (for cloud folders)

    Returns:
        dict with backup info, or None if no changes (for incremental)
    """
    manifest = load_manifest()

    # Decide: full or incremental?
    need_full = False

    if not manifest["backups"]:
        need_full = True  # No backups exist
    elif not _get_baseline_hashes():
        need_full = True  # No hash baseline
    else:
        # Check age of last full backup (calendar days, not hours)
        full_backups = [b for b in manifest["backups"] if b["type"] == "full"]
        if full_backups:
            last_full = max(full_backups, key=lambda x: x["created_at"])
            last_full_date = datetime.fromisoformat(last_full["created_at"]).date()
            if (datetime.now().date() - last_full_date).days >= 7:
                need_full = True
        else:
            need_full = True  # No full backup exists

    if need_full:
        return create_full_backup(backup_dir)
    else:
        return create_incremental_backup(backup_dir)


def create_full_backup(backup_dir=None):
    """
    Create a full backup of all data.

    Args:
        backup_dir: Optional custom backup directory (for cloud folders)

    Returns:
        dict with backup info or raises exception
    """
    if backup_dir is None:
        backup_dir = get_backups_dir()
    else:
        backup_dir = Path(backup_dir)

    # Validate location before starting
    valid, error = validate_backup_location(backup_dir)
    if not valid:
        raise ValueError(error)

    filename = generate_backup_filename("full", backup_dir)
    backup_path = backup_dir / filename

    files = get_all_backup_files()
    if not files:
        raise ValueError("No files to backup")

    # Calculate hashes and collect file info for smart change detection
    hashes = {}
    file_info = {}
    total_size = 0

    # Create zip archive
    try:
        with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel_path, abs_path in files.items():
                zf.write(abs_path, rel_path)
                file_hash = get_file_hash(abs_path)
                meta = get_file_metadata(abs_path)
                hashes[rel_path] = file_hash
                file_info[rel_path] = {
                    "hash": file_hash,
                    "mtime": meta["mtime"],
                    "size": meta["size"],
                }
                total_size += meta["size"]
    except OSError as e:
        # Clean up partial backup
        if backup_path.exists():
            backup_path.unlink()
        raise ValueError(f"Failed to create backup: {e}")

    # Verify backup
    verify_backup(backup_path)
    mac = write_backup_mac(backup_path)

    # Update manifest
    manifest = load_manifest()
    chain_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    backup_info = {
        "filename": filename,
        "type": "full",
        "mac": mac,
        "chain_id": chain_id,
        "created_at": datetime.now().isoformat(),
        "file_count": len(files),
        "original_size": total_size,
        "backup_size": backup_path.stat().st_size,
        "backup_dir": str(backup_dir),
    }

    manifest["backups"].append(backup_info)
    manifest["current_chain_id"] = chain_id
    save_manifest(manifest)

    # Save hashes and file info to external state file
    _save_baseline_hashes(hashes, file_info)

    return backup_info


def create_incremental_backup(backup_dir=None):
    """
    Create an incremental backup (only changed files since last backup).

    Args:
        backup_dir: Optional custom backup directory

    Returns:
        dict with backup info, or None if no changes
    """
    manifest = load_manifest()

    # Get baseline from external state file
    previous_hashes = _get_baseline_hashes()
    if not previous_hashes:
        # No previous backup, need full backup first
        return create_full_backup(backup_dir)

    # Quick check: any files changed? (mtime/size only, no hashing)
    if not has_file_changes():
        return None  # No changes - skip expensive hash computation

    if backup_dir is None:
        backup_dir = get_backups_dir()
    else:
        backup_dir = Path(backup_dir)

    # Validate location before starting
    valid, error = validate_backup_location(backup_dir)
    if not valid:
        raise ValueError(error)

    # Get current state (uses smart mtime/size change detection)
    current_hashes, current_file_info = get_file_hashes()

    # Find changes
    changed_files = {}
    files = get_all_backup_files()

    for rel_path, current_hash in current_hashes.items():
        if rel_path not in previous_hashes or previous_hashes[rel_path] != current_hash:
            changed_files[rel_path] = files[rel_path]

    # Check for deleted files (track in manifest but don't include in zip)
    deleted_files = [p for p in previous_hashes if p not in current_hashes]

    if not changed_files and not deleted_files:
        # No changes - update baseline in external state file
        # This prevents checkpoint-induced hash changes from appearing
        # as "changes" on the next backup check
        _save_baseline_hashes(current_hashes, current_file_info)
        return None

    filename = generate_backup_filename("incr", backup_dir)
    backup_path = backup_dir / filename

    total_size = 0

    # Create zip with only changed files
    try:
        with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel_path, abs_path in changed_files.items():
                zf.write(abs_path, rel_path)
                total_size += abs_path.stat().st_size

            # Include a metadata file listing deleted files
            if deleted_files:
                metadata = {"deleted_files": deleted_files}
                zf.writestr("_backup_metadata.json", json.dumps(metadata))
    except OSError as e:
        # Clean up partial backup
        if backup_path.exists():
            backup_path.unlink()
        raise ValueError(f"Failed to create backup: {e}")

    # Verify backup
    verify_backup(backup_path)
    mac = write_backup_mac(backup_path)

    # Update manifest
    backup_info = {
        "filename": filename,
        "type": "incremental",
        "mac": mac,
        "chain_id": manifest["current_chain_id"],
        "created_at": datetime.now().isoformat(),
        "file_count": len(changed_files),
        "deleted_count": len(deleted_files),
        "original_size": total_size,
        "backup_size": backup_path.stat().st_size,
        "backup_dir": str(backup_dir),
    }

    manifest["backups"].append(backup_info)
    save_manifest(manifest)

    # Save hashes and file info to external state file
    _save_baseline_hashes(current_hashes, current_file_info)

    return backup_info


# ---------------------------------------------------------------------------
# Backup authentication (security review 2026-09, #18)
#
# The encrypted payloads inside a zip self-authenticate, but the metadata
# that drives a restore (tombstones, the manifest sidecar) did not, and a
# plain ZIP is trivially editable by anyone who can write to the backup
# folder. Every zip now gets an HMAC-SHA256 over its bytes, keyed from the
# master via HKDF, written to <zip>.mac beside it and recorded in the
# manifest entry. Restore verifies it whenever the archive is unlocked.
# ---------------------------------------------------------------------------


def mac_sidecar_path(zip_path) -> Path:
    return Path(str(zip_path) + ".mac")


def compute_backup_mac(zip_path, key: bytes) -> str:
    """Hex HMAC-SHA256 of the file's bytes under ``key``."""
    import hmac

    h = hmac.new(key, digestmod=hashlib.sha256)
    with open(zip_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _current_mac_key():
    from core.encryption import Encryption

    return Encryption.backup_mac_key()


def write_backup_mac(zip_path) -> str | None:
    """Tag a freshly written zip. Returns the hex tag, or None if locked."""
    key = _current_mac_key()
    if key is None:
        return None
    tag = compute_backup_mac(zip_path, key)
    mac_sidecar_path(zip_path).write_text(tag)
    return tag


def check_backup_mac(zip_path, expected: str | None = None) -> str | None:
    """Verify a zip's tag. Returns a problem string, or None if fine.

    Compares against ``expected`` (the manifest's record) when given and
    otherwise against the .mac sidecar. Cannot verify while locked; the
    caller decides what "unverifiable" means for its path. A backup with
    no tag at all (written before 1.1) is reported so the caller can warn.
    """
    import hmac

    key = _current_mac_key()
    if key is None:
        return None
    zip_path = Path(zip_path)
    if expected is None:
        sidecar = mac_sidecar_path(zip_path)
        if not sidecar.exists():
            return (
                f"{zip_path.name}: no integrity tag (backup predates 1.1, or the tag was removed)"
            )
        expected = sidecar.read_text().strip()
    actual = compute_backup_mac(zip_path, key)
    if not hmac.compare_digest(actual, expected):
        return f"{zip_path.name}: integrity check FAILED — the backup was modified after it was written"
    return None


def verify_backup(backup_path):
    """
    Verify backup zip integrity.
    Raises exception if corrupted.
    """
    try:
        with zipfile.ZipFile(backup_path, "r") as zf:
            bad_file = zf.testzip()
            if bad_file:
                # Delete corrupted backup
                os.remove(backup_path)
                raise ValueError(f"Backup verification failed: {bad_file} is corrupted")
    except zipfile.BadZipFile:
        os.remove(backup_path)
        raise ValueError("Backup file is corrupted")


def list_backups(location: str | Path | None = None):
    """
    List all available backups with details.
    Returns list sorted by date (newest first).

    Args:
        location: Ignored (kept for API compatibility). Each backup's
                  stored location is used to check if file exists.
    """
    manifest = load_manifest()
    backups = []

    for backup in manifest["backups"]:
        # Use the location where this backup was actually saved
        backup_path = get_backup_path_for_entry(backup)

        if backup_path.exists():
            backups.append(
                {
                    "filename": backup["filename"],
                    "type": backup["type"],
                    "chain_id": backup["chain_id"],
                    "created_at": backup["created_at"],
                    "file_count": backup["file_count"],
                    "backup_size": backup["backup_size"],
                    "backup_size_mb": round(backup["backup_size"] / (1024 * 1024), 2),
                    "path": str(backup_path),
                }
            )

    # Sort by date, newest first
    backups.sort(key=lambda x: x["created_at"], reverse=True)
    return backups


def get_restore_points():
    """
    Get available restore points.

    ALL backups are valid restore points:
    - Full backups restore directly
    - Incremental backups restore by applying chain (full + incrementals)
    - Pre-restore backups are also valid restore points

    Returns list of restore points with display info.
    """
    return build_restore_points(load_manifest()["backups"])


def build_restore_points(backups, override_dir=None):
    """Build restore points from a list of manifest entries.

    Split out of get_restore_points so the disaster-recovery path can
    reuse it against a manifest found in a backup folder rather than the
    local one. `override_dir` resolves every entry's file against that
    folder instead of its recorded backup_dir — a recovered folder is
    rarely at the path it was written from (different machine, different
    home directory, iCloud mounted elsewhere).
    """

    def resolve(entry):
        if override_dir is not None:
            return Path(override_dir) / safe_backup_filename(entry["filename"])
        return get_backup_path_for_entry(entry)

    # Group by chain
    chains = {}
    for backup in backups:
        # A manifest entry missing chain_id is malformed (hand-edited, or
        # written by a pre-chain version). Skip it rather than raising —
        # a KeyError here would take down the whole restore screen, and
        # callers that gate on backup health need a clean "nothing usable"
        # answer instead of a crash.
        chain_id = backup.get("chain_id")
        if not chain_id:
            log.warning(f"Skipping manifest entry without chain_id: {backup.get('filename', '?')}")
            continue
        if chain_id not in chains:
            chains[chain_id] = {"full": None, "incrementals": [], "pre_restore": None}

        if backup["type"] == "full":
            chains[chain_id]["full"] = backup
        elif backup["type"] == "pre_restore":
            chains[chain_id]["pre_restore"] = backup
        else:
            chains[chain_id]["incrementals"].append(backup)

    # Build restore points
    restore_points = []

    # Safety backups first: each is standalone and each is its own
    # restore point.
    #
    # These used to be grouped by a shared chain_id of "pre_restore",
    # which meant the chains dict held a single slot and every safety
    # backup overwrote the last — only the newest was ever offered. The
    # others sat on disk and in the manifest, unreachable, and the moment
    # you want an older one is precisely after a second bad restore.
    #
    # Matched on type rather than chain_id so entries written before this
    # change (chain_id == "pre_restore") still appear.
    for backup in backups:
        if backup.get("type") != "pre_restore":
            continue

        backup_path = resolve(backup)
        if not backup_path.exists():
            continue

        created = datetime.fromisoformat(backup["created_at"])
        display_time = created.strftime("%b %d, %Y at %I:%M %p").replace(" 0", " ")

        restore_points.append(
            {
                "id": f"pre_restore_{backup['filename']}",
                "filename": backup["filename"],
                "display_name": f"{display_time} (Safety backup)",
                "created_at": backup["created_at"],
                "type": "pre_restore",
                "is_safety": True,
                "chain_id": backup.get("chain_id", "pre_restore"),
                "dependent_count": 0,
                "files_needed": [str(backup_path)],
                "macs": {str(backup_path): backup.get("mac")},
            }
        )

    for chain_id, chain in chains.items():
        if chain.get("pre_restore") and not chain.get("full"):
            # Already emitted above.
            continue

        if not chain["full"]:
            continue  # Skip orphaned incrementals

        # Sort incrementals by date
        chain["incrementals"].sort(key=lambda x: x["created_at"])

        # Count dependents for this chain's full backup
        dependent_count = len(chain["incrementals"])

        # Full backup as restore point
        full_backup = chain["full"]
        backup_path = resolve(full_backup)

        if backup_path.exists():
            # Format date with time
            created = datetime.fromisoformat(full_backup["created_at"])
            display_time = created.strftime("%b %d, %Y at %I:%M %p").replace(" 0", " ")

            restore_points.append(
                {
                    "id": f"{chain_id}_full",
                    "filename": full_backup["filename"],
                    "display_name": display_time,
                    "created_at": full_backup["created_at"],
                    "type": "full",
                    "is_safety": False,
                    "chain_id": chain_id,
                    "dependent_count": dependent_count,
                    "files_needed": [str(backup_path)],
                    "macs": {str(backup_path): full_backup.get("mac")},
                }
            )

        # Each incremental in the chain is also a restore point.
        #
        # A missing incremental is NOT skipped. Skipping it silently
        # produced a restore point whose files_needed had a hole in the
        # middle — full + incr1 + incr3, with incr2 gone — and every
        # verification layer downstream reported it clean, because those
        # layers check that the listed files open, not that the list is
        # complete. The password-change and v3-migration gates would then
        # open their non-resumable windows on the strength of a chain
        # that silently drops one backup's changes AND its deletions.
        #
        # Mid-chain loss is exactly the cloud-eviction case the
        # verification layer exists for, so the missing file stays in
        # files_needed and is reported through the existing path rather
        # than being quietly dropped here.
        files_needed = [str(backup_path)]
        macs = {str(backup_path): full_backup.get("mac")}
        for i, incr in enumerate(chain["incrementals"]):
            incr_path = resolve(incr)
            files_needed = files_needed + [str(incr_path)]
            macs = {**macs, str(incr_path): incr.get("mac")}

            # Format date with time
            created = datetime.fromisoformat(incr["created_at"])
            display_time = created.strftime("%b %d, %Y at %I:%M %p").replace(" 0", " ")

            restore_points.append(
                {
                    "id": f"{chain_id}_incr_{i}",
                    "filename": incr["filename"],
                    "display_name": display_time,
                    "created_at": incr["created_at"],
                    "type": "incremental",
                    "is_safety": False,
                    "chain_id": chain_id,
                    "dependent_count": 0,
                    "files_needed": files_needed.copy(),
                    "macs": dict(macs),
                }
            )

    # Sort by date, newest first
    restore_points.sort(key=lambda x: x["created_at"], reverse=True)

    # Annotate which credentials each point would need. Done once here
    # with the live key file read a single time, rather than per point.
    try:
        salt_path = Config.get_salt_path()
        current_blob = salt_path.read_bytes() if salt_path.exists() else None
    except Exception:
        current_blob = None

    for point in restore_points:
        creds = describe_restore_point_credentials(point.get("files_needed", []), current_blob)
        point["credential_status"] = creds["status"]
        point["credential_note"] = creds["note"]

    return restore_points


# ============================================================================
# Disaster recovery: finding backups when the local index is gone
# ============================================================================

# full_2026-08-15_111308.zip / incr_2026-08-15_111309_412773.zip
_BACKUP_FILENAME_RE = re.compile(
    r"^(full|incr|pre_restore)_(\d{4}-\d{2}-\d{2})_(\d{6})(?:_(\d{1,6}))?\.zip$"
)

# Filenames use "incr"; manifest entries say "incremental".
_TYPE_FROM_PREFIX = {
    "full": "full",
    "incr": "incremental",
    "pre_restore": "pre_restore",
}


def reconstruct_manifest_entries(folder):
    """Rebuild manifest entries from the zips in a folder, by filename.

    The last resort, for when a backup folder survived but its manifest
    did not. Backup filenames carry type and a sortable timestamp, and
    the writer only ever appends to the newest chain, so the structure
    is recoverable: each `full_` opens a chain, every `incr_` after it
    joins that chain, and `pre_restore_` files stand alone.

    This is inference, not a record. It is wrong if two machines wrote
    to one folder, since their chains would interleave by time and get
    stitched into one. Entries are marked `reconstructed` so the caller
    can say so plainly rather than presenting a guess as a fact.
    """
    folder = Path(folder)
    entries = []

    try:
        names = [p.name for p in folder.iterdir() if p.is_file()]
    except OSError as e:
        log.warning(f"Could not read backup folder {folder}: {e}")
        return entries

    # Parse first, then sort CHRONOLOGICALLY. Sorting the filenames
    # directly does not work: the type prefix leads, so every "full_"
    # sorts ahead of every "incr_" regardless of date, and a folder
    # holding two chains gets stitched into one with all the fulls at the
    # front. Timestamp order is the whole basis for inferring which full
    # an incremental belongs to.
    parsed = []
    for name in names:
        match = _BACKUP_FILENAME_RE.match(name)
        if not match:
            continue

        prefix, date_part, time_part, micro = match.groups()
        try:
            created = datetime.strptime(f"{date_part} {time_part}", "%Y-%m-%d %H%M%S")
        except ValueError:
            continue

        parsed.append((created, micro or "", name, _TYPE_FROM_PREFIX[prefix]))

    parsed.sort(key=lambda item: (item[0], item[1], item[2]))

    current_chain = None

    for created, _micro, name, backup_type in parsed:
        if backup_type == "pre_restore":
            chain_id = f"pre_restore_{name}"
        elif backup_type == "full":
            current_chain = created.strftime("%Y%m%d_%H%M%S")
            chain_id = current_chain
        else:
            if current_chain is None:
                # Incremental with no preceding full: an orphan. Kept out
                # rather than invented a chain for — build_restore_points
                # drops orphaned incrementals anyway.
                continue
            chain_id = current_chain

        size = 0
        try:
            size = (folder / name).stat().st_size
        except OSError:
            pass

        entries.append(
            {
                "filename": name,
                "type": backup_type,
                "chain_id": chain_id,
                "created_at": created.isoformat(),
                "backup_size": size,
                "backup_dir": str(folder),
                "reconstructed": True,
            }
        )

    return entries


def discover_restore_points_in(folder):
    """Find restore points in a folder that is not the local backups dir.

    The recovery entry point: the user knows where their backups are,
    and nothing on this machine does. Prefers the manifest sidecar
    written alongside the zips; falls back to filename reconstruction
    when there isn't one.

    Returns (points, source) where source is "manifest", "reconstructed",
    or "empty" — the caller needs to tell the user which, because a
    reconstructed chain deserves a second look at the dates before
    anyone overwrites anything with it.
    """
    folder = Path(folder)

    if not folder.is_dir():
        raise ValueError(f"Not a folder: {folder}")

    # Refuse another application's backups outright. EdgeCase's are
    # byte-for-byte plausible here — same filenames, same key-file paths
    # — and restoring one would overwrite this archive's key file with
    # another app's while finding no database to go with it. Checked on
    # the manual path as well as the search path, or the folder picker
    # becomes the hole the search was careful to close.
    if not folder_holds_mailrepo_backups(folder):
        if _looks_like_backup_folder({p.name for p in folder.iterdir() if p.is_file()}):
            raise ValueError(
                "That folder holds backups from a different application, not MailRepo."
            )
        return [], "empty"

    sidecar = folder / "manifest.json"
    if sidecar.exists():
        try:
            with open(sidecar, "r") as f:
                manifest = json.load(f)
            points = build_restore_points(manifest.get("backups", []), override_dir=folder)
            if points:
                return points, "manifest"
            # A sidecar listing nothing that is actually present is worse
            # than no sidecar — fall through and look at real files.
            log.warning(f"Manifest in {folder} matched no files on disk; reconstructing")
        except (json.JSONDecodeError, ValueError, OSError) as e:
            log.warning(f"Could not read manifest in {folder}: {e}")

    entries = reconstruct_manifest_entries(folder)
    if not entries:
        return [], "empty"

    points = build_restore_points(entries, override_dir=folder)
    for point in points:
        point["reconstructed"] = True

    return points, ("reconstructed" if points else "empty")


def prepare_restore(restore_point_id):
    """
    Prepare for restore by extracting to staging folder.
    Does NOT replace production files yet.

    Returns path to staging folder.
    """
    restore_points = get_restore_points()
    point = next((p for p in restore_points if p["id"] == restore_point_id), None)

    if not point:
        raise ValueError(f"Restore point not found: {restore_point_id}")

    return prepare_restore_from_point(point)


def prepare_restore_from_point(point):
    """Stage a restore from an already-resolved restore point.

    Same work as prepare_restore, minus the lookup. The recovery path
    has its point in hand from a folder scan, and cannot look it up by
    id because the local manifest that ids refer to is exactly what is
    missing.
    """
    # Authenticity gate. A restore replays tombstones and replaces the
    # key file and database; a tampered zip must not get that far.
    for path_str in point.get("files_needed", []):
        problem = check_backup_mac(path_str, (point.get("macs") or {}).get(path_str))
        if problem and "no integrity tag" not in problem:
            raise ValueError(problem)

    # Create pre-restore backup first (safety net)
    create_pre_restore_backup()

    staging_dir = get_restore_staging_dir()

    # Clear any existing staging
    if staging_dir.exists():
        shutil.rmtree(staging_dir)

    staging_dir.mkdir(parents=True)

    # Replay the chain in order. Deletions are applied PER ZIP, straight
    # after that zip's own extraction — not accumulated and applied at the
    # end.
    #
    # Accumulating them loses delete-then-recreate: a file deleted in
    # incremental N and recreated in N+1 gets extracted correctly by N+1
    # and then removed by N's stale tombstone, so the restore reports
    # success while reconstructing a state that never existed. Not
    # hypothetical for this app — permanently delete an archived email,
    # later re-commit the same message to the same folder, and the path
    # repeats exactly.
    #
    # Per-zip ordering is unambiguous because a path cannot be both
    # changed and deleted within a single backup.
    for backup_path in point["files_needed"]:
        with zipfile.ZipFile(backup_path, "r") as zf:
            names = zf.namelist()

            for name in names:
                if name != "_backup_metadata.json":
                    zf.extract(name, staging_dir)

            if "_backup_metadata.json" in names:
                metadata = json.loads(zf.read("_backup_metadata.json"))
                # deleted_files is attacker-controlled once anyone can
                # write to the backup folder: validate before joining,
                # then confirm the result is still inside staging.
                staging_root = staging_dir.resolve()
                for rel_path in metadata.get("deleted_files", []):
                    staged_path = staging_dir / safe_backup_relpath(rel_path)
                    if not staged_path.resolve().is_relative_to(staging_root):
                        raise UnsafeBackupPathError(f"tombstone escapes staging: {rel_path!r}")
                    if staged_path.is_file():
                        staged_path.unlink()

    # Write restore marker
    marker = {
        "restore_point_id": point["id"],
        "prepared_at": datetime.now().isoformat(),
        "point_info": point,
    }
    with open(staging_dir / ".restore_marker", "w") as f:
        json.dump(marker, f)

    return str(staging_dir)


def create_pre_restore_backup():
    """Create a backup of current state before restore (safety net).

    Goes to the CONFIGURED backup location, not the repo-local default.
    The safety net is worth least on the machine that is about to
    overwrite itself: if the restore goes wrong badly enough to take the
    disk with it, a rollback copy that never left the machine is no
    rollback at all. It also keeps this consistent with every other
    backup path, which all honour backup_location.
    """
    from core.database import get_setting

    try:
        location = get_setting("backup_location", "")
    except Exception:
        # Settings live in the encrypted DB. If it is not readable here,
        # fall back rather than refusing to take the safety backup.
        location = ""

    backup_dir = Path(location) if location else get_backups_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)

    filename = generate_backup_filename("pre_restore", backup_dir)
    backup_path = backup_dir / filename

    files = get_all_backup_files()
    if not files:
        return None  # Nothing to back up

    with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel_path, abs_path in files.items():
            zf.write(abs_path, rel_path)

    verify_backup(backup_path)
    mac = write_backup_mac(backup_path)

    # Add to manifest
    manifest = load_manifest()
    manifest["backups"].append(
        {
            "filename": filename,
            "type": "pre_restore",
            "mac": mac,
            "chain_id": f"pre_restore_{filename}",
            "created_at": datetime.now().isoformat(),
            "file_count": len(files),
            "backup_size": backup_path.stat().st_size,
            "backup_dir": str(backup_dir),
        }
    )
    save_manifest(manifest)

    return str(backup_path)


def check_restore_pending():
    """Check if there's a pending restore to complete."""
    marker_path = get_restore_staging_dir() / ".restore_marker"
    if marker_path.exists():
        with open(marker_path, "r") as f:
            return json.load(f)
    return None


def complete_restore():
    """
    Complete a pending restore by replacing production files.
    Should be called at startup before database is opened.

    Returns dict with restore info or None if no restore pending.
    """
    staging_dir = get_restore_staging_dir()
    marker = check_restore_pending()
    if not marker:
        return None

    data_dir = get_data_dir()
    archive_dir = get_archive_dir()

    # Replace database
    staged_db = staging_dir / "data" / "mailrepo.db"
    if staged_db.exists():
        data_dir.mkdir(parents=True, exist_ok=True)
        target_db = data_dir / "mailrepo.db"
        if target_db.exists():
            target_db.unlink()
        # A -wal left from an unclean exit would be replayed into the
        # restored database on next open. Remove both sidecars first.
        for ext in ("-wal", "-shm"):
            sidecar = data_dir / f"mailrepo.db{ext}"
            if sidecar.exists():
                sidecar.unlink()
        shutil.copy2(staged_db, target_db)

    # Replace security files. (.secret_key is no longer used or backed
    # up; one found in an old backup is simply not restored.)
    for security_file in [".salt"]:
        staged_file = staging_dir / "data" / security_file
        if staged_file.exists():
            target_file = data_dir / security_file
            if target_file.exists():
                target_file.unlink()
            shutil.copy2(staged_file, target_file)

    # Replace archive folder
    staged_archive = staging_dir / "archive"
    if staged_archive.exists():
        if archive_dir.exists():
            shutil.rmtree(archive_dir)
        shutil.copytree(staged_archive, archive_dir)

    # Clean up staging
    shutil.rmtree(staging_dir)

    # Mark the restore UNVERIFIED until someone proves they can open it.
    # From this moment the data on disk is data nobody has vouched for:
    # if the backup's password turns out to be lost, the login screen is
    # a wall and — without this marker — the recovery routes are dead
    # too, because a key file now exists. The marker keeps the recovery
    # door open (auth's _recovery_door_open) so the user can go back and
    # restore a DIFFERENT backup, including the pre-restore safety
    # backup. The first successful login (or verified recovery key)
    # deletes it, which is also what closes the door — so an archive in
    # normal use, which by definition has been opened since its last
    # restore, is never exposed by it.
    set_restore_unverified()

    return {
        "restored_at": datetime.now().isoformat(),
        "restore_point": marker["restore_point_id"],
        "original_date": marker["point_info"]["created_at"],
        # Carried from the point the user chose: the login screen after
        # the relaunch is the one place that can say which password the
        # restored archive wants — without it, a perfectly correct
        # restore is indistinguishable from a rejected password. .get()
        # because markers staged by older builds carry no note.
        "credential_note": marker["point_info"].get("credential_note", ""),
        "credential_status": marker["point_info"].get("credential_status", ""),
    }


def _restore_unverified_marker():
    """Path of the unverified-restore marker.

    In the data directory beside the key files it describes, so it lives
    and dies with the data it vouches for. NOT in get_all_backup_files
    (which names its files explicitly), so it never rides into a backup
    zip — full, incremental, or pre-restore — and the manifest sidecar
    machinery records zips, so it never appears there either.
    """
    return get_data_dir() / ".restore_unverified"


def set_restore_unverified():
    """Record that the data on disk came from a restore no one has
    opened yet. Failure is logged, never raised — refusing to finish a
    restore over a bookkeeping file would be worse than the gap."""
    try:
        marker = _restore_unverified_marker()
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"restored_at": datetime.now().isoformat()}))
    except Exception as e:
        log.warning(f"Could not write restore-unverified marker: {e}")


def restore_unverified():
    """True if the last restore has not yet been opened successfully."""
    try:
        return _restore_unverified_marker().exists()
    except OSError:
        return False


def clear_restore_unverified():
    """A demonstrated credential vouches for the restored data; the
    recovery door closes behind it."""
    try:
        _restore_unverified_marker().unlink(missing_ok=True)
    except OSError as e:
        log.warning(f"Could not clear restore-unverified marker: {e}")


def cancel_restore():
    """Cancel a pending restore (remove staging folder)."""
    staging_dir = get_restore_staging_dir()
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
        return True
    return False


def cleanup_old_backups(retention, custom_location=None):
    """
    Delete backups older than the retention period.

    Retention periods:
    - '1_month': 30 days
    - '6_months': 180 days
    - '1_year': 365 days
    - 'forever': no deletion

    Rules:
    - Always keep at least one valid restore point
    - Delete entire chains when their newest incremental exceeds retention
    - Only delete if a newer chain exists
    """
    if retention == "forever":
        return

    retention_days = {"1_month": 30, "6_months": 180, "1_year": 365}.get(retention)

    if not retention_days:
        return

    manifest = load_manifest()

    # No backup_dir here on purpose: every deletion resolves its path
    # from the manifest entry via get_backup_path_for_entry(), so files
    # written under a previous backup location are still found and
    # removed rather than being orphaned on disk.

    cutoff_date = (datetime.now() - timedelta(days=retention_days)).isoformat()

    # Group backups by chain
    chains = {}
    safety_backups = []
    for backup in manifest["backups"]:
        if backup["type"] == "pre_restore":
            safety_backups.append(backup)
            continue
        chain_id = backup.get("chain_id")
        if chain_id:
            if chain_id not in chains:
                chains[chain_id] = {"full": None, "incrementals": []}
            if backup["type"] == "full":
                chains[chain_id]["full"] = backup
            else:
                chains[chain_id]["incrementals"].append(backup)

    # Sort chains by the full backup date (oldest first)
    sorted_chain_ids = sorted(
        chains.keys(),
        key=lambda cid: chains[cid]["full"]["created_at"] if chains[cid]["full"] else "",
    )

    # Always keep the newest chain
    if len(sorted_chain_ids) <= 1:
        return

    # ...but only if it actually works. The docstring promised "at least
    # one VALID restore point" and the code checked only that a chain was
    # newest. If the newest chain is corrupt, truncated or evicted and
    # every older chain has aged past retention, this would delete the
    # only chain that opens. Since Session 69 cleanup runs on every
    # automatic backup, so the deletion side executes daily.
    newest_chain_id = sorted_chain_ids[-1]
    newest_points = [
        p
        for p in get_restore_points()
        if p.get("chain_id") == newest_chain_id and p["type"] != "pre_restore"
    ]
    if not newest_points:
        log.warning("Retention cleanup skipped: newest chain has no usable restore point.")
        return

    newest_problems = verify_restore_point_files(newest_points[0])
    if newest_problems:
        log.warning(
            "Retention cleanup skipped: the newest chain does not verify "
            f"({'; '.join(newest_problems)}). Refusing to delete older "
            "backups while the one being kept is unusable."
        )
        return

    chains_to_delete = []

    # Check each chain except the newest
    for chain_id in sorted_chain_ids[:-1]:
        chain = chains[chain_id]
        if not chain["full"]:
            continue

        # Find the newest backup in this chain
        all_in_chain = [chain["full"]] + chain["incrementals"]
        newest_date = max(b["created_at"] for b in all_in_chain)

        if newest_date < cutoff_date:
            chains_to_delete.append(chain_id)

    # Delete marked chains
    for chain_id in chains_to_delete:
        chain = chains[chain_id]

        for incr in chain["incrementals"]:
            # Resolve per entry, not against the current directory: after a
            # backup-location change, old-location files would otherwise be
            # dropped from the manifest and left on disk forever.
            incr_path = get_backup_path_for_entry(incr)
            if incr_path.exists():
                incr_path.unlink()
                mac_sidecar_path(incr_path).unlink(missing_ok=True)
            if incr in manifest["backups"]:
                manifest["backups"].remove(incr)

        if chain["full"]:
            full_path = get_backup_path_for_entry(chain["full"])
            if full_path.exists():
                full_path.unlink()
                mac_sidecar_path(full_path).unlink(missing_ok=True)
            if chain["full"] in manifest["backups"]:
                manifest["backups"].remove(chain["full"])

    if chains_to_delete:
        save_manifest(manifest)
        log.info(f"Retention cleanup: Deleted {len(chains_to_delete)} old backup chain(s)")

    # Orphaned incrementals: chains whose full backup is gone.
    #
    # These can never be restored — replay needs the full — but the loop
    # above skips them, because it bails on `if not chain["full"]`. They
    # accumulated in the manifest and on disk indefinitely. Only removed
    # once past retention, so a chain whose full is briefly missing (an
    # eviction, a sync in progress) is not destroyed on sight.
    orphans_deleted = 0
    for chain_id, chain in chains.items():
        if chain["full"] or not chain["incrementals"]:
            continue
        newest_date = max(b["created_at"] for b in chain["incrementals"])
        if newest_date >= cutoff_date:
            continue
        for incr in chain["incrementals"]:
            incr_path = get_backup_path_for_entry(incr)
            if incr_path.exists():
                incr_path.unlink()
                mac_sidecar_path(incr_path).unlink(missing_ok=True)
            if incr in manifest["backups"]:
                manifest["backups"].remove(incr)
            orphans_deleted += 1

    if orphans_deleted:
        save_manifest(manifest)
        log.info(
            f"Retention cleanup: Deleted {orphans_deleted} orphaned "
            f"incremental(s) with no surviving full backup"
        )

    # Clean up old safety backups
    safety_deleted = 0
    for backup in safety_backups:
        if backup["created_at"] < cutoff_date:
            backup_path = get_backup_path_for_entry(backup)
            if backup_path.exists():
                backup_path.unlink()
                mac_sidecar_path(backup_path).unlink(missing_ok=True)
            if backup in manifest["backups"]:
                manifest["backups"].remove(backup)
            safety_deleted += 1

    if safety_deleted:
        save_manifest(manifest)
        log.info(f"Retention cleanup: Deleted {safety_deleted} old safety backup(s)")


def verify_restore_point_files(restore_point) -> list:
    """
    Verify every file a restore point depends on is actually usable.

    A manifest entry is a claim, not evidence. This opens each file in the
    chain, which is what proves the claim:

      - exists() catches a deleted or moved backup
      - a zero/short size catches a truncated write
      - opening the zip forces cloud-storage materialization, so an
        iCloud-evicted placeholder fails here instead of at restore time
      - testzip() catches silent corruption

    Returns a list of human-readable problems. Empty list means the whole
    chain is verified good.
    """
    problems = []

    for path_str in restore_point.get("files_needed", []):
        path = Path(path_str)
        name = path.name

        if not path.exists():
            problems.append(f"{name}: missing from disk")
            continue

        try:
            size = path.stat().st_size
        except OSError as e:
            problems.append(f"{name}: cannot stat ({e})")
            continue

        if size == 0:
            problems.append(f"{name}: zero bytes")
            continue

        try:
            with zipfile.ZipFile(path, "r") as zf:
                bad_file = zf.testzip()
        except zipfile.BadZipFile:
            problems.append(f"{name}: not a readable zip (corrupt or truncated)")
            continue
        except OSError as e:
            # Cloud-evicted files and permission failures land here.
            problems.append(f"{name}: unreadable ({e}) — cloud-evicted or blocked?")
            continue

        if bad_file:
            problems.append(f"{name}: corrupt entry ({bad_file})")
            continue

        # Authenticity, when a key is in hand. The manifest's record of
        # the tag is preferred (the local manifest is not in the backup
        # folder); a backup folder found by disaster recovery carries
        # only the sidecar, which an attacker without the key still
        # cannot forge. A legacy backup with no tag is a warning, not a
        # refusal — otherwise every pre-1.1 backup becomes unrestorable.
        expected = (restore_point.get("macs") or {}).get(path_str)
        problem = check_backup_mac(path, expected)
        if problem and "no integrity tag" in problem:
            log.warning(problem)
        elif problem:
            problems.append(problem)

    return problems


def key_file_fingerprint(blob):
    """Identify which credentials a key file belongs to, without using them.

    Returns the SHA-256 prefix of each wrapper half plus the format
    version. Comparing these against the live key file says which
    credentials a backup needs, without trying a single password:

      - MRC2 vs MRC3 tells you whether it predates recovery keys
      - the password half changes only when the password changes, because
        rewrap_password mints a fresh salt every time
      - the recovery half changes only when the recovery key is rotated

    That separation is a property of the envelope: each rewrap touches
    one half and leaves the other byte-identical.
    """
    if not blob or len(blob) < 4:
        return None

    magic = blob[:4]

    if magic == b"MRC2":
        return {"version": 2, "password_id": None, "recovery_id": None}

    if magic != b"MRC3":
        # No recognised magic. The magic was introduced with v2, so a key
        # file without it predates v2 — the Fernet/PBKDF2 scheme, whose
        # code was removed entirely in the v1 cleanup. Backups this old
        # cannot be opened by any current build.
        return {"version": 1, "password_id": None, "recovery_id": None}

    # Offsets mirror core.encryption's MRC3 layout. Imported lazily to
    # keep utils.backup free of a core.encryption dependency at module
    # scope (backup runs in contexts where encryption may be locked).
    from core.encryption import (
        V3_OFF_SALT_PW,
        V3_OFF_SALT_RK,
        V3_SALT_FILE_LENGTH,
    )

    if len(blob) != V3_SALT_FILE_LENGTH:
        return None

    pw_half = blob[V3_OFF_SALT_PW:V3_OFF_SALT_RK]
    rk_half = blob[V3_OFF_SALT_RK:]

    return {
        "version": 3,
        "password_id": hashlib.sha256(pw_half).hexdigest()[:16],
        "recovery_id": hashlib.sha256(rk_half).hexdigest()[:16],
    }


def read_key_file_from_chain(files_needed):
    """Extract the key file that a restore point would actually land on.

    Incrementals only carry files that changed, so most do not contain
    data/.salt. The effective key file is the one from the LAST backup in
    the chain that has it — that is what extraction leaves on disk.
    """
    blob = None
    for path_str in files_needed:
        try:
            with zipfile.ZipFile(path_str, "r") as zf:
                names = zf.namelist()
                for candidate in ("data/.salt", ".salt"):
                    if candidate in names:
                        blob = zf.read(candidate)
                        break
        except Exception:
            continue
    return blob


def describe_restore_point_credentials(files_needed, current_blob=None):
    """What credentials would open this restore point, versus today's.

    Returns a dict with a machine-readable `status` and a `note` written
    for someone about to click Restore. Never raises: a restore screen
    that cannot render because a fingerprint failed is worse than one
    that says nothing.
    """
    unknown = {"status": "unknown", "note": ""}

    try:
        if current_blob is None:
            salt_path = Config.get_salt_path()
            current_blob = salt_path.read_bytes() if salt_path.exists() else None

        current = key_file_fingerprint(current_blob)
        backup = key_file_fingerprint(read_key_file_from_chain(files_needed))

        if not backup:
            return unknown

        if backup["version"] == 1:
            return {
                "status": "obsolete_crypto",
                "note": (
                    "Created before the May 2026 encryption upgrade. This "
                    "build cannot open it — the old scheme was removed. It "
                    "is not a usable restore point and can be deleted."
                ),
            }

        if current is None:
            # No key file on this machine at all — the disaster case, and
            # the one place this function matters most. There is nothing
            # to compare against, but silence here is the wrong answer:
            # after a total loss the user is about to type a password,
            # and needs to know which one.
            if backup["version"] == 2:
                return {
                    "status": "no_current_key",
                    "note": (
                        "Opens with the master password that was in use "
                        "when this backup was made. It predates recovery "
                        "keys, so no recovery key will open it."
                    ),
                }
            return {
                "status": "no_current_key",
                "note": (
                    "Opens with the master password and recovery key that "
                    "were in use when this backup was made — not any you "
                    "have set since."
                ),
            }

        if backup["version"] == 2:
            if current and current["version"] == 3:
                return {
                    "status": "predates_recovery_key",
                    "note": (
                        "Predates recovery keys. Restoring this returns the "
                        "archive to password-only — your recovery key will "
                        "not open it, and you would need to add a new one."
                    ),
                }
            return {"status": "current", "note": ""}

        if not current or current["version"] != 3:
            return unknown

        password_changed = backup["password_id"] != current["password_id"]
        recovery_rotated = backup["recovery_id"] != current["recovery_id"]

        if password_changed and recovery_rotated:
            return {
                "status": "both_changed",
                "note": (
                    "Both your password and recovery key have changed since "
                    "this backup. It opens only with the ones in use at the "
                    "time."
                ),
            }
        if password_changed:
            return {
                "status": "password_changed",
                "note": (
                    "Your master password has changed since this backup. It "
                    "opens with the password you used then, not your current "
                    "one. Your recovery key still works."
                ),
            }
        if recovery_rotated:
            return {
                "status": "recovery_key_rotated",
                "note": (
                    "Your recovery key has been replaced since this backup. "
                    "It opens with the earlier key, or with your current "
                    "password."
                ),
            }

        return {"status": "current", "note": ""}
    except Exception as e:
        log.warning(f"Could not fingerprint restore point credentials: {e}")
        return unknown


def get_verified_latest_restore_point():
    """
    Newest restore point whose entire chain verifies on disk.

    Returns (restore_point, problems). If a usable point is found,
    problems is empty. If the newest point fails verification, we do NOT
    silently fall back to an older one — the caller is told what broke,
    because a user who believes they have a backup from an hour ago must
    not be handed one from last week without being told.

    Returns (None, problems) when nothing usable exists.
    """
    points = get_restore_points()
    if not points:
        return None, ["No restore points found in the manifest."]

    newest = points[0]
    problems = verify_restore_point_files(newest)
    if problems:
        return None, problems
    return newest, []


def get_backup_status():
    """
    Get current backup status for display.
    Uses CALENDAR DATE for "Today" comparison, not hours.
    """
    manifest = load_manifest()
    backups = [b for b in manifest["backups"] if b["type"] in ("full", "incremental")]

    if not backups:
        return {
            "has_backups": False,
            "last_backup": None,
            "last_backup_display": "Never",
            "backup_count": 0,
        }

    last = max(backups, key=lambda x: x["created_at"])
    last_datetime = datetime.fromisoformat(last["created_at"])
    last_date = last_datetime.date()

    now = datetime.now()
    today = now.date()
    yesterday = today - timedelta(days=1)

    time_str = last_datetime.strftime("%I:%M %p").lstrip("0")

    if last_date == today:
        diff_seconds = (now - last_datetime).total_seconds()
        if diff_seconds < 60:
            display = "Just now"
        elif diff_seconds < 3600:
            minutes = int(diff_seconds // 60)
            display = f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        else:
            display = f"Today at {time_str}"
    elif last_date == yesterday:
        display = f"Yesterday at {time_str}"
    else:
        days_ago = (today - last_date).days
        if days_ago < 7:
            display = f"{days_ago} days ago"
        else:
            display = last_datetime.strftime("%B %d, %Y")

    return {
        "has_backups": True,
        "last_backup": last["created_at"],
        "last_backup_display": display,
        "last_backup_type": last["type"],
        "backup_count": len(backups),
    }


def detect_cloud_folders():
    """
    Detect available cloud sync folders.
    Returns list of {name, path} dicts.
    """
    home = Path.home()
    cloud_folders = []

    # iCloud Drive
    icloud = home / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
    if icloud.exists():
        cloud_folders.append({"name": "iCloud Drive", "path": str(icloud / "MailRepo Backups")})

    # Dropbox
    dropbox = home / "Dropbox"
    if dropbox.exists():
        cloud_folders.append(
            {"name": "Dropbox", "path": str(dropbox / "Apps" / "MailRepo Backups")}
        )

    # Google Drive (new location)
    google_drive_new = home / "Library" / "CloudStorage"
    if google_drive_new.exists():
        for folder in google_drive_new.iterdir():
            if folder.name.startswith("GoogleDrive"):
                cloud_folders.append(
                    {"name": "Google Drive", "path": str(folder / "My Drive" / "MailRepo Backups")}
                )
                break

    # Google Drive (old location)
    google_drive_old = home / "Google Drive"
    if google_drive_old.exists() and not any(c["name"] == "Google Drive" for c in cloud_folders):
        cloud_folders.append(
            {"name": "Google Drive", "path": str(google_drive_old / "MailRepo Backups")}
        )

    # OneDrive
    onedrive = home / "OneDrive"
    if onedrive.exists():
        cloud_folders.append({"name": "OneDrive", "path": str(onedrive / "MailRepo Backups")})

    return cloud_folders


def _looks_like_backup_folder(names):
    """True if this directory's file names look like a MailRepo backup set."""
    if "manifest.json" in names:
        return True
    return any(_BACKUP_FILENAME_RE.match(name) for name in names)


def folder_holds_mailrepo_backups(folder):
    """Confirm a folder holds THIS application's backups.

    Checked in order of authority:

    1. The stamp in the sidecar manifest. MailRepo marks every folder it
       writes to, so its own backups identify themselves.
    2. Failing that, the contents of a full backup. Folders written
       before stamping existed carry no marker, and refusing those would
       make recovery useless to the person who has been backing up
       diligently all along — exactly the person it is for.

    The fallback stays narrow: the database name is the only thing that
    separates a MailRepo backup from an EdgeCase one (see APP_ID).
    """
    folder = Path(folder)

    stamp = read_folder_stamp(folder)
    if stamp is not None:
        return stamp.get("app") == APP_ID

    try:
        candidates = sorted(
            (p for p in folder.iterdir() if p.is_file() and p.name.startswith("full_")),
            reverse=True,
        )
    except OSError:
        return False

    for candidate in candidates[:3]:
        try:
            with zipfile.ZipFile(candidate, "r") as zf:
                names = zf.namelist()
        except Exception:
            continue

        if any(name.endswith("data/mailrepo.db") or name == "mailrepo.db" for name in names):
            return True

        # A readable full backup that is definitively something else.
        # Stop rather than hoping an older one disagrees.
        return False

    return False


def find_backup_locations():
    """Where this archive's backups are, without guessing.

    Two checks, both certain:

    1. The record. MailRepo notes every folder it writes backups to, in
       a file outside the application directory and outside the
       database, so it survives the loss that makes it necessary. It
       stores whatever location the user chose, on any platform.
    2. MailRepo's own default backups folder — the one place backups go
       when the user never chose a location, and the one place worth
       checking when the record itself is gone (a machine so new that
       even the state file never existed here).

    There is deliberately no filesystem search beyond these. An earlier
    version swept the disk for anything that looked like backups; it
    guessed at cloud-provider paths that turn out to move between OS
    versions, and it surfaced EdgeCase's byte-identical backup folders.
    A user who put backups somewhere of their own choosing knows where —
    the folder picker on the recovery screen covers that case without a
    single assumption.

    Results carry `known=True` when they came from the record.
    """
    results = []
    seen = set()

    for entry in get_known_locations():
        directory = Path(entry["path"])
        try:
            resolved = directory.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue

        if not folder_holds_mailrepo_backups(directory):
            continue

        try:
            points, source = discover_restore_points_in(directory)
        except Exception as e:
            log.warning(f"Recorded location {directory} could not be read: {e}")
            continue

        if not points:
            continue

        seen.add(resolved)
        results.append(
            {
                "path": str(directory),
                "label": _describe_location(directory),
                "source": source,
                "known": True,
                "last_written": entry.get("last_written"),
                "restore_point_count": len(points),
                "newest": points[0]["created_at"],
                "newest_display": points[0]["display_name"],
                "restore_points": points,
            }
        )

    if results:
        return results

    # No record. Check the one folder MailRepo itself owns before giving
    # up — an install that predates the location record, or a default
    # setup whose backups folder survived, lands here.
    default_dir = get_backups_dir()
    try:
        if default_dir.is_dir() and folder_holds_mailrepo_backups(default_dir):
            points, source = discover_restore_points_in(default_dir)
            if points:
                results.append(
                    {
                        "path": str(default_dir),
                        "label": _describe_location(default_dir),
                        "source": source,
                        "known": False,
                        "restore_point_count": len(points),
                        "newest": points[0]["created_at"],
                        "newest_display": points[0]["display_name"],
                        "restore_points": points,
                    }
                )
    except Exception as e:
        log.warning(f"Default backups folder could not be read: {e}")

    return results


def _describe_location(path):
    """A human label for where a backup folder lives."""
    path = Path(path)
    text = str(path)
    home = str(Path.home())

    if "com~apple~CloudDocs" in text:
        return f"iCloud Drive — {path.name}"
    if "/Dropbox/" in text or text.endswith("/Dropbox"):
        return f"Dropbox — {path.name}"
    if "/OneDrive" in text:
        return f"OneDrive — {path.name}"
    if "Google Drive" in text or "GoogleDrive" in text:
        return f"Google Drive — {path.name}"
    if text.startswith("/Volumes/") or text.startswith("/media/") or text.startswith("/mnt/"):
        return f"External drive — {path.name}"
    if text.startswith(home):
        return f"This computer — {path.name}"
    return str(path)


def check_backup_needed(frequency="daily"):
    """
    Check if an automatic backup should run.

    Uses CALENDAR DATE comparison against last check date, not hours:
    - 'daily': check if last check was on a different calendar date
    - 'weekly': check if last check was 7+ calendar days ago
    - 'session': always run on logout

    Args:
        frequency: 'session', 'daily', 'weekly', or 'manual'

    Returns:
        True if backup should run, False otherwise
    """
    if frequency == "manual":
        return False

    if frequency == "session":
        return True  # Always backup on logout

    manifest = load_manifest()
    backups = manifest["backups"]

    if not backups:
        return True  # No backups exist

    # Find most recent backup
    all_backups = [b for b in backups if b["type"] in ("full", "incremental")]

    if not all_backups:
        return True

    now = datetime.now()
    today = now.date()

    # Use last_backup_check if available, otherwise fall back to last backup date
    last_check = manifest.get("last_backup_check")
    if last_check:
        last_date = datetime.fromisoformat(last_check).date()
    else:
        # Legacy: no check recorded, use last backup date
        last_any = max(all_backups, key=lambda x: x["created_at"])
        last_date = datetime.fromisoformat(last_any["created_at"]).date()

    # Use calendar date comparison
    if frequency == "daily" and today > last_date:
        return True
    elif frequency == "weekly" and (today - last_date).days >= 7:
        return True

    return False


def record_backup_check():
    """
    Record that we checked for backup today.
    Called after backup attempt (whether successful or no changes).
    """
    manifest = load_manifest()
    manifest["last_backup_check"] = datetime.now().isoformat()
    save_manifest(manifest)
