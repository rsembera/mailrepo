# Backup State Migration — Final Cleanup

> **IMPLEMENTED 2026-06-14** (commit `c363fba`). The cleanup described below is
> done: both `refresh_hash_baseline()` calls and the function itself are
> removed; the reference comment in `backups.py` is retained. Full suite green
> (345 passed). Kept on file as a record of the migration's completion.

**Status:** The core migration to the external-state-file (Libram) pattern is
already complete. This note covers only the small remaining cleanup.

## Already done — do NOT redo
- `.backup_state.json` external state file, with read/write helpers
- `_get_baseline_hashes()` reads from the state file, with a migration fallback
  that pulls old hashes out of the manifest
- `create_full_backup` / `create_incremental_backup` auto-update the baseline,
  including the no-change incremental path
- `check_backup_needed()` is frequency-first (calendar-based; never gates on a hash)
- Hash baseline separated from the catalog (manifest holds the catalog only)
- `refresh_hash_baseline()` already marked DEPRECATED

## Remaining cleanup

1. Remove the two surviving `refresh_hash_baseline()` calls, both in the
   *no-backup* branch of the auto-backup flow:
   - `web/blueprints/auth.py` — `_run_auto_backup_check()`, else branch (~line 328)
   - `main.py` — shutdown auto-backup, else branch (~line 114)

   Delete the stale justifying comments along with them. They reason from the
   old hash-gated model ("update baseline so the next check doesn't see spurious
   changes"), but the decision is now frequency-first, so a stale baseline cannot
   cause a false "backup needed".

2. Remove the now-dead `refresh_hash_baseline()` function
   (`utils/backup.py` ~line 327). No other live callers.

3. `web/blueprints/backups.py` (~line 101) already has the correct
   "no need to call this here" comment — leave it as reference.

## Before deleting the function
- `grep -rn refresh_hash_baseline tests/` — update or drop any test that
  references it.
- Run the full suite (345 tests), then commit.

## Why removing the calls is safe
The only consumer of the baseline is `create_incremental_backup` (changed-file
selection). A stale baseline can only show *more* files as changed, never fewer —
so no change can ever be missed. Worst case: the database file is included in the
next incremental when it technically didn't need to be, and it's the primary data
file so it's in nearly every incremental anyway. Harmless.

Cleanup, not a build — roughly 15 minutes.
