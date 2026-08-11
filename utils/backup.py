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


def get_backup_path_for_entry(backup_entry: dict) -> Path:
    """Get the path where a backup file should be located based on its manifest entry."""
    backup_dir = (
        Path(backup_entry.get("backup_dir", ""))
        if backup_entry.get("backup_dir")
        else get_backups_dir()
    )
    return backup_dir / backup_entry["filename"]


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

    secret_key_path = data_dir / ".secret_key"
    if secret_key_path.exists():
        files["data/.secret_key"] = secret_key_path

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


def save_manifest(manifest):
    """Save backup manifest to disk (atomic, crash-safe write)."""
    ensure_backup_dir()
    _atomic_write_text(get_manifest_file(), json.dumps(manifest, indent=2))


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

    raise RuntimeError(
        f"Could not generate a unique backup filename in {directory}"
    )


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

    # Update manifest
    manifest = load_manifest()
    chain_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    backup_info = {
        "filename": filename,
        "type": "full",
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

    # Update manifest
    backup_info = {
        "filename": filename,
        "type": "incremental",
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
    manifest = load_manifest()
    backups = manifest["backups"]

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
            log.warning(
                f"Skipping manifest entry without chain_id: {backup.get('filename', '?')}"
            )
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

        backup_path = get_backup_path_for_entry(backup)
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
        backup_path = get_backup_path_for_entry(full_backup)

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
        for i, incr in enumerate(chain["incrementals"]):
            incr_path = get_backup_path_for_entry(incr)
            files_needed = files_needed + [str(incr_path)]

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
        creds = describe_restore_point_credentials(
            point.get("files_needed", []), current_blob
        )
        point["credential_status"] = creds["status"]
        point["credential_note"] = creds["note"]

    return restore_points


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
                for rel_path in metadata.get("deleted_files", []):
                    staged_path = staging_dir / rel_path
                    if staged_path.exists():
                        staged_path.unlink()

    # Write restore marker
    marker = {
        "restore_point_id": restore_point_id,
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

    # Add to manifest
    manifest = load_manifest()
    manifest["backups"].append(
        {
            "filename": filename,
            "type": "pre_restore",
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
        shutil.copy2(staged_db, target_db)

    # Replace security files
    for security_file in [".salt", ".secret_key"]:
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

    return {
        "restored_at": datetime.now().isoformat(),
        "restore_point": marker["restore_point_id"],
        "original_date": marker["point_info"]["created_at"],
    }


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
    backup_dir = Path(custom_location) if custom_location else get_backups_dir()

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
            # Always use current backups directory (app may have moved)
            incr_path = backup_dir / incr["filename"]
            if incr_path.exists():
                incr_path.unlink()
            if incr in manifest["backups"]:
                manifest["backups"].remove(incr)

        if chain["full"]:
            # Always use current backups directory (app may have moved)
            full_path = backup_dir / chain["full"]["filename"]
            if full_path.exists():
                full_path.unlink()
            if chain["full"] in manifest["backups"]:
                manifest["backups"].remove(chain["full"])

    if chains_to_delete:
        save_manifest(manifest)
        log.info(f"Retention cleanup: Deleted {len(chains_to_delete)} old backup chain(s)")

    # Clean up old safety backups
    safety_deleted = 0
    for backup in safety_backups:
        if backup["created_at"] < cutoff_date:
            # Always use current backups directory (app may have moved)
            backup_path = backup_dir / backup["filename"]
            if backup_path.exists():
                backup_path.unlink()
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
