"""
MailRepo - Backup System
Handles full and incremental backups with encryption support.

User-facing simplification:
- Single "Backup Now" button (system auto-decides full vs incremental)
- All backups are valid restore points
- No exposed complexity about backup chains
"""

import os
import json
import hashlib
import zipfile
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from core.config import Config
from utils.log import get_logger

log = get_logger(__name__)


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
    backup_dir = Path(backup_entry.get('backup_dir', '')) if backup_entry.get('backup_dir') else get_backups_dir()
    return backup_dir / backup_entry['filename']


def get_restore_staging_dir():
    return get_data_root() / '.restore_staging'


def get_manifest_file():
    return get_backups_dir() / 'manifest.json'


def ensure_backup_dir():
    """Create backups directory if it doesn't exist."""
    get_backups_dir().mkdir(parents=True, exist_ok=True)


def get_file_hash(filepath):
    """Calculate SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


def get_file_metadata(filepath):
    """Get file metadata (mtime, size) for quick change detection."""
    stat = filepath.stat()
    return {
        'mtime': stat.st_mtime,
        'size': stat.st_size
    }


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
    db_path = data_dir / 'mailrepo.db'
    if db_path.exists():
        files['data/mailrepo.db'] = db_path
    
    # Security files (salt and secret key - essential for decryption)
    salt_path = data_dir / '.salt'
    if salt_path.exists():
        files['data/.salt'] = salt_path
    
    secret_key_path = data_dir / '.secret_key'
    if secret_key_path.exists():
        files['data/.secret_key'] = secret_key_path
    
    # Archive folder (all email files - encrypted and unencrypted)
    if archive_dir.exists():
        for filepath in archive_dir.rglob('*'):
            if filepath.is_file() and not filepath.name.startswith('.'):
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
    previous_file_info = state.get('file_info', {})
    
    hashes = {}
    new_file_info = {}
    
    for rel_path, abs_path in files.items():
        current_meta = get_file_metadata(abs_path)
        prev_info = previous_file_info.get(rel_path, {})
        
        # Check if file might have changed (mtime or size different)
        if (prev_info.get('mtime') == current_meta['mtime'] and 
            prev_info.get('size') == current_meta['size'] and
            prev_info.get('hash')):
            # File unchanged - reuse cached hash
            file_hash = prev_info['hash']
        else:
            # File changed or new - compute hash
            file_hash = get_file_hash(abs_path)
        
        hashes[rel_path] = file_hash
        new_file_info[rel_path] = {
            'hash': file_hash,
            'mtime': current_meta['mtime'],
            'size': current_meta['size']
        }
    
    return hashes, new_file_info


def load_manifest():
    """Load backup manifest from disk."""
    manifest_file = get_manifest_file()
    if manifest_file.exists():
        try:
            with open(manifest_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError) as e:
            # Manifest corrupted - backup the bad file and start fresh
            corrupted_path = manifest_file.with_suffix('.json.corrupted')
            shutil.copy(manifest_file, corrupted_path)
            log.warning(f"manifest.json was corrupted, backed up to {corrupted_path.name}")
    return {
        'backups': [],
        'last_full_hashes': {},
        'current_chain_id': None,
        'last_backup_check': None
    }


def save_manifest(manifest):
    """Save backup manifest to disk."""
    ensure_backup_dir()
    with open(get_manifest_file(), 'w') as f:
        json.dump(manifest, f, indent=2)


# ============================================================================
# External Backup State File (Libram-style)
# 
# Hash baseline is stored in .backup_state.json, NOT in the manifest.
# This avoids the circular modification problem where checking database
# state requires modifying the database.
# ============================================================================

def _get_backup_state_file():
    """Get path to backup state file (stored in data dir, not backups)."""
    return get_data_dir() / '.backup_state.json'


def _read_backup_state():
    """Read backup state from external JSON file."""
    state_file = _get_backup_state_file()
    if state_file.exists():
        try:
            with open(state_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _write_backup_state(state):
    """Write backup state to external JSON file."""
    state_file = _get_backup_state_file()
    get_data_dir().mkdir(parents=True, exist_ok=True)
    with open(state_file, 'w') as f:
        json.dump(state, f, indent=2)


def _get_baseline_hashes():
    """
    Get hash baseline from external state file.
    Falls back to manifest for migration from old system.
    """
    state = _read_backup_state()
    if 'last_backup_hashes' in state:
        return state['last_backup_hashes']
    
    # Migration: check manifest for old-style hashes
    manifest = load_manifest()
    if manifest.get('last_full_hashes'):
        # Migrate to new system
        _write_backup_state({
            'last_backup_hashes': manifest['last_full_hashes'],
            'last_backup_check': manifest.get('last_backup_check')
        })
        return manifest['last_full_hashes']
    
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
    state['last_backup_hashes'] = hashes
    
    # Update file_info for smart change detection
    if file_info:
        state['file_info'] = file_info
    elif 'file_info' not in state:
        # Build file_info from current state if not present
        files = get_all_backup_files()
        state['file_info'] = {}
        for rel_path, abs_path in files.items():
            if rel_path in hashes:
                meta = get_file_metadata(abs_path)
                state['file_info'][rel_path] = {
                    'hash': hashes[rel_path],
                    'mtime': meta['mtime'],
                    'size': meta['size']
                }
    
    _write_backup_state(state)


def refresh_hash_baseline():
    """
    DEPRECATED: This function exists for backward compatibility only.
    
    The new system automatically updates the baseline in create_backup(),
    so manual refresh is no longer needed.
    """
    # Still works, but shouldn't be necessary
    current_hashes = get_file_hashes()
    _save_baseline_hashes(current_hashes)


def generate_backup_filename(backup_type):
    """Generate unique backup filename."""
    timestamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')
    return f"{backup_type}_{timestamp}.zip"


def validate_backup_location(backup_dir):
    """
    Validate that backup location is accessible and writable.
    Returns (success, error_message) tuple.
    """
    backup_dir = Path(backup_dir)
    
    # Check if it's a cloud folder
    cloud_indicators = ['iCloud', 'CloudDocs', 'Dropbox', 'Google Drive', 'OneDrive', 'CloudStorage']
    is_cloud = any(indicator in str(backup_dir) for indicator in cloud_indicators)
    
    try:
        # Try to create directory
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        # Try to write a test file
        test_file = backup_dir / '.write_test'
        try:
            test_file.write_text('test')
            test_file.unlink()
        except PermissionError:
            if is_cloud:
                return False, "Cannot write to cloud folder. Please check that the cloud service is running and you're signed in."
            return False, "Permission denied. Cannot write to this location."
        except OSError as e:
            if is_cloud:
                return False, f"Cloud folder not accessible. Please check your internet connection and that the cloud service is online."
            return False, f"Cannot write to backup location: {e}"
        
        return True, None
        
    except PermissionError:
        if is_cloud:
            return False, "Cannot access cloud folder. Please check that the cloud service is running and you're signed in."
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
    
    if not manifest['backups']:
        need_full = True  # No backups exist
    elif not _get_baseline_hashes():
        need_full = True  # No hash baseline
    else:
        # Check age of last full backup (calendar days, not hours)
        full_backups = [b for b in manifest['backups'] if b['type'] == 'full']
        if full_backups:
            last_full = max(full_backups, key=lambda x: x['created_at'])
            last_full_date = datetime.fromisoformat(last_full['created_at']).date()
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
    
    filename = generate_backup_filename('full')
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
        with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for rel_path, abs_path in files.items():
                zf.write(abs_path, rel_path)
                file_hash = get_file_hash(abs_path)
                meta = get_file_metadata(abs_path)
                hashes[rel_path] = file_hash
                file_info[rel_path] = {
                    'hash': file_hash,
                    'mtime': meta['mtime'],
                    'size': meta['size']
                }
                total_size += meta['size']
    except OSError as e:
        # Clean up partial backup
        if backup_path.exists():
            backup_path.unlink()
        raise ValueError(f"Failed to create backup: {e}")
    
    # Verify backup
    verify_backup(backup_path)
    
    # Update manifest
    manifest = load_manifest()
    chain_id = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    backup_info = {
        'filename': filename,
        'type': 'full',
        'chain_id': chain_id,
        'created_at': datetime.now().isoformat(),
        'file_count': len(files),
        'original_size': total_size,
        'backup_size': backup_path.stat().st_size,
        'backup_dir': str(backup_dir)
    }
    
    manifest['backups'].append(backup_info)
    manifest['current_chain_id'] = chain_id
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
    
    filename = generate_backup_filename('incr')
    backup_path = backup_dir / filename
    
    total_size = 0
    
    # Create zip with only changed files
    try:
        with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for rel_path, abs_path in changed_files.items():
                zf.write(abs_path, rel_path)
                total_size += abs_path.stat().st_size
            
            # Include a metadata file listing deleted files
            if deleted_files:
                metadata = {'deleted_files': deleted_files}
                zf.writestr('_backup_metadata.json', json.dumps(metadata))
    except OSError as e:
        # Clean up partial backup
        if backup_path.exists():
            backup_path.unlink()
        raise ValueError(f"Failed to create backup: {e}")
    
    # Verify backup
    verify_backup(backup_path)
    
    # Update manifest
    backup_info = {
        'filename': filename,
        'type': 'incremental',
        'chain_id': manifest['current_chain_id'],
        'created_at': datetime.now().isoformat(),
        'file_count': len(changed_files),
        'deleted_count': len(deleted_files),
        'original_size': total_size,
        'backup_size': backup_path.stat().st_size,
        'backup_dir': str(backup_dir)
    }
    
    manifest['backups'].append(backup_info)
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
        with zipfile.ZipFile(backup_path, 'r') as zf:
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
    
    for backup in manifest['backups']:
        # Use the location where this backup was actually saved
        backup_path = get_backup_path_for_entry(backup)
        
        if backup_path.exists():
            backups.append({
                'filename': backup['filename'],
                'type': backup['type'],
                'chain_id': backup['chain_id'],
                'created_at': backup['created_at'],
                'file_count': backup['file_count'],
                'backup_size': backup['backup_size'],
                'backup_size_mb': round(backup['backup_size'] / (1024 * 1024), 2),
                'path': str(backup_path)
            })
    
    # Sort by date, newest first
    backups.sort(key=lambda x: x['created_at'], reverse=True)
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
    backups = manifest['backups']
    
    # Group by chain
    chains = {}
    for backup in backups:
        chain_id = backup['chain_id']
        if chain_id not in chains:
            chains[chain_id] = {'full': None, 'incrementals': [], 'pre_restore': None}
        
        if backup['type'] == 'full':
            chains[chain_id]['full'] = backup
        elif backup['type'] == 'pre_restore':
            chains[chain_id]['pre_restore'] = backup
        else:
            chains[chain_id]['incrementals'].append(backup)
    
    # Build restore points
    restore_points = []
    
    for chain_id, chain in chains.items():
        # Handle pre_restore backups (standalone, not part of a chain)
        if chain_id == 'pre_restore' and chain.get('pre_restore'):
            backup = chain['pre_restore']
            backup_path = get_backup_path_for_entry(backup)
            if backup_path.exists():
                # Format date with time
                created = datetime.fromisoformat(backup['created_at'])
                display_time = created.strftime('%b %d, %Y at %I:%M %p').replace(' 0', ' ')
                
                restore_points.append({
                    'id': f"pre_restore_{backup['filename']}",
                    'filename': backup['filename'],
                    'display_name': f"{display_time} (Safety backup)",
                    'created_at': backup['created_at'],
                    'type': 'pre_restore',
                    'is_safety': True,
                    'chain_id': 'pre_restore',
                    'dependent_count': 0,
                    'files_needed': [str(backup_path)]
                })
            continue
        
        if not chain['full']:
            continue  # Skip orphaned incrementals
        
        # Sort incrementals by date
        chain['incrementals'].sort(key=lambda x: x['created_at'])
        
        # Count dependents for this chain's full backup
        dependent_count = len(chain['incrementals'])
        
        # Full backup as restore point
        full_backup = chain['full']
        backup_path = get_backup_path_for_entry(full_backup)
        
        if backup_path.exists():
            # Format date with time
            created = datetime.fromisoformat(full_backup['created_at'])
            display_time = created.strftime('%b %d, %Y at %I:%M %p').replace(' 0', ' ')
            
            restore_points.append({
                'id': f"{chain_id}_full",
                'filename': full_backup['filename'],
                'display_name': display_time,
                'created_at': full_backup['created_at'],
                'type': 'full',
                'is_safety': False,
                'chain_id': chain_id,
                'dependent_count': dependent_count,
                'files_needed': [str(backup_path)]
            })
        
        # Each incremental in the chain is also a restore point
        files_needed = [str(backup_path)]
        for i, incr in enumerate(chain['incrementals']):
            incr_path = get_backup_path_for_entry(incr)
            if incr_path.exists():
                files_needed = files_needed + [str(incr_path)]
                
                # Format date with time
                created = datetime.fromisoformat(incr['created_at'])
                display_time = created.strftime('%b %d, %Y at %I:%M %p').replace(' 0', ' ')
                
                restore_points.append({
                    'id': f"{chain_id}_incr_{i}",
                    'filename': incr['filename'],
                    'display_name': display_time,
                    'created_at': incr['created_at'],
                    'type': 'incremental',
                    'is_safety': False,
                    'chain_id': chain_id,
                    'dependent_count': 0,
                    'files_needed': files_needed.copy()
                })
    
    # Sort by date, newest first
    restore_points.sort(key=lambda x: x['created_at'], reverse=True)
    return restore_points


def prepare_restore(restore_point_id):
    """
    Prepare for restore by extracting to staging folder.
    Does NOT replace production files yet.
    
    Returns path to staging folder.
    """
    restore_points = get_restore_points()
    point = next((p for p in restore_points if p['id'] == restore_point_id), None)
    
    if not point:
        raise ValueError(f"Restore point not found: {restore_point_id}")
    
    # Create pre-restore backup first (safety net)
    create_pre_restore_backup()
    
    staging_dir = get_restore_staging_dir()
    
    # Clear any existing staging
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    
    staging_dir.mkdir(parents=True)
    
    # Track deleted files across incrementals
    deleted_files = set()
    
    # Extract backups in order (full first, then incrementals)
    for backup_path in point['files_needed']:
        with zipfile.ZipFile(backup_path, 'r') as zf:
            # Check for metadata about deleted files
            if '_backup_metadata.json' in zf.namelist():
                metadata = json.loads(zf.read('_backup_metadata.json'))
                deleted_files.update(metadata.get('deleted_files', []))
            
            # Extract all other files (overwrites previous versions)
            for name in zf.namelist():
                if name != '_backup_metadata.json':
                    zf.extract(name, staging_dir)
    
    # Remove files that were deleted in later backups
    for rel_path in deleted_files:
        staged_path = staging_dir / rel_path
        if staged_path.exists():
            staged_path.unlink()
    
    # Write restore marker
    marker = {
        'restore_point_id': restore_point_id,
        'prepared_at': datetime.now().isoformat(),
        'point_info': point
    }
    with open(staging_dir / '.restore_marker', 'w') as f:
        json.dump(marker, f)
    
    return str(staging_dir)


def create_pre_restore_backup():
    """Create a backup of current state before restore (safety net)."""
    ensure_backup_dir()
    
    filename = f"pre_restore_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.zip"
    backup_path = get_backups_dir() / filename
    
    files = get_all_backup_files()
    if not files:
        return None  # Nothing to back up
    
    with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for rel_path, abs_path in files.items():
            zf.write(abs_path, rel_path)
    
    verify_backup(backup_path)
    
    # Add to manifest
    manifest = load_manifest()
    manifest['backups'].append({
        'filename': filename,
        'type': 'pre_restore',
        'chain_id': 'pre_restore',
        'created_at': datetime.now().isoformat(),
        'file_count': len(files),
        'backup_size': backup_path.stat().st_size,
        'backup_dir': str(get_backups_dir())
    })
    save_manifest(manifest)
    
    return str(backup_path)


def check_restore_pending():
    """Check if there's a pending restore to complete."""
    marker_path = get_restore_staging_dir() / '.restore_marker'
    if marker_path.exists():
        with open(marker_path, 'r') as f:
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
    staged_db = staging_dir / 'data' / 'mailrepo.db'
    if staged_db.exists():
        data_dir.mkdir(parents=True, exist_ok=True)
        target_db = data_dir / 'mailrepo.db'
        if target_db.exists():
            target_db.unlink()
        shutil.copy2(staged_db, target_db)
    
    # Replace security files
    for security_file in ['.salt', '.secret_key']:
        staged_file = staging_dir / 'data' / security_file
        if staged_file.exists():
            target_file = data_dir / security_file
            if target_file.exists():
                target_file.unlink()
            shutil.copy2(staged_file, target_file)
    
    # Replace archive folder
    staged_archive = staging_dir / 'archive'
    if staged_archive.exists():
        if archive_dir.exists():
            shutil.rmtree(archive_dir)
        shutil.copytree(staged_archive, archive_dir)
    
    # Clean up staging
    shutil.rmtree(staging_dir)
    
    return {
        'restored_at': datetime.now().isoformat(),
        'restore_point': marker['restore_point_id'],
        'original_date': marker['point_info']['created_at']
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
    if retention == 'forever':
        return
    
    retention_days = {
        '1_month': 30,
        '6_months': 180,
        '1_year': 365
    }.get(retention)
    
    if not retention_days:
        return
    
    manifest = load_manifest()
    backup_dir = Path(custom_location) if custom_location else get_backups_dir()
    
    cutoff_date = (datetime.now() - timedelta(days=retention_days)).isoformat()
    
    # Group backups by chain
    chains = {}
    safety_backups = []
    for backup in manifest['backups']:
        if backup['type'] == 'pre_restore':
            safety_backups.append(backup)
            continue
        chain_id = backup.get('chain_id')
        if chain_id:
            if chain_id not in chains:
                chains[chain_id] = {'full': None, 'incrementals': []}
            if backup['type'] == 'full':
                chains[chain_id]['full'] = backup
            else:
                chains[chain_id]['incrementals'].append(backup)
    
    # Sort chains by the full backup date (oldest first)
    sorted_chain_ids = sorted(chains.keys(), 
                              key=lambda cid: chains[cid]['full']['created_at'] if chains[cid]['full'] else '')
    
    # Always keep the newest chain
    if len(sorted_chain_ids) <= 1:
        return
    
    chains_to_delete = []
    
    # Check each chain except the newest
    for chain_id in sorted_chain_ids[:-1]:
        chain = chains[chain_id]
        if not chain['full']:
            continue
        
        # Find the newest backup in this chain
        all_in_chain = [chain['full']] + chain['incrementals']
        newest_date = max(b['created_at'] for b in all_in_chain)
        
        if newest_date < cutoff_date:
            chains_to_delete.append(chain_id)
    
    # Delete marked chains
    for chain_id in chains_to_delete:
        chain = chains[chain_id]
        
        for incr in chain['incrementals']:
            # Always use current backups directory (app may have moved)
            incr_path = backup_dir / incr['filename']
            if incr_path.exists():
                incr_path.unlink()
            if incr in manifest['backups']:
                manifest['backups'].remove(incr)
        
        if chain['full']:
            # Always use current backups directory (app may have moved)
            full_path = backup_dir / chain['full']['filename']
            if full_path.exists():
                full_path.unlink()
            if chain['full'] in manifest['backups']:
                manifest['backups'].remove(chain['full'])
    
    if chains_to_delete:
        save_manifest(manifest)
        log.info(f"Retention cleanup: Deleted {len(chains_to_delete)} old backup chain(s)")
    
    # Clean up old safety backups
    safety_deleted = 0
    for backup in safety_backups:
        if backup['created_at'] < cutoff_date:
            # Always use current backups directory (app may have moved)
            backup_path = backup_dir / backup['filename']
            if backup_path.exists():
                backup_path.unlink()
            if backup in manifest['backups']:
                manifest['backups'].remove(backup)
            safety_deleted += 1
    
    if safety_deleted:
        save_manifest(manifest)
        log.info(f"Retention cleanup: Deleted {safety_deleted} old safety backup(s)")


def get_backup_status():
    """
    Get current backup status for display.
    Uses CALENDAR DATE for "Today" comparison, not hours.
    """
    manifest = load_manifest()
    backups = [b for b in manifest['backups'] if b['type'] in ('full', 'incremental')]
    
    if not backups:
        return {
            'has_backups': False,
            'last_backup': None,
            'last_backup_display': 'Never',
            'backup_count': 0
        }
    
    last = max(backups, key=lambda x: x['created_at'])
    last_datetime = datetime.fromisoformat(last['created_at'])
    last_date = last_datetime.date()
    
    now = datetime.now()
    today = now.date()
    yesterday = today - timedelta(days=1)
    
    time_str = last_datetime.strftime('%I:%M %p').lstrip('0')
    
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
            display = last_datetime.strftime('%B %d, %Y')
    
    return {
        'has_backups': True,
        'last_backup': last['created_at'],
        'last_backup_display': display,
        'last_backup_type': last['type'],
        'backup_count': len(backups)
    }


def detect_cloud_folders():
    """
    Detect available cloud sync folders.
    Returns list of {name, path} dicts.
    """
    home = Path.home()
    cloud_folders = []
    
    # iCloud Drive
    icloud = home / 'Library' / 'Mobile Documents' / 'com~apple~CloudDocs'
    if icloud.exists():
        cloud_folders.append({
            'name': 'iCloud Drive',
            'path': str(icloud / 'MailRepo Backups')
        })
    
    # Dropbox
    dropbox = home / 'Dropbox'
    if dropbox.exists():
        cloud_folders.append({
            'name': 'Dropbox',
            'path': str(dropbox / 'Apps' / 'MailRepo Backups')
        })
    
    # Google Drive (new location)
    google_drive_new = home / 'Library' / 'CloudStorage'
    if google_drive_new.exists():
        for folder in google_drive_new.iterdir():
            if folder.name.startswith('GoogleDrive'):
                cloud_folders.append({
                    'name': 'Google Drive',
                    'path': str(folder / 'My Drive' / 'MailRepo Backups')
                })
                break
    
    # Google Drive (old location)
    google_drive_old = home / 'Google Drive'
    if google_drive_old.exists() and not any(c['name'] == 'Google Drive' for c in cloud_folders):
        cloud_folders.append({
            'name': 'Google Drive',
            'path': str(google_drive_old / 'MailRepo Backups')
        })
    
    # OneDrive
    onedrive = home / 'OneDrive'
    if onedrive.exists():
        cloud_folders.append({
            'name': 'OneDrive',
            'path': str(onedrive / 'MailRepo Backups')
        })
    
    return cloud_folders


def check_backup_needed(frequency='daily'):
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
    if frequency == 'manual':
        return False
    
    if frequency == 'session':
        return True  # Always backup on logout
    
    manifest = load_manifest()
    backups = manifest['backups']
    
    if not backups:
        return True  # No backups exist
    
    # Find most recent backup
    all_backups = [b for b in backups if b['type'] in ('full', 'incremental')]
    
    if not all_backups:
        return True
    
    now = datetime.now()
    today = now.date()
    
    # Use last_backup_check if available, otherwise fall back to last backup date
    last_check = manifest.get('last_backup_check')
    if last_check:
        last_date = datetime.fromisoformat(last_check).date()
    else:
        # Legacy: no check recorded, use last backup date
        last_any = max(all_backups, key=lambda x: x['created_at'])
        last_date = datetime.fromisoformat(last_any['created_at']).date()
    
    # Use calendar date comparison
    if frequency == 'daily' and today > last_date:
        return True
    elif frequency == 'weekly' and (today - last_date).days >= 7:
        return True
    
    return False


def record_backup_check():
    """
    Record that we checked for backup today.
    Called after backup attempt (whether successful or no changes).
    """
    manifest = load_manifest()
    manifest['last_backup_check'] = datetime.now().isoformat()
    save_manifest(manifest)
