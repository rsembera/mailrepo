# Backup State Management

**Created:** February 16, 2026  
**Updated:** February 19, 2026  
**Status:** ✅ Implemented  
**Reference:** Libram's `WAL_Checkpoint_Backup_Handling.md`

---

## Summary

MailRepo uses an external state file (`data/.backup_state.json`) to store the hash baseline for change detection, following the Libram pattern. This avoids the circular modification problem where checking database state requires modifying the database.

---

## How It Works

### External State File

Hash baseline is stored in `data/.backup_state.json`:

```json
{
  "last_backup_hashes": {
    "data/mailrepo.db": "sha256...",
    "data/.salt": "sha256...",
    "archive/1/email.eml.enc": "sha256...",
    ...
  }
}
```

### Key Functions

| Function | Purpose |
|----------|---------|
| `_get_backup_state_file()` | Returns path to `.backup_state.json` |
| `_read_backup_state()` | Reads external state file |
| `_write_backup_state()` | Writes external state file |
| `_get_baseline_hashes()` | Gets hash baseline (with migration fallback) |
| `_save_baseline_hashes()` | Saves hash baseline |

### Automatic Baseline Updates

The baseline is automatically updated in two places:

1. **After successful backup** - `create_full_backup()` and `create_incremental_backup()` save the new hashes
2. **When no changes found** - `create_incremental_backup()` updates baseline even when returning `None`

This second case is critical: it ensures WAL checkpoint-induced hash changes don't accumulate as false "changes".

---

## Migration

On first run after the refactor, `_get_baseline_hashes()` checks for old-style hashes in `manifest.json` and migrates them to the new state file automatically.

---

## Why This Matters

The previous system stored `last_full_hashes` in `manifest.json` and required manual `refresh_hash_baseline()` calls after WAL checkpoints. This was fragile because:

1. Forgetting to call `refresh_hash_baseline()` caused spurious backups
2. Calling it at the wrong time (before comparison) caused missed changes
3. Multiple code paths needed careful coordination

The new system is self-contained in the backup module - no external coordination required.

---

## Testing

Verified scenarios:
1. ✅ No backup when nothing changed
2. ✅ No backup after WAL checkpoint alone
3. ✅ Real file changes trigger backup
4. ✅ Database changes trigger backup
5. ✅ Repeated calls don't create spurious backups
6. ✅ Migration from old manifest-based system

---

*Implemented February 19, 2026*
