# Future Enhancement: External Backup State File

**Created:** February 16, 2026  
**Status:** Deferred (post-1.0)  
**Priority:** Low  
**Reference:** Libram's `WAL_Checkpoint_Backup_Handling.md`

---

## Summary

Consider refactoring MailRepo's backup hash baseline storage to use an external state file (like Libram) instead of storing it in the manifest. This eliminates the need for manual `refresh_hash_baseline()` calls after WAL checkpoints.

---

## Current Approach

MailRepo stores `last_full_hashes` in `manifest.json` and requires calling `refresh_hash_baseline()` after every `checkpoint()` to prevent false-positive backup triggers. Currently this is only needed in one place (`main.py` `_cleanup()`), so the coordination burden is minimal.

---

## Libram's Approach

Libram stores backup state in an external `data/.backup_state.json` file:

```json
{
  "last_backup_hash": "sha256...",
  "last_backup_check": "2026-02-16T15:30:00"
}
```

**Benefits:**
- No circular modification (checking state doesn't change the database)
- No manual coordination needed after checkpoints
- Frequency-first checking avoids unnecessary hash comparisons
- Self-contained in backup module

---

## When to Implement

Consider implementing this if:
- Adding more checkpoint sites (e.g., after large imports)
- Experiencing false-positive backup bugs
- Doing a major backup system refactor

---

## Implementation Scope

Estimated effort: 2-3 hours

1. Add external state file functions (`_read_backup_state()`, `_write_backup_state()`)
2. Modify `create_backup()` to write final hash after checkpoint
3. Update `check_backup_needed()` to check frequency before hashing
4. Remove `refresh_hash_baseline()` function and its call in `main.py`
5. Handle migration from manifest-based storage

---

## Decision (Feb 2026)

**Deferred.** Current system works correctly with `refresh_hash_baseline()` called in the single checkpoint location. Not worth the risk of architectural changes this close to release.

---

*Reference: `/Users/rick/Applications/libram/docs/WAL_Checkpoint_Backup_Handling.md`*
