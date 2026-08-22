# MailRepo — Session Log

Running record of planning sessions and decisions. Most recent first.

---

## May 30, 2026 — Road to 1.0: v1 cleanup pass + backup UX fixes (SHIPPED)

**Participants:** Rick, Claude (Opus 4.7) on the MacBook.

The day the road-to-1.0 list emptied. Two focused sessions:

### v1 cleanup pass (commit `9337954`)

The "satisfying diff" pass we had earmarked at the end of yesterday's plan, with one scope expansion. Discovered that `core/migration.py` references v1 primitives (`Encryption._fernet_v1`, `Encryption.swap_v1_to_v2`) — so removing the v1 code from `encryption.py` necessarily breaks the migration module. Discussed three options (half-cleanup that leaves dead primitives, stub the migration, full cleanup including deleting the migration module + UI) and Rick made the right call: nuke it. The migration was a one-time event that already ran; future v3 migration will be different code anyway. Git history preserves the pattern for reference.

Net diff: **126 insertions, 2,460 deletions across 12 files.**

Files deleted entirely (1,797 lines):
- `core/migration.py` (577 lines)
- `tests/test_migration.py` (262 lines)
- `web/blueprints/migration.py` (262 lines)
- `web/static/js/views/migration.js` (527 lines)
- `web/static/css/modules/migration.css` (169 lines)

`core/encryption.py` shrank from 697 → 373 lines: removed v1 PBKDF2 + Fernet (`_derive_fernet_v1`, `_derive_db_key_v1`, the `_derive_db_key` backward-compat alias), the `cryptography.fernet` import, the v1 PBKDF2 constants, the `_fernet_v1` / `_db_key_v1` class attributes, `_unlock_v1`, `_derive_and_set_v2_keys`, `get_crypto_version`, `get_migration_marker_path`, `is_migration_in_progress`, `get_db_key_v2`, `swap_v1_to_v2`, `derive_fernet_for_password`, and `update_password` (the wrapper that branched between v1/v2 paths). The dual-decode branch in `decrypt()` collapsed to "expect 0x02 prefix or error."

What stays as forward infrastructure for any hypothetical v3 migration: `SALT_MAGIC_V2` (the MRC2 magic), `VERSION_BYTE_V2` (0x02), and the `.v2` suffix in HKDF info strings. A v3 KDF would use `mailrepo.file.v3` etc. and derive cryptographically distinct keys even if the master collided.

`web/blueprints/auth.py` shrank from 505 → 413 lines: `change_password_progress` now just calls `change_master_password` directly. No version branching. The 90-line legacy Fernet path (count files, walk decrypt-with-old + encrypt-with-new, walk credentials, PRAGMA rekey, `update_password`) all removed.

`tests/test_encryption_v2.py` shrank from 241 → 149 lines: removed `test_get_crypto_version_returns_2_for_new_install`, the entire `TestDualDecode` class (it manually built a v1 archive to test the mid-migration scenario that can no longer exist), the entire `TestMigrationHelpers` class, and the outdated comment in `test_tampered_version_byte_fails` about routing to v1.

Test suite: 70 → 53 (the 17 removed are exactly the 12 migration tests + 1 get_crypto_version + 1 dual-decode + 3 migration helpers).

Production smoke-tested after the changes: logged in, browsed emails, confirmed decrypt works. Zero errors logged.

Backup recovery note: v1 backups (the ~100 from before yesterday\'s migration) age out under the 6-month retention by November 29, 2026. Until then, restoring a v1 backup is theoretically possible by checking out commit `353ae2f` (the pre-cleanup state), running the migration against the v1 backup to bring it forward, then returning to current.

### Backup UX fixes (commit not yet pushed at log-write time)

The three known bugs from May 29 morning\'s investigation, plus one bonus fix that surfaced during testing.

1. **"No changes since last backup" message auto-dismisses too fast.** `showMessage` had a 5s timeout for non-error messages. Doubled to 10s. Enough time to register and read comfortably.

2. **Status card doesn\'t update last-checked timestamp on no-op Backup Now click.** Added a third `.status-item` to the status card: "Last Checked" with id `last-checked-display`. `performBackup()` now writes the current wall-clock time (h:mm AM/PM) to it on every successful POST to `/api/backup/now` — regardless of whether a backup was actually created. Persistent feedback that the check happened.

3. **300px backup history scrollbar invisible on macOS.** The `.backup-list` had `overflow-y: auto`, which on macOS only shows the scrollbar during active scrolling — making the list look static unless the user happens to hover and try. Changed to `overflow-y: scroll` and added explicit `::-webkit-scrollbar` styling (10px width, theme-aware thumb color, hover state) plus Firefox\'s `scrollbar-width: thin` + `scrollbar-color`. Always-visible scrollbar.

**Bonus fix surfaced during testing:** the entire Backup & Restore page wasn\'t scrolling — Rick couldn\'t reach the Backup History section below the viewport. Traced to a CSS rule in `backups-view.css`:

```css
.email-list:has(.backups-view) {
    overflow: visible;  /* intent: prevent double scrollbar */
}
```

The original author meant for `.backups-view` to be its own scrolling container, but never added `overflow-y: auto` to `.backups-view` itself — so neither the parent `.email-list` (now disabled by this rule) nor `.backups-view` was scrolling. The fix: remove the `:has()` override entirely. Settings view doesn\'t have this override and scrolls fine via its parent `.email-list`, so backups should follow the same pattern. The nested scroll concern (page scroll + backup-list internal scroll) is fine — they\'re at different levels of the DOM and don\'t conflict.

### Road to 1.0: complete

All five items shipped:
1. ✓ Frontend trigger UI (May 29 evening)
2. ✓ Production migration on the real archive (May 29 evening, ran clean end-to-end on 1,648 files)
3. ✓ v2-native password change flow (May 29 late evening, production-tested)
4. ✓ Backup UX fixes (today)
5. ✓ v1 cleanup pass (today)

**MailRepo is at 1.0.**

The version string in `main.py` was already `1.0.0` — Rick spotted it in the server startup banner this morning. So the bump happened ahead of the actual feature completion, which is the right order for a project where you tag-then-confirm rather than confirm-then-tag.

---

## May 29, 2026 — Crypto refactor implementation: Encryption v2, DB lock, Migration module, SSE endpoint

**Participants:** Rick, Claude (Opus 4.7) on the MacBook.

A focused multi-session day implementing the v1 → v2 crypto migration designed yesterday. By end of day: the backend is complete and tested; frontend trigger UI and Apollo testing remain for next session. Production migration on Rick\'s real archive is held until Apollo testing passes.

### Morning: backup investigation (no commit)

Started with a backup investigation, not crypto. Rick clicked "Backup Now" in the Backup & Restore screen and saw no visible change — `Last backup` didn\'t update, history didn\'t update. Tracing the code path showed the backup system is working correctly: `create_backup()` falls through to `create_incremental_backup()` → `has_file_changes()` returns False when mtime/size match the baseline → returns None → endpoint returns `{success: True, message: "No changes since last backup"}`. The frontend does call `showMessage('No changes...', 'info')` but the message auto-dismisses after 5 seconds. Plus the 300px backup history is invisible-scrollbar territory on macOS.

So three real UX bugs (info message disappears too fast, status card doesn\'t update on no-op click, history is hard to scroll), but the system is working. Verified yesterday\'s `incr_2026-05-28_075654.zip` is intact (11.7 MiB, integrity OK) and its chain root `full_2026-05-27_104941.zip` (211.4 MiB, 1644 files, OK). The UX bugs are deferred until after the migration is done — modifying backup code immediately before depending on backup for recovery is wrong sequencing.

To get a today-dated recovery point, invoked `create_full_backup()` directly from a Python shell, bypassing the change-detection. Wrote `full_2026-05-29_091216.zip` (211.6 MiB, 1651 files, integrity verified end-to-end). Manifest now has 102 backups, fresh chain root for the day.

### Encryption class refactor (`e59ca2b`)

Rewrote `core/encryption.py` to support both v1 (PBKDF2 + Fernet, legacy) and v2 (Argon2id + HKDF-Expand + AES-256-GCM, current) side by side. Auto-detect on decrypt via the leading byte (0x02 = v2, anything else = v1 Fernet). During migration, both key sets can live in memory simultaneously so mid-walk archives keep working: v1 files decrypt via Fernet, v2 files via AES-256-GCM, new writes go out as v2.

Argon2id parameters: m=256MiB, t=6, p=1. Measured ~750ms per derivation on the M4 — t was tuned upward from the planning placeholder of t=4 because t=4 landed at ~516ms, below the target window.

Atomic salt file replacement uses the textbook fsync + os.replace + directory fsync pattern. The directory fsync is the step usually missed; without it, the rename can vanish on power loss even though the file data was synced.

Added a v2-archive guard at the top of `change_password_progress` in `auth.py` so the existing Fernet-based password change refuses cleanly on v2 archives rather than silently corrupting. v2-native password change is a tracked follow-up.

Tests: 17 new in `test_encryption_v2.py` covering salt file format, wire format (version byte placement, random nonces), AAD binding (tampered byte/nonce/ciphertext/truncation all fail loud), lock/unlock roundtrip, and the critical mid-migration dual-decode scenario (v1 archive built by hand, v2 keys injected, decrypt() correctly routes both).

All 52 tests green. Real-world unlock verified on Rick\'s live v1 archive before commit.

### Plan doc reconciliation (`cdd5229`)

After the Encryption commit, Rick asked whether the migration would address all the issues we\'d found. Honest answer was "mostly, not entirely" — and he wanted both the scope clarifications written down AND the broader DB threading concern folded in.

Updated `docs/Crypto_Refactor_Plan.md` to:
- Add scope item 5: general DB threading lock (was previously in "Out of scope" with only the narrow `_migration_active` flag in scope).
- Add a new "What this work does NOT address" section: backup UX bugs, v2 password change, v1 cleanup pass.
- Add a "Road to 1.0" section listing the 5 remaining pre-1.0 items in priority order.
- Reconcile Argon2 parameters with what shipped (t=6, measured).
- Update concurrent-access risk/failure rows to reflect the lock-based mechanism rather than flag-only.

Doc-only change. 126 insertions, 27 deletions.

### Database threading lock (`076f3db`)

Added `threading.RLock()` at the class level on `Database`, plus `_migration_active` bool + `_migration_thread_id` for the rekey exclusivity window. Every public DB method (`execute`, `executemany`, `fetchone`, `fetchall`, `commit`, `checkpoint`, `get_connection`, `set_key`, `transaction`) now wraps its body in `with cls._lock:` + `cls._check_migration()`. RLock (reentrant) because methods call each other (`fetchone` → `execute`, `transaction` → `get_connection`); a non-reentrant lock would deadlock on the same thread re-acquiring.

`_check_migration()` matches `threading.get_ident()` against the stored migration thread ID and bypasses for the migration\'s own calls. That\'s how Phase 2 can still call `Database.execute` during its exclusive window (which it needs to: WAL checkpoint, the actual rekey).

Public `acquire_for_migration()` / `release_after_migration()` methods bracket the Phase 2 window. Explicit pair (not context manager) because the migration spans non-Python boundaries — PRAGMA rekey, salt file write, in-memory key swap — and unambiguous ownership transfer is clearer than scope-based.

Tests: 6 new in `test_database_threading.py`: concurrent inserts from two threads (no deadlock, correct final count), acquire blocks query in another thread (worker alive but not progressing), migration thread can still query during its own window, release unblocks waiting threads, reentrant lock works for `fetchone` → `execute` and nested `transaction` calls.

All 58 tests green. Verified real-world unlock again before commit.

### Migration module (`b7db944`)

`core/migration.py` (577 lines) — the heart of the day\'s work. Two-phase structure with the per-file 0x02 version byte as the resumability hook.

**Phase 1 (file layer):** walks every `.eml.enc` in the archive, decrypts with v1 Fernet, encrypts with v2 AES-256-GCM, atomically replaces. Re-encrypts IMAP credentials. Verification step counts that every archive file starts with 0x02 and random-sample-decrypts to confirm v2 keys produce sensible plaintext. Then writes the durable `.migration_phase_1_complete` marker.

**Phase 2 (database layer):** refuses to start if backup is older than 24h (non-overridable — Phase 2 isn\'t resumable, backup IS the recovery path). Acquires `Database.acquire_for_migration()`, WAL checkpoint, `PRAGMA rekey` to v2 db_key, atomic v2 salt file write with MRC2 magic, `swap_v1_to_v2()` to clear v1 in-memory state, delete marker.

**Halt-loud on corruption:** `_migrate_file` raises `MigrationCorruptionError` naming the specific filepath if v1 decrypt fails. Does not silently skip — a v1 decrypt failure means real disk damage or a real bug, both of which the user wants to see clearly.

**Atomic file replacement** is the textbook `_atomic_write_file` helper: temp + fsync(file) + os.replace + fsync(directory). Used for both per-file Phase 1 writes and the salt file write in Phase 2.

**Pre-flight checks:** `run_preflight()` returns `{ok, checks}` dict covering: unlocked, v1-decrypt-sample, argon2-cffi live derivation (catches missing dep + OOM in one shot), disk space ≥2× archive, backup age (overridable for Phase 1 only).

**Progress streaming:** both phases take an optional `progress_cb` invoked with status dicts. The SSE endpoint (next commit) plugs this callback into the SSE stream.

Tests: 12 new in `test_migration.py`. State detection across all four classifications (`not_needed` / `fresh` / `phase_1_interrupted` / `phase_2_pending`). Atomic write correctness. `_migrate_file` content equivalence (decrypt of v2 == original plaintext), skip already-v2 (resumability), halt-loud on corrupted v1. End-to-end Phase 1 happy path (tiny archive built by hand → all v2 → marker written → runtime decrypt still works → progress events received). Resumability: simulate partial run, lock + re-unlock, resume cleanly.

All 70 tests green. The unit tests cover the core logic; the plan\'s Apollo Tests 1-8 (interrupt/resume/corruption/concurrent-access under real conditions) are the next layer.

Notable implementation detail: the migration module had to be written via a chunked Python REPL because heredoc with the full 577-line content was being blocked by the shell layer. Several chunks of ~50-80 lines each via `interact_with_process`. One f-string quote-escape bug (over-escaped `row[\\"id\\"]` inside a subscripted f-string expression, which is invalid in Python) — fixed with a single byte replacement.

### SSE endpoint + integration polish (this commit)

`web/blueprints/migration.py` (262 lines) — the HTTP/SSE wrapper. Five endpoints:
- `GET  /migration/api/state` — returns Migration state + pre-flight checks
- `POST /migration/api/start-phase-1` — validates password, stashes in session
- `GET  /migration/api/phase-1-progress` — SSE stream of Phase 1
- `POST /migration/api/start-phase-2` — validates marker + v2 keys + backup ≤24h
- `GET  /migration/api/phase-2-progress` — SSE stream of Phase 2

Phase 2 doesn\'t need the password (v2 keys are already loaded from Phase 1 or from a mid-migration unlock). The two-step authorize-then-stream pattern mirrors `change_password_progress` in auth.py.

A small but important `_stream_migration()` helper bridges Migration\'s synchronous `progress_cb` into an SSE stream via a thread + queue. The worker thread runs the actual migration and pushes events through the queue; the generator consumes them and yields `data: {json}\\n\\n`. Three error categories handled with distinct status codes: `corruption` (filepath named), generic `MigrationError`, and `unexpected`.

Updated `Encryption.is_migration_in_progress()` to also detect the Phase 1 interrupted case — previously it only checked the marker, but if Phase 1 crashes before writing the marker there are v2 files on disk without one. The updated check is: salt is v1 AND (marker exists OR any v2 file exists in the archive). Walks short-circuit on the first 0x02 byte. After migration to v2 the early-return on version check means this scan never runs.

Updated `is_api_request()` in `web/app.py` to also match URL paths containing `/api/`, not just endpoints under the `api.` blueprint. This was a latent issue affecting backup endpoints too: previously, unauthenticated AJAX calls to `/backups/api/...` or `/migration/api/...` would get HTML 302 redirects instead of JSON 401, which frontend code can\'t handle gracefully. Now properly returns JSON 401 for any `/api/` path.

Blueprint registered in `web/app.py`. Endpoint smoke-tested via curl (unauthenticated → `HTTP 401 {"error": "Authentication required"}` — correct). Real-world unlock verified again with all changes in place.

All 70 tests still green. The SSE flow itself isn\'t unit-tested (it depends on Flask app context + session state); Apollo testing will exercise it end-to-end through the browser.

### Where we are at end of day

Committed and pushed: `e59ca2b` → `cdd5229` → `076f3db` → `b7db944` → (this commit).

**Backend is feature-complete.** Encryption class supports both versions. Database is thread-safe and migration-aware. Migration module handles both phases with halt-loud-on-corruption, atomic file replacement, full verification, and resumability. SSE endpoints stream progress to the browser. Unlock-resume detection handles all three mid-migration states.

**Not yet built:**
1. Frontend trigger UI — banner detection on unlock, password confirmation modal, progress UI consuming the SSE streams. This is the next session\'s opening work.
2. Apollo testing — copy archive aside, run Tests 1-8 from the plan (dry-run, interrupt-mid-Phase-1, power-loss, content equivalence, app function, unlock-time, corrupted-file, concurrent-access).
3. Production migration on Rick\'s archive — held until Apollo testing passes.

The backup UX bugs from this morning, v2-native password change, and v1 cleanup pass are tracked in the plan\'s "What this work does NOT address" section — all pre-1.0 but post-migration work.

### Evening session: production migration + v2 password change

Picked back up around 9 PM. Three more commits, all on production:

**Production migration on the real archive (`944b0aa` UI + the actual migration run, no new commit for the run itself).** Built the frontend banner + modal + progress UI consuming the SSE streams: `web/static/js/views/migration.js` (527 lines), `web/static/css/modules/migration.css` (~140 lines), banner + modal markup in `index.html`. Banner detects state on unlock and renders state-appropriate copy ('Migrate' / 'Resume' / 'Finalize'). Modal body re-renders for Phase 1 (preflight checklist + password) vs Phase 2 (backup-status check). Progress UI maps SSE stages to a single progress bar.

Skipped the originally-planned Apollo testing and dry-run-on-a-copy after Rick correctly pushed back: the 8-test adversarial plan was over-engineered for a one-shot migration on a battery-powered laptop with a fresh full backup beside it. The production run IS the test; the first time the code touches a real-sized archive is where any unit-test-missed issue would surface, whether on a copy or the real thing. Same exposure, just one has the word 'test' in front of it.

Hit the button. Phase 1: ~25 seconds for 1,648 files. Marker written. Phase 2: backup-age check passed (morning backup was ~13h old), DB rekeyed, v2 salt file written. Logged out, logged back in with same password — proves the SQLCipher rekey worked since the new password (still the same value, but derived via Argon2id + HKDF to a different key) successfully decrypts the rekeyed DB. End-to-end clean.

Post-migration verification: salt file starts with `MRC2`, marker gone, all 1,648 archive files start with 0x02, zero stray `.v2tmp` files.

**Note on the count.** Rick caught that 1,634 (from earlier in the context) was stale — the actual archive holds 1,648 files. He'd committed 14 more since the older session figures were carried forward.

**v2-native password change (`3f0e67a`).** Closed item 3 from the road to 1.0 in the same evening. Built `core/password_change.py` (336 lines) mirroring `core/migration.py`'s architecture: pure function `change_master_password(old, new, progress_cb)`, no Flask coupling, SSE wrapping in the auth blueprint via the same thread+queue bridge used for the migration. Same safety net: non-overridable backup-≤24h check at the top, halt-loud on file decrypt failure naming the specific file, atomic file replacement.

One architectural difference from the migration is worth noting: there's no version-byte distinction between 'encrypted under the old password's v2 key' and 'encrypted under the new password's v2 key' — both are 0x02-prefixed v2. The version byte tells you the cipher, not the key. So resumability is implemented via try-old-then-new-fallback: each file is attempted with the OLD file_key first; if that fails, the NEW file_key is attempted; if that also fails, halt loud. A previously-interrupted run resumes cleanly because already-migrated files decrypt under NEW. A truly corrupt file fails both and gets named in the error.

`web/blueprints/auth.py` `change_password_progress` now branches on `Encryption.get_crypto_version()`. v2 path delegates to `change_master_password`. v1 path kept verbatim for completeness (dead code on Rick's now-v2 archive; removed in the upcoming v1 cleanup commit). Removed the 'not implemented for v2' guard that `39e0ce2` added as a placeholder. SSE event vocabulary matches the existing `settings.js` handler exactly (counting / counted / encrypting+current+total / credentials / database / finalizing / complete) so no frontend changes were needed for the password change itself.

Rick ran the password change end-to-end on his live archive tonight: ~25 seconds for 1,648 files + credentials + DB rekey + salt file rewrite. Logged out and back in with the new password.

**Logout-modal UX fix (also in `3f0e67a`).** Rick noticed the post-password-change auto-logout had a ~30-60s silent pause. Traced it to the auto-backup at `/auth/logout`: every one of the 1,648 files had a new mtime, so `has_file_changes()` returned True and a full backup ran. `settings.js`'s old behavior was to show a click-to-dismiss 'Password Changed' alert and then `window.location.href = '/auth/logout'`, leaving the user staring at the settings view for the duration of the backup with no feedback. Fix: replace the alert with a direct transition into the logout flow, reusing the existing `#logoutModal` with status text 'Saving backup of your re-encrypted archive. This may take up to a minute.' Pure UX change, no path that breaks the password change flow itself.

**End-of-day status.**

Five of the five items in today's road-to-1.0 list that are crypto-related are shipped:
1. ✓ Frontend trigger UI
2. ✓ Production migration on the real archive
3. ✓ v2-native password change flow

Two non-crypto items remain:
4. Backup UX fixes (1-2h) — three known bugs from this morning's investigation
5. v1 cleanup pass (~1h) — remove the dual-decode logic, the v1 PBKDF2 KDF, the cryptography.fernet import, the v1 branch from update_password, the v1 branch from change_password_progress

All on `main` and pushed: `e59ca2b` → `cdd5229` → `076f3db` → `b7db944` → `39e0ce2` → `944b0aa` → `3f0e67a`. Seven commits, started 9 AM, finished ~10:30 PM with three real meals + one client meeting in between.

**What's not fully verified.** Being honest about the edges of confidence:
- Phase 1 migration: unit-tested + production-tested. High confidence.
- Phase 2 migration: production-tested only. The unit tests don't cover Phase 2 because it depends on actual SQLCipher rekey behavior.
- Password change file walk + DB rekey: production-tested only, no unit tests written. Worked end-to-end on Rick's archive but edge cases (mid-walk interrupt, then resume) aren't exercised by any test.
- Logout-modal UX fix: code reviewed, not actually run end-to-end (Rick chose not to do a password-change revert tonight).
- `is_api_request()` broadening: smoke-tested for /migration/api/*; other paths (/backups/api/*, /auth/api/*) weren't re-exercised after the change, though the global fetch wrapper handles CSRF auto-injection so the change should be transparent.

None of these are vulnerabilities. They're "fewer test scaffolds than the migration's Phase 1 has" gaps. Worth knowing before stamping a 1.0.

---


## May 27, 2026 — Stage Thread feedback + max-thread setting + sidebar auto-refresh

**Participants:** Rick, Claude (Opus 4.7) on the MacBook.

Three related improvements after Rick noticed a multi-second silence between clicking "Stage" on a thread and the email actually greying out. Question about the perceived lag turned into a discussion of three real issues, all addressed.

### Stage Thread: pending-state feedback (`15f50e8`)

The `find_thread` server call is genuinely slow — it issues 15-25 sequential IMAP commands (one SEARCH per wanted message-id in each direction, fetch_thread_headers on each match, repeat across the source folder + Sent + INBOX for up to 5 iterations). On NCF that's the few seconds Rick was seeing. The work is inherently sequential against a single IMAP connection; we can't safely parallelize.

What was missing wasn't speed but feedback. After the folder picker closed there was no visible indication anything was happening, which read as a glitch even though it was working.

Fix: while the request is in flight, the Staged Items rail button (#stagedRailBtn) shows a busy state — icon pulses, small spinner ring in the corner (same corner as the count badge, hidden during the pending phase so no collision). Clears the instant the request resolves, before any error alert, so the spinner's lifetime matches the actual network work rather than the time an error modal sits open.

Implementation in `web/static/js/components/thread-stage.js`: `_setStagedRailBusy(true/false)` helper toggles a `.busy` class and adds/removes the spinner element. CSS in `web/static/css/modules/layout.css` adds the pulse keyframe + spinner, both using `--rail-text-active` so they read correctly on the dark rail across all five themes.

### Stage Thread: thread-size cap raised + validated setting (`0583a4f`, `efe3ab1`)

Rick raised a sharper question while we were here: the `max_messages=100` cap in `find_thread` had been silently truncating long client matters and there was no way for the user to know or tweak it. Discussed three options:

- Remove the cap — rejected. Without a bound, a pathological mailing-list thread could hammer the IMAP server with thousands of sequential commands and trip provider rate-limiting. NCF is a small community ISP; that matters.
- Raise the default and call it done — partial. Better, but still no user control for the rare big-thread case.
- **Make it a setting with belt-and-braces server-side validation** — the right answer, taken.

Two commits to ship it cleanly:

**Commit `0583a4f`** — raised default to 500, added `THREAD_MAX_MESSAGES_DEFAULT/CEILING/FLOOR` constants in `core/imap.py`, and made `find_thread` self-clamp into `[FLOOR=10, CEILING=2000]` regardless of caller input. This is the defence-in-depth layer: even if a bad value reaches the function by some path other than the settings UI (manual DB edit, future bug, crafted API call), the server still can't be made to run an unbounded walk.

**Commit `efe3ab1`** — added the user-facing setting:
- `GET/POST /api/settings/thread-max-messages` endpoint with allowed-set validation (100/250/500/1000/2000). Anything outside that set returns 400. Mirrors the trash-retention / session-timeout pattern exactly.
- Dropdown in Settings → Email Accounts using the existing `custom-select` component. Defaults to 500. A fixed option list is self-validating — there's no free-text field to type a stupid number into.
- `/api/threads/find` now reads the stored setting and passes it through to `find_thread`. Falls back to the module default if missing/unparseable; `find_thread` clamps regardless.

Two validation layers — UI dropdown + server allowed-set check + `find_thread` clamp — mean no input path can make a thread walk run unbounded.

While diagnosing the original report I also confirmed something Rick had asked about: starting Stage Thread from the middle or end of a thread does correctly stage the whole exchange. `find_thread` walks both directions (backwards via References/In-Reply-To headers, forwards by searching for messages that reply to each known id), with each newly-found message contributing its own headers back into the wanted set. Five iterations of fan-out until no new messages turn up. The ordering in the result is normalized to date-ascending. No bug here, working as designed; only caveat is that broken/missing References headers on some intermediate message can clip a branch.

### Sidebar: auto-refresh IMAP folder list on expand (`e26636e`)

Rick noticed his NCF Mail sidebar in MailRepo didn't show "Mortgage 2026" — a folder he'd created on the server weeks ago. Compared MailRepo's tree against Apple Mail's view of the same NCF account; several folders were missing or stale (Ethics Complaint 2 absent, Taxes 2024 still showing as Taxes).

Diagnosed: the IMAP folder list is cached in `accounts.cached_folders` with no time-based expiry. The backend comment was explicit: *"no time-based expiry — folders rarely change. Only refresh on explicit request or when cache is missing."* The endpoint honoured `?refresh=1` and `loadAccountLabels(accountId, forceRefresh)` accepted the flag — but **no UI path ever passed forceRefresh=true**. Capability built at function and endpoint level, never given a trigger. Effectively cached forever.

I initially called this a "missing feature" and proposed adding a manual right-click refresh. Rick correctly pushed back twice: first that I shouldn't have implied a refresh button existed when I wasn't sure, and second that the user shouldn't have to think about this at all — expanding an account should be the refresh trigger.

I then over-complicated by proposing a TTL-based design. Rick reframed simply: *"Expanding an account should trigger a check to see if the folder structure has changed."* That was the right answer — folder lists rarely change so the network cost lands cleanly at a deliberate user action, not background polling.

Concern with the naive "always force-refresh on expand": a multi-second IMAP round-trip stalls every chevron click. Solution, same pattern as Apple Mail and Thunderbird: **render from cache instantly so the sidebar appears with zero perceived latency, then re-fetch live in the background and only re-render if the folder list actually changed.** New/renamed folders catch up within a second or two; if nothing changed, no flash.

Implementation:
- Extracted the render-and-wire-handlers logic from `loadAccountLabels` into a private `_renderAccountFolders` helper so the cached pass and the background re-render share the exact same DOM code path.
- Added a third mode to `loadAccountLabels`: `{ refreshInBackground: true }`. Renders the cache first, then fires a `?refresh=1` request without awaiting it, comparing sorted folder-name lists and only re-rendering on change. Sorted-name comparison catches every user-producible case: additions, removals, renames.
- The account-expand handler in `handleTreeItemClick` now calls with `refreshInBackground: true`.
- Backward-compatible signature: legacy boolean argument (`forceRefresh`) still works.

Rick tested by collapsing and re-expanding NCF Mail; the missing folders appeared after the background refresh. Working as intended.

### Today's commit chain

| Commit | What |
|---|---|
| `15f50e8` | Stage Thread: pending-state feedback on the rail button |
| `0583a4f` | Stage Thread: raise thread-size default to 500, add hard ceiling |
| `efe3ab1` | Stage Thread: make max thread size a validated setting |
| `e26636e` | Sidebar: auto-refresh IMAP folder list on account expand |

### What's pending

- **Apollo pull.** Still behind from May 18 onward; now also today's four commits.
- **Probe scripts cleanup post-1.0.** `/tmp/add_flagged_at.py`, `/tmp/decouple_trash.py` still sitting in /tmp.
- **`find_thread` performance optimization (optional).** The function re-`select_folder`s on every iteration even when the folder hasn't changed, and issues one SEARCH per id rather than batching with IMAP `OR` criteria. Would genuinely reduce the thread-find wait time. Out of scope for today since the feedback indicator + the setting cover the user-visible issue.

---

## May 24, 2026 — Year dividers in the archive folder list

**Participants:** Rick, Claude (Opus 4.7) on the MacBook.

Rick's idea: archive folders with a year or two of correspondence would read better with a year divider between rows. Discussed two designs — simple labelled rules vs. collapsible per-year sections. Went with simple rules. Rationale: an archive is a reference tool you scroll to scan; collapsible sections add a click between the user and "show me everything" and the "current year always open" heuristic misfires in archive folders where the most recent email might be from a year ago. A labelled rule is passive wayfinding — visible while scrolling, never traps content.

### What got built

Pure render-layer feature in `web/static/js/components/email-list.js` — no schema change, no API change, no migration. The `date` field is already in the list payload.

- New `getEmailYear(email)` helper next to the existing `parseDateToMs` — returns the four-digit year or null for unparseable dates.
- In `renderEmailList`, the row-rendering map tracks the previous row's year and emits a `<div class="email-year-divider">` before a row when the year changes.
- Three guards, per the agreed scope: archive folder view only (`isArchiveView`), date sort only (`currentSort` starts with `date` — the grouping is meaningless under sender/subject sorts), and only when the folder spans more than one year (a single-year divider is just noise).

CSS in `web/static/css/modules/email-list.css`: a `.email-year-divider` block. First pass was a muted-gray hairline — Rick correctly called it too faint. Restyled to be theme-aware via `--color-primary` (every theme defines it): a bold year label in the theme accent colour inside a soft accent-tinted pill, with a 2px accent-tinted rule beside it. Left-aligned — discussed centering the pill with a line on each side and decided against it; centering pulls the scan target off the left edge where the sender names align, and reads as a section header rather than a quiet tick.

### Scope discipline

Considered and declined: collapsible sections, centered pill treatment. Both rejected for good reasons rather than effort — the simple left-aligned rule is the correct silhouette for a passive wayfinding marker.

### Website

No website update needed. The docs never mentioned year dividers (the feature didn't exist at the last docs pass), so there's no inaccuracy to fix. A one-line mention could fold into the "Browsing Your Archive" section on the next real website pass — not worth a dedicated trip.

### What's pending

- **Apollo pull.** Still several commits behind from the May 18 session plus this one.
- Manual theme check across all five themes for the divider — Obsidian especially (light-blue accent on dark background; the 12%-opacity pill should be checked for visibility there).

---

## May 18, 2026 — Flagging feature build + trash decoupling

**Participants:** Rick, Claude (Opus 4.7) on the MacBook.

Two pieces of work today: built the flagging feature spec'd in `docs/Flagging_Plan.md`, then found and fixed a real data-model bug in the Trash that had been latent since launch.

### Flagging feature: built and shipped

Followed the design doc closely. Five checkpoints, each landed as its own commit so each step was independently testable:

1. **`dea0f0d`** — schema column (`flagged_at INTEGER` on messages) + threaded the field through the four existing endpoints (search, folder emails, single email, trashed emails). Foundation, nothing user-visible yet.

2. **`93e195c`** — `PATCH /api/messages/<id>/flag` endpoint, star toggle button in the viewer's action bar (archive-only, hidden otherwise), theme-aware via a new `--color-star` CSS variable defaulting to `--color-primary` per theme. End-to-end toggle path works: click → server update → icon swap.

3. **`b713fd5`** — read-only star indicator on flagged email-list rows. Placed next to the date so the row layout stays consistent across flagged/unflagged rows. Unflagged rows show nothing — no empty-star placeholders.

4. **`72933aa`** — Starred pseudo-folder in the sidebar with its own view: `GET /api/messages/flagged` returns all flagged emails sorted by `flagged_at DESC`, each row shows the folder path so the user knows where each starred email lives. Clicking opens the standard viewer; prev/next walks the starred set.

5. **`dbb1e81`** — `s` keyboard shortcut to toggle the star from the viewer. Verified `s` was unbound before claiming it.

**Polish along the way (`7ad1102`):** context-aware unstar. Unstarring from within the Starred view drops the row immediately rather than leaving a stale entry behind. Required a small dance: `inStarredContext` flag in `starred.js`, exported `dropFromStarredList` for the mail.js toggle handler to call, and avoiding `renderEmailList()` in that context (which would have overwritten the Starred template with the regular folder-list template — that produced a clear "rows lose folder paths and gain action buttons" bug during testing).

Rick noted during testing that unstarring from a regular folder view should NOT remove the row (the list isn't filtered by star status); only the Starred view filters that way. The context check honors that.

### Trash decoupling: data model fix

Rick reported a bug: trash one email individually, then trash the folder containing another email, then click "Delete Folders" on the Folders tab → both emails disappear. The Folders tab and Emails tab implied independent collections but the FK cascade (`messages.folder_id REFERENCES folders(id) ON DELETE CASCADE`) made them coupled. Individually-trashed emails whose folder happened to also be in trash were cascade-deleted along with the folder.

Diagnosed and discussed two fix tiers:
- **"V1" fix:** clearer messaging on the Delete Folders button. Rick called this out as papering over the problem: "you wouldn't necessarily know, clicking the Delete Folders button, that it will also delete emails that are listed separately in the Emails tab."
- **The right fix:** decouple individually-trashed emails from their folder entirely, so the cascade can't reach them.

Took the right fix. Schema change (`581d17e`):
- `messages.folder_id` is now nullable (was `NOT NULL`)
- New `messages.original_folder_id INTEGER` with `FK ON DELETE SET NULL`

When an email is individually trashed, `folder_id` moves to `original_folder_id` and `folder_id` is set to `NULL`. The cascade can no longer reach it. Restore reverses the move; if the original folder is gone or itself trashed, the backend returns 409 with `needs_destination=true` and the frontend opens the folder picker.

Pre-release direct schema edit, applied to Rick's existing DB via `/tmp/decouple_trash.py` (table rebuild — SQLite can't `ALTER` nullability in place). Idempotent. 1634 messages preserved across the migration with zero detached (Rick had no individually-trashed emails at migration time).

Endpoint changes in `web/blueprints/api/emails.py`:
- `delete_message` sets `original_folder_id = folder_id`, `folder_id = NULL`
- `restore_message` re-attaches via `original_folder_id`; returns 409 with `needs_destination` flag if the original is gone or trashed
- `get_trashed_emails` reads from `original_folder_id` (now where the source folder lives for trashed emails). Adds `original_folder_unavailable` flag

Frontend (`trash.js`):
- Trash email rows now show "Originally in: <folder>" beneath the subject. Falls back to "Original folder is gone" (muted) when the source folder is unavailable.
- `restoreEmail` handles the 409 by opening the existing folder-tree picker with `confirmLabel: 'Restore'`, then re-calls itself with the chosen folder_id.

The `empty_trash` endpoint required no logic change — it already scoped to `folder_id IN (trashed_folders)`, which now correctly excludes individually-trashed emails since they have `folder_id IS NULL`. The two Trash tabs are now genuinely independent.

### Commit chain (today)

| Commit | What |
|---|---|
| `dea0f0d` | Flagging: schema column + thread flagged_at through existing endpoints |
| `93e195c` | Flagging: PATCH /flag endpoint + viewer star toggle |
| `b713fd5` | Flagging: read-only star indicator on flagged list rows |
| `72933aa` | Flagging: Starred pseudo-folder view |
| `7ad1102` | Flagging: context-aware unstar in Starred view |
| `dbb1e81` | Flagging: 's' keyboard shortcut |
| `581d17e` | Decouple individually-trashed emails from their folder |

### Trash decoupling tested + a string/number bug surfaced

Rick tested the decoupling fix and reported a separate bug: trashing a folder didn't update the main view — the Testing folder vanished from the sidebar but the main pane still showed its contents and email count.

Tracked it to a string-vs-number mismatch in `deleteFolder`. The sidebar passes `row.dataset.id` (always a string) through `onFolderSelect(id)` → `selectView({ type: 'folder', id })`, so `state.currentView.id` is a string when set from a sidebar click. But `deletedFolderIds` is built from `state.folders[].id` (numbers from the backend). Array `.includes()` is strict equality, so `[33].includes("33")` was silently false — the view-clearing branch never fired.

Fix in `db2b34f` (one-liner in folder-mgmt.js): use `.some(fid => fid == currentId)` instead of `.includes`, matching the loose-equality pattern used elsewhere in the codebase for folder ID comparisons. Verified working.

### What's pending
- **Apollo pull.** That machine is now several commits behind; pull before next session there.
- **Probe scripts cleanup post-1.0:** `/tmp/add_flagged_at.py`, `/tmp/decouple_trash.py` aren't checked into the repo (one-off migrations only Rick runs), but worth noting they exist and what they did for any future archeology.

---


## May 17, 2026 — Polish: Delete→Trash rename, prev/next nav, Flagging design doc

Three polish items after Stage Thread shipped this morning.

### Archive folder right-click: "Delete" → "Trash" (commit `5fd688a`)

The action soft-deletes a folder (sets `deleted_at`) — folders go to Trash where they can be restored. The flow always said "Move to Trash" on the confirm button and in the body, but the menu label and modal title said "Delete", which was misleading. Renamed both. Kept the danger styling and trash icon — still a destructive action even if reversible. Internal function name `deleteFolder` left unchanged; renaming would touch a dozen call sites for no user-facing benefit. Trash view permanent-delete and Settings account-delete still correctly say "Delete" (those are genuinely destructive).

### Flagging feature design doc (commit `1810a5b`)

Drafted `docs/Flagging_Plan.md` (225 lines) for a single-color star/flag feature on archived emails. Scope decisions made during the conversation:

- Archive-only. Rick: "I would not flag emails on the IMAP server by the way, that's mail client territory."
- Single color, not multiple. Solo-practitioner workflow doesn't need a taxonomy; that's what folders are for.
- Theme-aware via `--color-star` CSS variable, defaulting to `--color-primary` per theme. If any theme reads poorly, override per-theme.
- Toggle in the viewer action bar only, NOT in list rows. Rationale: list rows are visually busy already, and the decision to flag happens after reading, not while scanning.
- Read-only star indicator on flagged list rows so users can see what they've flagged without opening each email.
- "Starred" pseudo-folder in sidebar (near Trash) showing all flagged emails across the archive, sorted by `flagged_at DESC`.
- Schema: `flagged_at INTEGER` column (null = unflagged). Storing a timestamp instead of a boolean costs the same and gains free sortability for the pseudo-folder.
- Keyboard shortcut: `s` in the viewer.

Build slated for next session, 6-8 hour estimate.

### Prev/Next navigation for archived emails (commit `eb7fede`)

Chevron-up (previous, newer) and chevron-down (next, older) buttons in the viewer action bar. Scope decisions:

- Archive folder views only. Rick: "I had thought of the prev/next only being active within archive folders, not search results." Buttons hidden (not disabled) for live IMAP, search results, and import previews — absence is intentional rather than broken.
- Disabled at list boundaries, no wraparound.
- Placement: end of the action row, after existing action icons, before the close-X. Read order: actions on this email → navigate to a different email → close.
- Keyboard shortcuts: `j` (next/older), `k` (previous/newer), `Escape` (close). Chose `j`/`k` over arrow keys because arrows would conflict with scrolling the email body. Skipped when an input has focus or modifier keys are held.

Verified end-to-end against Rick's real archive.

### Today's commit chain (this afternoon)

| Commit | What |
|---|---|
| `5fd688a` | Rename archive-folder 'Delete' action to 'Trash' |
| `1810a5b` | Add Flagging Plan design doc |
| `eb7fede` | Add prev/next navigation for archived emails |

### What's pending for next session

- Build the flagging feature per `docs/Flagging_Plan.md`. Sized for a single session.

---

## May 17, 2026 — Stage Thread feature: build and test

**Participants:** Rick, Claude (Opus 4.7) — back on the MacBook (primary dev machine).

Built and verified the "Stage thread to..." feature designed in `docs/Stage_Thread_Plan.md`. Found and fixed three collateral bugs along the way.

### Build order

Deviated from the design doc's phasing in one place: built header-walk FIRST and skipped the IMAP THREAD extension entirely for Phase 1, rather than building THREAD with header-walk as fallback. Reasoning: header-walk works on every RFC 3501 server (including NCF's mystery setup), so it's the safer universal path to prove first. THREAD optimization can be added later if header-walk turns out slow on real workloads.

### What got built

**Backend (commit `20b2337`):**
- `core/imap.py`: `get_special_folder()` extended with `'sent'`. Verified against Rick's real accounts — NCF returns `'Sent'`, both Gmail accounts return `'[Gmail]/Sent Mail'`.
- `core/imap.py`: new `fetch_thread_headers(uid)` — light fetch of MESSAGE-ID, IN-REPLY-TO, REFERENCES, FROM, SUBJECT, DATE.
- `core/imap.py`: new `find_thread(source_folder, source_uid, also_search_folders, max_messages=100, max_iterations=5, deadline_seconds=10)`. Bidirectional walk via IN-REPLY-TO and REFERENCES. Returns sorted-by-date list with `truncated` and `timed_out` flags.
- `web/blueprints/api/threads.py` (new): `POST /api/threads/find` endpoint. Auto-includes Sent folder + INBOX (if source is elsewhere) in the search. Handles IMAPError → 502, unexpected → 500.

**Frontend (commit `93cdf4d`):**
- New `messages-square` icon in the email viewer's action bar, hidden by default. `_updateStageThreadButton(context)` shows it only when `context.type === 'account'` (live IMAP).
- `web/static/js/components/thread-stage.js` (new, lazy-loaded): opens the existing folder-tree picker (`openChangeDestinationModal`), POSTs to `/api/threads/find`, then writes each thread member into `state.staged` with the same shape the existing staging code produces.

**Polish during end-to-end testing:**
- `991f58d` — modal z-index bumped to 1050 so the folder picker sits above the email viewer overlay (both were at 1000; viewer won the DOM-order tie). Latent bug; would have hit any modal opened from the viewer.
- `7f61164` — `openChangeDestinationModal` accepts `confirmLabel`; Stage Thread passes `'Stage'` instead of the default `'Move'`. Also removed a redundant pre-stage confirmation modal — the Review screen IS the audit step, an extra confirm is friction without value.
- `22bb64c` — staged entries keyed by UID (not `message_id`) to match the existing `email-list.js` renderer convention, so rows gray out correctly.
- `18b4273` — call `renderEmailList()` after staging so the visual indicator updates without requiring a manual refresh.

### Collateral bugs found and fixed

Three pre-existing bugs surfaced while testing against Rick's real "Swarna" two-message exchange (a Gmail-mobile picture message with no body text, two attached images):

1. **Live email viewer dropped image-only emails entirely (`8c4696c`, regression fix in `9f98d17`):** Gmail mobile attaches images with BOTH `Content-Disposition: attachment` AND `Content-ID`. The old `fetch_full` logic treated any image part with a Content-ID as inline and skipped it from the attachments list — even when the html body had no `cid:` references. Result: invisible to the user.

   Fix: pre-scan the html for actually-referenced cids, only treat a part as inline if its Content-ID is in that set. Also added a visually-empty-body detector in `renderEmailContent` that falls through to a placeholder when the html is just `<div dir="auto"></div>` and attachments are present.

   The `9f98d17` follow-up removed a redundant `import re` inside `fetch_full` that was triggering `UnboundLocalError` — Python compile-time scoping promoted all `re` references in the function to local, the new pre-scan code used `re` before the inner import statement, hit unbound local. Module already imports `re` at the top, so the inner imports were pure cruft.

2. **Archived email viewer had the same bug (`1a0c639`):** `web/blueprints/api/emails.py` has its own parsing logic (separate from `fetch_full`) for the `/api/folders/<folder_id>/emails/<message_id>` route. Same too-eager Content-ID handling. Fixed with the same approach, factored into a `_collect_referenced_cids(msg)` helper used by both `get_archived_email` and `download_archived_attachment` (must match filtering so indices line up).

### Verified end-to-end

Real two-message exchange on NCF: header-walk finds both ends (INBOX uid=129995 + Sent uid=129993) in 0.88s, no truncation, no timeout. Stage Thread button → folder picker → "Stage" → both messages staged with correct `sourceFolder`. Review screen groups them under destination. Commit succeeds. Both messages decrypt cleanly from disk with full MIME tree intact (both image/jpeg parts preserved at original byte counts).

### Today's commit chain

| Commit | What |
|---|---|
| `c3ee80f` | (May 16, Apollo) Stage Thread design doc |
| `20b2337` | Stage Thread: backend |
| `93cdf4d` | Stage Thread: frontend |
| `8c4696c` | Live viewer: fix image-only emails appearing blank |
| `9f98d17` | Fix UnboundLocalError regression from 8c4696c |
| `991f58d` | Modal z-index above email viewer overlay |
| `7f61164` | Stage Thread polish: confirm button label, drop redundant confirmation |
| `22bb64c` | Stage Thread: key staged entries by UID for visual indicator |
| `18b4273` | Stage Thread: re-render list after staging so rows gray out |
| `1a0c639` | Archive viewer: same image-only fix as the live viewer |

### Deferred

- IMAP THREAD extension optimization (Phase 2 per design doc). Worth measuring on real workloads first to see if header-walk is actually slow enough to need it.
- Account-level "also search Inbox when threading from other folders" setting (Phase 2).
- Pre-stage thread visualization (Phase 3 — Rick's call was that the Review screen is enough).
- Archived viewer's "(No content)" string could be updated to match the live viewer's friendlier "(This message has no text — see attachments above.)" — minor consistency polish, not a bug.
- Dev probe scripts (`scripts/probe_*.py`) — keep for now while the feature is fresh; clean up post-1.0.

---

## May 16, 2026 — Stage Thread design doc (Apollo)

Drafted `docs/Stage_Thread_Plan.md` (242 lines) on Apollo: a "Stage thread to..." action for the live email viewer. One-click filing of an entire conversation across Inbox and Sent. Scope intentionally narrow — live IMAP only, no archive-side threading, no schema changes, no recipient-based bulk pull. Pushed as `c3ee80f`. Build slated for the next session.

---

## May 11, 2026 — Remove dead legacy commit routes

**Participants:** Rick, Claude (Opus 4.7) — back on the MacBook.

**Context:** Rick asked whether MailRepo protects against duplicate commits (e.g. accidentally committing the same batch of emails to the same archive folder twice). Verifying this in the code turned up two things:

1. **Duplicate protection is solid.** `commit.py`\'s `_check_duplicate(folder_id, message_id)` helper queries `messages WHERE folder_id = ? AND message_id = ? AND deleted_at IS NULL` and is called at three sites in the streaming commit path (single-email commit, resume-interrupted-commit, folder-commit). Duplicates are added to the `skipped` results with reason `"duplicate"`, the file isn\'t written, no DB row is inserted, and the user sees "N skipped (already archived)" in the commit summary. Scope is per-folder (filing copies in multiple folders is a legitimate workflow); ignores trashed copies (`deleted_at IS NULL`) so re-archiving after a trash works; degrades gracefully if `Message-ID` is missing (`if not message_id: return False`).

2. **There was a pile of dead code carrying parallel duplicate protection.** `web/blueprints/api/staging.py` (306 lines) registered two routes — `POST /api/commit` and `POST /api/commit-folders` — that the frontend never called. The file\'s own header comment said "These routes are kept for potential API/testing use," but verification across the repo found zero callers: no JS fetch, no test, no script. The streaming commit path in `progress.py` (plus `commit.py` helpers) has been doing the work for months.

**Fix:**

- Deleted `web/blueprints/api/staging.py` outright (`commit_staged`, `commit_folders`, `_create_archive_folder_path` — all dead).
- Removed `from . import staging` from `web/blueprints/api/__init__.py`.
- Annotated the corresponding step in `docs/Refactoring_Plan.md` as superseded with a pointer to where the work actually lives now.

### Files changed

- `web/blueprints/api/staging.py` — **deleted** (12,424 bytes / 306 lines)
- `web/blueprints/api/__init__.py` — removed the staging import
- `docs/Refactoring_Plan.md` — annotated Step 3.4 as superseded
- `docs/Session_Log.md` — this entry

### Verified

App boots cleanly. All three live `/api/commit/*` routes (`/discard`, `/pending`, `/stream`) still register. Total `/api/` route count drops by two (from 80 to 78) — the two dead routes — with no other changes to the URL map. The note in the API module that another `staging` module no longer exists doesn\'t cause any import errors (only `web/blueprints/api/__init__.py` referenced it).

Naming note: `web/static/js/components/staging.js` is the frontend staging UI component and is unrelated to the deleted `api/staging.py`. Same name, different concerns; no overlap.

---

## May 10, 2026 — Remove 5K export limit; update website with export feature

**Participants:** Rick, Claude (Opus 4.7) — working on Apollo (Linux ThinkPad) for the first time this session, since the website lives here.

### Removed the 5,000-email export limit

Phase 1 added a hard cap at 5,000 emails per export with the comment "to protect the user (and the server) from accidental huge exports." Reviewing this while drafting docs for the website, the rationale doesn't hold up: MailRepo is a local-first single-user app, and the export UI already has a percent-based progress bar (loading 0–30%, rendering 30–80%, WeasyPrint 80–85%, packaging on top) plus an indeterminate "pulsing" mode during the WeasyPrint phase. The user always sees what's happening. If they want to export 12,000 emails and wait, that's their tradeoff.

Removed the limit check from `_run_export_job` in `web/blueprints/api/exports.py`. Marked the corresponding open question in `docs/Bulk_Export_Plan.md` as resolved with the new reasoning.

### Updated the MailRepo website with export documentation

The website at `/home/rick/Websites/mailrepo-website` (last updated April 1) was missing any mention of the bulk export feature shipped May 3. Updated three pages:

- **`docs.html`** — added a new "Exporting" section under "Using MailRepo," between Searching and Retention Vault. Covers the three entry points (folder, search, batch select), the three output formats (PDF / .eml ZIP / both), AES-256 encryption with passphrase handling and recipient-tooling notes, attachment handling (PDFs merged on the back, images and other types as sibling files), saving and reveal, and the "Load remote images" toggle. Sidebar nav updated to match.
- **`index_final.html`** — replaced the outdated "How it works" line ("export individual threads when you need them") with a more accurate description, and added a fourth feature card.
- Verified all factual claims against actual source code on Apollo (which had been six weeks behind — pulled to current `011859d` first). Caught and corrected three inaccuracies in my first draft: Windows 11 native AES support shouldn't be cheerleaded since MailRepo doesn't target Windows, the cover page doesn't actually carry the source folder name for batch-select exports (backend ignores the frontend's nicely-formatted label and uses `"{N} selected emails"`), and PDF appendices are referenced in each email's attachment list with a labeled appendix page — not "in the cover."

### Files changed (app repo)

- `web/blueprints/api/exports.py` — removed the limit check
- `docs/Bulk_Export_Plan.md` — marked open question 6 as resolved
- `docs/Session_Log.md` — this entry

### Files changed (website repo)

- `docs.html` — new Exporting section + sidebar nav entry
- `index_final.html` — feature card + How it works update

### Verified

`exports.py` parses cleanly. App still boots. Website renders locally. Both repos commit and push successfully.

---

## May 8, 2026 — Email viewer: kill double scrollbars

**Participants:** Rick, Claude (Opus 4.7)

**Issue:** When viewing an archived HTML email, the viewer panel showed two scrollbars: a thick one inside the iframe rendering the email body, and the outer `.email-viewer-body` scrollbar at the panel edge. Later: the same iframe was also showing a horizontal scrollbar at the bottom on emails with wide content.

### Root cause (vertical)

`renderHtmlBody` in `mail.js` was sizing the iframe to its content using three timed `setTimeout` snapshots (100ms / 500ms / 1s). If layout shifted after the third snapshot — slow images, web fonts loading, late CSS — the iframe stayed at the old height and its built-in scrollbar appeared on top of the parent\'s.

### Fix part 1 — vertical scrollbar (commit `541ede2`)

Two complementary changes:

- **ResizeObserver** inside the iframe now tracks the document\'s height continuously instead of guessing when content is "done". Image-load and window-load listeners cover gaps where some browsers don\'t fire ResizeObserver for image loads. Falls back to the original timed snapshots if observer setup throws.
- **`overflow-y: hidden`** on the iframe document\'s `html, body` so the iframe physically cannot show its own vertical scrollbar regardless of content. The outer `.email-viewer-body` is the single vertical scroll context. Belt-and-braces with the height tracking — even if a measurement is missed, no internal scrollbar appears.

Also added `display: block` on the iframe element to remove the small inline-element baseline gap that was making the scroll area subtly taller than visible content.

### Fix part 2 — horizontal scrollbar (commit `5dfe162`)

After the vertical fix, a horizontal scrollbar appeared on emails with wide content. Common cause: 600–700px fixed-width tables (most email templates), long unbroken URLs, wide images. Same approach as Gmail / Apple Mail in their reading panes: hide horizontal overflow entirely and constrain wide content to fit.

Extended the iframe document CSS:

- `overflow: hidden` on `html, body` (was just `overflow-y: hidden`) — no scrollbar on either axis, ever
- `table { max-width: 100% }` so fixed-width tables shrink to fit
- `pre, code` get `white-space: pre-wrap` + `overflow-wrap: anywhere` so code blocks wrap instead of overflowing
- `word-break: break-word` + `overflow-wrap: anywhere` on body and links so long URLs / message IDs break at any character rather than pushing the viewport wider

In rare cases where content physically can\'t fit even with these rules (e.g. a 1200px image with explicit dimensions overriding CSS), it gets clipped at the right edge rather than triggering a scrollbar — same trade-off Gmail makes.

### Files changed

- `web/static/js/views/mail.js` (`renderHtmlBody`: ResizeObserver + iframe document CSS)
- `docs/Session_Log.md` (this entry)

### Verified

Confirmed via screenshots from Rick that both vertical and horizontal scrollbars are now gone on the affected email. The outer `.email-viewer-body` is now the only scroll context in the email viewer.

---

## May 6, 2026 — Review screen: unify destination picker

**Participants:** Rick, Claude (Opus 4.7)

**Issue:** The Review screen's "Change Destination" button opened a custom `icon-select` dropdown — a flat list of all archive folders rendered with depth-indented padding. The rest of the app (Stage modal, Move Email, Move Folder) had standardized on the unified `renderFolderTree` modal-based picker, so this was a leftover inconsistency. With many folders, the flat list was hard to navigate.

**Fix:** Added a `'change-destination'` mode to the existing Stage modal, then swapped the Review screen's inline dropdown for a button that opens the Stage modal in this mode.

The Stage modal already uses `renderFolderTree` and was sized correctly for tree picking — adding a third mode flag (`'staging'` / `'folders'` / `'change-destination'`) was a much smaller change than building a new picker. The new mode:
- Renames the modal title to "Change Destination" and the confirm button to "Move"
- Pre-selects the current destination so the tree highlights it
- On confirm, fires a callback with the new folder ID instead of running staging logic

The Review screen now calls `openChangeDestinationModal({currentDestId, onConfirm})` and wires the callback to its existing `changeDestination(oldDestId, newDestId)` function. No backend changes; same data flow as before, just a different picker UI.

While in there, added an X close button to the Stage modal header (consistency with the Move Email and Move Folder modals which already have one).

The dead `dest-change-dropdown` branch in `initIconSelects()` was removed; the matching CSS rule in `review-view.css` is now orphaned but harmless, left for a future cleanup pass.

### Files changed

- `web/static/js/components/staging.js` (`openChangeDestinationModal` + new branch in `confirmStage`)
- `web/static/js/views/review.js` (`renderDestinationDropdown` rewritten as a button; dead `dest-change-dropdown` handler removed)
- `web/templates/main/index.html` (X close button on Stage modal)
- `docs/Session_Log.md` (this entry)

### Verified

JS syntax checks pass. App boots without import errors. The change-destination mode reuses the same `renderFolderTree` instance the Stage modal already mounts, so creating a new folder mid-flow continues to work in this mode too (same `onAddFolder` plumbing).

---

## May 5, 2026 — UI fix: shared scroll context in three-pane layout

**Participants:** Rick, Claude (Opus 4.7)

**Issue:** Selecting a deeply nested archive folder pushed the email pane off the top edge of the screen. The email rows for the selected folder were technically there but had to be scrolled back into view at the page level. Confirmed via screenshot.

**Root cause:** `.app-container` used `min-height: 100vh`, so the document grew with its content rather than being capped at the viewport. The sidebar (which hosts the long folder tree) had `overflow: hidden` but no fixed height, so when the folder tree got tall it pushed the parent past the viewport, and the page itself became the scroll context. From the user's perspective: clicking a folder caused the email list to "open below" the visible area.

**Fix (commit `3881be4`):** Switched the layout to a fixed-height shell.
- `.app-container`: `height: 100vh` + `overflow: hidden` so the document is exactly one viewport tall, never more.
- `.sidebar`: `height: 100%` + `overflow-y: auto` so the folder tree scrolls inside its own pane.
- `.main-content` already had `overflow: hidden` and `.email-list` already had `flex: 1; overflow-y: auto`, so the right side was already correctly set up — it just needed the parent to stop growing.

**Follow-up (commit `f064d81`):** First fix introduced nested scrollbars — the new outer `.sidebar` scroll layered on top of the existing `.section-content.expanded { max-height: 500px; overflow-y: auto }` per-section caps. Three nested scrollbars in some cases. Removed the per-section caps so each section grows naturally and only the outer sidebar scrolls. One scrollbar per pane, no nesting.

Trade-off: when many sections are expanded simultaneously, the user may need to scroll past one to reach the next. Acceptable for the visual cleanliness.

### Files changed

- `web/static/css/modules/layout.css` (`.app-container` height lock)
- `web/static/css/modules/sidebar.css` (sidebar own scroll + per-section cap removal)

### Verified

Each pane now scrolls independently. Selecting any folder, no matter how deeply nested, lands the email pane in view. Single scrollbar in the sidebar, single scrollbar in the email list, no page-level scroll.

---

## May 3, 2026 — Bulk Export Phase 3 (late evening)

**Participants:** Rick, Claude (Opus 4.7)

**Work Done:**

Closed out the bulk-export plan. Three pieces in sequence:

### 3a — Encryption (AES-256 ZIP via pyzipper)

Added `pyzipper>=0.3` dependency. The export modal grew an "Encrypt this export" checkbox; when checked, password + confirm fields appear with live validation (length warning at < 8 chars, match indicator). Frontend validates before submitting; backend receives the password in the start payload, uses it once for the ZIP write, doesn\'t log it.

Format-aware encryption:
- **PDF + password** → wrapper AES ZIP containing the PDF
- **eml + password** → native AES eml ZIP (no double-wrapping; single layer)
- **both + password** → single wrapper AES ZIP with PDF + flat `emails/<folder>/<file>.eml` (no nested ZIP)

Recipient notes surfaced in the modal: macOS Archive Utility doesn\'t open AES, recommend The Unarchiver; Windows 11 (23H2+) and Linux unzip 6.0+ are native.

### 3b — One-time first-use friction modal

First time the user opens the export modal in this browser, an "About exports" screen explains the encryption-boundary issue: an export creates a regular file on disk outside MailRepo\'s encrypted database. Has a "Don\'t show again" checkbox (default on) stored under `localStorage["mailrepo.exportWarningDismissed"]`. Once dismissed, the modal opens straight to the form view. Cancel aborts without consuming the dismissal so the user can re-enter and see the warning.

### 3c — Non-PDF attachments as sibling files

`pdf_export.py` already discriminated PDF attachments (pypdf-merged onto the back) from image/other attachments (previously just listed by name). Now image and other-type attachments are returned in a separate `other_attachments` list on the `complete` event. `exports.py` packages them as `attachments/email-N/<filename>` sibling files inside a wrapper ZIP, with per-email-folder filename de-duplication. Composes cleanly with encryption: encrypted exports get the same wrapper, just AES-256.

Email body attachment list now reads "(see attachments/email-N/)" when the file is actually included alongside (vs "(image attachment)" before, which was a dead-end).

Wrapper-vs-bare logic:
- No password, no non-PDF attachments → bare PDF (preserves the original Phase 1 behavior for the simple case)
- No password, has non-PDF attachments → plain ZIP wrapper
- Password → encrypted ZIP wrapper

### Files changed

- `requirements.txt` (+pyzipper)
- `core/pdf_export.py` (other_attachments tracking + return)
- `web/blueprints/api/exports.py` (encryption helpers, wrapper-ZIP logic, attachment packaging)
- `web/static/js/components/export-modal.js` (encryption section, first-use warning)
- `web/static/css/modules/export.css` (styling for both)
- `docs/Bulk_Export_Plan.md` (Phase 3 status)
- `docs/Session_Log.md` (this entry)

### Verified offline

Plain and encrypted ZIPs round-trip correctly. Wrong-password decryption raises RuntimeError as expected. Filename sanitization handles weird characters (`tricky..name//here.png` becomes a valid ZIP entry name). De-duplication kicks in correctly for repeated filenames within the same email folder. App boots, all five export endpoints register.

### Deferred (no longer in scope of the bulk-export plan)

- Custom export filename input
- TOC for >20-email exports
- Verbose headers option
- Anchor-id collision sanitization (cosmetic warnings only)

The bulk-export plan is now complete. Future export work would be its own design conversation.

---

## May 3, 2026 — Bulk Export Phase 2 (evening)

**Participants:** Rick, Claude (Opus 4.7)

**Work Done:**

Wired two new entry points into the existing bulk-export modal:

1. **Archive batch-select → Export.** The archive folder view\'s toolbar already had All / Clear / Move / Trash for batch operations on selected archived emails. Added an "Export…" button between Move and Trash. Calls `openExportModal({source: 'messages', message_ids, label})` with a label like "12 emails from Clients/Smith" so the cover page reflects the source folder.

2. **Search results → Export results.** The search view\'s toolbar gets an "Export…" button next to Clear, conditionally visible only when results are showing (not on the initial helper screen, not on the empty-results state). Calls `openExportModal({source: 'search', query, folder_id, include_subfolders, folder_name})`, which re-runs the FTS query at export time. Re-running the query on the backend rather than embedding all the message ids is intentional — it scales to large result sets and stays consistent with what the user saw.

Backend already supported both `messages` and `search` selection sources from Phase 1; this was pure frontend wiring. The form-state-preservation fix earlier this session applies to both new entry points by construction.

### Bug fixed earlier today

**Form state lost when opening destination picker.** Switching to the picker view re-rendered the modal HTML; coming back re-read `window._export`, which only got updated in `_startExport`. Result: opening the picker after picking options reset everything to defaults. Fixed with three layers: a `_captureFormState()` helper that reads form values into `window._export`, `change` listeners on every form input that call it, and an explicit call right before `_openPickerView` tears down the form\'s DOM.

### Files changed

- `web/static/js/components/email-list.js` (Export button + handler in archive toolbar)
- `web/static/js/views/mail.js` (Export results button + handler in search toolbar)
- `web/static/js/components/export-modal.js` (form-state preservation fix from earlier today)
- `docs/Bulk_Export_Plan.md` (Phase 2 status)
- `docs/Session_Log.md` (this entry)

### Deferred to Phase 3

- AES-256 encrypted ZIP via pyzipper with one-time warning modal
- Non-PDF attachment handling (images, Office docs in sibling folder)

---

## May 3, 2026 — Bulk Export Phase 1

**Participants:** Rick, Claude (Opus 4.7)

**Work Done:**

Built the bulk PDF export feature end to end, from skeleton through polish. The bulk-export design doc had this scoped as four phases; we collapsed phases 1 + 4 into a single shippable Phase 1 covering folder-source export, PDF rendering, attachments, save-to-disk, progress UI, cover page, and a remote-content toggle. Phases 2 (search/messages sources) and 3 (encryption + non-PDF attachment handling) remain.

### What's new

**Backend (`core/pdf_export.py` ~922 lines, `web/blueprints/api/exports.py` ~700 lines):**
- WeasyPrint pipeline: combined HTML document → single render → pypdf merge for PDF attachments
- Cover page with scope, email count, date range, export date
- Email sections with header table (From/To/Cc/Date/Folder) and CSS-scoped HTML body
- Appendix page listing PDF attachments before they're merged onto the back
- 5 endpoints: `/api/export/start`, `/progress/<job_id>` (SSE), `/download/<job_id>`, `/cancel/<job_id>`, `/reveal`

**Frontend (`web/static/js/components/export-modal.js` ~520 lines, `export.css` ~340 lines):**
- Modal with form view → progress view → complete view → error view
- Custom folder picker (no native dialogs); last-used directory persisted in `localStorage`
- Sort toggle (chronological / reverse)
- Include cover page checkbox
- Include subfolders checkbox (folder source)
- "Load remote images" checkbox (default off)
- Triggered from sidebar folder context menu and ⋯ button — same `openExportModal({source:'folder', folder_id, folder_name})` entry point

### The hard problems

**CSS scoping (cream-on-cover-page bleed).** Email HTML often sets a body background via inline `<body style="background: cream">` or a `<style>body { background: cream }</style>` block, sometimes wrapped in `@media only screen`. Concatenated naively into one combined document, that cream applied to the cover page and every email afterward. Fix: rewrite `<html>`/`<body>`/`<head>` tags as scoped `<div class="email-shell">` containers, preserving attributes (including inline styles), and rewrite selectors in `<style>` blocks to be prefixed with `.email-scope-eN`. Recursive descent into `@media`/`@supports`/`@layer`/`@container`/`@scope` so nested selectors get scoped too. Verified with three real email styles plus the user's actual `.eml` files.

**WeasyPrint table-layout quirks (centering).** Two HTML attributes WeasyPrint doesn't honor like browsers do:
- `<table width="100%">` renders content-width, not container-width. Fix: `table[width="100%"] { width: 100% !important }` in base CSS.
- `<td align="center">` doesn't center block-level descendants (nested tables). Fix: `td[align="center"] > table { margin: 0 auto !important }`.

Both took several test iterations to isolate (variants A/B/C/D in `/tmp/center_*.pdf`) before landing on the right rules. Both are now in `_BASE_CSS`, scoped to `.email-body-html` so they don't affect the cover page or appendix tables.

**80% stall.** WeasyPrint's `write_pdf()` is synchronous with no progress callback, so the progress bar sat at 80% for 10–15s during a 200-email render and looked frozen. Fix: when the WeasyPrint phase starts, send `{"indeterminate": true}`; the JS modal flips the bar to a pulsing-opacity animation and changes the status to "Composing PDF (N emails)… this can take a moment." Bar resumes determinate mode at 85% once render completes.

**Log noise from blocked images.** With remote loading off, WeasyPrint logs an ERROR for every blocked `<img src="https://...">` — hundreds of lines per export. Fix: temporarily raise the `weasyprint` logger to CRITICAL during the blocked render and restore it afterward. Real WeasyPrint failures still surface via the surrounding try/except.

### Files changed

- `core/pdf_export.py` (new)
- `web/blueprints/api/exports.py` (new)
- `web/blueprints/api/__init__.py` (registered `exports` blueprint)
- `web/static/js/components/export-modal.js` (new)
- `web/static/css/modules/export.css` (new)
- `web/static/css/main.css` (registered `export.css`)
- `web/static/js/components/context-menu.js` (folder menu calls `openExportModal`, label "Export…")
- `requirements.txt` (added `weasyprint>=60.0`, `pypdf>=4.0`)
- `docs/Bulk_Export_Plan.md` (Phase 1 status section appended)
- `docs/TESTING_CHECKLIST.md` (added export tests)

### Deferred

- Custom export filename (auto-generated names sufficient for now)
- TOC for >20-email exports
- Verbose headers option (full raw headers)
- Anchor-id collision sanitization (cosmetic warnings only)
- Phase 2: batch-select toolbar and search-results toolbar wiring
- Phase 3: AES-256 encrypted ZIP via pyzipper with one-time warning

---

## May 1, 2026 — Evening Session

**Participants:** Rick, Claude (Opus 4.7)

**Work Done:**

### Folder actions ⋯ button (sidebar discoverability)

Folder management has always been right-click only on the sidebar tree, which is poorly discoverable — users don't know the menu exists, and right-click on trackpads is awkward (control-click, two-finger tap, varies by system). Added a persistent affordance: a `⋯` button that appears on row hover (always visible on touch) and opens the same context menu, anchored below the button.

**Decision on drag-to-rearrange:** discussed but deferred. Users already control folder order via numeric prefix convention (`01`, `02`, …); adding drag would introduce a competing ordering mechanism plus significant complexity (drop target ambiguity, auto-expand timing, touch gestures, accessibility, schema changes). If reordering becomes a real need, "Move up / Move down" menu items would be the simpler next step.

**Changes:**

1. **`context-menu.js`** — Factored menu-build logic into private `_showFolderMenu(folderId, folder)`. Existing `showFolderContextMenu(e, …)` retains cursor-position behavior for right-click. New `showFolderContextMenuAtElement(e, anchorEl, folderId, folder)` opens the same menu anchored just below the button's left edge; viewport edge detection still applies.

2. **`sidebar.js`** — `createFolderTreeItem` now appends a `<button class="folder-actions-btn">` (Lucide `more-horizontal`) inside the row. Click handler stops propagation and calls `showFolderContextMenuAtElement` — propagation must be stopped or (a) the row's click handler navigates into the folder and (b) the document-level "click outside" listener immediately closes the menu.

3. **`sidebar.css`** — Button is `position: absolute` at the right edge of the row (not in flex flow), `opacity: 0` by default, fades to `opacity: 1` on `.tree-item-row:hover` or `:focus-visible`. `@media (hover: none)` makes it always visible on touch devices.

### Bug fixed: horizontal scrollbar in sidebar

First-pass implementation put the `⋯` button in the row's flex flow with `margin-left`, which widened every row by ~30px. Combined with `.tree-label { white-space: nowrap }` and `.section-content.expanded { overflow-x: auto }`, long folder names spilled past the container and triggered a horizontal scrollbar on the whole archive section.

Fix:
- `.folder-item > .tree-item-row` now uses `position: relative` with 32px right padding to reserve space for the button.
- `.folder-actions-btn` is `position: absolute` at `right: 6px`, vertically centered — out of the flex flow entirely, so it contributes no width.
- `.tree-label` got `overflow: hidden; text-overflow: ellipsis; min-width: 0` — long names truncate with `…` instead of pushing the row wider. This was actually a latent issue; the dots button only made it visible.

### Files Changed

- `web/static/js/components/context-menu.js` — Refactored to share menu-build logic; new `showFolderContextMenuAtElement` for anchored opening.
- `web/static/js/components/sidebar.js` — Added `⋯` button to folder rows; wired click with stopPropagation.
- `web/static/css/modules/sidebar.css` — Absolute-positioned button, label ellipsis, touch-device handling.
- `docs/TESTING_CHECKLIST.md` — 7 new test cases for the ⋯ affordance.

---

## April 30, 2026 — Evening Session

**Participants:** Rick, Claude (Opus 4.7)

**Work Done:**

### Search scope picker overhaul

The previous session added a folder-scope dropdown to the archive search, but used a native `<select>` that dumped every folder into a flat list with no way to navigate the tree. Replaced it with a proper folder picker.

**Changes:**

1. **Scope button instead of `<select>`** — Toolbar now has `[input] [Scope: All folders ▾] [Search] [Clear]`. The scope button shows the current scope label and tints when a specific folder is selected.

2. **Folder picker modal** — Clicking the scope button opens a modal with:
   - Filter input at the top (narrows the tree, auto-expands ancestors of matches)
   - "All folders" row to reset scope
   - "Include subfolders" checkbox (defaults on)
   - Recursive folder tree with expand/collapse, reusing the existing `renderFolderTree` component

3. **Include subfolders toggle** — Backend already searched folder + descendants when `folder_id` was passed. Added `include_subfolders` query param (defaults `true`); when `false`, only the chosen folder is searched. Frontend sends the param and reflects state in the scope label as `Folder/Path (only)`.

4. **Scope-aware helper text** — Initial search-view sentence now reads:
   - "…across your entire archive." (no scope)
   - "…in **Folder** and its subfolders." (folder + subs)
   - "…in **Folder** only." (folder only)
   
   Re-renders on scope change (when no results are showing) so the sentence stays accurate.

5. **Fixed Enter-to-search after first search** — The inline `onkeydown` attribute combined with `innerHTML` re-emission was leaving the input without focus after results rendered. Replaced with a real `addEventListener('keydown')` and added focus + caret-position preservation across re-renders so subsequent searches work without clicking back into the field.

### Bugs Fixed

- **Empty folder tree in picker** — Passing `filter: undefined` into `renderFolderTree` clobbered the component's default filter via object spread, leading to `state.folders.filter(undefined)` and an empty `rootFolders` array. Fixed by only setting `treeOptions.filter` when a filter function actually exists.

- **Stale "across your entire archive" copy** — Helper text claimed whole-archive scope even when a specific folder was selected. Now scope-aware.

### Files Changed

- `web/static/js/views/mail.js` — Scope button, picker modal, tree rendering, filter, subfolder toggle, scope-aware helper, focus preservation, Enter handler. Removed `buildFolderOptions`.
- `web/static/css/modules/content.css` — Scope button styles, picker modal styles, subfolder checkbox row styles. Removed `.search-folder-select`.
- `web/blueprints/api/emails.py` — Added `include_subfolders` query param to `/api/search`.
- `docs/TESTING_CHECKLIST.md` — New test cases for picker, subfolder toggle, scope-aware helper, multi-search Enter.

---

## February 4, 2026 — Afternoon Session (Session 31)

**Participants:** Rick, Claude (Opus 4.5)

**Work Done:**

### Manual Testing Begins (TESTING_CHECKLIST.md)

Nuked database and archive for fresh start. Began working through the testing checklist from the top.

**Sections tested:**
- First Run / Setup — ✅ all pass
- Accounts (IMAP) — ✅ added two accounts (NCF Mail, Personal Gmail), both connected

### Bug Fixes

1. **Modal z-index stacking** — Error modal appeared behind Add Account modal (both at z-index 1000). Fixed by setting alert/confirm/prompt modals to z-index 1100 in modals.css.

2. **CSS syntax error (critical)** — First z-index fix accidentally broke `.modal-overlay` base rule, removing `opacity: 0; visibility: hidden; transition`. All modals became visible on page load. Root cause: stray CSS line broke the parser, preventing `.modal-overlay.active` from ever taking effect. Fixed by restoring the complete rule.

3. **Dynamic sidebar account refresh** — Adding a second account in Settings didn't update the sidebar (server-rendered at page load, never refreshed). Added `refreshSidebarAccounts()` to sidebar.js that fetches from `GET /api/accounts` and rebuilds the accounts section. Wired up the existing `accountsChanged` custom event (already dispatched by settings.js, but nobody was listening).

### UX Improvements

- **Advanced settings collapse on modal open** — IMAP server settings `<details>` now collapses each time Add Account modal opens, instead of staying expanded from previous use.
- **Default font size changed to Small** — Updated both base.html and settings.js defaults from Medium to Small.
- **IMAP folder indentation** — Top-level IMAP folders now indent 12px under their account name in the sidebar, making the hierarchy clearer.

### Files Changed

- `web/static/css/modules/modals.css` — z-index stacking fix, CSS syntax repair
- `web/static/js/views/settings.js` — Collapse advanced settings, default font size
- `web/templates/base.html` — Default font size
- `web/static/js/components/sidebar.js` — `refreshSidebarAccounts()`, IMAP folder indent
- `web/static/js/app.js` — Import and wire up `accountsChanged` listener

**Status:** Testing in progress. First Run and Accounts sections complete. Next: Authentication, Email Browsing, Imports.

---

## February 4, 2026 — Morning Session (Session 30)

**Participants:** Rick, Claude (Opus 4.5)

**Work Done:**

### Pre-Release Security Audit

Comprehensive review of all security-critical code paths. Full results in `docs/Security_Audit.md`.

**Areas reviewed:**
- Encryption implementation (PBKDF2, Fernet, SQLCipher)
- Authentication flow (rate limiting, session timeout, CSRF)
- Database security (parameterized queries, WAL, foreign keys)
- API endpoint protection (auth enforcement, CSRF validation)
- IMAP credential handling (encrypted storage, SSL/TLS)
- File system operations (path traversal protection, size limits)
- Email archive security (encryption at rest, on-access decryption)
- Settings/reset safeguards (password + "RESET" confirmation)
- Backup/restore (WAL checkpoint, path validation)
- Configuration (secret key generation, file permissions)
- Frontend XSS protection (escapeHtml, sandboxed iframes, JSON API)

**Result:** No critical issues found. Minor observations documented (SESSION_COOKIE_SECURE=False for localhost, in-memory rate limiting, duplicate logger import). All acceptable for target deployment.

**Decision — Circular dependency:** staging.js ↔ folder-selection.js circular import acknowledged but not refactored. Works correctly, causes no bugs. Refactoring at ship stage would introduce risk without meaningful benefit.

### Documentation Update

- Created `docs/Security_Audit.md` — full audit results
- Rewrote `docs/Navigation_Map.md` — was badly out of date (Mac paths, Gmail OAuth references, old file structure). Now reflects actual codebase: ~20,100 lines of code across 76 source files (per cloc).
- Updated `docs/Session_Log.md` — this entry

**Status:** Ready for manual testing per TESTING_CHECKLIST.md.

---

## February 3, 2026 — Afternoon Session (Session 29)

**Participants:** Rick, Claude

**Work Done:**

### Security Review

1. **CSRF protection for API endpoints** (`461bf6b`)
   - Added CSRF token generation at login, stored in Flask session
   - Token embedded in `<meta name="csrf-token">` tag on every page
   - Extended existing fetch interceptor in base.html to auto-inject `X-CSRF-Token` header on all POST/PUT/DELETE/PATCH requests
   - Server validates token on all state-changing `/api/*` requests, returns 403 if missing or invalid
   - Uses `secrets.compare_digest` for timing-safe comparison
   - Zero changes to existing fetch calls (47 call sites covered automatically)

2. **Security review findings:**
   - **Email rendering (no action needed):** HTML emails rendered in sandboxed iframe with `allow-same-origin allow-modals` (no `allow-scripts`). CSP blocks remote content by default. "Load Remote Content" button allows images when user explicitly requests. This matches standard email client behavior.
   - **HTML sanitization (not added):** Considered server-side sanitization (bleach/nh3) but decided against it. The iframe sandbox already prevents JS execution, and sanitization could break legitimate email rendering. Desktop email clients (Thunderbird, Apple Mail) use the same sandbox approach.
   - **Flask secret key:** Already persisted to disk with 0o600 permissions ✓
   - **Session timeout:** Already implemented with configurable duration ✓
   - **Localhost binding:** Already bound to 127.0.0.1 only ✓

**Files Changed:**
- `web/app.py` — CSRF token generation and validation
- `web/templates/base.html` — Meta tag + fetch interceptor extension

**Commits:**
- `461bf6b` — Add CSRF protection for all state-changing API requests

---

## January 30, 2026 — Evening Session (Session 25)

**Participants:** Rick, Claude

**Work Done:**

### Bug Fixes

1. **Backup directory portability fix** (`e8105a3`)
   - Backups weren't being found after moving app from `/Users/rick/apps/mailrepo` to `/Users/rick/Applications/mailrepo`
   - Root cause: manifest.json stored absolute `backup_dir` path at backup creation time
   - Fix: Always use current `get_backups_dir()` instead of stored path from manifest
   - Affected functions: `list_backups()`, `get_restore_points()`, `cleanup_old_backups()`

2. **Double scrollbar on Backups page** (`afbe57c`, `770dfbb`)
   - Backups view was showing two scrollbars
   - Fix: Added CSS `:has()` rule to disable parent scroll when showing backups view

3. **Sidebar folder tree broken** (`770dfbb`)
   - Archive folders rendering with huge spacing, children appearing inline instead of below
   - Root cause: `backups-view.css` had global `.folder-item` rule with `display: flex`
   - Fix: Scoped all folder-item rules to `.folder-picker-container .folder-item`

### Logging Improvements

1. **Suppress polling log messages** (`afbe57c`, `8edf172`)
   - Added `PollingFilter` class to filter out noisy werkzeug logs
   - Suppresses: `/api/session-status`, `/api/keepalive`, heartbeat `HEAD /` requests
   - Also suppresses static file 304 responses

2. **Backup on shutdown with logging** (`1caa02d`)
   - Added shutdown handlers (SIGINT, SIGTERM) like EdgeCase
   - Checkpoints WAL before backup
   - Checks backup frequency setting to determine if backup needed
   - Prints "Backup completed: {filename}" to terminal
   - Runs post-backup command if configured

**Commits:**
- `e8105a3` — Fix: Always use current backups directory, not stored path from manifest
- `afbe57c` — Fix: Double scrollbar on Backups page, suppress polling log messages
- `1caa02d` — Add backup on shutdown with logging (like EdgeCase)
- `8edf172` — Suppress static file 304 responses and all polling status codes from logs
- `770dfbb` — Fix: Scope folder-item styles to backup picker only

**Status:** All backup and logging issues resolved. App is now portable (can be moved to different directory).

---

## January 27, 2026 — Morning Session (Session 19)

**Participants:** Rick, Claude

**Work Done:**

### Code Cleanup
- Removed all debug print statements from `progress.py` (10 statements)

### Destination Modal Polish
- Breadcrumbs now wrap to next line instead of horizontal scrolling
- Removed redundant back arrow button (breadcrumb links handle navigation)
- Added "Archive" root link to breadcrumbs, then removed it (root folders are distinct entities)

### Archive Folder Navigation Redesign
- Full breadcrumb trail in main view (e.g., "Client A > 2024 > Q1")
- Breadcrumbs only appear when in nested folders
- Replaced awkward subfolder pills with inline text links ("Subfolders: January, February, March")
- Design decision: Root folders are distinct archives; navigate between them via sidebar, not breadcrumbs

### IMAP Folder Navigation
- Added breadcrumbs + subfolder links to IMAP folder browsing (consistency with archive view)
- Fixed title to show folder name only, not full path (e.g., "Comfort King" not "Home/Comfort King")
- Fixed duplicate subfolder bug (was showing each folder twice)
- Fixed IMAP cache lookup bug (string/number accountId mismatch in Map key)

### Bug Fixes
- Fixed logout triggering browser's "Changes may not be saved" warning (added skip flag for intentional navigation)

### Verified
- Multi-account staging already works (emails from different accounts can be staged together)

### Code Review & Refactoring Plan
- Full codebase scan: ~12,000 lines total across Python + JavaScript
- Created `docs/Refactoring_Plan_V2.md` with prioritized improvements
- Key targets: split `progress.py` (1,202 lines), split `folder-mgmt.js` (1,200 lines), consolidate shared utilities
- Estimated 8-12 hours total work, non-blocking for release
- Discussion: MailRepo's "curated archive" model is the right scope; don't try to compete with corporate archiving software

**Commits:**
- `50a5f40` — UI polish: remove debug logging, breadcrumb wrapping, remove redundant back button
- `7e9764c` — Add full breadcrumb trail to archive folder navigation
- `dd4ccd9` — Replace subfolder pills with inline links, remove Archive root from breadcrumbs
- `3cdfb96` — Fix: Skip beforeunload warning on logout
- `35aabf6` — Update docs for Session 19
- `72c401d` — Add IMAP folder breadcrumbs and subfolder navigation (matches archive view)
- `6f1e7c0` — Fix: Remove duplicate subfolder detection in IMAP navigation
- `0b0ab2b` — Fix: IMAP navigation cache lookup with string/number accountId

**Status:** Navigation consistency complete. Refactoring plan documented. Ready for next session.

**Next Session:** Review refactoring plan (docs/Refactoring_Plan_V2.md) or continue with feature work.

---

## January 26, 2026 — Afternoon/Evening Session (Session 16)

**Participants:** Rick, Claude

**Work Done:**

### Features Implemented

1. **Grey out staged folders** (`bda9a6d`)
   - Folders already staged now appear greyed out with disabled checkboxes in folder selection view
   - Matches existing behavior for staged emails (visual consistency)

2. **ZIP export for archive folders** (`719291b`, `fa7efcc`)
   - Full implementation of folder export feature
   - Backend endpoint decrypts `.eml.enc` files on the fly
   - Builds ZIP with folder structure preserved
   - Sanitizes filenames and handles duplicates
   - Added download icon button to each folder row in Manage Folders view
   - Fixed SQLCipher Row object `.get()` compatibility issue

### Folder Selection UI Redesign
- Replaced checkboxes with select/clear icon buttons per folder
- Added "Select All", "Clear Selected", and "Stage (N)" toolbar buttons
- Fixed selection state persistence (was being cleared on refresh)
- Fixed scroll position reset after staging/selecting
- Fixed onclick handlers breaking with special characters in folder paths (escapeForOnclick helper)

### Email List UI Redesign
- Redesigned to match folder selection pattern - table-style layout
- Added same toolbar buttons (Select All, Clear Selected, Stage)
- Action buttons aligned to right in Actions column
- Removed search bar from toolbar

### Commit Logic Review
- Confirmed full folder path preservation works correctly
- Both `staging.py` and `progress.py` use the same approach - creates full hierarchy under destination

### Sidebar/Navigation Cleanup
- Removed Import button from left rail
- Replaced "New Folder" button in sidebar with "Import" button
- Import button now last item in sidebar (after Imports section)
- Welcome message restored to original (links to Settings for adding accounts)

### CSS Fixes
- Fixed email list grid column alignment with increased specificity
- Added inline-icon class for icons in links

**Commits:**
- `bda9a6d` — Fix: Grey out already-staged folders in folder selection view
- `719291b` — Add: ZIP export for archive folders
- `fa7efcc` — Fix: SQLCipher Row object doesn't support .get() in ZIP export
- `148ac47` — Change: Selecting a parent folder now auto-selects all children
- `6a11ac4` — Remove dead checkbox-based folder selection code
- (additional commits for UI redesign work)

**Status:** ZIP export working. Folder selection now cascades to children. Dead code removed (~115 lines).

---

## TODO Before Release

- [x] ~~**Migrate to SQLCipher**~~ ✅ Done Jan 21, 2026
- [x] ~~**Implement full-text search**~~ ✅ Done Jan 21, 2026 (FTS5)
- [x] ~~**Consolidate database migrations**~~ ✅ Schema v3 is now the base
- [ ] **Unstage emails** — Click staged rail button to view/manage staged emails
- [ ] **Archive folder management** — Rename, delete, create subfolders in Settings
- [ ] **Attachments** — View/download attachments from emails
- [ ] **Archived email operations** — Move, delete, export as .eml
- [ ] **Import UI** — File picker for .eml and .mbox import (backend ready)
- [ ] **ZIP export** — Export folders as unencrypted ZIP

---

## January 21, 2026 — Afternoon Session (Continued)

**Participants:** Rick, Claude

**Work Done:**

1. **Cloned repo to Mercury (Linux dev machine):**
   - Set up development environment on Mercury ThinkPad
   - Configured git user for commits
   - All dependencies installed including SQLCipher

2. **UI/UX improvements for Add Account flow:**
   - Removed redundant "Connect Gmail Account" button from main view
   - Added `?accounts` URL parameter to auto-expand Email Accounts section
   - Replaced Google "Learn more" link with app-specific password info modal
   - Cleaned up import dropdown (removed old encrypted emoji references)

3. **Fixed button styling:**
   - Fixed `a.btn` elements getting link underline on hover
   - Changed btn-secondary text color from muted to normal for better visibility

4. **Dark mode fixes:**
   - Fixed theme switching to update both `<html>` and `<body>` elements
   - Replaced hardcoded `white` backgrounds with CSS variables in settings.css
   - Fixed theme swatch borders in dark mode
   - Decided to keep theme/font selector cards light for consistent swatch visibility

5. **New theme system - 5 themes:**
   - Renamed Teal → **Lagoon** (`#1F8F74`)
   - Renamed Slate → **Graphite** (`#475569`)
   - Renamed Dark → **Midnight** (`#1e1e2e`)
   - Added **Bloom** (`#3B6EA5`) - muted navy blue
   - Added **Rose** (`#A65568`) - dusty rose
   - Inspired by Zoom's theme naming (Bloom, Agave, Rose, Classic)

**Commits:**
- `2ce9c2a` — Improve add account UX and remove Gmail-specific references
- `01e21fc` — Fix dark mode theme switching
- `2c23258` — Fix theme/font option swatches in dark mode
- `d2dc810` — Fix theme swatch borders in dark mode
- `ce8cf27` — Remove shadow/border from theme swatches in dark mode
- `2d58cde` — Fix dark mode CSS variable specificity
- `17b225e` — Keep theme/font selectors light for consistent swatch visibility
- `4a6ccb5` — Add Bloom and Rose themes, rename existing themes

**Status:** Development environment working on Mercury. Theme system expanded with 5 professional themes.

---

## January 21, 2026 — Afternoon Session

**Participants:** Rick, Claude

**Work Done:**

1. **Migrated to SQLCipher for full database encryption:**
   - Replaced standard SQLite with SQLCipher (`sqlcipher3` package)
   - Database now fully encrypted at rest using master password
   - Added `_derive_db_key()` in encryption.py for separate DB key derivation
   - Database initialization deferred until after authentication

2. **Implemented FTS5 full-text search:**
   - Added `messages_fts` virtual table for subject, sender, body_text
   - Created triggers to keep FTS index in sync with messages table
   - Added `extract_body_text()` helper to parse email content for indexing
   - Added `/api/search` endpoint for searching archived emails

3. **Removed per-folder encryption choice:**
   - All emails now encrypted (database + files)
   - Removed `encrypted` column references throughout codebase
   - Simplified folder creation UI (no encryption radio buttons)
   - Updated `create_archive.html` with security note instead

4. **Schema updated to v3:**
   - Added `body_text` column to messages table
   - Migration path from v2 preserved for existing installs
   - Fresh installs get complete schema with FTS

5. **Updated documentation:**
   - README.md rewritten with current feature set
   - Session_Log.md updated with completed TODOs

**Files Changed:**
- `core/database.py` — SQLCipher support, FTS5 schema, v3 migration
- `core/encryption.py` — Added `_derive_db_key()` and `get_db_key()`
- `core/importer.py` — Removed encrypted parameter (always encrypt)
- `web/app.py` — Deferred DB init until after auth
- `web/blueprints/auth.py` — Init DB after login/setup
- `web/blueprints/api.py` — Removed encrypted refs, added search endpoint
- `web/blueprints/main.py` — Removed encrypted handling
- `web/templates/main/index.html` — Removed lock icons from folder list
- `web/templates/main/create_archive.html` — Replaced encryption choice with security note
- `web/static/css/shared.css` — Added security-note styling
- `requirements.txt` — Added sqlcipher3
- `README.md` — Complete rewrite

**Commits:**
- `9f136c6` — Migrate to SQLCipher for full database encryption

**Status:** Core security model complete. Database and all emails encrypted at rest. Full-text search working.

---

## January 20, 2026 — Evening Session (~9:00 PM)

**Participants:** Rick, Claude

**Work Done:**

1. **Fixed beforeunload warning:**
   - "Review & Commit" button was triggering "Are you sure you want to leave?" alert
   - Fixed by removing the listener before intentional navigation

2. **Fixed sidebar folder update:**
   - Creating folder from stage modal now updates sidebar immediately
   - Added `updateSidebarFolders()` function

3. **Redesigned Review page:**
   - Now uses three-pane layout consistent with main view
   - Shows actual account names instead of "Account 2"
   - Fixed date formatting (was showing "Invalid Date")
   - Fixed checkbox alignment
   - Replaced native select with custom icon-select dropdowns for "After commit" action

4. **Added duplicate detection:**
   - Checks Message-ID before archiving
   - Skips emails already in destination folder
   - Shows "X skipped (already archived)" in results

5. **Added archive email viewing:**
   - Click archive folder → loads archived emails
   - Click archived email → opens viewer with decrypted content
   - Added `/api/folders/<id>/emails/<id>` endpoint

6. **Fixed JSON serialization error:**
   - SQLite Row objects weren't JSON serializable for accounts data
   - Convert to dicts before passing to template

**Commits:**
- `12ada1e` — Fix: disable beforeunload warning when navigating to Review page
- `f9a64f7` — Update sidebar when creating folder from stage modal
- `43fd722` — Redesign Review page: three-pane layout, account names, fix date/alignment, custom dropdowns
- `5f84dc1` — Add duplicate detection - skip emails already in destination folder
- `0f50dbc` — Fix: convert Row objects to dicts for JSON serialization in review page
- `e0f4b48` — Add ability to view archived emails with decryption support

**Discussion — Security & Search:**
- Identified that subject/sender are stored unencrypted in SQLite — security gap
- Discussed full-text search options; FTS5 needs plaintext which conflicts with encryption
- Decision: Migrate to SQLCipher for full database encryption, then implement FTS5 inside the encrypted DB
- This maintains security promise while enabling full content search

**Status:** Core archiving workflow complete and tested. Security enhancement (SQLCipher) is next priority.

---

## January 20, 2026 — Afternoon Session (~2:00 PM)

**Participants:** Rick, Claude

**Work Done:**

1. **Fixed IMAP folder selection bug:**
   - Folder names with spaces (e.g., "Rabbit Vets") failed with parse error
   - Root cause: IMAP SELECT command requires quoted folder names
   - Fix: Changed `self.connection.select(folder)` to `self.connection.select(f'"{folder}"')` in `core/imap.py`

2. **Added horizontal scroll to sidebar:**
   - Long folder names now scrollable instead of truncated
   - Updated `.section-content` to `overflow-x: auto`

3. **Improved account selection UX:**
   - Clicking account name now auto-selects INBOX (previously just expanded/collapsed)
   - More intuitive - one click to see your mail

**Commits:**
- `48e810e` — Fix IMAP folder quoting for names with spaces
- `64fcb0c` — Add horizontal scroll to sidebar for long folder names
- `4f0e6b6` — Auto-select INBOX when clicking account name

**Status:** All fixes complete. Ready for continued testing.

---

## January 20, 2026 — Lunch Session (~12:00 PM)

**Participants:** Rick, Claude

**Work Done:**

1. **Replaced Gmail OAuth with IMAP:**
   - Deleted `core/gmail.py`
   - Created `core/imap.py` — full IMAP client with connection, auth, folder listing, email fetching
   - Created `core/importer.py` — mbox and .eml import functionality
   - Updated `api.py` — all Gmail endpoints replaced with IMAP + import endpoints
   - Removed Google dependencies from `requirements.txt`

2. **Updated Settings Page for IMAP:**
   - IMAP credentials form instead of OAuth
   - Auto-detect server from email domain
   - Added import section for .mbox and .eml files
   - Replaced all browser `alert()` and `confirm()` with styled modals

3. **Fixed Main View for IMAP:**
   - Changed "labels" to "folders" throughout
   - Updated folder loading to use IMAP folder list
   - Fixed email ID handling (uid vs id)

4. **Added Folder Caching:**
   - Database migration v1→v2: added `cached_folders` and `cached_folders_at` columns
   - Cache folder list for 1 hour, return stale cache on connection errors
   - First load slow, subsequent loads instant

5. **Added Email Viewer:**
   - Slide-out panel when clicking on an email
   - Displays full headers, text/HTML body, attachment list
   - HTML content rendered in sandboxed iframe

**Commits:**
- `cf5fdda` — Replace Gmail OAuth with IMAP, add mbox/eml import, styled modals
- `5209eb3` — Fix IMAP folder loading in main view
- `2e2a37e` — Add folder caching, email viewer panel

**Status:** IMAP working, folder caching in place, email viewer functional. Ready for testing.

---

## January 19, 2026 — Evening Session (~9:30 PM)

**Participants:** Rick, Claude

**Work Done:**

1. **Settings Page Polish:**
   - Made About modal logo larger (240px), removed redundant "MailRepo" text
   - Tightened About modal spacing
   - All settings sections start collapsed

2. **Simplified Appearance Options:**
   - Reduced themes from 5 to 3: Teal (default), Slate, Dark
   - Removed Plum and Amber themes (too bright, not adding value)
   - Reduced fonts from 5 to 3: Lexend, Libre Baskerville, Source Sans
   - Removed Lora and Literata fonts
   - Updated font sizes to match Synesius: S=16px, M=18px, L=20px

3. **Major Refactoring — Extracted Inline CSS/JS:**
   - `settings.html`: 916 → 240 lines (extracted to `settings.css` + `settings.js`)
   - `review.html`: 654 → 69 lines (extracted to `review.css` + `review.js`)
   - Deleted 6 unused font files (Lora-*.ttf, Literata-*.ttf)
   - Removed dead theme code from `themes.css`
   - Removed dead font declarations from `shared.css`

4. **Final Codebase Stats:**
   - All templates under 250 lines (clean HTML only)
   - CSS/JS properly separated into static files
   - No dead code remaining

**Commits:**
- `61886c2` — Simplify appearance settings
- `e4d8e76` — Start with all sections collapsed  
- `964c237` — Refactor settings.html
- `2459638` — Refactor review.html

**Status:** Codebase is clean and well-organized. Ready for next phase of work.

---

## January 18, 2026 — Late Evening Session (~10:00 PM)

**Participants:** Rick, Claude

**Work Done:**

1. **Created `core/gmail.py`** — Complete Gmail API integration module:
   - OAuth flow with `InstalledAppFlow`
   - Encrypted credential storage
   - Token refresh handling
   - Email listing and fetching
   - Message operations (archive, trash, delete, move)
   - Raw RFC 2822 download for .eml export

2. **Updated `web/blueprints/api.py`** — Added working Gmail endpoints:
   - `POST /api/accounts` — Create account record
   - `POST /api/accounts/<id>/authorize` — Run OAuth flow
   - `GET /api/accounts/<id>/emails` — Fetch emails from Gmail
   - `GET /api/accounts/<id>/labels` — Get Gmail labels
   - `DELETE /api/accounts/<id>` — Remove account
   - Updated `POST /api/commit` — Downloads emails, encrypts if needed, saves to archive, executes source actions

3. **Updated `core/__init__.py`** — Export Gmail classes

4. **Created `web/templates/main/review.html`** — Full review page:
   - Displays staged emails grouped by source account
   - Inline destination folder dropdown
   - Per-account "after commit" action dropdown (leave/archive/trash/delete)
   - Progress modal during commit
   - Results modal with success/failure counts
   - Retry failed button

5. **Updated `web/blueprints/main.py`** — Added `/review` route

**Status:** The app is now functionally complete for the core workflow:
- ✅ Password setup and login
- ✅ Create encrypted/unencrypted folders
- ✅ Connect Gmail via OAuth
- ✅ Browse inbox
- ✅ Stage emails to folders
- ✅ Review staged emails
- ✅ Commit (download, encrypt, save, update Gmail)

**Still TODO:**
- Settings page UI improvements
- .mbox import
- ZIP export
- Polish and testing

---

## January 18, 2026 — Evening Session (~9:30 PM)

**Participants:** Rick, Claude

**New Decisions:**

1. **First-run flow:** After master password setup, take users to a "Create an Archive" page before anything else. Forces a deliberate decision about folder structure.

2. **Encrypted vs. unencrypted folder trees:** Users can create either encrypted or unencrypted root folders. Encryption flag is set at folder creation and inherited by all children. Use case: personal emails/newsletters don't need encryption overhead.

3. **ZIP export:** Allow users to export entire archives or selected folder trees as unencrypted ZIP files. Decrypts .eml.enc files on the fly. Essential for portability and "your data, your control" promise.

4. **Password always required:** Even if user only has unencrypted folders, master password is still required on startup. Rationale: OAuth tokens are always encrypted, so password is needed regardless.

**Code Discovery:**

Realized significant code already exists from previous sessions:
- Flask app structure complete (`main.py`, `web/app.py`)
- Core module done (`config.py`, `database.py`, `encryption.py`)
- Auth blueprint working (setup, login, logout)
- Main blueprint started (index, create_archive, settings)
- Database schema implemented (accounts, folders, messages, settings tables)
- Templates exist but need UI work

**Housekeeping:**

- Updated Navigation_Map.md to reflect actual code state
- Created Session_Log.md for context recovery

---

## Previous Sessions (Date Unknown)

**What Was Built:**

1. **Core infrastructure:**
   - `core/config.py` — Paths, constants, FlaskConfig class
   - `core/database.py` — SQLite connection, schema creation, migration support
   - `core/encryption.py` — Fernet encryption, PBKDF2 key derivation, password verification

2. **Flask app:**
   - `main.py` — Entry point, runs on port 5050
   - `web/app.py` — Factory pattern, blueprint registration, auth middleware
   - `web/blueprints/auth.py` — `/auth/setup`, `/auth/login`, `/auth/logout`
   - `web/blueprints/main.py` — `/`, `/archive/create`, `/settings`
   - `web/blueprints/api.py` — API endpoints (contents not verified)

3. **Templates:**
   - `base.html` — Base layout
   - `auth/setup.html` — Password setup
   - `auth/login.html` — Login form
   - `main/index.html` — Main dashboard
   - `main/create_archive.html` — First-run folder creation

4. **Static assets:**
   - `css/shared.css`, `css/main.css`
   - `js/main.js`
   - `fonts/` directory

---

## January 18, 2026 — Afternoon Session

**Participants:** Rick, Claude

**Topic:** UI design deep-dive

**Key Decisions:**

1. **Stage → Review → Commit workflow:** 
   - Browse emails, check boxes, click "Stage" to pick destination folder
   - Staged emails grey out but stay visible
   - Can stage from multiple accounts/folders before reviewing
   - Review page shows all staged emails grouped by source
   - Can change destinations or unstage before committing
   - Per-source-folder dropdown: what to do with originals after commit (leave, archive, trash, delete, move)

2. **Navigation warning:** If user tries to navigate away with staged emails, show warning modal with options to clear selections or stay.

3. **Folder creation mid-flow:** "+ New Folder" option in folder picker modal. Opens nested modal to name folder and choose encrypted/unencrypted. Returns to picker with new folder selected.

4. **Error handling on commit:** Continue on individual failures, show summary ("47 filed, 3 failed"), keep failed emails staged for retry.

5. **Archive view:** Accessed via "Archive" option in account dropdown. Shows folder tree and archived emails. Can view, download, print, re-file, or delete.

6. **.mbox import (not .pst):** Rick's existing archive is .mbox format. Python stdlib `mailbox.mbox()` makes this trivial—no external dependencies.

7. **Responsive design from the start:** Reuse EdgeCase/Synesius CSS patterns.

**UI Inspiration Sources:**
- EdgeCase: `/Users/rick/apps/edgecase/web/static/css/shared.css`
- Synesius: `/Users/rick/apps/synesius/web/static/css/shared.css`

---

## January 16, 2026 — Initial Planning

**Participants:** Rick

**Created:** Original project plan

**Initial scope:** Gmail-only MVP, encrypted local archive, simple filing UI, search, multi-account support.

---

## Open Questions (None Currently)

All major design decisions have been resolved. Ready to continue building.

---

## What's Next to Build

1. ~~Test IMAP workflow end-to-end~~ ✅ Working!
2. ~~Viewing archived emails~~ ✅ Working!
3. **Migrate to SQLCipher** — Full database encryption (security priority)
4. **Full-text search** — FTS5 indexing inside encrypted DB
5. **Unstage emails** — Click staged rail button to view/manage staged emails, unstage individually or clear all
6. **Archive folder management** — In Settings: rename, delete, create subfolders (parent_id already exists)
7. **Attachments** — View/download attachments from emails (server and archived)
8. **Archived email operations** — Move, delete, export as .eml, print (open in new window)
9. Import UI for .eml and .mbox files (backend ready in `core/importer.py`)
10. ZIP export for folders

---

## Terminology

- **Archive** — The root container; the entire local email archive system
- **Folder** — Top-level container within the archive (e.g., "Client: Smith", "Personal")
- **Subfolder** — Nested folder within a folder (e.g., "2024", "Litigation")
- **Stage** — Select emails to be included in the next commit (Git analogy)
- **Commit** — File staged emails to the archive permanently

---

## Parking Lot (Future Ideas)

- **Import folder structure options:**
  - Import multiple .mbox files, mirror as folder tree
  - Parse folder hints from headers (X-Mozilla-Status, etc.) to auto-suggest structure
  - Bulk .eml import from directory with folder mirroring
- Auto-suggest folders based on sender/subject patterns
- AI categorization
- EdgeCase integration (link folders to client files)
- Encrypted backup export (keep .eml.enc intact)

---

## Session 31 — February 5, 2026

**Focus:** Code quality cleanup and IMAP bug fixes

### Code Quality (-122 lines net)
- Deduplicated `decode_header_value` — 3 inline copies in filesystem.py removed, all use `decode_email_header` from email_parser.py
- Extracted `_save_email_to_archive()` and `_check_duplicate()` in commit.py — shared across all 4 commit functions (IMAP email, import email, IMAP folder, import folder)
- Removed double fetch in `commit_imap_folder()` — was calling both `fetch_full()` and `fetch_raw()`, now uses only `fetch_raw()` + `parse_email_metadata()`
- Fixed N+1 query pattern in `search_emails()` — builds folder path map from single query instead of per-result parent chain walking
- Fixed colon-in-folder-name edge case in `_find_action_for_source()`
- Added explanatory comment for in-memory rate limiting design choice in auth.py

### IMAP Bug Fixes
- **\Noselect folder support** — Parse `\Noselect` flag from IMAP LIST response. Virtual containers like `[Gmail]` now expand children instead of throwing "Failed to select folder" error. Handled in sidebar and folder-selection views (dimmed appearance, no action buttons).
- **Ghost deleted emails** — Changed default IMAP search from `ALL` to `NOT DELETED` to filter messages flagged for deletion but not yet expunged. (Gmail ghost email turned out to be a server-side sync issue unrelated to this flag.)
- **Folder cache invalidation** — Cache auto-invalidates when cached data is missing the new `noselect` field, ensuring one-time migration.

### Deferred
- filesystem.py os.path → pathlib conversion (cosmetic, low risk-reward)
- filesystem.py module split (741 lines, manageable as-is)
- Database class-level state refactor (testability only, no functional impact)

### Commits
- `2af76f6` — Code quality cleanup: DRY violations, N+1 queries, edge cases
- `622ae83` — Handle IMAP \Noselect folders (e.g. [Gmail] container)
- `f37923b` — Filter out deleted ghost messages from IMAP search results
- `b5bd662` — Invalidate folder cache when missing noselect field


---

## Session 31 (continued) — February 5, 2026

**Focus:** Database reset bug fixes (MacBook Air M4)

### Database Reset Fixes
- **Missing .secret_key cleanup** — `reset_database()` now deletes Flask session key file in addition to salt, database, archives, and backups
- **Segfault on reset** — Removed `Encryption.lock()` call from reset handler; clearing SQLCipher's in-memory key during response processing caused segfault in the C extension. Keys are naturally replaced on next password setup.
- **Stale data diagnosis** — "file is not a database" error was caused by new `.salt` (from aborted first-run) paired with old `mailrepo.db` (encrypted with different salt). Fix: delete mismatched database file.

### Commits
- `5d37375` — Fix database reset: delete .secret_key and lock encryption
- `bb20719` — Fix segfault on database reset: don't lock encryption mid-request


---

## Session 32 — February 6, 2026

**Focus:** UI fix, cross-project security audit

### UI Fix
- Progress bar count text ("61 of 62") was clipped top/bottom when displayed inline beside the bar. Moved count to its own line below the bar. Single source: progress.js component handles all progress bars with counts.

### Cross-Project Security Audit
Checked MailRepo against 5 bugs found in Synesius:
1. ✅ `verify_password` — Uses Fernet-encrypted verification token, not just SQLCipher open test
2. ✅ `change_password` — Full rekey: re-encrypts .eml.enc files, IMAP credentials, PRAGMA rekey, updates verification token
3. ⚠️ **Session race condition — FIXED.** Login didn't set `last_activity` or clear stale session. Safari/Firefox could redirect back to login after successful auth.
4. ✅ Hardcoded secret key — Auto-generates to `.secret_key` with 0o600 permissions
5. ✅ Copy-paste artifacts — Clean

### Session Race Condition Fix
- `session.clear()` before setting new session values on login
- Set `last_activity` and CSRF token during login (not just in before_request)
- `make_response()` for explicit cookie handling on redirect
- `SESSION_COOKIE_NAME = 'mailrepo_session'` to prevent localhost collision
- Applied to both login and first-run setup flows

### Commits
- `fa2687a` — Fix clipped text in progress bar count
- `20ae895` — Fix session race condition on login (Safari/Firefox double-login bug)


---

## Session 34 — February 8, 2026 (Mercury)

### Testing: Search, Batch Ops, Trash, Backup/Restore

**Search fixes:**
- Body text not indexed for HTML-only emails — refactored extract_body_text to prefer HTML-derived text
- Added /api/search/reindex endpoint to rebuild FTS for existing emails
- All search tests pass

**Sort options added:**
- Icon button dropdown for email lists (date, sender, subject)
- Applied to archive folders, IMAP folders, and Trash views
- Replaced native select in Trash with consistent icon dropdown

**Bugs fixed:**
- Trash folders empty state showing "No folders match ''" with no search query
- Custom select dropdown going off-screen — auto-flip based on viewport space
- Restore modal not appearing (toggling `hidden` class instead of `active`)
- `complete_restore()` never called on startup — wired into main.py
- Cancel Restore triggering unsaved settings warning
- Restore modal button alignment (wrong CSS class)
- Shortened "Select All" to "All" for toolbar space

### Commits
- `bb85ac7` — Fix search not finding email body text (HTML preference, reindex endpoint)
- `9035e95` — Add sort options to email list (date, sender, subject)
- `71d4e67` — Shorten Select All button label to All
- `b863783` — Replace native sort select with icon dropdown in Trash view
- `47e950f` — Fix Trash folders empty state showing search message with no query
- `742ee86` — Auto-flip custom select dropdown when near screen edge
- `754d6c8` — Fix restore modal not appearing (wrong class toggle)
- `4d58e41` — Wire up restore execution on server startup
- `683e0bd` — Fix cancel restore triggering unsaved settings warning
- `3300a4c` — Fix restore modal button alignment (modal-buttons -> modal-actions)



---

## Session 35 — February 11, 2026 (Mercury)

### Feature: Retention Vault

Implemented folder-level retention system for compliance workflows. Folders can be moved to a "vault" with a future deletion date, then permanently deleted after review when overdue.

**Database:**
- Added `retention_date` column to folders table (Unix timestamp, NULL = normal archive)
- Added index `idx_folders_retention` for vault queries

**Backend API (6 endpoints):**
- `GET /api/folders/vault` — List vault folders with email counts and overdue status
- `GET /api/folders/vault/overdue-count` — Badge count for left rail
- `POST /api/folders/{id}/vault` — Move folder tree to vault with retention date
- `POST /api/folders/{id}/vault/restore` — Restore folder tree from vault
- `DELETE /api/folders/{id}/permadelete` — Permanently delete overdue folder
- `POST /api/folders/batch-permadelete` — Batch delete overdue folders

**Frontend:**
- Date picker component (ported from EdgeCase) with year/month/day grid navigation
- "Move to Vault" modal with date picker and preset buttons (1/3/5/7/10 years)
- Vault view with grid layout matching Trash view styling
- Restore modal with folder destination picker
- Overdue alert banner (mail view only)
- Vault badge in left rail showing overdue count

**UI Polish:**
- Vault icon positioned before Trash in left rail (logical flow: archive → vault → trash)
- Alert banner only shows on mail view, not Settings/Trash/etc.
- Modal width increased to prevent calendar clipping

### Commits
- `8c7f2dc` — Add Retention Vault feature (database, API, frontend, UI)
- `0a92a23` — Align Vault view styling with Trash view
- `38f96a7` — Fix duplicate overdueCount declaration in vault.js
- `91fd117` — Move Vault icon before Trash in left rail


---

## Session 36 — May 29, 2026 (MacBook)

### Crypto Refactor: v1 → v2 (PBKDF2/Fernet → Argon2id/AES-256-GCM)

Replaced the original PBKDF2 + Fernet encryption stack with a modern
Argon2id + AES-256-GCM + HKDF setup. Designed for forward-migratability
(per-file version byte, HKDF info strings include version) so a future
v3 can ship the same way without touching v2 files.

**Crypto stack:**
- Argon2id KDF replacing PBKDF2 (memory-hard, post-quantum-friendlier)
- AES-256-GCM AEAD replacing Fernet (authenticated, faster)
- HKDF with version-tagged info strings for forward isolation
- New per-file salt magic `MRC2` (was `MRC1`) and version byte `0x02`
- v3 forward path: `MRC3` / `0x03` / `.v3` HKDF info — cryptographically
  distinct keys even if the master password collides across versions

**Migration architecture:**
- Two-phase walk: Phase 1 rekeys the SQLCipher database; Phase 2 walks
  every file on disk, decrypts with v1, re-encrypts with v2.
- Marker-file resumability so interrupted migrations resume from the
  last completed file rather than starting over.
- Migration exclusivity flag on the DB to prevent concurrent migrations.
- New thread-safety RLock around DB ops (paired with the migration flag).
- SSE-based progress streaming with unlock-resume detection.
- Banner + modal UI during migration showing Phase 1/2 progress.

**Production migration:**
- 1,648 files migrated successfully on Rick's archive.
- Zero corruption, zero data loss, full round-trip verified.

**v2-native password change:**
- Replaced the old in-place rekey with a v2-native flow.
- Logout-modal during post-change backup (the rekey produces a new DB,
  and the backup of the post-change state takes long enough that
  blocking the UI is the right behavior).

### Commits
- `e59ca2b` — Encryption: dual v1/v2 class with Argon2id + AES-256-GCM
- `cdd5229` — Crypto plan: fold DB threading lock into scope
- `076f3db` — Database: thread-safety lock + migration exclusivity flag
- `b7db944` — Migration: two-phase v1->v2 crypto migration module
- `39e0ce2` — Migration: SSE blueprint + unlock-resume detection
- `944b0aa` — Migration UI: banner + modal + Phase 1/2 progress
- `3f0e67a` — Password change: v2-native flow + logout-modal post-change


---

## Session 37 — May 30, 2026 (MacBook)

### v1 Cleanup, 1.0 Ship, Post-1.0 Setup, Frontend Cleanup Start

The day MailRepo shipped 1.0 (feature-complete, dogfooding before tag).
Three threads: strip the v1 crypto paths now that v2 is production,
set up the post-1.0 infrastructure, and start a parallel cleanup pass
on the frontend that runs into Session 38.

**v1 cleanup (-2,334 lines):**
- Stripped Fernet + PBKDF2 from `core/encryption.py` (dual-class became
  v2-only).
- Deleted the migration module, blueprint, banner, modal, and SSE
  endpoint — all the v1->v2 scaffolding from Session 36.
- v1 migration code preserved in git history at `353ae2f` as a
  reference template if/when a future v3 migration ships.

**Backup UX fixes + 1.0 ship:**
- Backup state UI polish (clearer "last backup" formatting, status
  badge colors).
- Declared the 1.0 feature set complete.
- Decision: dogfood for an unspecified period before `git tag v1.0.0`.

**Post-1.0 infrastructure:**
- Created `docs/Post_1_0_Backlog.md` from items deferred during the
  road-to-1.0 push.
- Removed `docs/Future_Backup_Refactor.md` (the backup state externalization
  had already been implemented; the planning doc was obsolete).
- Struck the phantom "Future_Backup_Refactor" entry from the backlog.

**Backlog items closed during the session:**
- Item 1: split `progress.py` (1,114 lines → 61 lines main + 3 focused
  modules: streams, state, handlers).
- Item 2: 15 unit tests for `core/password_change.py` (test count
  53 → 68).
- Item 4: created `CHANGELOG.md` (Keep a Changelog format), archived
  legacy plan docs to `docs/archive/`, fixed `.gitignore`.

**Frontend cleanup pass — start:**
- Built `web/static/js/delegate.js` — the `bindActions(container,
  handlers, eventTypes)` helper that the whole pass uses. Event-to-
  attribute map: click→data-action, input→data-input, change→data-change,
  submit→data-submit, keydown→data-keydown. Uses
  `closest('[data-${attr}]')` to resolve nested clickables.
- Converted `starred.js` (1st file). Established the per-view-root
  binding pattern.
- Converted `trash.js` (2nd file). Refined the pattern after a cross-
  talk bug: binding on shared parents caused multiple views'
  handlers to fire on the same elements. Fix: bind on view-specific
  child wrappers (`.starred-view-root`, `.trash-view-root`) so the
  listener dies with the view when innerHTML is replaced.

### Commits
- `9337954` — v1 cleanup pass: strip Fernet/PBKDF2 + delete migration
- `85fc21d` — Backup UX fixes + Session_Log: ships 1.0
- `8efb8be` — Post-1.0: README crypto refresh + Post_1_0_Backlog.md
- `75b1cca` — Backlog: strike phantom Future_Backup_Refactor entry
- `2a9f880` — Cleanup: split progress.py into three focused modules
- `5fdf7f1` — Add unit tests for core/password_change.py (15 tests)
- `0ff4c67` — Item 4: CHANGELOG.md + docs/ archive cleanup + .gitignore fix
- `0da63d9` — Frontend cleanup: delegation helper + starred.js (1st)
- `650e1c1` — Frontend cleanup: trash.js (2nd) + binding pattern refined


---

## Session 38 — May 31, 2026 (MacBook)

### Frontend Cleanup Pass — Complete

Picked up the frontend cleanup pass started in Session 37 and ran it
to completion. Goal: replace every inline `onclick="..."` and every
`window.X = X` cross-module dispatch with delegated `data-action` /
`data-tpl-action` handlers backed by ES imports. Eleven files
total — the remaining nine views/components plus a final index.html
template pass.

**Views/components converted (9 of 11 this session):**
- `export-modal.js` (3rd) — was already addEventListener-based; just
  cleaned the `window._export` singleton to module-local state and
  dropped `window.openExportModal`.
- `review.js` (4th) — 5 window exports + 6 inline handlers. Deleted
  dead `unstageSource` along the way.
- `folder-mgmt.js` (5th) + `context-menu.js` caller simplification.
- `settings.js` (6th) — 10 window exports, 7 inline handlers. Kept 3
  on window pending the template batch.
- `folder-selection.js` (7th) — 11 window exports, 16 inline handlers.
  Two render functions share one bind helper.
- `vault.js` (8th) — 14 inline handlers, 14 window exports. Three
  binding helpers: main vault, folder-detail, restore-picker modal
  (outside emailList).
- `email-list.js` (9th) + `mail.js`/`app.js` callback wiring — extended
  `initEmailList` config with `onOpenEmail` + `onRefresh` callbacks
  so email-list no longer reaches into mail.js via window.
- `mail.js` (10th) — 2,183 lines, the largest file. Three binding
  sites: `.search-view-root` (per-render), `#subfoldersBar`
  (persistent), `#viewerBody` (persistent).

**Search view UX refactor:**
Rick noted during mail.js testing that the search input shrank when
the Export button appeared, and that separate Search/Clear buttons
felt inconsistent with every other filter input in the app.
Refactored:
- Shell/list split — toolbar (with input) rendered once, body rebuilt
  on each search. Input stays in DOM, no focus loss.
- Removed Search and Clear buttons; X clear button inside the input
  (consistent with starred, trash, vault, folder-selection,
  email-list filter inputs).
- Live search with 300ms debounce.
- Export button always visible, disabled when no results — no toolbar
  reflow.
- Helper text now prominently mentions `*` for prefix matching.
- No-results state shows context-aware hint: "Try `<query>*` to match
  all words starting with `<query>`" — suppressed when the query
  already uses FTS5 syntax.
- Decision worth preserving: I initially auto-prefixed queries client-
  side ("consul" silently becomes "consul*"). Rick pushed back and
  was right — silently rewriting input would break legitimate exact-
  word matching (e.g., searching "Smith" to find Smith but not
  Smithson) and confuse power users. Helper text is the honest fix.

**closeModal consolidation:**
Three modules each defined their own `closeModal` and assigned to
`window.closeModal`. Last loaded won. In practice `settings.js` won
and its `resetAccountModal` cleanup worked — but fragile.
- `modals.js` becomes canonical. New
  `registerModalCloseHandler(modalId, callback)` extension point.
- `imports.js` and `settings.js` drop their duplicate definitions
  and import the canonical version.
- `settings.js` registers `resetAccountModal` for `addAccountModal`
  via the new API.

**Template inline-onclick conversion (11th file):**
The final piece. `web/templates/main/index.html` had 43 inline
`onclick="X()"` handlers calling functions exposed via `window.X = X`.
- New file: `web/static/js/template-bindings.js` — imports every
  template-callable function as a named ES import, maps action names
  to handlers, sets up a single delegated click listener on
  `document.body`.
- Argument handling via data attributes: `data-modal-id`,
  `data-direction`, `data-confirm`, `data-prompt-cancel`,
  `data-rail-view`.
- `registerHandler(action, fn)` escape hatch for `handleLogout`
  (which lives in app.js and can't be imported here without a cycle).
- All 43 onclicks in `index.html` converted to `data-tpl-action`
  attributes.
- 21 `window.X = X` assignments dropped across 8 files.
- Bonus: `move-email-modal.js`'s render-generated inline onclick
  (the only stray inline-onclick-in-rendered-HTML outside index.html)
  also converted to `bindActions` delegation.

**Bug worth preserving:** during the template-bindings work I removed
the `window.X` assignments for five viewer functions (`copyAsReply`,
`viewEmailSource`, `downloadEmail`, `printEmail`, `loadRemoteContent`)
but forgot to add the `export` keyword to their declarations. Missing
named imports in `template-bindings.js` exploded at module-link time
in the browser — but `node --check` passes (parse-time, not link-
time). Symptom: folder tree rendered flat, accounts section missing.
Lesson: run a name-vs-export audit before declaring a window-to-import
conversion done.

**End state:**
- Zero inline `onclick` attributes anywhere in the codebase.
- Zero `window.X` assignments for cross-module function dispatch.
- Two legitimate `window.X` remaining: `getMountedImports`
  (cross-module lazy reference in review.js + mail.js) and
  `skipBeforeUnloadWarning` (internal self-reference in app.js).

### Commits
- `5e798d6` — export-modal.js (3rd)
- `b18a43b` — review.js (4th)
- `34341c5` — folder-mgmt.js (5th) + context-menu.js
- `c6695e4` — settings.js (6th) + About credit update
- `1b747e7` — folder-selection.js (7th)
- `498345a` — vault.js (8th)
- `7cca298` — email-list.js (9th) + mail.js/app.js callbacks
- `da54946` — mail.js (10th)
- `8368bd5` — Search view UX: live search + X-in-input + always-show Export
- `12bf631` — Consolidate closeModal: one canonical implementation
- `1604c94` — Template inline onclicks -> data-tpl-action (11th, final)


---

## Session 39 — May 31, 2026 (MacBook)

### Pre-1.0-tag Code Review + Fixes

An outside-eyes review against `docs/Code_Review_Prompt.md` (the reusable
prompt written end of Session 38), followed by fixing everything it
surfaced. Goal: a clean bill of health before `git tag v1.0.0`.

**Review outcome:** no critical findings. One important (master passwords
transiting the client-side session cookie in the password-change flow),
the rest suggestions and doc drift. The two threads flagged hardest came
back clean — the missing-export audit found zero broken named imports
across all 29 JS files, and the crypto construction verified correct
(Argon2id params, HKDF domain separation, GCM AAD binding, and the
SQLCipher raw-key `x'...'` form so the HKDF subkey is used directly with
no double-KDF). SQL is fully parameterized. The backup WAL-checkpoint
false-positive handling and the save-baseline-after-verify ordering both
verified correct. Findings written to `docs/Code_Review_Findings.md`.

**Fixes (all committed; suite 68 -> 85 green):**
- **#1 (important) — password-change credentials off the cookie.** The
  flow stashed current+new master passwords in the Flask session (a
  signed-but-unencrypted client cookie). Moved to the export pipeline's
  one-time job-id model: passwords held only in a server-side dict keyed
  by an opaque token, TTL-GC'd, consumed once by the SSE endpoint.
  Frontend passes the id in the EventSource URL.
- **#2 — atomic backup writes.** New `_atomic_write_text`
  (temp + fsync + os.replace + dir-fsync); `save_manifest` and
  `_write_backup_state` route through it.
- **#3 — JSON 500 safety net.** `@app.errorhandler` returns JSON on
  `/api/` paths; non-API routes and the debugger untouched.
- **#4 — modal picker listener stacking.** `dataset.actionsBound` guard
  so the move-email and restore-destination pickers bind exactly once.
- **#9 — bare `except:`** in accounts.py narrowed to `except Exception:`.
- **Color aside — server-side folder-color validation** (null or
  `#rgb`/`#rrggbb`), since color lands in a `style` attribute on render.
- **#6 — documented** the intentional exclusion of `export_progress`
  from the session-timeout skip set.
- **#7/#8 — Navigation_Map** schema block regenerated from `SCHEMA_SQL`
  (server/port/is_gmail/original_parent_id aren't columns;
  pending_commit.batch_id and email_cache.uid_data were also wrong),
  test_encryption.py label corrected.

**Backup test module (#5):** new `tests/test_backup.py`, 17 tests —
state-file round-trip + corruption degrade, the two-layer change
detector, the WAL-checkpoint no-spurious-backup case, and the
interrupted-backup baseline-safety invariant. Suite 68 -> 85.

**Left for the author:** one manual end-to-end test — change the master
password once to confirm the job-id handoff completes — since that
exercises the live re-encryption path the unit suite can't.

**Still open (next sessions):** test coverage for `pending_commit.py`
(top priority — data-integrity, as testable as backup) and the API
blueprints, then `exports.py` and `importer.py`. IMAP/PDF tiers are
high-cost/low-ROL and likely skippable.

### Commits
- `e1b3d11` — Security: password-change credentials server-side, not in cookie
- `4da009a` — Security: validate folder color server-side
- `2eebb99` — Backup: atomic, crash-safe state-file and manifest writes
- `4400c33` — API: return JSON on uncaught errors for /api/ paths
- `efb74d2` — Frontend/cleanup: bind modal pickers once; narrow bare except
- `c81c34e` — Tests: backup change detection + interrupted-backup safety
- `181ea22` — Docs: code-review findings + resolutions; nav-map schema; changelog


### Continued — Test coverage plan + pending_commit tests

Added `docs/Test_Coverage_Plan.md`: a tiered plan for filling the coverage
gap. Auth-flow tests (login/logout, password-change via job id, rate-limit
lockout, CSRF) were elevated to Tier 1 — per an Opus 4.7 suggestion — since
they cover the security boundary and validate the Session 39 #1 fix, which
otherwise leans only on a manual test. Then completed the first item:
`tests/test_pending_commit.py`, 19 tests covering session creation, the
pending -> committed -> post_action_done state machine, resume detection,
post-action filtering (excludes 'leave' and import-sourced items), clear
vs discard, and the source-key helpers. Suite 85 -> 104, all green.

Next session: Tier 1 auth-flow tests, then the Tier 2 API blueprints.

### Commits (continued)
- `9989da5` — Docs: test coverage plan
- `1085f7f` — Tests: commit-resume state machine (pending_commit, 19 tests)


### Continued — Website docs: v2 crypto stack

(On Apollo, `~/Websites/mailrepo-website/` — separate repo, push target
Sentinel.) Updated `docs.html`'s Encryption section to reflect the v2
stack. Was still describing v1: Fernet (AES-128-CBC) for files and
PBKDF2-HMAC-SHA256 with 480,000 iterations for key derivation. New text
describes AES-256-GCM file encryption (with the per-file random nonce),
Argon2id as the password KDF, and the HKDF subkey derivation with
distinct labels for the database key vs the file-encryption key (so a
key valid for one purpose can't be substituted for the other). Added a
one-sentence explanation of why memory-hard KDFs matter, since that's
the property that distinguishes Argon2id from PBKDF2 in a way relevant
to the audience's threat model — someone with a backup drive trying to
brute-force the passphrase offline.

Audited the rest of the site (`index.html`, `index_final.html`,
`why.html`, `download.html`) for stale crypto claims; only docs.html's
Encryption section was actually wrong. The other pages either don't
make implementation-specific claims, or use the generic "AES-256"
framing that's still accurate for v2 (SQLCipher AES-256 for the
database; AES-256-GCM for files). `index.html` is still the "Coming
Soon" placeholder; `index_final.html` is the staged real homepage
waiting for tag day.

The site itself is not yet live — Sentinel push is a staging point.
The public flip (swap `index_final.html` into `index.html`, point DNS
at it) is paired with `git tag v1.0.0` per the original plan, not done
now.

### Commits (continued, mailrepo-website repo)
- `7ce9867` — docs: update Encryption section to reflect v2 crypto stack


---

## Session 40 — June 1, 2026 (MacBook)

### Tier 1 auth-flow tests

Continued the test-coverage plan. Wrote `tests/test_auth.py` — 22 tests
covering the auth boundary: setup (validation, redirects), login (success,
wrong password, redirects, rate-limit lockout), logout (locks + clears
session), CSRF enforcement on the `/auth/api` endpoints (missing token →
403, valid token → passes), and the password-change job-id handoff.

The handoff tests are the point: they validate the Session 39 #1 fix
end to end — POST mints a job id, passwords are held server-side and never
land in the session cookie, and the SSE endpoint consumes the job exactly
once — which retires the manual test that fix previously relied on. The
full end-to-end change test also surfaced (and now exercises) a good
safety guard in `change_master_password`: a non-overridable requirement
that a backup be <=24h old before a rekey, since the DB-rekey window
isn't resumable and the backup is the recovery path. The test creates a
backup first, exactly as the app requires of the user.

Suite 104 -> 126, all green (full run ~4 min; backgrounded past the tool
timeout). Rebased onto the website-docs commit pushed from the other chat
(`6674293`) — clean, no conflicts.

Per the coverage plan, next is Tier 2: the API blueprints (`emails`,
`imports`, `accounts`, `commit`, `threads`, `settings`) via the Flask
test-client template.

### Commits
- `891b095` — Tests: auth-flow suite (auth.py, 22 tests)


---

## Session 41 — June 1, 2026 (MacBook)

### Tier 2 API-surface tests

Completed Tier 2 of the test-coverage plan in one sitting — the full
user-facing API surface, one committed/pushed module at a time. Suite
126 → 238, all green (full run ~6m55s).

- `test_api_emails.py` (28) — FTS search with folder scoping, the
  subfolder toggle, and trash exclusion; folder listing; the
  decrypt-and-parse viewer and raw-source endpoint exercised against
  **real AES-256-GCM `.eml.enc` fixtures** (a seed helper encrypts a
  crafted RFC822 message to disk and inserts the row, so the viewer's
  decrypt path runs for real, not mocked); soft-delete (folder detach to
  `original_folder_id`); restore across all three branches
  (original / needs-destination 409 / chosen destination); permanent
  delete (row + file both gone); flag set/clear + flagged list; move.
- `test_api_imports.py` (19) — mbox/eml scan + import validation, a real
  single-`.eml` import round-trip, import-email content + an attachment
  read from a file on disk, and the unencrypted-ZIP folder export read
  back and verified to **decrypt to the original bytes** (incl. nested
  subfolders).
- `test_api_accounts.py` (23) — listing + the runtime `is_gmail`
  detection (decrypts stored credentials via `IMAP.save_credentials`/
  `load_credentials`, inspects host), create/update validation, the
  no-password update path, test/emails guards, the cached-folder fast
  path that returns without touching IMAP, delete, and email-domain
  server detection. Live IMAP paths left at the validation boundary.
- `test_commit.py` (22) — unit tests for the pure `commit.py` helpers
  (archive-folder-from-path nested chain + reuse, duplicate detection
  incl. trashed/other-folder, summary singular/plural + post-actions,
  the 3- and 4-part post-action key parsing with colon folder names),
  the atomic `_save_email_to_archive` including **orphan-file cleanup on
  DB failure** (monkeypatched insert), plus the SSE `/api/commit/stream`
  endpoint: empty-payload error event, and a full import round-trip
  (create session → walk → archive row + encrypted file → pending_commit
  cleared). Pairs with the Session 39 pending_commit state-machine tests.
- `test_api_threads.py` (6) — the request-validation boundary that runs
  before any IMAP connect (required/typed `account_id`, `folder`, `uid`;
  unknown account; no-credentials account).
- `test_api_settings.py` (14) — the validated settings endpoints
  (trash retention, session timeout, thread-max-messages) with GET
  defaults and allow-list rejection; session-status incl. the "Never"
  timeout; keepalive; and the reset-database guards (confirmation text +
  password) without running the destructive reset. Verified first that
  `Encryption.unlock` *raises* on a wrong password, so the wrong-password
  test safely hits the 401 guard and never falls through to the wipe.

### Gotcha worth remembering

A bodyless POST to a route that reads an *optional* JSON body returns
**415 Unsupported Media Type**, not the route's own fallback: Flask's
`request.get_json()` raises before `or {}` can apply when there's no
JSON content-type. Surfaced on `/api/folders/<id>/export`. The real
frontend always sends a body, so it's a test-only artifact — fix is to
pass `json={}` in the test. Anything testing a POST route with an
optional body needs the same.

### Commits
- `dc1fb43` — Tests: emails API (api/emails.py, 28 tests)
- `522e2b4` — Tests: imports + export API (api/imports.py, 19 tests)
- `dc40021` — Tests: accounts API (api/accounts.py, 23 tests)
- `5d490fa` — Tests: commit workflow (commit.py + progress_commit.py, 22 tests)
- `905e1ee` — Tests: threads + settings API (api/threads.py, api/settings.py, 20 tests)
- (this entry) — Docs: Session 41 log; coverage plan + Navigation_Map + changelog to 238

### On the horizon

Tier 1 + Tier 2 of the coverage plan are now done — `pending_commit`,
`auth`, and the full API surface cover the real data-integrity and
security paths. Remaining: Tier 3 (`api/exports.py` scope resolution +
job state machine + encrypted-ZIP round-trip; `core/importer.py` with
the `test_files/` samples) is fixture-heavy but ~1 session; Tier 4
(`core/imap.py`, `core/pdf_export.py`) is the recommended skip. Then the
remaining pre-tag items and the dogfooding period before `git tag
v1.0.0`.


---

## Session 42 — June 2, 2026 (MacBook)

### Tier 3 pipelines + the cheap IMAP helpers

Completed Tier 3 of the coverage plan and folded in the connection-free
IMAP helpers I'd flagged at the end of Session 41. Suite 238 → 320, full
run green (3m55s). One module per commit, as usual.

- `test_api_exports.py` (39) — the export pipeline, no network / no
  WeasyPrint. Three areas: (1) **scope resolution** —
  folder/messages/search sources, recursive subfolder collection,
  FTS folder-scoping, slash-path + "(+ subfolders)" labels, unknown-
  source `ValueError`; (2) the in-memory **job state machine** —
  new/push/fail/finish, in-memory vs save-to-disk with filename
  disambiguation, the "no mkdir -p" missing-destination failure, and TTL
  garbage collection; (3) the **`.eml` ZIP builders** — both plain and
  AES-256 (pyzipper), built from real encrypted fixtures and read back to
  confirm they **decrypt to the original bytes**, plus wrong-password
  rejection, empty/skip-missing/dedup. Endpoint contracts on top: start
  validation, a synchronous worker run for the eml path, download
  404/409/200, cancel, and the reveal path-allowlist (403 on an unknown
  path — the small anti-`open`-arbitrary-file guard).
- `test_importer.py` (29) — driven by the `test_files/` edge-case
  samples. Header decoding (RFC 2047 q/b), metadata extraction (subject
  default + 500-char truncation, bad-date → None). The property that
  matters for an archive: **mail is never silently dropped or altered**.
  Malformed `.eml` files (no-headers, bad-encoding, truncated) archive
  byte-for-byte; the 17MB and multi-attachment samples round-trip; a
  corrupt mbox accounts for every message as success-or-failure rather
  than aborting the whole import. Plus message-id vs sha256 filenames,
  the progress callback, and bad-path → `ImportError` for scan + import.
  (PST untouched — needs `libpst`.)
- `test_sync_cache.py` (14) — the connection-free IMAP pieces. The
  sync-cache state round-trip (per account+folder, INSERT-OR-REPLACE,
  clear) and the **freshness TTL** (no-state/fresh/stale, 120s constant)
  that throttles how often we re-hit a server; plus `IMAP.detect_server`
  as a pure domain lookup (case-insensitive, name-wrapped addresses,
  unknown/malformed → None).

### Notes

- The export job registry (`_JOBS`) and the sync-cache module-global
  connection are both process-global, so each test file has an autouse
  fixture that clears them — `_JOBS` between tests, and
  `sync_cache.close()` so the connection rebuilds against the current
  temp data dir. Worth remembering for any future test that touches
  module-level singletons.
- `mailbox.mbox` is lenient: it **creates** a missing file rather than
  raising, so "nonexistent mbox" isn't an error path — the real raise
  comes from a path whose *parent* doesn't exist. The API layer guards
  existence before calling, so this only matters for direct unit tests.
- Probed the deliberately-broken samples before asserting: `corrupt.mbox`
  actually scans to 2 messages (the corruption is in content, not mbox
  framing), and Python's email parser swallows all three malformed
  `.eml` files without raising. Tests assert observed behavior, not
  guesses.
- Mid-session the Desktop Commander MCP server went unresponsive right
  after `test_sync_cache.py` was written; the file was committed in the
  next sitting once it recovered. No work lost — the two Tier 3 modules
  were already pushed.

### Commits
- `396280f` — Tests: exports pipeline (api/exports.py, 39 tests)
- `025a7d5` — Tests: importer (core/importer.py, 29 tests)
- `6e90bad` — Tests: sync cache + detect_server (core/sync_cache.py, core/imap.py, 14 tests)
- (this entry) — Docs: Session 42 log; coverage plan + Navigation_Map + changelog to 320

### On the horizon

The coverage plan is now effectively complete: Tiers 1–3 done, Tier 4
deliberately limited to the cheap helpers (the rest — live IMAP
connect/fetch and WeasyPrint PDF rendering — is dogfooding/skip by
design). Remaining before the tag: the pre-tag items still open in the
code review, then the dogfooding period itself, then `git tag v1.0.0`
paired with the website update. Packaging (`.deb` / `.dmg`) is the
flagged next focus after the tag.


---

## Session 43 — June 4, 2026 (Apollo)

### Pre-tag verification + repo-wide lint pass

Verified the three pre-tag blockers and the cleanup items against actual
source (not the findings doc), then did a full ruff pass. Worked on
Apollo this session; it was 5 commits behind origin at the start (the
Session 42 test commits + the June 2 password-change confirmation) — Rick
pulled it current before the code changes.

**Verification result:**
- **#1 (master password in cookie):** fixed, confirmed in source —
  `auth.py` holds passwords in a server-side `_pw_change_jobs` dict keyed
  by `secrets.token_urlsafe(32)`, TTL-GC'd; nothing in the session.
- **#3 (JSON 500 handler):** fixed — `@app.errorhandler(Exception)` in
  `app.py`.
- **#4 (modal listener accumulation):** fixed — `actionsBound` guard in
  `move-email-modal.js` and `vault.js`.
- **#7, #8:** fixed (schema block, test label).
- **#9 (bare except in accounts.py):** the doc said fixed, the code
  disagreed. The originally-cited line was addressed, but the file had
  grown new bare excepts and a ruff sweep found **32** across 11 files.
  This is exactly the doc-vs-source mismatch worth catching pre-tag —
  the lesson reinforced: verify claims against source, the doc can drift.

**Lint pass (ruff E/F/W/I), two commits, suite green at 320 throughout:**
- `56639a1` — substantive: all 32 bare `except:` → `except Exception:`
  (also a real fix in the SSE generators, which had been swallowing
  `GeneratorExit`); 37 F-rule removals (unused imports/locals, a
  duplicate `parsedate_to_datetime` import, empty f-strings, the dead
  `old_db_key_hex` derivation in the password-change verify path); split
  a semicolon idiom; `per-file-ignores` documenting the intentional
  route-registration imports and `sys.path` entry point / dev scripts.
- `31f921b` — cosmetic: 1119 whitespace + import-ordering fixes,
  behavior-preserving.

Codebase is now ruff-clean except for 171 whitespace-inside-string
findings (e.g. the `SCHEMA_SQL` block), deliberately left — fixing them
would edit string contents, not formatting.

### Notes

- Confirmed `except Exception:` is the right call everywhere here: no
  spot legitimately wants to swallow `KeyboardInterrupt`/`SystemExit`,
  and in the SSE generators it's strictly safer (lets `GeneratorExit`
  propagate for cleanup).
- Did **not** blind-run `ruff --fix`: the 11 `F401`s in
  `web/blueprints/api/__init__.py` are side-effect imports that register
  every API route — ruff correctly marks them unfixable; removing them
  would 404 the whole API. Left them, added a documented per-file-ignore.
- Ran the full suite (5 min) after the substantive changes and again
  after the import-reordering pass, since `I001` reorders across ~50
  files and reordering can in principle change side-effect order. Clean
  both times.

### Commits
- `56639a1` — Lint: eliminate bare excepts + dead code; document intentional ignores
- `31f921b` — Lint: whitespace + import ordering (ruff W291/W293/I001)
- (this entry) — Docs: Session 43 log; Code_Review_Findings addendum; changelog

### On the horizon

Engineering checklist for the tag is now genuinely clear: all code-review
items closed (and re-verified against source), #1's re-encryption path
manually confirmed (Session 42), test suite at 320 covering every path
worth covering, and the codebase ruff-clean. What remains is non-code:
the dogfooding stretch, then `git tag v1.0.0` paired with the website
update, then `.deb`/`.dmg` packaging.

---

## Session 44 — June 4, 2026 (Apollo)

### Frontend JS audit + final lint, format, and blame-ignore tooling

A cleanup session triggered by Rick reviewing a transcript of an
earlier Opus 4.8 session that had hedged its way around two questions:
"do we need to lint the JS?" and "what about the 93 console.* calls?"
Re-examined both against actual source, then continued through the
remaining "neat and tidy" items — whitespace cleanup, the formatter
pass, and blame-ignore tooling.

**Frontend JS audit (no changes):**

- `console.*` calls: the prior framing of "93 debug logging calls worth
  cleaning up" was wrong. A careful pass found **0 `console.log`**, 81
  `console.error`, and 12 `console.warn` — all inside `catch` blocks or
  guarding missing/invalid conditions. This is correct error reporting,
  not debug noise. A `?debug=1` flag pattern would have been actively
  harmful — silencing error output is the opposite of what you want.
  Decision: leave them alone.
- `var` keyword: 0 occurrences. The prior count of "1 var" was a false
  positive from grepping inside strings/comments.
- Loose `==`/`!=`: 68 total. Dominant patterns are the safe `== null`
  idiom and intentional string-vs-number coercion on DOM data
  attributes. No bugs, style-only.
- eslint setup: deferred to post-tag. Adding a Node/npm dev toolchain
  to a deliberately Node-free project is a real architectural change
  better made deliberately than reflexively, and eslint wouldn't catch
  the bug class that actually bites this codebase (the missing-`export`-
  after-dropping-`window.X` failure mode is a module-link issue at
  runtime, not a syntax issue).

Lesson reinforced: count-based summaries ("93 console calls") are not
findings. Look at the calls.

**Whitespace cleanup (commit `268a45a`):**

Reversed Session 43's deliberate decision to leave the 171 W291/W293
findings on string-literal-internal whitespace. With the dry-run
`--diff` in hand showing the changes are pure trailing-whitespace
removal inside docstrings and inside multi-line SQL query strings, and
with SQL being whitespace-insensitive at token boundaries, the
"editing string contents" worry is technically real but practically
empty. Applied via `ruff check --fix --unsafe-fixes`. 19 files, 171
insertions / 171 deletions, all whitespace. `ruff check` now reports
**All checks passed!** with no remaining errors. `pytest`: 320 passed
in 5m08s, unchanged.

**Formatter pass (commit `27ac235`):**

Ran `ruff format` for the first time on the codebase. 51 of 59 files
reformatted; 8 already conformant. The changes are stylistic only:
quote-style normalization (single → double), multi-line dict/call
literals collapsed onto one line where they fit within line-length,
function-call argument formatting normalized. No behavior changes.

One regression introduced by the formatter and fixed in the same
commit: `core/pdf_export.py` had an f-string with outer single quotes
containing inner double quotes (`f'...{_esc(email.get("cc"))}...'`).
The formatter flipped the outer to double, creating same-quote
nesting that only parses on py3.12+ per PEP 701. Since
`pyproject.toml` targets py3.11, changed the inner quote-style
instead (`email.get('cc')`) — same dict lookup, py3.11-valid syntax.
This is a known ruff format edge case worth noting; the fix is one
character.

Final state: `ruff check` clean, `ruff format --check` clean,
`pytest` 320 passed in 5m10s.

**Blame-ignore tooling (commit `fcd3f71`):**

Added `.git-blame-ignore-revs` referencing the format commit, so
the 51-file reformat doesn't obscure `git blame` six months from
now. GitHub honours this file automatically; local clones need a
one-time `git config blame.ignoreRevsFile .git-blame-ignore-revs`.

### Notes

- The earlier Opus 4.8 session's `node --check` "syntax errors" had
  been `node: command not found` (no Node on Apollo) — counted as
  findings rather than tool-availability misses. Verified directly
  this session that Node is not on the box.
- Two false starts on the first test re-run (one tool timeout, one
  accidental re-run) burned extra time. Real test duration is
  ~5m10s; Argon2id is the dominant cost. Three full pytest runs
  this session, all green at 320.
- README contributing/development note deliberately skipped — no
  contributor plans right now.

### Commits

- `268a45a` — Lint: strip trailing whitespace in docstrings (ruff W291/W293)
- `27ac235` — Style: apply ruff format across the Python codebase
- `fcd3f71` — Tooling: add .git-blame-ignore-revs for the ruff format commit
- (this entry) — Docs: Session 44 log; changelog

### On the horizon

Unchanged from Session 43: dogfooding, then `git tag v1.0.0` paired
with the website update, then `.deb`/`.dmg` packaging. The repo is
now ruff-check clean, ruff-format conformant, with blame-ignore
tooling in place, 320 tests green, and the pre-tag blockers
verified against source. Code-side, this is as neat as it goes
short of larger refactors that aren't tag-blocking.


## Session 45 — June 8, 2026 (MacBook)

### Gmail provider-aware permanent delete (post-1.0 feature)

Implemented the long-deferred Gmail delete path from
`docs/Gmail_Delete_Implementation_Plan.md`. Gmail's IMAP delete only
removes a folder's *label*, leaving the message in All Mail; real
delete is honoured only in Trash and Spam. The Delete post-commit
action had been hidden for Gmail accounts because of this. It is now
re-enabled with a provider-aware path.

Started by reviewing the plan against actual source. The plan was
sound but three issues surfaced from reading the code:

- **Loop selection bug.** The post-commit dispatch selects the source
  folder once, then iterates UIDs. The Gmail delete path changes the
  selected folder as a side effect (it must, to expunge in Trash), so
  from the second UID onward the move would run against the wrong
  folder. Single-call unit tests would never catch this. Fixed by
  re-selecting the source folder before each message, and added a
  dispatch test over 3 UIDs that asserts the re-select count.
- **UID discovery.** Plan floated Message-ID search as primary; that's
  fragile. Switched to COPYUID (UIDPLUS) as primary, Message-ID search
  as fallback only (and Gmail supports UIDPLUS, so the fallback is rare).
- **Over-broad expunge.** The shared `move_email` used a bare EXPUNGE
  that sweeps every `\Deleted` message in the folder. Now UID-scoped
  when UIDPLUS is present, bare-expunge preserved as the fallback.

The plan doc was rewritten to split the work into two commits and fold
in these fixes before any code was written.

**Commit 1 — `move_email` hardening (provider-agnostic):**

Upgraded the shared primitive: prefers IMAP MOVE (RFC 6851, atomic)
when the server advertises it, falls back to COPY + STORE + scoped
EXPUNGE; returns the destination UID parsed from the COPYUID response
code (Optional[str]; None means "moved but UID unreported", not
failure). New helpers `_has_capability` (reads imaplib's cached
capability tuple — no extra round-trip), `_parse_copyuid` (handles
both the bracketed data form and imaplib's keyword-stripped
`untagged_responses` form — a test caught that second form), and
`_expunge_uid`. `archive_email`/`trash_email` moved to the
success-not-raising contract (NOT `is not None`, which would misread a
successful no-COPYUID move as failure).

**Commit 2 — Gmail delete path:**

`delete_email_via_trash(uid, source_folder)`: in-place delete when the
source is already Trash/Spam, otherwise move-to-Trash-then-expunge.
Returns True-with-warning if the message reached Trash but couldn't be
expunged (Gmail auto-purges in ~30 days). Added a `spam` type to
`get_special_folder`. Hoisted `_imap_escape` to module scope (was
nested in `find_thread`) so the Message-ID search reuses it. New
`core/account_utils.py::is_gmail_host` as the single source of truth
for the host check; `accounts.py` refactored onto it. Dispatch in
`commit.py` routes by host and re-selects per iteration. `review.js`
always offers Delete now; removed the dead `isGmail` plumbing and the
`isGmailAccount` helper (verified no dangling refs; `node --check`
clean).

### Tests

Added `tests/test_imap.py` (20 tests — mock the connection object only,
no real IMAP, no Argon2id, ~0.2s), `tests/test_account_utils.py` (4),
and `tests/test_commit_dispatch.py` (2, including the per-iteration
re-select guard). Full suite: **346 passed** (was 320). ruff check and
format clean.

### Notes

- This is the project's first direct unit coverage of `core/imap.py`.
  It stays within the "no real IMAP protocol tests" principle — these
  exercise MailRepo's own dispatch/parsing logic against a mock
  connection, not the protocol against a server.
- Still requires live-Gmail dogfooding before the feature is signed
  off: delete from Inbox → confirm gone from All Mail; multi-email
  commit deletes all (guards the loop fix in production); non-Gmail
  account still deletes correctly (guards the Commit 1 change).

### Commits

- `88f230e` — docs: revise Gmail permanent-delete implementation plan
- `1c918d4` — feat(imap): harden move_email with IMAP MOVE, COPYUID, scoped expunge
- `e0d0ee0` — feat(imap): provider-aware permanent delete for Gmail
- (this entry) — Docs: Session 45 log; changelog; navigation map

### On the horizon

Gmail delete is code-complete and pushed; live dogfooding is the
remaining sign-off. Otherwise unchanged from Session 44: the release
sequence (version label is open — nothing shipped yet), website update,
then `.deb`/`.dmg` packaging.

## Session 46 — June 9, 2026 (Apollo morning, MacBook evening)

### Morning: docs sweep for stale v1 crypto references

A drive-by question about the class-level key state in `Encryption`
led to documenting the key-management threat model in the module
docstring (deliberate design: single-user/single-archive, instance
injection changes nothing, CPython can't mlock/zeroize, memory
disclosure out of scope). While adding the planned pointer to
`Security_Audit.md`, found the February audit still described the
retired v1 crypto (PBKDF2/Fernet) — added a dated addendum rather
than rewriting the historical record. A follow-up sweep found
`MailRepo_Project_Plan.md` (a living doc) described v1 in eight
places; all corrected to Argon2id/HKDF/AES-256-GCM. Session_Log,
Code_Review_Prompt, Post_1_0_Backlog, and docs/archive references
are historical and were left as-is.

### Morning: website accuracy review

Reviewed all five pages of the draft site against the codebase.
Verified accurate: v2 crypto description, themes, fonts, search
operators, all defaults, shortcuts, Gmail delete description. Fixed:
the folder-caching section claimed background polling (actual:
120s cache TTL + re-check on access); staging note now distinguishes
ephemeral pre-commit staging from interrupted commits (which persist
and resume); Ubuntu floor 20.04 → 22.04 (Python 3.13; 20.04 past
standard EOL); `index_final.html` nav self-links → `index.html` so
go-live is a pure rename. GitHub footer links deferred to go-live.

### Evening: targeted review of IMAP move/delete/expunge (pre-tag)

The review scoped in the morning. **Critical finding:** the Session
44–45 Gmail-aware delete was wired into `apply_post_commit_actions()`
in `commit.py` — a function with **no route and no caller**. The live
workflow (`/api/commit/stream` in `progress_commit.py`) still called
plain `delete_email()` on Gmail, which only strips the label and
leaves the message in All Mail — silent false assurance of permanent
deletion, and a direct contradiction of the docs page shipped that
morning. The dispatch tests drove the dead function, which is how it
appeared covered. Session 45's "live dogfooding before sign-off"
caveat would have caught it; the review caught it first.

Two further findings: `delete_email()` used a bare `EXPUNGE`
(removes every \Deleted-flagged message in the folder, including
ones flagged by other clients — MailRepo had `_expunge_uid()` but
this one method didn't use it), and `_parse_copyuid()` read
`untagged_responses` without consuming, so a stale COPYUID could be
misattributed to a later move (worst case: expunging the wrong
message in Trash).

Verified safe: UID stability across expunging loops (all UID-based
commands), COPY-fallback halfway-failures all land on "message still
on server", and the re-select caller contract.

### Fixes

- New `apply_email_action()` in `commit.py` — the single shared
  dispatcher for post-commit server actions, with Gmail routing and
  the per-message source re-select. Both live call sites in
  `progress_commit.py` now use it. The dead
  `apply_post_commit_actions()` and `_find_action_for_source()`
  were removed — the duplication is *why* the bug happened.
- `delete_email()` → `_expunge_uid()` (scoped UID EXPUNGE under
  UIDPLUS).
- `_parse_copyuid()` → `connection.response("COPYUID")`, which pops
  the entry.
- `test_commit_dispatch.py` rewritten against `apply_email_action`
  (the code the app actually runs), keeping the per-message
  re-select ordering assertion; `test_imap.py` gains a
  stale-COPYUID regression test. Full suite: **345 passed**
  (net −1: removed 6 dead-code tests, added 5).

### Notes

- Root-cause lesson for the log: tests that drive a parallel
  implementation create false confidence — coverage must target the
  code the routes actually execute. The new dispatch tests import
  the helper that `progress_commit.py` imports.
- Session 45's dogfooding checklist (delete from Inbox → confirm
  gone from All Mail, multi-email commit, non-Gmail delete) still
  stands and is now testing the right code path.

### Commits

- `32102ae` — docs: document key-management threat model; flag v1 crypto in audit
- `103d62f` — docs: update project plan to v2 crypto (Argon2id/HKDF/AES-256-GCM)
- `2b73d81` (website repo) — accuracy fixes from pre-launch review
- `c0f01b8` — fix(imap): wire Gmail-aware delete into live commit path; scope expunge; consume COPYUID
- (this entry) — docs: Session 46 log; changelog

### On the horizon

**Late-evening addendum:** Live-Gmail dogfooding completed and PASSED.
Three test emails staged from Inbox, committed with Delete action —
"3 deleted on server", and a Gmail search (which includes All Mail)
returned no matches. Archive and Trash actions and a non-Gmail delete
also verified working. Sessions 44–46's Gmail delete is signed off.

Remaining: general dogfooding, then tag + website go-live (rename
`index_final.html`, real GitHub URLs, download links, screenshots),
then `.deb`/`.dmg` packaging. Backlog addition from review: none —
Finding 3 was fixed rather than deferred.


---

## Session 47 — June 12, 2026 (MacBook)

### Dogfooding failure: silent post-commit server failures

First real-mail dogfooding hiccup. A 3-email Gmail commit with Delete
action archived locally fine, then hung ~60s on "Updating server..."
and reported "3 server updates failed" — with zero diagnostics
anywhere. Not the console, not the summary, nowhere.

Code reading found why: every failure handler in the post-commit
action phase of `progress_commit.py` was a bare `except IMAPError`
that incremented a counter and discarded the error string — six
silent paths in all (per-email, per-folder, per-account, missing
credentials, and both paths in `_apply_folder_post_action`).

A second, related bug: the "Server not responding" SSE notice checked
`isinstance(e, (socket.timeout, OSError))`, but `connect()` wraps all
exceptions into `IMAPError` first — so the one scenario the friendly
message was written for (a connect timeout) is precisely the one it
could never fire on.

Best guess at the actual cause: a transient connection failure to
imap.gmail.com during the post-action phase (the 60s hang matches the
socket timeout in `connect()`). The failure counted 3-at-once, which
fits the connect or select_folder bulk paths. Unprovable after the
fact — which is the point of the fix. Rick deleted the three emails
manually in Apple Mail; the local archive copies were intact
throughout, as designed.

### Fixes

- `progress_commit.py`: module logger; `logger.warning` with action,
  UID, folder/account, and error text in all six silent failure
  paths.
- `progress_commit.py`: the socket-timeout check now also inspects
  `e.__cause__`, so the "Server not responding" notice can fire on
  wrapped connect failures.
- `core/imap.py`: `connect()` and `login()` use `raise ... from e`
  so the underlying socket error survives as `__cause__`.
- `main.py`: `logging.basicConfig` (WARNING+, timestamps).
  Console-only by design — error strings can contain folder names,
  which shouldn't hit disk unencrypted.

### Notes

- Lesson for the log: failure *counters* without failure *reasons*
  are a diagnosability dead end. The commit-phase handlers already
  recorded `str(e)` per item; the post-action handlers never did.
  Any new except-and-count handler should log the error text.
- The 60s IMAP socket timeout is the floor on how long a dead-server
  commit can hang. Acceptable for now; a shorter timeout or a
  per-phase progress message could soften it post-1.0 if dogfooding
  surfaces it again.

### Commits

- `e3bc914` — Add logging to post-commit server action failure paths
- (this entry) — docs: Session 47 log; changelog

### On the horizon

Unchanged from Session 46: general dogfooding (now with working
failure diagnostics), then tag + website go-live, then `.deb`/`.dmg`
packaging. If the "3 failed" symptom recurs, the console will now
name the failing path and Gmail's actual error.


---

## Session 48 — June 14, 2026 (MacBook)

*(Logged retroactively in Session 49 — this entry was missed at the time.)*

### Backup state migration: final cleanup

Closed out the last item in `docs/Backup_State_Cleanup.md`. The
migration to the external `.backup_state.json` (Libram-style) pattern
was already complete; what remained were two vestigial
`refresh_hash_baseline()` calls and the now-dead function itself.

Both calls lived in the *no-backup* branch of the auto-backup flow —
`web/blueprints/auth.py` (`_run_auto_backup_check`) and the shutdown
handler in root `main.py`. Their justifying comments reasoned from the
old hash-gated model ("update the baseline so the next check doesn't
see spurious changes"), but the backup decision is now frequency-first
(calendar-based) and never gates on a hash, so a stale baseline can't
produce a false "backup needed".

### Verification (before deleting anything)

Checked against source rather than trusting the planning doc:

- `grep` confirmed exactly the three sites the doc named, and **zero**
  references in `tests/` — so the "update or drop tests" step was a
  no-op.
- The doc called `create_incremental_backup` the *only* baseline
  consumer; there's actually a second reader in `create_backup()` (the
  full-vs-incremental dispatch), but it only checks whether a baseline
  *exists* — never its contents — and an absent baseline just forces a
  full backup. Conservative, so the safety argument holds: a stale
  baseline can only mark *more* files changed, never fewer, so no
  change is ever missed.

Full suite: 345 passed.

### Commits

- `c363fba` — Remove dead refresh_hash_baseline() and its stale callers
- `f8a5f75` — Mark Backup_State_Cleanup as implemented (kept the
  planning note on file with an IMPLEMENTED banner rather than deleting it)


---

## Session 49 — June 22, 2026 (MacBook)

### Investigation: why does the "Stage thread" button appear late?

Started as a question, not a bug report. Rick noticed the "Stage
thread to folder" button in the live email viewer appears in sync with
the email body — every *other* toolbar button is already there — which
reads as if some evaluation runs in the background before the button is
allowed to show.

It doesn't. The button's visibility (`_updateStageThreadButton` in
`mail.js`) is a pure context check: show it for any live IMAP message
(`type === 'account'` with accountId/folder/uid). It does no thread
analysis. The actual conversation walk (`POST /api/threads/find`, a
multi-second IMAP round-trip) only runs *on click*. The lateness was
purely an ordering artifact — the show-call sat *after*
`await fetchWithRetry(...)`, so it landed at the same instant as the
rendered body. (This also explains the earlier surprise that the
button staged a single email for a thread whose other members had been
deleted: correct behaviour — thread size is only known post-walk.)

### The real issue underneath

Tracing that ordering surfaced a latent correctness problem with the
*other* viewer buttons. The four always-on actions — copy-as-reply,
view-source, download, print — have no visibility gating at all, so
they're clickable during the load window. During that window
`currentViewerContext` is either `null` (fresh open → the handlers'
own guards make the click a silent no-op) or still pointing at the
*previously-viewed* email (switching messages with the viewer open →
the click acts on the wrong message). The Stage thread / star /
prev-next buttons sidestepped this only because they were already
hidden until their context was ready — so the button that looked
*confusing* was in fact the correctly-behaved one.


### Fix — gate the whole action group on load

- `openEmailViewer` adds a `loading` class to the overlay before the
  fetch. CSS hides every button inside `.email-viewer-actions` while
  it's set; the close button lives *outside* that group, so it stays
  available the entire time (you can always bail out of a slow load).
- The class clears only after `renderEmailContent` runs (success path),
  once context and `emailData` are populated. On a failed load it stays
  on — nothing to act on — and `closeEmailViewer` resets it.
- `currentViewerContext` is nulled at load-start, so button handlers
  *and* the j/k/s keyboard shortcuts short-circuit on their existing
  null guards during the load instead of acting on the prior email.
  Escape stays unconditional.
- `openSearchResult` (which builds an already-loaded viewer) clears any
  stale `loading` before showing.

Net: the toolbar now appears as one unit, after the body — no trickle,
no "is it thinking?" — and the stale-/null-context window on the
always-on buttons is closed.

### Notes

- Frontend only; `node --check` clean on `mail.js`. The Python suite
  doesn't exercise this. Needs a hard browser refresh to clear cached
  JS/CSS when testing.
- The CSS rule uses `!important` deliberately: the per-button helpers
  set inline `display`, which an external rule can't otherwise override.

### Commits

- `d35438a` — Hide viewer action buttons until the email finishes loading
- (this entry) — docs: Session 48 backfill + Session 49 log; changelog;
  navigation map

### On the horizon

Unchanged: dogfooding → `git tag v1.0.0` + website go-live →
`.deb`/`.dmg` packaging. The printable-recovery-key feature
(envelope-encryption model) remains the highest-leverage pre-launch
item still on the board.


---

## Session 50 — June 27, 2026 (MacBook)

### Bug: bulk export silently did nothing

Dogfooding turned up a broken export — selecting a couple of archived
emails, choosing ".eml ZIP", and clicking Export did nothing. The JS
console showed an unhandled rejection in `_startExport`
(export-modal.js): `TypeError: Attempted to assign to readonly
property` — WebKit's wording for reassigning a `const`.

Root cause: `_exportPrefs` was declared `const` (line 45), but
`_startExport` reassigns it wholesale to capture the validated form
state (format / sort / include-subfolders / etc.) for the session. The
per-property writes elsewhere (`_exportPrefs.format = …`) are legal on a
const object, so only the wholesale reassignment threw — killing every
export before the POST to `/api/export/start`. Introduced by an earlier
frontend-cleanup "prefer const" pass (commit `5e798d6`, "export-modal.js
converted"); only surfaced now because export isn't an everyday action.

Fix: `const _exportPrefs` → `let _exportPrefs`. The reassigned object
literal has the same five keys as the declaration, so nothing is
dropped — restores the pre-cleanup behaviour exactly.

### Why node --check missed it

`node --check` only parses; const-reassignment is a runtime strict-mode
error, not a syntax error — the same blind spot that lets missing
`export` keywords through. The JS gate can't catch this class.


### Swept for siblings

Ran ESLint's read-only-binding rule family (`no-const-assign`,
`no-import-assign`, `no-func-assign`, `no-class-assign`,
`no-self-assign`) across all 29 files in `web/static/js`: zero
violations. Validated the check with a positive control (a
function-local const reassignment + an import reassignment, both
correctly flagged), so the clean result is trustworthy and covers
function-local scope, not just module-level. `_exportPrefs` was the only
instance of this family in the frontend. ESLint was run one-off via npx
— no config committed, no dependency added.

### Commits

- `8b4ae15` — Fix export: _exportPrefs must be 'let', not 'const'
- (this entry) — docs: Session 50 log + changelog

### Also this period (June 26–27 — diagnostic only, no code changes)

- **Logout hang during backup (June 26):** ~60s logout spinner during an
  incremental backup. Traced to the post-backup rsync to Sentinel —
  buffered subprocess output (no live progress) plus the upload running
  synchronously in the logout path. Confirmed normal: the ~12 MB
  incremental (dominated by the whole re-included SQLCipher DB; only
  ~11 KB of genuinely new email that round) at the evening's ~204 KB/s
  uplink ≈ 60s. All three of the day's incrementals were ~12 MB, so it
  was bandwidth, not data volume.
- **Considered and declined:** making the DB backup truly incremental
  (rsync delta on the raw DB would cut ~12 MB to ~290 KB — measured —
  but needs a delta-friendly artifact and couples MailRepo to a
  transport, violating the transport-agnostic `post_backup_command`
  design); and backgrounding the post-backup command (sleep / lid-close
  mid-transfer makes process lifecycle and failure-reporting
  machine-dependent and fragile). rsync is a backup-of-a-backup, so
  neither earns the complexity. Left as-is.
- **Network binding (June 27):** verified MailRepo binds `127.0.0.1`
  (hardcoded in `main.py`, both the dev and Waitress paths) — loopback
  only, not network-exposed. EdgeCase similarly defaults to loopback;
  `0.0.0.0` only behind an explicit `--lan` / `EDGECASE_LAN=1` opt-in
  with a plaintext-HTTP warning. Both correct.


---

## Session 51 — July 1, 2026 (MacBook)

### Standardize destination-folder pickers on renderFolderTree

Rick noticed the move-emails destination picker rendered a flat,
fully-expanded folder list with no chevrons, unlike the commit/stage
modal's collapsible tree. Goal: converge every archive-folder
destination picker on the shared `renderFolderTree` component.

**Audit.** Already on the standard: the sidebar, the commit/stage modal,
the folder-management tree, and — on inspection — the folder-move picker
(its lone `.folder-select-item` was just a "root level" row above an
already-`renderFolderTree` tree; self/descendant exclusion was already
handled via a `filter`). The real custom outliers were the move-emails
picker and the vault restore picker, plus one genuinely dead handler.

**Component (folder-tree.js).** Added a small reusable
`isSelectable: (folder) => boolean` option. When it returns false the row
is shown and its chevron still expands (children stay reachable), but the
row itself can't be selected. Serves the move picker's "not the current
folder" rule; the folder-move picker keeps using `filter` for its harder
self/descendant exclusion.


**move-email-modal.js** (commit `a7eb5f5`). Dropped its custom
`renderFolder()`, the delegated selectFolder handler, and the now-unused
escapeHtml/bindActions imports. Now calls renderFolderTree with
`isSelectable: f => f.id != currentFolderId` and a `(current)` tag via
renderActions. Matches the commit modal exactly.

**vault.js restore picker** (commit `93d9ce8`). Replaced its flat
renderer + delegated selectDest with an "Archive Root" option above a
renderFolderTree tree, mirroring the folder-move picker. Vault folders
(retention_date) are excluded by the default filter, so the folder being
restored can't appear as its own destination.

**Dead code (commit `93d9ce8`).** Removed `staging.handleFolderSelect`:
it was bound to `#folderSelectList` clicks, but that container is filled
by renderFolderTree (`.folder-tree-row` rows) while the handler only
matched the old `.folder-select-item` rows — so it could never fire.
Dropped the function, its app.js import, and its addEventListener.

### Verification

`node --check` clean on every touched file; ESLint read-only-binding
sweep (`no-const-assign` etc.) clean. Frontend only — the Python suite
doesn't exercise these paths.

### Commits

- `a7eb5f5` — Move-email picker: use the shared renderFolderTree
- `93d9ce8` — Vault restore picker: use renderFolderTree; drop dead
  handleFolderSelect
- (this entry) — docs: Session 51 log; changelog; navigation map counts

### On the horizon

Unchanged: dogfooding → `git tag v1.0.0` + website go-live →
`.deb`/`.dmg` packaging.


---

## Session 52 — July 1, 2026 (MacBook)

### Doc verification + move-email partial-failure fix

Session opened as a docs audit: verify Opus 4.8's Session 51
documentation (commit `bf4c8eb`) against actual source. All checks
passed — every Navigation_Map line count (six touched files plus JS/CSS
section totals and the 38,721 table total) matched `wc -l` exactly, and
every code claim (isSelectable semantics, chevron-expand on disabled
rows, handleFolderSelect fully removed, both picker conversions) matched
the shipped code. The disabled-row guard was also confirmed type-safe:
`parseInt` on the data attribute vs. numeric API ids on both sides of
the `disabledIds` Set.

**Finding (pre-existing, not Session 51).** Reading the full
move-email-modal.js during verification surfaced two silent-failure
problems in `confirmMoveEmail()`, both violating the project's logging
principle:

1. A failed PATCH logged only the email ID — no HTTP status, no server
   error text, no target folder — and the user was never alerted (the
   catch-all only fired on thrown exceptions, which a non-ok response
   never produced).
2. View removal used the full `pendingMoveEmailIds` list, not the moves
   that succeeded. Partial failure made every selected email vanish
   from the current view; the failures silently reappeared in the old
   folder on next reload. The UI lied until refresh.

**Fix (commit `430f48b`).** Each move is tried individually inside its
own try/catch; successes collect into a `movedIds` Set and only those
are filtered from `state.emails`. Failures log action, email ID, target
folder ID, HTTP status, and response text (or thrown error). If any
moves failed, a "Move Incomplete" alert reports failed/total and points
to the console. View re-render and selection clearing are skipped when
nothing moved.

**Deliberately left alone.** The loose `!=` / `==` id comparisons in
move-email-modal.js and folder-tree.js are type-safe here (numeric ids
on both sides) and match the component's existing style — tightening to
strict equality would be churn without benefit.

### Verification

`node --check` clean; ESLint `no-const-assign` sweep clean (note:
ESLint 10 replaced `--no-eslintrc` with `--no-config-lookup` for
one-off npx runs). File grew 93 → 112 lines; Navigation_Map counts
refreshed (JS 16,340 → 16,359; table total 38,721 → 38,740; overview
stays ~38,700).

### Commits

- `430f48b` — Fix move-email partial-failure handling: only drop moved
  emails from view
- (this entry) — docs: Session 52 log; changelog; navigation map counts

### On the horizon

Unchanged: dogfooding → `git tag v1.0.0` + website go-live →
`.deb`/`.dmg` packaging.


---

## Session 53 — July 2, 2026 (MacBook)

### Investigation: 60–90s Gmail delete

Rick reported a commit-with-delete of two Gmail emails that sat at
"Updating server…" for 60–90 seconds before completing successfully. Not
the old timeout-and-skip failure mode (that path bails with a "server not
responding" message and skips — this one succeeded), so the time was real
work.

Traced the Gmail delete path. Gmail's plain IMAP delete only removes a
label, so `delete_email_via_trash` does the Gmail-safe dance per message:
re-SELECT source → resolve trash → resolve spam → UID MOVE to
`[Gmail]/Trash` → SELECT Trash → STORE `\Deleted` → UID EXPUNGE. About
seven commands per message, ~14 for two, and Gmail's per-command IMAP
latency (plus its slow EXPUNGE) dominates. The MOVE itself is atomic
(RFC 6851), so that part is fine. Conclusion: most of the 60–90s is Gmail
being Gmail on a real permanent delete, not a MailRepo bug.

### Fix: cache list_folders() per connection (commit `c1f3178`)

One genuine inefficiency: `get_special_folder()` resolved trash/spam by
running a full IMAP LIST and scanning names, and `list_folders()` hit the
server every call — so a two-email delete fired four uncached Gmail LISTs
(trash + spam, twice), and a Gmail LIST is slow.

Memoized `list_folders()` on the IMAP instance for the connection's
lifetime (`self._folder_cache`). Safe: clients are short-lived per
operation and never create/rename/delete server folders, so the set can't
change under the cache; it resets on `connect()`, with a
`force_refresh=True` escape hatch. Removes the redundant-LIST slice of the
latency; the per-message SELECT/STORE/EXPUNGE and Gmail's inherent
per-command latency are unchanged.

### Deliberately not done

Batching the delete (one UID-set MOVE + a single EXPUNGE instead of
per-message) would cut round-trips further, but it's a real change for a
cosmetic win on a chatty-by-nature Gmail operation — left as an optional
follow-up.

### Verification

`ast.parse` clean; ruff clean; targeted `tests/test_imap.py` 21 passed;
full suite 345 passed (3:39).

### Commits

- `c1f3178` — imap: cache list_folders() per connection to cut redundant
  Gmail LISTs
- (this entry) — docs: Session 53 log; changelog; navigation map counts

### On the horizon

Unchanged: dogfooding → `git tag v1.0.0` + website go-live →
`.deb`/`.dmg` packaging.


---

## Session 54 — July 2, 2026 (MacBook)

### Batch Gmail permanent-deletes (commit `f51eac4`)

Follow-up to Session 53's Gmail-delete diagnosis. The per-message delete
path runs ~7 IMAP commands per message (re-SELECT source → resolve trash →
UID MOVE → SELECT Trash → STORE `\Deleted` → UID EXPUNGE), and Gmail's
per-command latency made multi-deletes slow — the 60–90s two-email delete
that started this thread.

**New: `delete_emails_via_trash(uids, source_folder)`.** One UID-set MOVE
to Trash, one SELECT Trash, one set STORE `\Deleted`, one UID EXPUNGE — ~5
commands regardless of N. Two helpers:
- `_expand_uid_set`: expand an IMAP sequence-set (`4,7:9` → 4,7,8,9).
- `_parse_copyuid_map`: parse COPYUID's positionally-parallel src/dst sets
  into a `{src_uid: dst_uid}` map so the STORE/EXPUNGE in Trash hit the
  right new UIDs.

**Correctness.** Returns a `{uid: bool}` map — partial failures reported
per-uid, not swallowed (same discipline as the move-emails fix). No COPYUID
(rare on Gmail/UIDPLUS) → messages reached Trash, report True and rely on
~30-day auto-purge, matching the per-message path. Single-message and
in-place (source already Trash/Spam) delegate to the retained per-message
`delete_email_via_trash`.

**Integration.** `progress_commit` batches only Gmail delete items with 2+
per folder; single deletes and every other action keep their existing
per-item path (skip guard via `handled_ids`).

### Verification

8 new unit tests (set expansion, COPYUID mapping incl. ranges + mismatch,
one-MOVE-for-many with dst-set expunge, no-COPYUID success, MOVE-failure
raise, single/in-place delegation). Full suite 353 passed; ruff clean.

**Live dogfood (Rick):** deleted a small batch of throwaway emails from a
real Gmail folder — count correct, messages gone, Trash empty (so the real
COPYUID mapping parsed as expected, not the auto-purge fallback). The one
thing the mocked tests couldn't prove, now confirmed end-to-end.

### Commits

- `f51eac4` — imap: batch Gmail permanent-deletes into one MOVE + one
  EXPUNGE
- (this entry) — docs: Session 54 log; changelog; navigation map counts

### On the horizon

Unchanged: dogfooding → `git tag v1.0.0` + website go-live →
`.deb`/`.dmg` packaging.


---

## Session 55 — July 2, 2026 (MacBook)

### Fix: hybrid Inbox/Staged screen when navigating mid-stage (commit `9665477`)

Rick opened an email, clicked Stage conversation, and navigated to the
Staged Items screen while the stage spinner was still up — and saw a hybrid
screen: the Staged Items chrome ("Staged Items" header, hidden sidebar) but
with the *inbox* list painted into it, showing the email he'd just opened.
Clicking away and back fixed it.

**Cause.** Staging a thread is an async server round-trip; on completion,
`_findAndStageThread` unconditionally called `renderEmailList()` to gray out
the newly-staged rows. All top-level views share one `#emailList` content
element, and `state.currentView` isn't updated when entering the Staged
Items (review) screen — so that trailing repaint overwrote the review
content with the inbox list while leaving the review chrome in place.

**Fix.** Track which screen owns the shared content area
(`state.activeScreen`), set by every `show*View` entry point. On stage
completion, repaint the *active* screen:
- review → `renderReviewView()` (now exported) so the thread's emails
  appear immediately, no manual re-navigation
- mail → `renderEmailList()` (previous behaviour)
- any other screen → leave it; it renders correctly on return

Touched all eight screen entries (mail, review, settings, vault, trash,
starred, backups, folder-selection) because they all render into the one
shared element — flagging only two would just move the clobber to a third
screen. Added the `state` import to settings.js and backups.js, which
lacked it.

### Verification

`node --check` clean on all 10 touched files; ESLint read-only-binding
sweep clean. Frontend only — the Python suite doesn't exercise this;
awaiting Rick's live re-run of the stage→navigate sequence.

### Commits

- `9665477` — Fix stage-thread hybrid view: repaint the active screen on
  completion
- (this entry) — docs: Session 55 log; changelog; navigation map counts

### On the horizon

Unchanged: dogfooding → `git tag v1.0.0` + website go-live →
`.deb`/`.dmg` packaging.


---

## Session 56 — July 3, 2026 (MacBook)

### Slow Sentinel backup: diagnosed (partially) + instrumented

Rick asked whether the slow backup was the office internet. It wasn't. Ran a
battery of live tests to Sentinel — all fast (3–4.6 MB/s) — and ruled out:
office/home internet, rsync directory scan (2s full-dir dry-run), the transport,
process QoS (the server runs at normal priority; a forced `taskpolicy -b`
transfer only fell to ~1.8 MB/s), and the iCloud-write/rsync race (faithful
replication → 4.6 MB/s). iCloud's `bird` uploader was active during the slow
18:11 window per the unified log, but only in seconds-long bursts — too short to
explain a 60s crawl. Could not reproduce the ~204 KB/s the real backups hit
(2026-06-26 and 2026-07-03, both ~204 KB/s); it's genuinely transient. Cause
unpinned.

Rather than chase a ghost, instrumented it. A wrapper script
(`~/Applications/mailrepo-ops/backup-sync.sh`, outside the repo — machine-specific
paths) runs the sync with identical terminal output and logs the outcome: a
one-line `OK` normally, and a full diagnostic snapshot only when a real ≥1 MB
transfer comes in under 1 MB/s — rsync summary, interface, iCloud `bird`
activity, `nettop`, top CPU, and an independent 12 MB throughput probe to
Sentinel (the datum that splits link-vs-flow). Log at
`~/Applications/mailrepo-ops/backup-sync.log`. Two script bugs caught during a
live test and fixed: a no-op re-sync's meaningless rate was falsely tripping the
SLOW branch (now gated on ≥1 MB actually sent), and the probe needed `-av` to
emit a rate line.

Tracked in `docs/Known_Issues.md` (new) so a future chat can pick it up cold.

**Manual step (Rick):** set MailRepo's post-backup command to
`/Users/rick/Applications/mailrepo-ops/backup-sync.sh`, replacing the raw rsync.

### Commits

- (this entry) — docs: add Known_Issues.md (slow-backup tracking + instrumentation)
  and register it in the Navigation Map. No repo code changed; the wrapper lives
  outside the repo.

### On the horizon

Unchanged: dogfooding → `git tag v1.0.0` + website go-live → `.deb`/`.dmg`.


---

## Session 57 — July 4, 2026 (MacBook)

### Review pass over the July 2–3 work (Sessions 50–56)

Rick asked for a second-opinion review of the recent commits, made in
sessions with another Claude instance. Scope: the three July 2–3 code
commits (`c1f3178` LIST cache, `f51eac4` batched Gmail delete,
`9665477` stage-thread hybrid-view fix) plus the earlier unreviewed
frontend work (`430f48b` move-email partial failures, `a7eb5f5` /
`93d9ce8` folder-picker standardization, `8b4ae15` export const→let).

### Findings

**Clean, verified by inspection:**
- LIST cache: resets on connect, populated only on success, no caller
  mutates the returned list.
- Stage-thread fix: all `restoreDefaultHeaderActions` /
  `clearHeaderActions` call sites are genuine mail-screen entries, so
  the `activeScreen = 'mail'` claims are correct — the one place the
  pattern could have gone wrong.
- Folder-tree `isSelectable`: no string/number coercion bug
  (`parseInt` on dataset vs numeric ids on both sides);
  `setSelected(null)` exists and clears row highlights.
- Vault restore picker root/tree selection sync: correct in both
  directions.
- Move-email fix: per-move try/catch, only successes filtered from
  state; the unguarded repaint is fine because the modal blocks
  navigation during the await sequence (unlike thread staging).
- Repo-wide sweep: all 29 JS files pass `node --check` and eslint
  `no-const-assign`.

**Bug found and fixed — post-commit failure double-counting**
(commits `72bc4dc`, `ffe52db`):

The batched delete's post-batch re-select of the source folder
(needed: `apply_email_action` only re-selects on its Gmail-delete
branch, so remaining archive/trash items in the folder depend on the
caller contract) sat inside the folder-level try *after* batch
successes were counted and marked done. A connection death between
the batch and the re-select would hit the folder handler's
`failed += len(folder_items)`, recounting every already-handled item
— summaries like "3 succeeded, 3 failed" for 3 items, with done-marks
disagreeing with the numbers.

First fix (`72bc4dc`): guard the re-select; on failure count only
unhandled items, clear the folder cache for deletes that landed,
continue to the next folder.

Second fix (`ffe52db`): the account-level `except Exception` had the
same recount bug one level up (a non-IMAPError escaping mid-folder,
e.g. malformed item_data, added `len(account_items)` over items
already counted). Replaced the folder-scoped `handled_ids` with an
account-scoped `accounted_ids` set, updated at every point an item is
definitively counted; both outer handlers now count only unaccounted
items.

Also from the review's minor findings (`ffe52db`): the UID sort
comment in `delete_emails_via_trash` wrongly claimed the sort was
needed for COPYUID parallelism (the map zips the server's own
response sets) — rewritten, with a tuple sort key so a stray
non-numeric UID can't TypeError; and `list_folders()` now returns
shallow copies so callers can't poison the cache.

### Notes

- Coverage observation for Rick's consideration: nothing in the test
  suite drives `_apply_post_actions_from_pending` directly (SSE
  generator scaffolding cost) — the accounting layer is verified by
  inspection only. This neighborhood has now produced two bugs
  (Session 46's dead-dispatch, this recount). Might warrant a Tier
  reconsideration in `Test_Coverage_Plan.md`.
- Verification: full suite 353 passed (pre-change baseline); the 71
  imap/commit tests re-run green after each change; ruff clean;
  eslint + node --check clean across all 29 JS files.

### Commits

- `72bc4dc` — Fix double-count when post-batch folder re-select fails
- `ffe52db` — Unify post-commit failure accounting; harden two review nits
- (this entry) — docs: Session 57 log; changelog; navigation map counts

### On the horizon

Unchanged: general dogfooding, then tag + website go-live, then
`.deb`/`.dmg` packaging. The July 2–3 work is now fully reviewed and
signed off. Sentinel slow-backup instrumentation (Session 56) remains
armed, awaiting a recurrence.


---

## Session 58 — July 11, 2026 (MacBook)

### Slow Sentinel backup: RESOLVED — office network shaping, not a MailRepo bug

The black box from Session 56 caught the slow run live (211,561 B/s, 60s), and
the snapshot's independent probe was *also* slow (241 KB/s) — which per the
decision rule pointed at the link, not the backup flow. New detail from Rick:
**it only ever happens at his counselling office, never at home.**

Chased two wrong theories before landing it, both recorded in
`docs/Known_Issues.md` so they aren't repeated: a supposed MTU misconfiguration
(the Tailscale interface is `utun8`, not `utun0` — and it was already at the
correct 1280), and a PMTU black hole (forcing the MTU to 1200 changed throughput
not at all; the ping-probe "drop line" simply tracks the interface MTU, which is
normal).

**What settled it: an asymmetry test.** Download from Sentinel 16.8 MB/s; upload
to Sentinel ~216 KB/s — same tunnel, same route, same moment, 80× slower one way
only. No MTU/routing/relay fault can do that; only outbound traffic shaping can.
Combined with Speedtest at the office reading 351/52 Mbps (ordinary TCP/443 is
untouched), a *pinned* rate across weeks (204,513 / 204,046 / 211,561 / 216,134
B/s — a flat ceiling, not congestion), and office-only occurrence: the office
network rate-limits outbound WireGuard-style UDP (port 41641).

Raw `ssh … 'cat > /dev/null'` — no rsync, no iCloud, no MailRepo — is equally
slow, so the app is not involved at any level. Nothing to fix. Issue closed;
`Known_Issues.md` rewritten as RESOLVED with the evidence, the dead ends, and the
options (accept it / Tailscale over TCP 443 / skip the sync on the office SSID).
The backup-sync black box is retained — it did its job and remains useful.

**Follow-up for Rick:** if `utun8` is still at MTU 1200 from testing, restore it
with `sudo ifconfig utun8 mtu 1280`. (The stray `utun0` change is harmless — those
transient interfaces are recreated by macOS.)

### Commits

- (this entry) — docs: Known_Issues.md rewritten as RESOLVED; Session 57 log.
  No code changed.

### On the horizon

Unchanged: dogfooding → `git tag v1.0.0` + website go-live → `.deb`/`.dmg`.


### Session 58 addendum — office-skip implemented; diagnosis independently verified

Second-opinion pass over the diagnosis (separate chat, same day): confirmed
`sentinel` resolves to the Tailscale IP; live re-ran the asymmetry test from
the office network (upload 237 KB/s vs download 2.75 MB/s, same tunnel,
seconds apart — reproduces on demand); confirmed `utun8` MTU restored to
1280. Verdict stands. Also fixed the duplicate session number (this entry
was originally logged as Session 57; Session 57 was July 4). Open
consistency question for Rick: the July 3 fast retests (3–4.6 MB/s, incl.
the 19:42 wrapper run) require that he was already home that evening —
believed but unconfirmed.

Then implemented Known_Issues option 3, prompted by the weekly-full math:
`create_backup()` auto-promotes to a full every 7 days (uncontrollable
timing), and the last full shipped 222 MB — ~18 min of blocked logout at
office rates. `backup-sync.sh` (ops dir, outside the repo) now skips the
Sentinel sync when the Wi-Fi SSID matches
`~/Applications/mailrepo-ops/office-networks.conf`, logging a `SKIP` line
and exiting 0; rsync catches up on the next non-office backup. Live-tested
at the office: 15 ms, clean skip, logged. The SSID never entered the repo
or the chat (written shell-side into the conf).

### Commits (addendum)

- `6da3f8a` — docs: fix duplicate session number (July 11 is Session 58)
- (this entry) — docs: Known_Issues option 3 implemented; Session 58 addendum


### Session 58 addendum 2 — pending-flag catch-up (Rick's design) + launchd trigger

Rick spotted the gap in the plain SSID skip: MailRepo only invokes the
post-backup command when a backup was actually *created*, so a no-changes
home logout would never push office-skipped backups — Sentinel could stay
stale indefinitely. (Verified in `web/blueprints/auth.py`: `post_cmd` runs
inside `if result:`, and `create_backup()` returns None on no changes.)
Also found while verifying: the post-backup command runs under a **300s
subprocess timeout**, so an office weekly full (~18 min at shaped rates)
would have been killed incomplete at 5 min — the earlier "blocks logout
~18 min" claim was wrong in the worse direction. Corrected in
Known_Issues.md.

Fix per Rick's design, kept entirely ops-side (no MailRepo change): the
office skip now touches `.sentinel-pending`; a launchd agent
(`ca.mailrepo.sentinel-catchup`, StartInterval 1800) re-runs
`backup-sync.sh --catchup`, which exits silently unless the flag is set
and the machine is off the office network, then runs the normal sync
(which clears the flag on success). launchd runs have no 300s cap, so
even a large pending full catches up reliably, within ~30 min of leaving
the office. Live-tested all three paths at the office: skip sets flag;
--catchup at office is a silent no-op; --catchup off-office (simulated by
moving the conf aside) logs CATCHUP, syncs (1s no-op), clears the flag.
Agent bootstrapped and verified loaded.


### Session 59 — July 12, 2026 (Apollo): website accuracy audit vs source

Full pass over the draft website (`/home/rick/Websites/mailrepo-website`)
comparing every checkable docs claim against the codebase, per the
verify-against-source principle (CHANGELOG was not trusted — good thing,
see below).

**Docs.html held up almost perfectly.** Verified against source: themes
(Pine/Graphite/Atlantic/Ember/Obsidian), fonts (Lexend/Libre
Baskerville/Source Sans, S/M/L), folder cache TTL (2 min =
`FOLDER_CACHE_TTL_SECONDS = 120`), backup frequency options + daily
default, retention options + forever default, trash auto-purge (default
never; 7/30/90/365), auto-logout (30 min default; 15/30/60/120/never),
thread staging limit (500 default; 100–2,000), Gmail delete-via-Trash
description incl. ~30-day fallback, keyboard shortcuts (j/k/s/Esc), FTS
columns, 12-char passphrase minimum, "Load remote images" export option,
Yahoo IMAP entry. Sessions 47–58 required no new documentation (internal
work; user-visible pieces already covered).

**One real docs gap, fixed:** the "Changing your passphrase" section
never mentioned the non-overridable backup-≤24h precondition
(`core/password_change.py`, `MAX_BACKUP_AGE_HOURS = 24.0`). Added a
paragraph explaining the requirement, the rationale (rekey window not
resumable), and the remedy (Backup Now, retry).

**Website link fix:** footer GitHub links on all four site pages
(index_final, why, docs, download) pointed at bare `github.com`; now
`github.com/rsembera/mailrepo`.

**CHANGELOG [1.0.0] section was stale in three places, corrected:**
- Themes listed as "Pine, Lagoon, Graphite, Midnight, Atlantic" —
  actual (per `themes.css`): Pine, Graphite, Atlantic, Ember, Obsidian.
- "Configurable retention (default 6 months)" — actual default is
  forever (`web/blueprints/backups.py`); options now listed.
- "Session-based backup" — system is schedule-based (session / daily /
  weekly / manual, default daily); 7-day full cycle confirmed in
  `utils/backup.py` and retained.

Launch gaps unchanged and known: live index.html is the Coming Soon
placeholder; index_final.html screenshot placeholders still pending.

### Commits

- (this entry) — docs: CHANGELOG 1.0.0 corrections; Session 59 log.
  No code changed.
- Website repo: docs.html 24h-backup note + GitHub footer links (all
  pages), pushed to Sentinel.


### Session 59 addendum — July 13, 2026 (Apollo): Ubuntu floor verified, 22.04 → 24.04

Pre-packaging verification of the website's "Ubuntu 22.04 LTS or later"
claim. Findings: README states Python 3.11+ as the floor; Session 44's
formatter pass deliberately preserved 3.11 (not 3.10) compatibility;
dev/test runs on 3.13. Ubuntu 22.04 ships Python 3.10 — below the floor
and never tested. Unless the eventual .deb bundles its own interpreter
(undecided, heavier build), the honest claim is 24.04 LTS (Python 3.12).

Website updated accordingly: docs.html requirements section +
download.html (card and sysreq grid), 22.04 → 24.04. Revisit only if
the .deb ends up shipping a bundled interpreter. No code changed;
pyproject.toml left untouched (pytest-config only; adding a [project]
section just for requires-python has tooling side effects).


### Session 59 addendum 2 — July 13, 2026 (Apollo): packaging guides drafted from EdgeCase

MailRepo had no packaging docs; EdgeCase has proven, shipped guides
(`Linux_Packaging_Guide.md`, `Mac_Packaging_Guide.md`) plus a working
py2app → sign → notarize → staple → DMG pipeline. Two findings that
revise earlier estimates:

- **Rick already holds a Developer ID certificate**
  (`RICHARD L SEMBERA (2GKBD5N2AH)`) with a notarytool keychain
  workflow — the "Apple enrollment is the calendar blocker" concern
  is moot. One-time step: create a "MailRepo Notarization" profile.
- **EdgeCase is a pywebview app** (desktop.py, PyGObject/GTK) — the
  native-window pattern recommended post-1.0 for MailRepo already
  ships in EdgeCase and is directly reusable when we get there.

Drafted `docs/Linux_Packaging_Guide.md` (154 lines) and
`docs/Mac_Packaging_Guide.md` (115 lines), adapted from EdgeCase with
MailRepo deltas called out and [VERIFY] markers for the live session:

- Data dir: launcher exports `MAILREPO_DATA_DIR` (hook already in
  `core/config.py` — no code change needed; ~/.local/share/mailrepo
  on Linux, ~/Library/Application Support/MailRepo on macOS).
- WeasyPrint: Pango/HarfBuzz Depends on Linux; Homebrew dylib
  bundling + rpaths on macOS is the expected long pole (no EdgeCase
  precedent — it uses reportlab).
- PST import: Depends: pst-utils on Linux; macOS [DECIDE] bundle
  readpst vs. graceful degradation (guide recommends degradation
  for 1.0).
- sqlcipher3: follow EdgeCase's macOS source-build-against-local-
  libsqlcipher recipe.
- py2app gotchas carried over: explicit `includes` for every module,
  `'argon2'`+`'_argon2_cffi_bindings'` in packages, pyproject.toml
  rename dance, sign-all-binaries-individually-first.
- TO CREATE: icon set (packaging/icons/), icon.icns,
  dmg_background.png, setup_app.py, single-instance/port handling in
  the launcher, possible requirements-runtime.txt split.

No code changed.
---

## Session 60 — July 18, 2026 (MacBook)

### Backlog cleared; office-shaper theory revised; catch-up mystery opened

Rick asked whether Thursday's office backup had reached Sentinel. It had
not — and unpacking why turned over two separate stones.

**The backlog.** Last successful sync was Jul 11. Pending: Jul 13 incr,
the Jul 15 weekly full (222.9 MB), Jul 16 ×2, Jul 17, Jul 18 incrs —
~285 MB. The Jul 17 14:14 catch-up had fired ("off office network") but
died 15s in with ssh I/O errors (likely lid-close/network transition);
the flag correctly survived. Every check since ran on office Wi-Fi.

**The mystery.** Rick worked at home the morning of Jul 18 with the flag
set — the backlog should have shipped and didn't. launchd events at 09:18
and 09:54 (interval-consistent) suggest the agent ran and silently
declined, but the catch-up's decline paths logged nothing — the same
diagnosability sin fixed in MailRepo in Session 47, reproduced in my own
ops script. Fixed: every --catchup invocation now logs one line to
catchup-debug.log (pending state + SSID verdict) regardless of outcome.
Open question for Rick: do home and office Wi-Fi share a name? Tracked as
OPEN in Known_Issues.md; next home session settles it.

**The theory revision.** Cleared the backlog manually from the office —
and all 285 MB shipped in 55s at 5.2 MB/s over a confirmed direct IPv6
path. The same office network that pinned a probe at 237 KB/s seven days
earlier. The static "office shapes outbound tunnel traffic" verdict is
falsified; the throttling is conditional (leading guess: load-adaptive
QoS; condition unknown). Retires the July 3 anomaly. Known_Issues.md
revised accordingly — the skip+catch-up design is unaffected either way.
Possible future refinement: throughput-probe-based skip instead of SSID.

### Commits

- (this entry) — docs: Known_Issues revision + OPEN item; Session 60 log

### Session 60 addendum — SSID collision ruled out; trigger hardened

Rick confirms home and office SSIDs are entirely different. That rules out
the shared-name misfire and implies the script never ran during the home
window (the un-instrumented code would still have logged CATCHUP/WARN given
flag-set + non-matching SSID; the log has neither). Suspect: the launchd
StartInterval trigger itself during that session. Hardened: interval
1800→600s, plus WatchPaths on /Library/Preferences/SystemConfiguration so
joining a network fires the check on arrival. Agent reloaded, verified
firing and logging (runs=1, correct verdict at office). Next home session's
debug log is the decider.

Bonus finding from the debug log: the old timer fired at 11:35:27 — inside
the brief window when the conf was moved aside for the manual push — and
started a second, concurrent, harmless sync. Sloppy on my part (the conf
move created a race); no damage, and it proves the interval timer was
firing at the office today, further isolating the failure to the morning
home window.


---

## Session 61 — July 20, 2026 (MacBook)

### Root cause found: the office-SSID conf contained the literal string `<redacted>`

Rick checked in on whether the weekend synced. Short answer: nothing was
pending (no MailRepo backups since the Sat 11:20 office run, which the
Sat manual push covered) — but the debug log showed 490 of 496 catch-up
invocations reporting `ssid=matches-conf` across BOTH locations. Rick's
SSIDs: office `waverley361`, home `NCF_1639098` — entirely different,
both 11 chars. The conf: 11 bytes = 10 chars + newline. Neither name is
10 characters. The conf contained the macOS location-permission
placeholder: modern macOS redacts SSIDs from CLI tools (`ipconfig
getsummary`, `system_profiler` both verified), so the Jul 11 shell-side
capture wrote `<redacted>` — which then "matched" every subsequent
redacted read, on every network on earth. Skip-everywhere since Jul 11.
(The Jul 11 privacy measure of keeping the SSID out of the chat was
unwittingly perfect: there was never an SSID in the pipeline at all.)

One cause explains every anomaly: the Sat-morning home declines were
real declines (trigger fine; launchd suspicion retracted — the 600s +
WatchPaths hardening was aimed at nothing but is harmless and kept);
the lone spontaneous catch-up (Jul 17 14:14) fired only because Wi-Fi
was unassociated in transit, hence the guaranteed I/O-error death.

### Fix — gateway-MAC discriminator, fail-open (per Rick: skip ONLY at 361 Waverley)

`backup-sync.sh` rewritten: skip only when the current default gateway's
MAC matches `office-gateways.conf`; sync on no-conf / unreadable /
no-match. No permissions, no redaction, also covers wired office
connections. New `--mark-office` mode appends the current gateway MAC to
the conf. Poisoned `office-networks.conf` deleted. Verified at home:
gateway MAC reads cleanly (92:aa:c3:34:dc:71), catch-up logs
`gw=no-conf` and exits silently. **Pending: Rick runs
`backup-sync.sh --mark-office` once at the office**; until then the
wrapper syncs everywhere (safe direction).

### Commits

- (this entry) — docs: root cause + gateway-MAC fix; Session 61 log


---

## Session 62 — July 24, 2026 (MacBook)

### Weekly full over iPhone tether: carrier shaping confirmed; constrained-link skip added

Weekly full (223.4 MB, 10:19) ran while Rick was at the office tethered
to his iPhone. Live measurement: 221 KB/s on a **confirmed direct IPv6
Tailscale path** (DERP-relay hypothesis tested and killed) — the pinned
throttle signature, now observed on a carrier tether. MailRepo's 300s
timeout killed the sync as predicted (~110 MB cellular burned across two
attempts). Backup itself safe in iCloud. EdgeCase note: it "syncs fine"
tethered because 750 KB at 221 KB/s is ~3.5s — same shaping, invisible
payload, same lesson as the office chapter.

Rick confirms he was (probably) NOT tethered during the July office slow
events, so the office attribution stands for those — but because of the
`<redacted>` bug we never truly knew the network for any of them.
Plan: throughput-probe `waverley361` before deciding whether it enters
the skip list at all (Saturday's 5.2 MB/s may have been its normal self).

### Fixes (ops wrapper)

- **Failed syncs now set the pending flag** (previously only office
  skips did — a killed/failed sync left nothing for the catch-up to
  retry). Note: MailRepo's timeout SIGKILLs the whole wrapper, so a
  timeout-killed run still can't set it; the flag was set manually today.
- **Constrained-link skip:** cellular tethers are IPv6-native (CLAT
  IPv4 gateway 192.0.0.1, NOARP — no gateway MAC exists to match), so
  MAC-based marking can't work there. macOS flags hotspot/expensive
  links as `constrained` on the interface; the wrapper now skips (and
  flags) on any constrained default route — covers any phone, any
  hotspot, no per-device marking. Distinct SKIP log lines for
  tether vs office-gateway; catch-up debug gains `gw=constrained-tether`.
- Both paths live-tested on the tether: SKIP + flag set + catch-up
  declines. Tonight at home: unconstrained, no conf match -> the 223 MB
  full ships automatically (~10s).

### Commits

- (this entry) — docs: Session 62; tether shaping + constrained-link skip

### Session 62 addendum — `--status` mode

Added `backup-sync.sh --status`: one command prints pending state, the
current network verdict (regular / constrained tether / office gateway),
and the last sync and skip log lines. Rick can check the sync system's
health at a glance without reading logs.

---

## Session 63 — July 24, 2026 (MacBook)

### Fix: spurious "Unsaved Selections" after Stage conversation

Rick selected an email, then staged its whole conversation, then got
"You have 1 email selected but not staged" on navigating away.
Root cause: thread-stage.js staged into state.staged but never pruned
state.selectedEmails, violating the selected/staged mutual-exclusion
invariant (selectEmail refuses staged emails; the reverse order had no
guard). Fixed by calling clearEmail() for any thread message currently
selected (probing both raw and String() key forms — selection keys are
dataset strings), which also refreshes the Stage (N) counter.
node --check + eslint clean. Commit 2fd9bbf.

### Session 63 addendum — waverley361 acquitted; case closed

The 12:16 catch-up shipped the morning full (223 MB) minutes after Rick
left the tether — over office Wi-Fi at ~5 MB/s. Evening incrementals
likewise ~5 MB/s. Every verified waverley361 measurement is fast; conf
stays empty; constrained-tether is the only deferral. Known_Issues
updated: probe question CLOSED.

### Session 63 correction — the morning full SHIPPED over the tether

Sentinel ctime: the 223.4 MB full landed complete at 10:25:38 over the
tether. MailRepo timeout=300 killed only the shell; orphaned rsync
finished 62s later; the UI reported failure for a success (backlog:
kill process group / async post-backup). True average 617 KB/s with ~5x
acceleration -- the flat-221-KB/s claim was bad arithmetic; tether
shaping UNCONFIRMED. The manual 10:26 pending flag chased a delivered
full all afternoon (the WARN storm; zombies re-arming via the new
touch-on-failure path). Constrained-skip kept on corrected grounds
(metered data + timeout misreporting). waverley361 acquittal stands.
Three wrong narratives corrected in one evening -- ctime over stories.

### Session 63 (cont.) — strip-down + honest timeout: spinner bounded, completion guaranteed

Per Rick, simplified to ONE RULE: defer Sentinel syncs on constrained
(metered/tether) links, sync everywhere else. Removed from the ops
wrapper: --mark-office, office-gateways.conf, gateway-MAC functions (all
born of the falsified office-throttle theory). Added: PID lockfile with
stale-lock stealing (the Jul 24 flag-flapping was overlapping zombie
runs) and PRE-ARMED pending flag (touched before every real sync,
cleared only on success — crash-safe by construction, replaces
touch-on-failure which could not survive a process-group kill).

MailRepo (cec22a6): run_shell_command now owns the process group
(start_new_session) and on timeout kills it wholesale, returning a
truthful message + stdout; auth.py logout path routes through it (was a
third inline subprocess.run). This is the fix for the morning finding:
orphaned rsync completing after a reported timeout.

Net guarantee Rick asked for: spinner time is hard-capped at 300s worst
case (instant on tethers, seconds on regular networks); sync completion
is decoupled and guaranteed by flag + catch-up, which has no timeout.
20-minute spinners are structurally impossible. All wrapper paths
live-tested (status, catchup silent/decline, lock contention, pre-arm +
clear on a real sync). Full suite 353 green.

## Session 64 — July 26, 2026 (MacBook)

Started as a release-readiness estimate and a "should we do Windows?"
question. Both answers moved, and a security bug surfaced on the way.

### Security fix: no more silent plaintext archive

core/database.py fell back to plain sqlite3 when sqlcipher3 failed to
import, and SQLCIPHER_AVAILABLE gated exactly one thing — the PRAGMA
key line. Three references in the whole codebase, all in that file.
Consequence: a missing sqlcipher3 produced an unencrypted archive with
an identical passphrase prompt, identical UI, identical success path,
no error and nothing logged. For an encrypted mail archive sold to
lawyers and therapists this is the one failure that must never be
quiet, and it is precisely what a packaged build without the native
extension bundled would produce.

The fallback dated to the original SQLCipher migration (9f136c6) —
migration-era scaffolding nothing had depended on since.

Added SQLCipherUnavailableError + require_sqlcipher(), called in
get_connection() BEFORE Config.get_database_path() and
sqlite3.connect(), since plain sqlite3 would otherwise create the file
before anything could object. PRAGMA key is now unconditional. The
plain-sqlite3 import stays so the module remains importable (the
sqlite3.Connection annotations and the error text itself need the name
bound) but can no longer reach the archive. main.py fails fast at
launch on stderr with exit 1, before the pending-restore path.

Four tests, incl. one asserting no file appears on disk when the guard
fires and one reading the live archive's bytes for a plaintext SQLite
header. Full suite 357 green (353 + 4). ruff clean. Commit 38127a6.

core/sync_cache.py deliberately uses plain sqlite3 for transient IMAP
folder state outside the encrypted DB — intentionally untouched.

### Windows spike (branch spike/windows, run 30208317114)

Rick has no Windows machine, so GitHub runners stood in. Six probes,
windows-latest, py3.11 and py3.14. Result: both rows identical.

Corrections to my own pre-spike estimate, which was wrong twice:

1. sqlcipher3 0.6.2 ships prebuilt Windows wheels — win_amd64, win32
   AND win_arm64, cp39 through cp314. I had claimed no Windows wheels
   exist; that was true of pysqlcipher3 and old sqlcipher3, stated as
   current fact without checking. requirements.txt already pins
   >=0.5.0, so a bare pip install on Windows pulls a wheel today.
   Verified live: cipher_version 4.12.0 community — same build as the
   Mac — real ciphertext header, canary absent from the file. Windows
   encryption is fully functional.

2. The WeasyPrint seam needed no work. core/pdf_export.py is the only
   file referencing it, its imports are lazy (in-function, nothing at
   module level), and its sole consumer web/blueprints/api/exports.py
   also imports lazily, inside two functions that sit under the
   except Exception at exports.py:464. So a box without WeasyPrint
   starts fine and fails PDF export as a job error. My "forks your
   export architecture" claim was unfounded.

Test suite on Windows: 87 passed, 39 failed, 189 errors. Every one of
those 228 traces to a single POSIX idiom in three places:

    dir_fd = os.open(str(path.parent), os.O_RDONLY)
    os.fsync(dir_fd)

  - core/encryption.py:358  (_atomic_write_salt_file)
  - core/password_change.py:340
  - utils/backup.py:42      (_atomic_write_text)

Windows refuses os.open() on a directory outright — PermissionError
errno 13 — and has no directory-fsync equivalent. Note os.replace IS
atomic on Windows (MoveFileEx), so the atomic-write pattern itself
survives; only the durability-of-the-rename step needs skipping. That
does mean a genuinely weaker guarantee on Windows: NTFS journals
metadata, but it is not the POSIX guarantee. Document it, don't paper
over it. Three ~4-line platform guards, not 228 problems.

WeasyPrint failed as predicted: cannot load library
'libgobject-2.0-0' — GTK stack absent.

Revised estimate: the Windows *port* is small (1–2 sessions), and the
real remaining cost is packaging and code signing, not architecture.
Signing economics unchanged — hardware token or cloud HSM, ~$200–400/yr
OV, SmartScreen until reputation accrues. Not a 1.0 item; a credible
1.1 one.

### Release readiness

Source tag is effectively ready — engineering checklist closed, what
remains is dogfooding plus the website going live paired with the tag.
The decision that actually gates the date is what download.html
promises: source-install now and packages later, or installers on day
one. Recommended decoupling the two so the tag does not wait on py2app.

Tooling: gh installed and authenticated (HTTPS, matching the existing
origin remote; workflow scope requested explicitly, which the spike
push needed). Note gh auth login's Enterprise prompt will happily take
a local hostname and then fail against Tailscale MagicDNS —
`gh auth login --hostname github.com --git-protocol https --web` skips
every prompt that can go wrong.

Decided (Claude's call, at Rick's delegation):

Guards deferred to 1.1, not landed now. They are trivial in size but
they sit in the three most consequential write paths in the product —
the salt file, the password change, and the backup state. Changing
durability behaviour in those files immediately before a release tag,
for zero benefit to either platform actually shipping at 1.0, is a bad
trade. They land as part of the Windows workstream, where they can be
verified on Windows rather than reasoned about from a Mac.

Branch spike/windows kept. On a private repo a stale branch costs
nothing, and the workflow is the verification harness for the 1.1
guards — deleting it means writing it twice. It cannot interfere with
the tag: it triggers only on pushes to that branch or manual dispatch,
never on main.

### Session 64 addendum — UI/UX survey

Source-level only; Claude can read the frontend but not use the app, so
flow/clarity questions are untouched and remain Rick's to judge.

Recorded in Post_1_0_Backlog.md under a new "UI / UX" section. Two
items worth doing, one cosmetic, three explicitly closed.

Worth doing: (1) there is no non-blocking feedback channel at all —
showAlert is the only output path, 80 call sites, no toast/status
system in the JS. Every completion notice is a click-to-dismiss modal,
which taxes repetitive stage/commit cycles and trains users to dismiss
dialogs unread, undermining the confirms that matter. (2) The
dynamically-rendered UI has almost no ARIA — 7 aria refs and 2 roles
across 16,386 lines of JS. No focus trap in any modal; SSE progress
has no aria-live or role=progressbar; no prefers-reduced-motion against
76 transition/animation declarations.

Two corrections to my own first pass, both caught by Rick:

- I justified accessibility work with an institutional-procurement
  argument. That does not apply to a free AGPL tool for solo
  practitioners. The honest case is just that some practitioners are
  blind or keyboard-only. Argument withdrawn, finding kept.
- I led with "irreversible operations are one click away." Wrong.
  Verified: both Permanent Delete and Delete All Folders live in
  trash.js and act only on already-trashed items, so deletion is
  two-stage by design. Confirms name the specific folder, count
  affected subfolders, use specific verbs and danger styling. Recorded
  in the backlog under "checked and found correct — do not re-raise"
  so a future session does not burn time re-discovering it.

Also verified fine: 27 empty states; only 6 raw error.message leaks
frontend-wide; all 11 outline:none rules paired with a visible focus
replacement (5 use border-color alone, weaker than the box-shadow ones
— logged as cosmetic).

---

## Session 65 — August 8, 2026 (MacBook)

### Root cause: the launchd catch-up NEVER worked — macOS TCC blocked iCloud Drive

Rick spotted a backup on disk but not on Sentinel (the Aug 7 weekly
full, 224 MB, created on a tether and correctly deferred). Investigation
showed catch-up runs "succeeding" with sent=29 bytes — an EMPTY file
list. Cause: ~/Library/Mobile Documents (iCloud Drive) is TCC-protected;
bash spawned by launchd has no Files-and-Folders grant, so readdir
returns empty and rsync ships nothing, exit 0. Log audit: 199 of 201
historical CATCHUP OK lines sent exactly 29 bytes — the launchd
catch-up never shipped a byte since 2026-07-11. The two real CATCHUP
transfers were manual invocations from a TCC-blessed shell. Every
genuine Sentinel delivery to date came from MailRepo-invoked post-backup
runs (user-session permissions). The system appeared healthy only
because MailRepo backs up frequently in a blessed context.

### Fixes

- Wrapper guard: an empty-readable source now refuses loudly
  ("ERROR source empty/unreadable (TCC?)"), keeps the pending flag, and
  exits 1 — this failure class can never again masquerade as OK. The
  guard caught its first real case 60s after installation (kickstart
  raced the permission grant).
- Permission: Rick granted /bin/bash Full Disk Access (System
  Settings > Privacy & Security). Trade-off noted: any launchd bash
  script on this Mac gains file access; acceptable on a single-user
  machine with a controlled LaunchAgents dir.
- Verified end-to-end: kickstarted agent shipped the 224.5 MB full
  at 5.8 MB/s in 40s — the catch-up's first-ever real delivery. Flag
  cleared; --status clean; Sentinel confirmed current.

### Also observed, parked

- WatchPaths storm: catch-up fired every ~10s in bursts (12:22-12:25) —
  SystemConfiguration churn, cause unknown. Harmless under the lock +
  no-op cost; consider a debounce if it persists.

---

## Session 66 — August 9, 2026 (MacBook)

### Discussion session: password-change comparison verified; roadmap decisions queued

Verified a Daybook-project claim comparing sibling password-change
implementations — accurate on all points. EdgeCase (migrate_crypto.py):
own backup, rekey_v2 marker, auto-rollback on exception AND
startup-marker recovery after hard crash, .keyinfo committed last, via
rebuild-and-swap of the DB. MailRepo (password_change.py): in-place
PRAGMA rekey, non-overridable <=24h backup gate ("backup IS the recovery
path" — recorded rationale in Crypto_Refactor_Plan.md: SQLCipher's rekey
window is inherently non-resumable), resumable file walk, halt-loud on
neither-key corruption. The two designs are different answers to the
same SQLCipher constraint.

Also surfaced: the printable-recovery-key feature (envelope encryption)
was logged in Session 49 as "highest-leverage pre-launch item," then
silently vanished from later horizon notes — no drop decision recorded.
Status: idea, owned by nobody since June.

### Recommendations made to Rick (decisions pending, for a FRESH session)

1. Backup hardening (1 session): zipfile.testzip() the newest backup at
   the password-change gate AND after each weekly full is created;
   interruption marker + startup detection for password change (crash
   currently presents as "wrong password" with no guidance).
2. Restore drill (procedure, once, pre-tag): restore latest full to a
   scratch location, open, spot-check. Never yet exercised end-to-end.
3. Recovery key / envelope encryption: recommended PRE-tag (audience
   argument: lawyers/therapists forgetting passwords; sequencing
   argument: post-1.0 format change means shipping a second migration).
   3-5 careful sessions; requires reading encryption.py first; delays
   tag/website/packaging. Rick may instead decide to ship without it as
   a documented stance — EXPLICIT decision either way, recorded here.

Implementation deliberately deferred to a new chat: this session carries
a month of backup-saga context; crypto work deserves a clean one.

---

## Session 67 — August 9, 2026 (MacBook)

### Restore drill: first end-to-end verification of a v2 backup

Rick asked whether a restore had ever been exercised before he started
archiving real mail. It had — Session 34, February 8, 2026, on Mercury —
and it was real, not theoretical: that session fixed `complete_restore()`
never being called on startup, plus three restore-modal bugs. You only
find "the startup hook was never wired" by running a restore and
watching nothing happen.

But that verification was stale in a way that mattered. The v2 crypto
landed June 4 (`e59ca2b`, Argon2id + AES-256-GCM), and `9337954` then
stripped Fernet/PBKDF2 out entirely. February restored a **v1** archive.
Nothing had ever restored a v2 one. Also landed since: external backup
state file, atomic state/manifest writes, per-backup stored locations.

And restore had zero automated coverage — `tests/test_backup.py` tested
creation, change detection and baseline safety, but never
`prepare_restore` / `complete_restore` / `get_restore_points`.

Rick had no test database. He doesn't need one: `prepare_restore()`
extracts to staging and explicitly does not replace production files.
Ran the scratch-copy variant instead — zero contact with the live tree.

**Method.** Copied the Aug 7 full (224 MB) + Aug 8 incremental to
`~/Applications/mailrepo-ops/restore-drill-2026-08-09/` (outside the
repo). Both were materialised in iCloud, not evicted stubs. `testzip()`
clean on both. Replayed the chain exactly as `prepare_restore()` does
(full first, incremental over it, deleted-file handling included):
1,757 files, 224,338,277 bytes.

The backup carries its own key material — `data/.salt` (85 bytes, `MRC2`
magic, v2), `data/.secret_key`, `data/mailrepo.db`. It restores on a
machine that has nothing else. DB header is not `SQLite format 3`.

Wrote `verify_restore.py` (kept in the ops dir, reusable). It points the
real application code at the staging copy via `MAILREPO_DATA_DIR`, with
a hard guard that aborts if `Config` resolves anywhere else. Password
comes from `getpass` — never in the chat, never on disk. Rick ran it.

**Result: PASSED.** Argon2id derivation against the restored salt
produced keys that opened the restored DB. `PRAGMA integrity_check =
ok`, 27 schema objects, 3 accounts / 69 folders / 1,754 messages. 25
emails sampled across the full set decrypted and parsed as RFC822.

Cross-checked against live: 1,754 archive files on both sides, zero diff
in the file list, and the DB message count matches the file count
exactly — no orphan rows, no orphan files. The chain is complete, not
merely readable.

Scratch cleaned up (443 MB → 16 KB); the script was kept.

### Backup hardening

**The gate trusted the manifest.** `_latest_backup_age_hours()` read
`manifest.json`, took the newest `created_at`, and returned an age. It
never checked that the file existed, was fully written, or — given
backups live in iCloud Drive — had not been evicted to a placeholder.
The non-resumable rekey window could open with no recovery path behind
it.

The existing test fixture *demonstrated* the hole: it wrote a manifest
entry for `full_test.zip` and never created the file, and
`test_accepts_with_recent_backup` passed. The suite was green while
authorising a rekey against a phantom backup.

Replaced with `get_verified_latest_restore_point()` in `utils/backup.py`,
which reuses `get_restore_points()` (so the unit verified is the *chain*,
not one file) and opens every file in it: exists, non-zero, valid zip,
`testzip()`. Opening forces cloud materialisation, so eviction fails
here rather than at restore time. On failure: refuse and name what
broke. Deliberately **no** silent fallback to an older backup — a user
who believes they have an hour-old backup must not be handed one from
last week without being told.

**Interruption marker.** The DB rekey + salt rewrite is non-resumable; a
crash inside it leaves a half-rekeyed archive whose symptom is "invalid
master password". That is the most misleading message available to us:
the password is correct and the data is recoverable. Marker is written
before the window, cleared after, detected at startup next to the
existing pending-restore check. Message tells the user to try both
passwords before concluding anything, and names the backup verified
moments earlier. Marker writes are best-effort — a marker failure must
not abort a change that has already re-encrypted the archive.

**Robustness.** `get_restore_points()` raised `KeyError` on manifest
entries lacking `chain_id`, which would take down the restore screen and
turn a health check into a crash. Now skipped with a warning.

### Corrections to Session 66's queued recommendations

Item 1a was wrong. `verify_backup()` already existed at
`utils/backup.py:611` and already ran `testzip()` after every full
(484), every incremental (587), and the pre-restore backup (854).
"Add testzip after each weekly full" was already done. Should not have
been queued without reading the file.

Checked and found correct — do not re-raise: `_backup_metadata.json` is
absent from most backup zips. That is by design; line 577 only writes it
when an incremental actually has deletions.

### Tests

365 pass, up from 357. New: gate refusal on missing / truncated /
zero-byte backup files; marker lifecycle including a simulated crash
inside the rekey window; corrupt-marker handling.

### Commits
- `347c44e` — Password-change gate: verify the backup on disk, not just the manifest
- docs commit (this entry, CHANGELOG, Navigation_Map)

### Still open

- Restore still has no automated coverage. The drill is automatable
  against a synthetic fixture (build small archive → back up → restore →
  assert it decrypts); that is the regression that would have caught a
  v2-breaks-restore bug in June. Recommended before the recovery key.
- Recovery key / envelope encryption: unstarted. Decision on pre- vs
  post-tag still Rick's, still not recorded.

---

## Session 68 — August 9, 2026 (MacBook)

### Automated restore coverage (commit `feea063`)

Restore had zero automated coverage. It had been exercised by hand
exactly twice — Session 34 (Feb 2026, v1 crypto) and the Session 67
drill (v2) — with the crypto stack replaced wholesale between them.

`tests/test_restore.py`, 21 tests: the Session 67 drill automated. Round
trip (staged files decrypt to original plaintext; backup carries its own
key material; restored DB is not plaintext SQLite), incremental chains
(later additions included, deletions propagate, older points exclude
newer files), safety (prepare leaves production untouched, takes a
pre_restore backup, writes a pending marker; cancel is byte-clean),
completion, and `verify_restore_point_files` tested directly rather than
only through the password gate.

Verified by mutation, not by going green: disabling deleted-file
application and disabling the testzip report each failed exactly one
test, and only its own.

### Recovery key / envelope encryption

Rick approved implementation. Four increments, each committed separately.

**The design fork that shaped everything (recorded before writing code).**
The cheap migration would set the v3 master to the value the current
password already derives: rewrite one file, re-encrypt nothing, atomic
and reversible. It is wrong. If master == Argon2id(password, salt), that
password remains a permanent path to the master regardless of rewrapping,
so password change would stop actually revoking the old password — a
silent downgrade for exactly the users who change passwords because one
was compromised. Migration therefore generates a random master and
re-encrypts once, at the cost of one password change. Rick's call, taken
explicitly.

**`79d6270` — v3 envelope primitives.** Master becomes 32 random bytes
wrapped twice: Argon2id(password) and HKDF(recovery key). Everything
below the master is unchanged; archive ciphertext stays v2 format, only
the key file changes. MRC3 is fixed 190 bytes: magic(4) salt_pw(32)
wrapped_pw(61) salt_rk(32) wrapped_rk(61). No separate verification
token — a wrong password fails the GCM tag on the wrapper, which is the
check v2 spent 61 bytes on.

Recovery key: 20 random bytes → 32 base32 chars → eight hyphenated
groups. Base32 has no 0/1/8 so those can only be typos, mapped to O/I/B
on parse. Generated, never user-chosen, so HKDF suffices — Argon2id buys
nothing against a uniformly random 160-bit secret, and recovery unlock is
instant. Full HKDF with per-archive salt rather than expand-only, because
printed keys get reused.

**`8e5f34d` — unlock wiring.** `unlock()` handles both formats, both
funnelling through `_adopt_master()` so they cannot drift. Added
`unlock_with_recovery_key()` (refuses on v2 with a specific reason),
`initialize_v3()`, `salt_file_version()` / `is_v3()` /
`has_recovery_key()`. Load-bearing test: unlocking by password and by
recovery key yield byte-identical file and DB keys — divergence would be
a silent split-brain.

**`917f08b` — the migration.** Reuses password_change's rekey helpers
rather than growing a parallel implementation; the interruption marker
gained a `phase` argument so both operations share one mechanism.

A TEST CAUGHT A REAL FLAW. The first version claimed to be re-runnable
and was not. An interrupted run leaves files under a random master that
existed only in memory; a second attempt minted a FRESH master, so those
files decrypted under neither key and `_rekey_file` correctly halted as
corruption. The user-facing message would have walked someone straight
into that halt. Fix: the candidate master is persisted before the walk,
wrapped under the old file key, in `data/.v3_migration_state`. No new
exposure — encrypted under the key already protecting the archive —
deleted on success. Unreadable state halts and says restore from backup
rather than minting a new master, because starting fresh would strand
every already-converted file.

Ordering: key file written LAST, after the DB rekey. Until that write
lands the archive is still described by the v2 key file, so a crash
leaves a re-runnable migration rather than an unopenable archive.

**`ec06131` — password change as rewrap, plus rotation.**
`change_master_password` branches on version. v3 replaces the password
wrapper and stops. The non-resumable window disappears for password
changes, and the backup gate is deliberately NOT applied there: the
operation is one atomic file replacement, so after `os.replace` either
the old key file is intact or the new one is, with no in-between state
for a backup to rescue. Recorded in the docstring so it does not get
"fixed" back.

`rotate_recovery_key()` requires the current password, not merely an
unlocked session — otherwise anyone with a live session could mint a
durable second credential surviving the user's next password change.

### Tests

466 pass, up from 357 at session start. New files:
`test_restore.py` (21), `test_recovery_key.py` (40),
`test_crypto_migration_v3.py` (40).

### Process note

First attempt at `test_restore.py` used the `create_file` tool, which
writes to the sandbox container, not Rick's Mac. Caught when ruff
reported the file missing. Only Desktop Commander reaches the real
filesystem.

### Commits
- `feea063` — Automated restore coverage
- `79d6270` — v3 envelope encryption primitives
- `8e5f34d` — Wire v3 into unlock; add initialize_v3
- `917f08b` — v2 → v3 crypto migration
- `ec06131` — v3 password change as rewrap; recovery key rotation
- docs commit (this entry, CHANGELOG, Navigation_Map)

### Still open

- **Nothing is wired to the UI.** New installs still get v2;
  `initialize_v3` and `migrate_to_v3` are not called from anywhere. The
  archive on this machine is untouched and still v2.
- Needed next: setup flow showing the recovery key, migration prompt +
  progress, unlock-by-recovery-key on the login screen, rotation in
  settings.
- Docs: threat-model note that a printed recovery key is a second
  full-access credential.
- **Before migrating Rick's real archive:** scratch-copy drill, same
  pattern as Session 67 — copy the archive, migrate the copy, confirm it
  opens under both password and recovery key.

### Session 68 addendum — UI, upgrade flow, and a CSRF finding

**Migration drill against a real copy (before any UI work).** Copied
`data/` + `archive/` to a scratch dir, gave it its own self-contained
backup, migrated, verified. 1,754 files in **2.1 seconds — 845 files/s**.
My earlier estimate of "about what one password change costs" was too
pessimistic: the walk is plain AES-GCM and Argon2id runs once, not per
file. Content byte-identical under both password and recovery key; DB
opened under the recovery-key-derived key. Scratch deleted, so the key
printed to the terminal now opens nothing. Live archive untouched.

Also learned: the live archive's newest backup was 25.6h old, past the
24h gate. The gate refused, correctly. That shaped the upgrade UI —
it takes a fresh backup itself rather than refusing.

**`8617eaa` — recovery key UI.** Setup now uses v3 and shows the key.
The key is rendered directly into the setup POST response, never put in
the session: Flask sessions are SIGNED, not encrypted, so anything there
is readable in the browser cookie jar. Screens: one-time key display
(copy / print / download, confirmation checkbox, beforeunload guard,
print styles that strip everything but the key), recovery login, and
post-recovery password reset. `set_password_after_recovery()` exists
because `change_master_password` needs the old password to unwrap the
master, which this user by definition does not have.

A test caught a wiring bug: the new routes were not in the
`before_request` public-endpoint allowlist, so `/auth/login/recovery`
redirected to login — unreachable for exactly the person locked out.

**`9fb9a0d` — upgrade flow, rotation, CSRF fix.** `/auth/upgrade`,
reached automatically when a v2 archive logs in. Rotation lives in
Settings, gated on the current password so an unlocked session alone
cannot mint a durable second credential.

**CSRF: I reported a bug that does not exist. Corrected same session.**

The claim was that no frontend code sends `X-CSRF-Token`, so every POST
must be 403ing. It was wrong, and it reached CHANGELOG, Security_Audit
and this log before being caught. All three have been corrected and the
redundant `getCsrfToken()` calls removed.

The truth: a global `window.fetch` interceptor in `base.html` (line 126)
injects the header on every state-changing request, reading it from the
meta tag. It has been there since `461bf6b` (Feb 3), whose commit message
says so outright — "Global fetch interceptor auto-injects X-CSRF-Token
header — zero changes to existing fetch calls (47 call sites)." Call
sites correctly do not set it themselves. That is the design.

How the error was made, because the shape is worth remembering:

1. Grepped `web/static/js/` for "csrf", got zero hits, and treated
   absence in that directory as absence everywhere. The interceptor is
   an inline script in `base.html`, outside the search path. I had
   already read line 6 of that same file — the meta tag — and did not
   look further down it.
2. "Confirmed" it with a probe that returned 403 without a token. But
   Flask's test client does not execute inline JS, so it can never
   exercise the interceptor. The result was guaranteed by the method
   and said nothing about production.
3. Dismissed the disconfirming evidence. I noted twice that Rick uses
   `/api/backup/now` and folder creation daily and wrote "that can't
   be" — then continued instead of treating the contradiction as the
   signal. A daily-driven app cannot have all its POSTs failing.

The first probe attempt also returned a misleading 200, because
`authenticated_client` in conftest wraps `post()` and injects the CSRF
header automatically.

**One real finding does survive.** That `authenticated_client` wrapper
means the suite structurally cannot catch a genuine CSRF regression:
every test that posts through it gets a valid token whether the code
under test would have supplied one or not. Logged in the backlog; not
changed today.

**Security_Audit.md** was documenting PBKDF2 and Fernet — retired in
June. Added a Session 68 addendum and a threat-model section on the
recovery key as a second full-access credential, including what MailRepo
deliberately does not offer (no email-me-my-key, no escrow, no vendor
recovery path). The CSRF row was briefly and wrongly downgraded to ⚠️;
restored to ✅ with the interceptor documented.

### Tests

490 pass, up from 357 at the start of Session 67. Mutation-verified in
three places this session: restore deleted-file handling, the testzip
report, the post-login upgrade redirect, and the automatic backup on
upgrade each failed exactly one test, and only its own.

### Commits (Session 68 — six code, two docs)
- `feea063` — Automated restore coverage
- `79d6270` — v3 envelope encryption primitives
- `8e5f34d` — Wire v3 into unlock; add initialize_v3
- `917f08b` — v2 → v3 crypto migration
- `ec06131` — v3 password change as rewrap; recovery key rotation
- `8617eaa` — Recovery key UI: setup, recovery login, post-recovery reset
- `9fb9a0d` — Upgrade flow, rotation in Settings (commit message claims a
  CSRF fix; that claim is wrong — see the correction above)
- `2318644` + this entry — docs

More than the usual two commits per session, noted deliberately: the
work split into genuinely independent increments, each shippable and
separately revertable.

### Still open

- Nothing here has been used through a browser. Claude can read the
  frontend but not operate it, so every screen added this session is
  unverified in the way that matters — flow, wording, whether the
  one-time key display reads as urgent enough.
- `authenticated_client` injects CSRF headers, so the suite cannot catch
  a real CSRF regression (backlog).

---

## Session 68 addendum 2 — Rick opens the app

Three bugs, all found within minutes of actually clicking through, none
visible to a green suite. Recorded together because the pattern matters
more than any one of them.

**1. The upgrade refused its own backup (`664c73e`).** The page promises
"a fresh backup will be taken", then called `create_backup()`, which
auto-decides full vs incremental. With a recent full on disk it picked
incremental, and `create_incremental_backup()` returns None when nothing
has changed — exactly the case for an idle archive. Nothing was written,
so the gate still saw the 26.6h-old backup and refused. Fixed by calling
`create_full_backup()`, which always produces a restore point.

Compounding it: the refusal rendered in the red box directly under the
password field, so it read as "it keeps rejecting my master password."
The password was never wrong. The generic failure path now leads with
"your archive has not been changed and your password is unaffected."

**2. Both recovery-key buttons showed at once (`664c73e`).** "Add a
Recovery Key" and "Generate New Recovery Key" are mutually exclusive and
the JS sets `hidden` on whichever does not apply — but the browser's
`[hidden] { display: none }` is a UA rule and loses to `.btn`'s
`display: inline-flex`. Added `[hidden] { display: none !important }`.
Never specific to this screen: any `.btn` in the app using the attribute
was affected.

**3. Post-migration Continue landed on "Create New Archive"
(`a85adf8`).** The most alarming-looking and the most trivial.
`recovery_key_confirmed()` always redirected to `main.create_archive` —
right after first-run setup, wrong after a migration. Looked exactly
like the upgrade had wiped everything. It had not: 1,754 files, MRC3 at
190 bytes, no leftover markers. Context is now submitted as a hidden
field and the redirect branches on it.

### Rick's live archive is now v3, and verified

Migrated successfully. `mailrepo-ops/verify_live_v3.py` (read-only,
getpass for both credentials) confirmed against the real archive:

- key file MRC3, recovery key available
- unlocks with the master password; database opens, 1,754 messages
- 25/25 sampled real messages decrypt under the password
- **unlocks with the recovery key**; 25/25 decrypt; database opens under
  the recovery-key-derived key

That last block is the one that matters. A recovery key that has never
been exercised is a promise, not a feature.

### The lesson worth keeping

Every failure this session was in the seams, not the crypto. The
envelope, the migration and the restore path were each drilled against
real data and held. What broke was a backup helper's no-op-on-no-changes
behaviour, a CSS specificity rule, and a hardcoded redirect — none of
which any amount of reading would have surfaced, and all of which a
person clicking through found immediately.

Standing implication: for UI work, "tests pass" is not evidence the
feature works. It is evidence the logic is not obviously wrong. Rick has
to open it.

### Commits
- `92c1282` — Correct the record: the CSRF bug I reported does not exist
- `664c73e` — Fix upgrade refusing its own backup; fix `[hidden]` on buttons
- `a85adf8` — Fix post-migration Continue landing on Create New Archive

### Still open

- The remaining screens are still unclicked: the recovery login and the
  post-recovery password reset have never been used through a browser.
  Worth exercising once — the recovery key is known good, so the risk of
  trying is now essentially nil.
- `authenticated_client` injects CSRF headers, so the suite cannot catch
  a real CSRF regression (backlog).

---

## Session 69 — August 9, 2026 (MacBook)

Short session, one feature and two findings, both from Rick asking
questions rather than from anything Claude went looking for.

### The question: should credential changes re-encrypt old backups?

No, and this is standard rather than a MailRepo judgement call. Encrypted
backups are immutable snapshots; rotating a credential protects the live
system, not copies already written. FileVault, BitLocker, Time Machine
and password managers all behave this way.

Three reasons recorded in `Security_Audit.md`: backups are the artifacts
you need when something has already gone wrong, so rewriting the whole
corpus risks them for a partial benefit; it cannot reach copies on
Sentinel, in iCloud version history, or on external media, and partial
revocation produces unwarranted confidence; and it does not work at all
for pre-v2 backups, where there is no wrapper to swap.

The remedy for a genuinely compromised credential is to rotate AND
destroy backups predating the rotation. That is policy, not software.

### The real gap: restoring silently changes which credentials work

Restoring replaces the key file, so a backup opens with whatever was in
force when it was taken. Restore something from before a password change
and your current password will not open it — with nothing on screen to
say so. Restore a pre-migration backup and your recovery key stops
working, because the wrapper it lives in did not exist yet.

**`232a0ed`** — every restore point is now annotated. No passwords and no
crypto operations needed: each rewrap touches exactly one half of the
MRC3 key file and leaves the other byte-identical, so comparing SHA-256
prefixes of the two halves against the live key file says precisely which
credential moved. MRC2 vs MRC3 covers the recovery-key case.

Subtlety worth remembering: incrementals only carry changed files, so
most do not contain the key file at all. The one that lands on disk comes
from the LAST backup in the chain that has it. Reading the full's copy
would misreport every chain spanning a change.

UI: a badge per restore point plus the note repeated in the restore
confirmation modal — the last screen before an irreversible action is
where this actually helps.

Estimated one to one and a half sessions; took well under one, because
the fingerprint approach removed the need to try credentials at all.

### Finding: 102 of Rick's 181 restore points are unopenable

Of 181: 1 current, 78 predating recovery keys, and 102 whose key files
carry no magic at all. Those 102 span 19 Feb – 29 May and are v1
Fernet/PBKDF2, whose code was deleted in `9337954`. No current build can
open them. They had been sitting in the restore list looking like valid
options for two and a half months; reaching for one in an emergency would
have restored files nothing could decrypt.

They now say "Cannot be opened" in red rather than appearing usable.
Left in place for now — not deleting backups while a crypto change is
still settling.

### Finding: retention cleanup never ran on automatic backups

Rick asked whether auto-delete was working. It was not, though not for
the reason it looked like.

The retention default is `"forever"`, so nothing being deleted is
correct behaviour if the setting was never changed. But
`cleanup_old_backups()` was called from exactly one place: the manual
Backup Now endpoint. `_run_auto_backup_check()` — which runs on logout
and produces nearly every backup — took the backup and ran the
post-backup command but never pruned. A user who set retention to six
months would have had it silently apply only on days they happened to
click the button. Fixed.

### Commits
- `232a0ed` — Show which credentials each restore point needs
- (this entry) — retention on the automatic path, Security_Audit
  revocation section, docs

### Still open

- The 102 obsolete backups can be deleted once dogfooding settles
  (~1.2 GB across iCloud and Sentinel).
- Recovery login and post-recovery password reset still unclicked.
- Adversarial review before tagging; `git tag v1.0.0` after a week of
  ordinary use.
- EdgeCase recovery key port — fresh session in that project. The
  envelope layer should transfer nearly unchanged; the migration should
  use EdgeCase's existing rebuild-and-swap machinery rather than
  MailRepo's in-place approach.

---

## Session 70 — August 9, 2026 (MacBook)

**Code review of Sessions 68–69, and the fix for what it found.**

Rick asked for a review of the day's work (recovery keys, v3 migration,
restore-point credentials, retention fix). Read `core/encryption.py`,
`core/crypto_migration_v3.py`, and `core/password_change.py` in full,
plus `web/blueprints/auth.py`, the app-level auth/CSRF middleware, and
the `utils/backup.py` credential-fingerprint work. Ran the full suite
first: 502/502 in 16:44.

**Verdict on the crypto and migration: sound.** Random master wrapped
twice, subkey derivation untouched so v2 ciphertexts stay valid, key
file written last so a crash leaves a re-runnable migration, resume
state wrapped under the old key so a second attempt cannot strand
converted files. The no-backup-gate argument for the v3 rewrap holds:
one atomic replace, no partial state. The restore-point fingerprint
trick (fresh salt per rewrap → each half identifies its credential)
is correct.

**One real finding — fixed this session.**
`/auth/login/recovery/new-password` checked `authenticated` + unlocked
but never `session["via_recovery_key"]`, and its form POST carried no
CSRF token (the app-level CSRF check covers `/api/` paths only, via the
`X-CSRF-Token` header). Since `set_password_after_recovery()` requires
no old password by design, this was the only state-changing route
reachable with zero credential knowledge: any unlocked session could
replace the master password. That is exactly the capability the
rotation endpoint withholds by demanding the password — its own
docstring makes the argument. Fix: the route now requires a session
established by the recovery login (redirects to the archive otherwise)
and verifies a CSRF token; `post_recovery_password.html` carries the
hidden input.

**Consistency fixes alongside it:**

- `/auth/upgrade` POST now verifies a CSRF token too
  (`upgrade.html` carries it). The password requirement already stopped
  a blind cross-site POST from succeeding, so this one is about keeping
  every state-changing `/auth/` form on the same rule.
- Stale comment in the password-change SSE endpoint ("All archives are
  on v2") replaced with a description of the actual v2/v3 branching.

**Tests.** Ten existing POSTs updated to carry the token (via a small
`_csrf(client)` helper); three new tests:
`test_password_reset_requires_a_recovery_login` (password-login session
is bounced from GET and POST, password provably unchanged),
`test_password_reset_requires_csrf`, and
`test_upgrade_post_requires_csrf`. Suite: 505 tests.
`test_recovery_key_web.py` + `test_auth.py` re-run after the change:
53/53.

**Noted, not fixed (footnote-grade):** the credential fingerprint will
report "password changed" if someone re-sets the *same* password via the
recovery path — rewrap mints a fresh salt, so the halves differ even
though the password still works. The warning errs conservative;
harmless.

**Docs:** CHANGELOG (Security section), Security_Audit (new row in the
recovery-key measures table), Navigation_Map (auth.py 769 lines, test
counts).

The "adversarial review" item under Still open in Session 69's list is
now partly served: Sessions 68–69 have had a hostile read. Earlier
sessions' surfaces have not.

**Addendum:** the login screen's recovery link wrapped awkwardly
("...recovery / key"). Restructured as plain-text question + link
("Forgot your password? [Use your recovery key]"), sized as a footer
link, with the link phrase nowrap so any wrap lands at the sentence
boundary. Third commit this session.

---

## Session 71 — August 10, 2026 (MacBook, late)

Design question only; no code changed.

Rick asked whether MailRepo's recovery key acting as "a second password"
was a good idea, given EdgeCase links recovery-key use to a password
change. Claude answered from Rick's description first and got the shape
of EdgeCase wrong; Rick pushed back and said to read the codebase.
Reading it changed the answer materially.

**EdgeCase does not merely couple the key to a password change — the
recovery key cannot log you in at all.** `/recover` verifies the key and
hands a short-lived server-side token to `/recover/reset`, which exists
solely to set a new master password. No authenticated state exists
anywhere on that path. The key never enters a cookie; the master never
enters the session. After a successful reset it deliberately does NOT log
the user in, so they type the new password once while the recovery key is
still in their hand — the cheapest confirmation the password is what they
think it is.

**MailRepo's divergence is bigger than the missing force.**
`unlock_with_recovery_key()` grants a full authenticated session; the
"Skip for now" link is a symptom of that, not the problem itself. Left
alone, a user who skips will reach for the printed key at every
subsequent login, and a 32-character string used routinely ends up
photographed or pasted into Notes — the break-glass credential migrating
into everyday storage, gradually enough that nobody notices deciding it.

Filed under a new **Security** section in `Post_1_0_Backlog.md`, flagged
as worth doing before `git tag v1.0.0` because it changes the security
model rather than the implementation. Note the direction of travel: for
this feature EdgeCase is the reference and MailRepo is the port, the
reverse of the usual relationship.

**Method note.** Claude reasoned about EdgeCase's design from Rick's
one-line description rather than reading it, and produced a confident but
wrong account. Same failure shape as the CSRF episode earlier in the day
and the retention-setting claim: treating an inference about a system as
knowledge of it. EdgeCase was readable at
`/Users/rick/Applications/edgecase` the whole time.

### Machine notes for the next session

Work is machine-agnostic — Flask routes, templates, tests — so Apollo is
fine. Verified: Apollo reachable at Tailscale IP `100.86.191.115` (the
bare hostname `apollo` does not resolve from the MacBook; no `~/.ssh/config`
entry exists, unlike `sentinel`). Both repos present:
`~/Applications/mailrepo` and `~/Applications/edgecase`.

Apollo's MailRepo was at `e11e721`, one pull behind. `git pull` first,
and keep session numbering from colliding with entries written on the
MacBook.

Expect the full suite to be slower on Apollo — Argon2id dominates
runtime, ~7.5 min on the M4. Targeted runs against `test_auth.py`,
`test_recovery_key_web.py` and `test_crypto_migration_v3.py` cover this
change; background the full suite once at the end.

---

## Session 72 — August 11, 2026 (Apollo)

First session on Apollo since 66. Implements the Session 71 backlog item.

### Recovery key resets the password; it no longer grants a session

Adopts EdgeCase's design wholesale. Worth noting the direction: EdgeCase
was the reference and MailRepo the port, the reverse of the usual
relationship between them.

**Before.** `/auth/login/recovery` called `unlock_with_recovery_key()`,
granted a full authenticated session, set `session["via_recovery_key"]`,
and offered the password reset with a "Skip for now" link. That made the
recovery key a second password. Someone who skipped would reach for the
printed key at every subsequent login, and a 32-character string used
routinely ends up photographed or pasted into a notes app — the
break-glass credential migrating into everyday storage. The skip link was
the symptom; the session grant was the problem.

**After.**

- `Encryption.verify_recovery_key()` checks a key and deliberately
  discards the master, so verification leaves the archive locked.
- `/auth/login/recovery` verifies only, then mints a server-side handoff
  token. The key never enters a URL or a cookie — same reasoning as the
  existing password-change job store, since the session is signed but not
  encrypted. Single entry, 5-minute TTL.
- `reset_password_with_recovery_key()` unwraps the master from the key
  file using the key itself and rewraps under the new password. Needs no
  unlocked session, adopts nothing into class state. Replaces
  `set_password_after_recovery()`.
- The reset is mandatory. No skip link; the token is the only way in.
- After success the user is **not** logged in. They have typed the new
  password exactly twice; using it once more while the recovery key is
  still in hand is the cheapest confirmation it is what they think.
- `session["via_recovery_key"]` is gone — there is no session on this
  path to flag.

**CSRF.** The reset route carries no session token and needs none: a user
who forgot their password has no session. The handoff token is what stops
a forged cross-site POST — 32 bytes of urlsafe randomness, minted only
after a key verifies, never exposed to a page an attacker controls. The
old `test_password_reset_requires_csrf` was replaced by a test that says
this rather than deleted silently.

**Also.** A malformed key no longer spends a rate-limit attempt. A typo
is not a guess, and fumbling a 32-character string should not lock you
out of your own recovery path. Picked up from EdgeCase on the second
read; it was not in last night's notes.

### A bug the tests caught

`set_password_post_recovery` is now unauthenticated and had to join the
`before_request` public-endpoint allowlist. Without it the route
redirected to `/auth/login` — unreachable for exactly the person it
exists for. Identical in shape to the Session 68 recovery-login bug, and
caught the same way.

### Method note

Last night Claude described EdgeCase's design from Rick's one-line
summary and got it wrong. This session started by reading it. Two details
were not in the summary and would have been missed again: the
malformed-key rate-limit exemption, and the existence of a separate
`/recovery-key/verify` route for checking a key without changing
anything. The second is a genuine feature MailRepo lacks — see below.

EdgeCase on Apollo was 44 commits behind and had none of the recovery-key
work; `git pull` first, or the reference is not there to read.

### Tests

510 pass. Rewrote the recovery-login suite for the new contract and added
coverage for: the key not unlocking the archive, the key not appearing in
the redirect URL or the session, the reset not logging the user in,
single-use tokens, forged tokens, and an authenticated session being
unable to reach the reset.

Verified by mutation: restoring the session grant fails exactly
`test_recovery_key_does_not_unlock_the_archive` and
`test_reset_does_not_log_the_user_in`, and nothing else.

**Apollo timing:** full suite 11m17s, against 7m21s on the MacBook Air
M4 — roughly 50% slower, Argon2id dominating as usual. Targeted runs are
still quick.

### Still open

- **Not clicked through.** Same caveat as every UI change this week: the
  logic is tested via HTTP, but nobody has used the new two-step flow in
  a browser. Now more worth doing than before, since the flow changed
  shape rather than gaining a field.
- **`/recovery-key/verify` equivalent.** EdgeCase lets a logged-in user
  check their recovery key without changing anything. MailRepo has no
  such route — the Session 68 drill needed a CLI script. Users should be
  able to confirm the key in the drawer is the right one. Small, and
  worth adding before the tag.
- Rick's live archive is v3 and verified; this change does not touch
  stored data, only the route flow.

---

## Session 73 — August 11, 2026 (Apollo)

Continues directly from 72. Two things: the verify endpoint that 72's
change made necessary, and the first ever lint of the frontend.

### Check a recovery key without using it

Ports EdgeCase's `/recovery-key/verify`, fitted to MailRepo's shape as an
API endpoint plus a Settings control rather than a page, matching how
rotation already works.

Session 72 made the recovery reset mandatory, which was right but left a
gap: the only way to find out whether the key in the drawer opens this
archive was to use it and lose your password doing so. Rick needed a
whole test database to exercise the flow. The Session 68 verification
drill needed a CLI script written for the occasion. A key that has never
been tested is one you are only assuming works.

`POST /auth/api/verify-recovery-key` verifies against the live key file
and changes nothing — no password, no rotation, no unlock. The underlying
`Encryption.verify_recovery_key()` discards the master deliberately.

Gated on an existing session rather than the master password, following
EdgeCase's reasoning verbatim: someone with a live session already has
the archive open, so this reveals nothing they do not have and writes
nothing. Demanding the password would only discourage the checking the
endpoint exists to encourage.

Malformed key reports the length problem; well-formed wrong key says it
does not open this archive and suggests issuing a new one — the same
typo-versus-wrong-key distinction the recovery login makes.

Settings gains "Check Recovery Key" beside the rotate button, shown only
when the archive has one. Field cleared on close rather than left holding
the key for whoever passes the screen next. Added `.password-success`,
since the result reuses the `.password-error` slot and a successful check
must not render in the failure colour.

8 tests. The load-bearing one asserts the key file is byte-identical
afterwards and that both credentials still work.

### Node on Apollo, and the first lint of the frontend

Apollo had no node, so `settings.js` shipped in the previous commit
without even a syntax check. Debian 13 carries node 20 in its own repos —
no NodeSource needed. Rick installed `nodejs` and `npm`.

**`node --check` found nothing.** All 29 files clean, including
everything written this week. (Note for next time: `.js` parses as
CommonJS by default and these are ES modules, so `import` reads as a
syntax error — needs `--input-type=module` with the file on stdin.)

**ESLint found a real bug, in code nobody had touched this week.**
`app.js:304` assigned to `selectedDestinationFolder`, which is
module-local to `staging.js` and never exported. `app.js` is an ES module
and therefore strict, so this was not creating an implicit global — it
threw `ReferenceError`. The line sits inside a try/catch, so the
user-visible symptom was: create a new folder from the stage-email
destination picker, the folder IS created server-side, and the UI then
reports "Failed to create folder" and does not select it.

`staging.js` already exports `setSelectedDestinationFolder()` and
`app.js` already imports it on line 24. One call site simply never used
it. One-word fix.

Exactly the class of bug the Python suite cannot see: 518 tests pass, no
test executes any JavaScript, and the failure only appears when a person
clicks one specific control.

`eslint.config.mjs` is now committed rather than living in `/tmp` and
being recreated each time. Rules narrow and boring: `no-undef`,
`no-unused-vars`, and a few no-dupe/no-unreachable checks. No style
opinions, nothing that would churn the codebase.

```
npx --yes eslint@9 --no-config-lookup -c eslint.config.mjs \
  "web/static/js/**/*.js" --ignore-pattern "**/lucide.min.js"
```

State: **0 errors, 64 warnings.** The warnings are unused imports and
unused `catch (e)` bindings. Left alone deliberately — silencing 64
cosmetic warnings across 29 files would bury the signal the next time
something real appears.

Two of the original three "errors" were the config missing browser
globals (`TextDecoder`, `ClipboardItem`), not code faults.

**Honest accounting of the tooling:** the reason for wanting node was
syntax checking, and syntax checking found nothing. All the value was in
`no-undef`. Worth remembering when weighing similar tooling.

### Tests

518 pass (was 510). Full suite on Apollo: 11m36s.

### Still open

- **The Settings check control has not been used in a browser.** The
  endpoint is tested through HTTP; the button, field, and result styling
  are not. `.password-success` is a new class that has never rendered.
- The staging fix wants confirming by hand — Rick would recognise
  whether the old symptom matches something he had seen and worked
  around.
- Adversarial review, then `git tag v1.0.0` once the live archive has a
  week of ordinary use behind it (migrated Sunday, so end of this week).

---

## Session 74 — August 11, 2026 (Apollo, then MacBook)

The pre-tag adversarial review, and fixing everything it found.

Rick had a separate model review the codebase using the v2 prompt from
`Code_Review_Prompt.md`. It returned 23 findings. Rick's instruction was
"if we know about it, let's fix it" — so all of them were addressed
rather than triaged into a backlog, except one that was wrong.

### Method

Every reproducible finding was reproduced in a sandbox **before** any
code changed, and every fix was verified by reverting it and confirming
the right test failed. This mattered: the same discipline that caught the
phantom CSRF bug in Session 68 applies to confident claims arriving from
outside, not just to Claude's own.

The repro script for findings 1 and 2 hit **finding 6 unprompted on its
first run** — four backups inside one second, all with the same filename,
overwriting each other and invalidating the results. The review reported
that its own repro had done the same thing.

### Critical — both in the restore path

**1. Delete-then-recreate lost files.** `prepare_restore()` accumulated
deleted-file tombstones from every zip in the chain into one set and
applied them after all extractions. A file deleted in incremental N and
recreated in N+1 was extracted correctly, then removed by N's stale
tombstone — the restore reported success while reconstructing a state
that never existed. The trigger is ordinary use: permanently delete an
archived email, later re-commit the same message to the same folder, and
the path repeats exactly. Deletions are now applied per zip, immediately
after that zip's own extraction.

**2. A missing mid-chain incremental was invisible.**
`get_restore_points()` skipped an incremental absent from disk and kept
building the chain, producing a restore point of full + incr1 + incr3
with incr2 silently gone. Every verification layer reported it clean.

This is a hole in the Session 67 work, and worth stating plainly: that
change verified every file in `files_needed` opens. It never asked
whether `files_needed` was complete. The layer built to catch cloud
eviction was blind to eviction happening one step earlier.

### The rest

3. Retention could delete the only *working* restore point — it kept the
newest chain by date without checking it opened, and since Session 69
cleanup runs on every automatic backup, the deletion side executes daily.
Now verifies before pruning and skips loudly.

4. `/archive/create` had no CSRF protection — outside `/api/`, so the
middleware skipped it, and unlike the other non-`/api/` forms it carried
no manual check.

5. Orphaned `.v3_migration_state` extended an old password's reach. The
file wraps the *current* master under the *old* password's file key, and
the only cleanup site was unreachable once the archive was v3. That turns
"an old credential opens old data" into "an old credential opens
everything current".

6, 7, 9, 10 — filename collisions; safety backups collapsing to one
visible restore point; retention resolving paths against the current
directory and orphaning files after a location change; safety backups
going to the repo-local dir that never syncs off-machine.

8, 11, 13–15, 17–23 — unmarked v2 file walk; logout as a state-changing
GET; password-change jobs outliving their TTL; unguarded
`request.get_json()`; truncated key file reported as a wrong password;
three false comments; the last cross-module window global; secret-key
chmod race; platform-wrong clipboard hint; orphaned incrementals never
pruned; handoff token in the URL.

**Rejected: nit 16.** It claimed two unreachable consecutive `return`s in
`set_password_post_recovery`. They are at different indentation — one
inside the POST branch, one the GET fallthrough. Both reachable.

### Security_Audit.md

The June addendum flagged that the document predated the v2 migration,
but the tables below still asserted PBKDF2 and Fernet as current — and a
reader skimming to the encryption table is exactly the one who misses a
note at the top. The v1 table is now marked HISTORICAL and followed by a
current v3 table. Three further rows were stale: IMAP credential storage
still said Fernet, the public-endpoint whitelist omitted the two recovery
routes, and "CSRF validation: all state-changing requests validated"
overstated — which is precisely the gap that let `/archive/create` ship
without a token.

### Tests

535 pass (was 518). New regression tests for findings 1, 2, 3, 4, 5, 6,
7, 10 and 12, each verified by reverting its fix.

### Found by Rick, not by tests

Both move paths (single and multi-select) needed a human click-through
after the window-global conversion — that path has no automated coverage
at all. And the recovery-key check field was too narrow to show a
39-character key, which defeats the entire purpose of a control whose job
is comparing against the copy in your drawer.

That is five UI issues this week found by using the app and zero found by
the suite. The tests catch logic regressions; they are structurally blind
to whether anything is usable.

### Timing note

Full suite: 8m20s on the MacBook Air M4, 11m46s on Apollo.

One wasted run: a suite started on the M4 against freshly pulled code
while edits were being made in parallel, so it tested a mix of both.
Killed and re-run clean. Start the suite or edit, not both.

### Commits
- `b1206f7` — restore path: delete-then-recreate, mid-chain gaps, filename collisions, safety backups
- `97fc29f` — regression tests for the above
- `ab093ee` — retention safety, orphaned migration state, CSRF on archive creation
- `2525579` — findings 8, 11, 13–15, 17–20, 22
- `eab8524` — suggestion 12, nits 21 and 23, Security_Audit body
- `84727e6` — widen the recovery-key fields
- (this entry) — docs

### Still open

- `git tag v1.0.0`, once the live archive has a week of ordinary use.
  Migrated Sunday, so around Friday.
- The frontend still has no automated behavioural coverage. ESLint
  `no-undef` is the only check, and every UI failure this week was found
  by hand.

---

## Session 75 — August 11, 2026 (MacBook, evening)

Short session, one feature, prompted by Rick noticing a limitation while
using the app.

### Retention Vault: arbitrary retention periods

The Move to Vault modal offered 1/3/5/7/10 years as quick-select buttons
and nothing else. Statutory retention varies by jurisdiction and
profession — 15 years is common for medical records, and "life of the
client plus N" can exceed anything on that row. For an application aimed
at lawyers and therapists, the presets being the only fast path was the
wrong default.

Worth noting what did NOT need changing: the date picker already accepted
any date, and `move_to_vault` already took an arbitrary timestamp. This
was purely a UI gap — a faster path to something already supported.

`applyYears()` is now shared between the preset buttons and the custom
input so the two cannot drift. Choosing a preset clears the custom field
and vice versa, so the modal never displays one value while the picker
holds another. Invalid input (non-integer, <1, >100) shows a message and
deliberately does **not** touch the picker: silently leaving a stale date
selected while the field reads something else is how a folder ends up
with the wrong deletion date, and this modal's whole job is scheduling
the destruction of correspondence.

Also fixed an unguarded `request.get_json()` in `move_to_vault` — same
class as the ones the review flagged in `auth.py`, where a JSON-less POST
would 500.

### Two layout passes, both prompted by Rick

**`a001dd3`** — the field rendered wider than the entire preset grid
above it, for a box holding two digits. Cause was specificity, not the
`width` being wrong: `shared.css` sets
`.form-group input[type="number"] { width: 100% }`, a two-class selector
that beats a bare `.date-preset-custom input`.

That is the **second CSS specificity bug in a week** — the `[hidden]`
one in Session 68 was the same shape, a plausible-looking rule quietly
losing to a more specific one elsewhere. Worth generalising: `shared.css`
has broad `.form-group` rules that override module CSS unless matched in
shape. Both were invisible from reading the JS, and both were found by
Rick looking at the screen.

**`957768d`** — with the size fixed it still read as bolted on: an
"or __ years" line floating below a wrapped preset grid. Now a sixth chip
inside the grid itself, same height and radius as the buttons, dashed
border to signal "fill this in" against the five fixed options, solid on
focus. Wraps with them.

The first version was a field added to a form; the second was a control
designed into a row. Rick's "seems a bit messy?" was the difference.

### Tests

4 new in `test_api_folders.py`: a 15-year period, a 50-year period,
non-numeric input, and a missing date. 14 pass in that file. Full suite
not re-run — the change is confined to one endpoint plus CSS/JS, and the
endpoint's tests pass.

### Commits
- `de36e7d` — allow an arbitrary number of years
- `a001dd3` — size the custom field correctly
- `957768d` — fold it into the preset row
- (this entry) — docs

### Still open

- `git tag v1.0.0`, once the live archive has a week of ordinary use.
  Migrated Aug 9, so around Friday Aug 14.
- Then packaging (.dmg / .deb). The WeasyPrint Homebrew dylib bundling
  is the expected long pole.

---

## Session 76 — August 13, 2026 (Apollo)

Prove a new key wrapper opens before writing it. One day before the tag.

### Where this came from

Rick was working on Daybook and its recovery-key design, and a
comparison against EdgeCase surfaced a claim about MailRepo: EdgeCase
verifies a newly wrapped key actually decrypts back to the master before
committing it, and MailRepo checks only that the blob is well-formed.

Read cold against source, the claim held. `write_v3_salt_file` is two
lines: `parse_v3_salt_blob(blob)` — magic bytes and length — then the
atomic write. All three rewrap paths end there: `build_v3_salt_blob`
(setup and migration), `rewrap_password` (password change and
recovery-key reset), `rewrap_recovery_key` (rotation). Consistent
across all three, so not an oversight in one spot.

### Why it was worth doing anyway, and why it wasn't urgent

The bug class this guards — a printed recovery key that does not open
the archive — was already covered by two tests: the `format`/`parse`
round trip in `test_recovery_key.py`, and `test_new_key_works`, which
rotates, locks, and unlocks with the returned key. A broken round trip
fails CI rather than shipping. The round trip is also structurally hard
to break: 20 bytes is exactly 32 base32 characters with no padding, and
`_RECOVERY_KEY_FIXUPS` only maps `0`/`1`/`8`, which cannot appear in
valid base32 output.

So: a real gap, already fenced upstream, and no risk to an archive
either way — rotation does not touch the password wrapper, so the worst
case is a dead second door rather than a lost one.

It went in regardless, on "if we know about it, fix it" grounds. Tagging
v1.0.0 with a written-down gap in the crypto write path is the wrong
way to start.

### What was rejected from the original plan

The first sketch had `rewrap_password` return its KEK alongside the
blob so the caller could verify. That changes a signature and every call
site a day before a tag, for no gain — each builder already holds
everything it needs to check its own output. The guards went inside the
builders instead. Nothing outside `core/encryption.py` moved.

### The cost asymmetry, which shaped the design

The two sides are not the same price, and the naive "verify through the
public unwrap path" would have been expensive on one of them.

`_assert_password_wrapper_opens` reads the wrapper back out of the
**assembled blob** and opens it with the KEK already in hand. Reading it
back from the blob rather than from the local variable is the part that
earns its keep: it catches a serialization error — a field written at
the wrong offset, salt and wrapper transposed — which a check against
the local variable cannot see. It deliberately does not re-derive from
the password. Argon2id here is m=256 MiB, t=6; a second pass would
double the cost of a password change to prove only that the KDF is
deterministic, which is not a plausible failure mode.

`_assert_recovery_wrapper_opens` does go through the full public path —
`unwrap_master_with_recovery_key` on the finished blob, re-parsing the
display string and re-deriving from the salt now stored in it. That
round trip is the actual failure mode on the recovery side, and it costs
HKDF rather than Argon2id, so there was no reason to check less.

Net effect on the success path: byte-identical output. The only new
behaviour is a raise on a path that should never execute.

### Tests

7 new in `TestWrapperVerifiedBeforeWrite`, covering both branches on the
password side (a wrapper that will not decrypt, and one that decrypts to
the wrong bytes), a simulated `format`/`parse` drift on the recovery
side, the setup path, and the consequence that matters — a refused write
leaves the key file untouched and the old credentials working.

Each was verified by reverting the guards: 6 of 7 failed, and the one
that still passed was `test_the_guards_do_not_fire_in_normal_operation`,
which should pass either way. Without the guards,
`test_a_refused_password_change_leaves_the_key_file_untouched` fails by
*not raising* — which is to say the key file gets written with a dead
wrapper. That is the whole finding, demonstrated.

One error worth recording: the first version of the drift test reached
for `Encryption.parse_recovery_key.__func__`. It is a `@staticmethod`,
so accessing it off the class already yields a plain function.

### Suite

546 passed on Apollo, 12m38s. Was 539 (535 after Session 74, plus
Session 75's 4, which had not had a full-suite run until now).

No frontend changes, so ESLint was not re-run.

### Commits
- `4b9f8e7` — verify the wrapper opens before writing the key file
- (this entry) — docs

### Still open

- `git tag v1.0.0`. The live archive was migrated Aug 9; a week of
  ordinary use lands tomorrow, Friday Aug 14, as planned.
- The frontend still has no automated behavioural coverage.


---

## Session 77 — August 15, 2026 (MacBook)

### Restoring when there is no archive to log in to

Rick hit this working on Daybook and suspected MailRepo shared it: after
catastrophic data loss the app sends the user to a first-login screen
with no way to restore from a backup. It does, and the shape of it was
worse than described.

**Confirmed, not assumed.** Built a throwaway archive in a temp dir,
backed it up to an external folder, deleted things, and hit the routes
with a test client. Three distinct failures.

*The one Rick found.* `app.py` gates on `Encryption.is_initialized()`,
which is only "does `data/.salt` exist". With that file gone every route
redirects to `/auth/setup`, whose sole offer is a new master password.
Deleting `data/` and `archive/` while leaving `backups/` intact:

```
is_initialized: False
restore points visible: 1      <- a good restore point exists
GET / -> 302 /auth/setup       <- and the app never mentions it
```

The data is right there, discoverable by code that already works, and
the UI walks past it into creating a fresh archive.

*Worse.* The manifest lives at `<app>/backups/manifest.json`, always
local, regardless of `backup_location`. Zips honour the setting and go
to iCloud; the index of them does not, and `get_all_backup_files()` does
not include it, so it exists in exactly one copy on the machine most
likely to die. Deleting the app directory including `backups/`, zips
safe offsite: `restore points visible: 0`. Fixing the route alone gets a
restore screen that says "no backups found".

*Quieter.* Delete only `mailrepo.db` and leave `.salt`: login succeeds,
`init_database()` makes a fresh empty one, and the user lands in a
working app with zero archives. `backup_location` lived in that
database. Silent partial loss with no warning.

### What was built

**Manifest sidecar.** `save_manifest()` writes a copy into every
directory the manifest's backups live in. Put at that level so anything
mutating the manifest — new backup, retention pruning — keeps copies
current without each call site remembering to. Failures log and
continue: a backup that succeeded must not report failure because a
cloud folder was briefly unwritable, and the canonical manifest is
already down by then.

**Folder discovery.** `get_restore_points()` split so
`build_restore_points(backups, override_dir=)` can resolve entries
against a named folder — a recovered folder is rarely at the path it was
written from. `discover_restore_points_in()` returns `(points, source)`,
preferring the sidecar and falling back to
`reconstruct_manifest_entries()`. `prepare_restore()` gained a sibling
`prepare_restore_from_point()`, because the recovery path has its point
in hand and cannot look it up by an id the missing local manifest
defines.

**Recovery routes.** `/auth/restore`, `/restore/scan`,
`/restore/prepare` — public for the same reason `auth.login` is, since
they exist for someone with no credential left to present. Narrow
because the gate runs the other way: each refuses once
`Encryption.is_initialized()` is true, so this cannot roll a live
archive back over its owner, and a completed restore grants no access —
the contents are still encrypted under the credentials in force when the
backup was taken. Own CSRF token minted on the page; `prepare` re-scans
rather than trusting an id and file list from the client. `setup.html`
links here, which is the part that actually closes the gap.

**Startup warning** for key-file-without-database, and a
`no_current_key` credential note so the disaster case says which
password opens the backup instead of returning `unknown` with an empty
string.

### The test that earned its keep

`test_a_new_full_starts_a_new_chain` failed, and it was a real bug.
Reconstruction sorted the folder listing by filename — but the type
prefix leads, so every `full_` sorts ahead of every `incr_` regardless
of date. A folder holding two chains would have been stitched into one
with all the fulls at the front, and the restore would have
reconstructed a state that never existed while every verification layer
reported it clean. Now parses timestamps first and sorts
chronologically.

Worth recording as a principle: reconstruction is inference, and
inference that looks right is the dangerous kind. Hence the
`reconstructed` flag on the points and the screen saying the list came
from filenames and to check the dates before overwriting anything.

### Verified

Total loss → `/auth/restore` → scan finds the offsite backup via sidecar
→ prepare → restart → `complete_restore()` → unlock → original plaintext
decrypts. Gate confirmed closed afterwards (302 to login, scan 403).
CSRF rejects a client that never loaded the page.

36 new tests in `tests/test_disaster_recovery.py`. Full suite 582 passed
in 9m19s. ESLint 0 errors / 64 warnings, unchanged from baseline.

### Notes for Rick

- The sidecar only helps backups made from here on. Existing iCloud
  backups have no sidecar and would come back through the reconstruction
  path. **One manual backup after this lands writes a sidecar covering
  the whole existing manifest**, upgrading them all at once. Worth doing
  during dogfooding.
- Daybook has the same shape of bug. The sidecar reasoning and the
  inverted gate on the recovery route should both port.

### Still open

- `git tag v1.0.0`.
- Manual verification of the credential badge + modal on password change
  (unchanged from Session 76).
- The frontend still has no automated behavioural coverage; the recovery
  screen is now part of that gap, and it is a screen that only runs on
  the worst day an archive ever has.


---

## Session 78 — August 15, 2026 (MacBook)

### MailRepo now knows where its own backups are

Rick, on the Session 77 recovery work: *"it can't just skip EdgeCase. It
has to know where its own backups are."* Correct, and the objection went
deeper than the bug it was pointing at.

Session 77 made restore reachable, but left MailRepo **guessing**. It
swept the disk for folders that looked like backups, then tried to
recognise its own by opening a zip and checking for `data/mailrepo.db`.
Running that against this actual machine found EdgeCase's backup folder
and offered it as a MailRepo restore point.

The two are indistinguishable from outside. Verified on a real pair:

```
EdgeCase: data/edgecase.db, data/.salt, data/.secret_key, ...
MailRepo: data/mailrepo.db, data/.salt, data/.secret_key, ...
```

Same filename convention, same key-file paths. Restoring one into the
other is worse than a failed restore: `complete_restore` finds no
database to copy and overwrites this archive's key file with the other
application's, leaving an archive that opens with nothing.

Filtering EdgeCase out by database name was treating the symptom. The
cause was that MailRepo neither marked its own backups nor remembered
where it had sent them.

### The two missing halves

**It didn't record where backups go.** `backup_location` lived in the
encrypted database — the one file guaranteed to be gone in the scenario
the record is needed for. Needing it and having lost it were the same
event. Now `Config.get_state_path()` gives a small state directory
*outside* the application folder (Application Support on macOS, XDG
config on Linux, `MAILREPO_STATE_DIR` to override), and
`record_backup_location()` writes to it on every backup — called from
inside `save_manifest` so nothing has to remember to.

**It didn't mark its own backups.** `save_manifest` now stamps each
manifest with `app` and `app_version` before writing it anywhere.
`folder_holds_mailrepo_backups()` trusts that stamp first, falling back
to inspecting a full backup only for folders written before stamping
existed. That fallback cannot be dropped — every backup made to date is
unstamped, and refusing those would make recovery useless to precisely
the person it exists for.

`find_backup_locations()` is the entry point now: **the record answers
first**, and only a genuinely new machine — state file gone with the old
disk, synced folder the only survivor — falls through to the sweep.
Measured at 0.000s against 0.68s, and it cannot confuse another app's
folder for its own because it isn't looking at folders at all.

### Also fixed while in there

- **Boot-volume double-scan.** macOS re-exposes the boot volume under
  `/Volumes/<name>` via a firmlink, which is not a symlink and does not
  collapse under `resolve()`. The sweep walked the whole disk a second
  time and labelled local folders "External drive". Filtered by device
  id, since the volume name varies per machine.
- **`/auth/setup` now redirects to `/auth/restore` when backups exist**,
  `?new=1` as the escape hatch. Leading with a page whose obvious action
  starts an empty archive over a recoverable situation was the original
  bug; a link at the bottom was not enough of a fix.
- **No more typing paths.** The screen opens by volunteering what it
  found. New public routes `/auth/restore/search` and
  `/auth/restore/browse`; the picker flags which folders hold backups
  and which belong to another application — named rather than hidden,
  since silently omitting a folder the user can plainly see reads as
  MailRepo failing to find it.

### Two test-harness bugs worth remembering

Both the same shape: the harness quietly voiding the property under test.

1. `conftest` initially set `MAILREPO_STATE_DIR` *inside* `temp_data_dir`
   — i.e. inside the app folder, destroying the exact property the state
   file exists to have. Caught by a test asserting the invariant
   directly (`app_dir not in record.parents`) rather than testing
   behaviour that happened to depend on it.
2. The fallback sweep walked the **real home directory** during tests
   and found the developer's own iCloud backups, so "no backups exist"
   failed on the machine it was written on. Now confined by
   `MAILREPO_SEARCH_ROOTS`.

### Verified

Total loss of the app directory with the state file surviving: record
answers instantly, no search. State file also destroyed (new machine):
falls through to the sweep and still finds it. EdgeCase folder refused
in both paths and through the manual picker. Setup redirects to restore;
`?new=1` still works. Full loop from total loss to decrypted plaintext.

62 tests in `tests/test_disaster_recovery.py`, 608 in the suite, ESLint
0 errors / 64 warnings.

### Notes for Rick

- **Run one manual backup.** It stamps and records your live iCloud
  folder, moving it off the reconstruction path and onto the recorded
  one. Currently that folder shows 187 restore points via filename
  reconstruction.
- **EdgeCase should get the same stamp.** Until it does, the two are
  separable only by database name. The stamp, the state file and the
  inverted setup redirect all port directly.

### Still open

- `git tag v1.0.0`.
- Manual verification of the credential badge + modal on password change.
- Frontend still has no automated behavioural coverage; the recovery
  screen is now a fair amount of untested JS, on a screen that only runs
  on the worst day an archive ever has.

---

## Session 79 — August 15, 2026 (MacBook)

### The disk search is gone

Rick's decision, made in plain-language terms and the better for it:
recovery should either *remember* where backups are or *ask* — never
hunt. Continuation of the Session 77–78 chat, picked up fresh with the
tree mid-refactor (the quick/deep sweep split was on disk, uncommitted,
two tests failing).

Rather than finish the sweep, it was removed entirely. The case for
removal, all of it observed rather than hypothesised in Sessions 77–78:

- It hardcoded cloud-provider paths that move between OS versions —
  Dropbox mounts under `~/Library/CloudStorage` on this very machine,
  not `~/Dropbox`.
- It surfaced EdgeCase's byte-identical backup folders, which forced
  the app-stamp work just to fence in the guessing.
- It walked the developer's real home directory during tests until
  confined by an env var that existed only to confine it.
- Everything it offered is covered better: the record (Session 78)
  answers instantly for any location the user ever chose, and the
  folder picker covers unknown locations with consent and zero
  assumptions.

Removed: `search_for_backups`, `sweep_for_backups`,
`_collect_from_roots`, `_search_roots`, `_SEARCH_SKIP`,
`_same_device_as_root`, the `MAILREPO_SEARCH_ROOTS` confinement, and
the now-unused `time` import. Net −162 lines.

### What recovery is now

1. **The record** — backups noted where they were written, in a state
   file outside the app folder. Location-agnostic and platform-agnostic
   because it stores what the user chose.
2. **The default folder** — the one directory MailRepo may check
   without guessing, because it is MailRepo's own. Covers installs
   predating the record.
3. **The picker** — everything else, by asking. The empty state now
   also says the one thing no local code can solve: backups on another
   computer or a disconnected drive must be connected or copied here
   first, then chosen.

### Verified

Full loop both ways: total loss with record surviving (setup redirects
to restore, backups offered, `known=True`) and new machine with record
gone (nothing offered, no hunting, picker flags the folder, restore
completes, plaintext decrypts, gate closes). One false alarm during
verification: the picker appeared not to flag a folder, which turned
out to be `/tmp` vs `/private/tmp` symlink spelling in the test script
itself, not the route.

Tests: the two that pinned auto-sweep now pin its absence, plus one for
the default-folder fallback. 63 in the file, **609 in the suite**
(9m58s). ESLint 0 errors / 64 warnings, unchanged.

### Still open

- `git tag v1.0.0`.
- Manual verification of the credential badge + modal on password change.
- **Run one manual backup during dogfooding** — stamps and records the
  live iCloud folder, moving it off filename reconstruction onto the
  recorded path.
- EdgeCase should get the same stamp + record + setup-redirect
  treatment; all three port directly.
- Frontend behavioural coverage gap unchanged; recover.js is manual-
  verification only.

**Addendum (same day):** Rick asked whether the fix is fully
device-independent. It is, with one cosmetic exception found on
review: the home-directory location label said "This Mac" on every
platform. Now "This computer". One-line change, 63 recovery tests
green, committed and pushed separately.

---

## Session 80 — August 16, 2026 (MacBook)

### The way back from a restore nobody can open

The residual gap in the restore story, found through Daybook and fixed
in both siblings today — EdgeCase's 3d1b7a5 this morning, MailRepo now.
A backup carries its key file as it stood, so a restored archive opens
with the credentials of the moment it was TAKEN. MailRepo said this
plainly on the restore screen — and then nothing after. Once the user
quit and relaunched, the login screen was silent: a correct restore
was indistinguishable from a rejected password. And if the credentials
were genuinely lost, the recovery gate was a hard
`Encryption.is_initialized()` check — the door slammed shut the moment
the restore landed, leaving no way back to a different backup,
including the pre-restore safety copy. Rollback story: delete files by
hand.

### What changed

1. **A restore is UNVERIFIED until someone proves they can open it.**
   `complete_restore()` writes `data/.restore_unverified` at the end.
   It sits beside the key files it describes, and stays out of every
   zip by construction: `get_all_backup_files()` names its files
   explicitly rather than globbing, so full, incremental, and
   pre-restore backups never pick it up, and the sidecar machinery
   records zips, so it never appears there either.
2. **While the marker stands, the recovery door stays open.**
   `_recovery_door_open()` — "not initialized OR unverified restore" —
   now gates all five recovery routes. Not a rollback hole: the only
   state exposed is an archive nobody has vouched for yet, and whoever
   could exploit the window could have used the recovery door moments
   earlier.
3. **A demonstrated credential closes it.** Both ways in vouch:
   password login (the password unwrapped the key file and opened the
   database) and recovery-key login (`verify_recovery_key` performs the
   full recovery-side unwrap). Daybook ruled this morning (7cecbb8, "a
   session proves the password and nothing else") that only what has
   been PROVED counts — both of these are demonstrations, not
   inferences, so clearing on both is consistent with the family, not
   a divergence. The comment in auth.py cites the ruling.
4. **The login screen says so.** main.py carries `complete_restore()`'s
   result into `app.config["RESTORE_COMPLETED"]`; a shared banner
   partial (`auth/_restored_banner.html`, included by login.html AND
   recovery_login.html — the second screen is exactly where someone
   with a lost password lands) names the restored date and the
   credential note chosen with the restore point. Peeked, not popped,
   so it survives failed attempts — precisely when it is needed. While
   the marker stands it also offers the way back: "Can't open it?
   Restore a different backup." Popped only on the vouch.

### Wrinkles checked rather than assumed

- **Second restore from the unverified state** takes its pre-restore
  safety copy cleanly — but the `backup_location` setting lives in the
  locked database, so the existing try/except falls back and the
  safety zip lands in the DEFAULT backups folder, not the configured
  cloud one. Documented behaviour, pinned by a test.
- **The recovery CSRF token does not survive the quit-and-relaunch**,
  and does not need to: `recover()` mints a fresh token on every GET
  and recover.js reads it from the rendered meta tag. A stale
  pre-relaunch tab gets a plain "Invalid request token" and a reload
  fixes it.
- **The marker survives a crash** between complete_restore and first
  login — it is a file, written before complete_restore returns.
  Pinned by test_marker_survives_a_relaunch.

### One existing test updated — the contract got stricter

`test_recovery_routes_close_after_a_successful_restore` pinned the
defect verbatim: door shut the moment complete_restore ran. Renamed to
`..._stay_open_until_the_restore_is_vouched_for` and rewritten to the
new contract. Per Daybook's commit this morning: a test updated because
the contract got stricter is the contract working.

### Proofs

22 new tests in `tests/test_unverified_restore.py`: marker roundtrip
and isolation tripwire, never-in-a-zip (full and pre-restore), set by
complete_restore and carrying the note, relaunch survival, door open
with the marker / closed without / closed again once cleared, both
vouch paths clearing it and both failure paths not, banner content
surviving a failed attempt, generic note when only the marker stands,
no banner in normal use, no way-back link once vouched, and the
second-restore safety copy.

All four sealing mutations run and each turned exactly its own guard
red: complete_restore not setting the marker (2 red), the door
reverted to is_initialized-only (2 red), login() not vouching (1 red),
recovery-key verify not vouching (1 red). Reverted, verified clean.

Suite 609 → 631. ESLint 0 errors / 64 warnings, unchanged (no JS
touched).

### Notes for the log

- MailRepo's conftest already isolates the marker structurally — the
  autouse fixture re-roots the whole data dir per test, which EdgeCase
  did not have and needed a dedicated fixture for. Documented in
  conftest, with a tripwire test asserting the marker path lives under
  the per-test temp dir so moving it (e.g. to the state dir) reopens
  the question loudly.
- Process slip caught mid-session: `pytest ... | tail -3` reports
  tail's exit code, not pytest's, so a `&&`-chained follow-up ran on a
  "pass" that wasn't. The pre-existing-test failure was present in the
  targeted batch and invisible. Checked `$?` explicitly thereafter;
  worth remembering.
- First template partial in the codebase
  (`auth/_restored_banner.html`) — two login screens carrying the same
  banner would otherwise drift.

---

## Session 81 — August 16, 2026 (MacBook, evening)

### The suite in 19 seconds — Daybook's fast-KDF port

Rick asked why the tests take forever and remembered Daybook did
something about it. It did, yesterday: production Argon2id costs most
of a second per hash and the suite performs hundreds of them — the
parameters were nearly the whole runtime (Daybook's run had hit 25
minutes on Apollo; ours was 9m48s on the M4, ~12 min on Apollo).

Ported directly. MailRepo's shape made it clean: every password-side
derivation already goes through one function (`_derive_master_v2`), and
the recovery-key side is HKDF — no Argon2, untouched. The parameters
now come from `argon2_parameters()`: production strength everywhere,
cheap (t=1, 1 MiB) only when BOTH `MAILREPO_FAST_KDF` and
`MAILREPO_DATA_DIR` are set. Not mocking — same algorithm, same call
site, archives still genuinely encrypted and genuinely reopened; only
the work factor changes.

The double guard is the safety, same doctrine as Daybook: the
parameters are not recorded in the key file, so an archive created
cheaply cannot be opened at production strength or the reverse —
getting this wrong locks someone out permanently, so the cheap path
must be unreachable by accident. A real install never sets the
data-dir override, so it can never reach it. One deliberate divergence
in rationale: Daybook's sandbox-alone-does-nothing case protects its
demo server; ours protects any future package or second-archive setup
that legitimately sets `MAILREPO_DATA_DIR`.

### What the fast suite can no longer prove, proved separately

`tests/test_kdf_cost.py` (8 tests, mirroring Daybook's):
- the production numbers pinned as literals (6 / 262,144 / 1 / 32) —
  the guard that notices if the cheap values ever become the real ones
- the cheap path needs both keys: default is production, flag alone
  does nothing, sandbox alone does nothing, both together are cheap
- a full v3 round trip at full cost — both credentials, both wrappers
- a timing floor (>0.25s per unlock, far under the ~750ms measured) so
  a parameter change that quietly made derivation cheap cannot leave
  every test green

### One latent footgun surfaced

Two Session-76 tests called `monkeypatch.undo()` to lift a junk-wrapper
patch. `undo()` reverts EVERYTHING on the shared per-test monkeypatch —
conftest's env vars included. Harmless before, because Config caches
its paths; fatal now, because `argon2_parameters()` reads the env live,
so mid-test the fixture archive (created cheap) was being unlocked at
production cost and correctly refused — the cost-mismatch guard working
as designed against its own test suite. Both tests now scope the patch
with `pytest.MonkeyPatch.context()` instead; no other `undo()` calls
exist in the tests (checked).

### Numbers

Full suite: **639 tests, 18.6s** (was 631 in 9m48s before this session
pair; 8 tests added here). The two deliberate full-cost tests are
~1.4s each and worth it. Crypto-heavy files that took minutes now run
in ~1s. ESLint untouched (no JS).

Apollo note: pull before next session there; its runs should drop from
~12 min to well under a minute.


---

## Session 82 — August 21, 2026 (MacBook)

### Two screens counting different things

Rick opened a Vault folder listed as `20240502-EK (100)` and got
"0 emails · Delete by: 2035-05-09" with "No emails in this folder"
under it. Nothing was lost. The folder holds no mail directly; all
100 emails live in its 2024 and 2025 subfolders.

`/api/folders/vault` counted the whole tree. That is the right number
for that screen — permanent deletion takes the folder and everything
beneath it, and the confirmation dialog quotes the same figure. The
folder view called `/api/folders/<id>/emails`, which returns direct
children only, like every other list in the app. Both were correct in
isolation and contradicted each other on screen.

### What changed

Ruled out changing the list to a direct count: the permadelete
confirmation would then say "delete all 0 emails?" about a folder
holding 100, which trades a confusing screen for a dangerous one.

So the counts stay recursive and the folder view learned to explain
itself. `/api/folders/vault` now also returns `counts` — a tree total
keyed by id for **every** vault folder, not just the top-level ones.
The old code ran one `COUNT(*)` per folder inside a nested function
defined in a loop; it is now a single grouped query plus a memoised
roll-up over a prebuilt child map.

The folder view uses `counts` in three places:
- each subfolder link carries its own total (`2024 (57), 2025 (43)`),
  so the subfolder numbers visibly add up to the parent's row
- the header reads `0 emails here · 100 in subfolders` instead of a
  bare `0 emails`
- the empty state points upward when there is somewhere to point

### Tests

Five, in `TestVaultSubfolderCounts`: counts returned for subfolders
and not only the top, the reported empty-parent case, nesting deeper
than one level, trashed emails excluded, non-vault folders absent
from the map. Two sealing mutations, each reddening exactly its own
guard — dropping the `deleted_at` filter fails only the trash test;
restricting `counts` to top-level folders fails only the three that
read subfolder entries.

644 tests (was 639), 19s, all green. ESLint unchanged: 0 errors, the
same 64 pre-existing warnings.

### Noted, not fixed

The main archive view renders subfolder links the same way, without
counts. It does not have the same contradiction — its header count is
direct and no other screen claims otherwise — so it is cosmetic
rather than a bug. Worth considering for consistency post-1.0.


---

## Session 83 — August 21, 2026 (MacBook)

### One counting rule, both views

Rick's call on the note from Session 82: align the archive view now
rather than after 1.0. Straightforward, and it turned out to be the
better shape rather than just the consistent one.

The archive view had the same defect, quieter. Its subfolder links
carried no counts, and its empty state said "This folder is empty" for
a folder holding a hundred emails one level down. Nothing on that
screen contradicted it, so it read as unhelpful rather than wrong.

### Consolidated rather than duplicated

Session 82 put a `counts` map on `/api/folders/vault`. Copying that
pattern to the archive side would have meant two mechanisms and two
staleness stories. Instead:

- `tree_email_counts()` in `folders.py` is the roll-up — one grouped
  query for direct counts, one memoised walk, `{folder_id: total}` for
  every folder not in the trash. Every folder size the app shows now
  comes from here.
- `/api/folders/<id>/emails` returns `subfolder_counts` for its direct
  children alongside the emails. Both views already call this endpoint
  on every folder open, so the numbers are computed fresh each time and
  cannot go stale after a move, delete or commit — which matters more
  in the archive than in the read-only vault.
- Yesterday's `counts` key is removed. The vault view now reads the
  same field the archive view does, and derives its header total by
  summing the subfolder links it is already rendering.

### On screen

Both views: `2024 (57), 2025 (43)` beside subfolder names, a header
that splits here from below (`0 archived emails here · 100 in
subfolders`), and an empty state that points upward when there is
somewhere to point. `.subfolder-count` is defined once in
`email-list.css`; the vault-scoped duplicate is gone.

`state.nestedEmailCount` carries the below-here number into
`renderEmailList()`, which is shared with the IMAP view — it is only
read when the current view is an archive folder.

### Tests

Six, replacing yesterday's five, now against the shared endpoint:
per-subfolder counts, counts reaching through deeper nesting, trashed
emails excluded, trashed subfolders absent from the map, a folder with
no subfolders reporting `{}`, and the Vault row total equalling what
the folder view accounts for (`emails + subfolder_counts`) — the
regression that started this pair of sessions.

Two sealing mutations, each reddening exactly its own guard: dropping
`deleted_at IS NULL` from the child query fails only the trashed-
subfolder test; emptying the roll-up's recursion fails only the two
tests that read nested totals.

645 tests, 18.7s, all green. ESLint: 0 errors, the same 64
pre-existing warnings.


---

## Session 84 — August 21, 2026 (MacBook)

### Review of Sessions 82–83, and one loose end

Read both days' commits against the code rather than the log. The
counting rule holds: `tree_email_counts()` excludes trashed folders
from the walk and soft-deleted emails from the grouped query, both
views sum only the subfolders they display, and `nestedEmailCount` is
read only when the current view is an archive folder (the Starred
view's borrowed `type: 'folder'` never renders an empty list through
that path). Nothing to change there.

### What was wrong

The toolbar "Search emails…" box (`handleSearch` in `app.js`) narrows
`state.emails` and re-renders. With no matches it landed in the folder
empty state. That has always been slightly wrong ("This folder is
empty" for a folder with emails that did not match), but Session 83
made it confidently wrong: a folder with direct emails and subfolder
totals now said "they are in the subfolders above" about emails that
were right there.

### Fix

`state.searchFilterActive` is set around the filtered render (try/
finally, so the flag and the swapped list are both restored even if
the render throws). The empty state checks it first and reports "No
Matches · No emails match your search", leaving the two folder
messages for genuinely empty folders.

Frontend only; no test surface. ESLint 0 errors, same 64 warnings.
645 tests, all green.

## Session 85 — August 22, 2026 (MacBook)

### Ported from EdgeCase: `save_manifest` resurrected missing backup destinations

EdgeCase `c5ba41e` fixed a bug MailRepo shares verbatim. `save_manifest`
writes a sidecar `manifest.json` into every directory returned by
`manifest_destinations`, which walks the entire backup history. Before
writing it called `destination.mkdir(parents=True, exist_ok=True)`, so
any `backup_dir` that had ever appeared in the manifest — a long-gone
install path, a removed cloud folder — was recreated on every backup as
an empty folder holding only a manifest. `record_backup_location` then
re-recorded it in `backup_locations.json`, and the recovery screen
offered a folder with zero restore points.

### Fix

In the sidecar loop, skip any destination where `not
destination.is_dir()` and drop the `mkdir`. If the folder is gone its
zips are gone, and a manifest there describes nothing. Verified before
porting the comment that MailRepo's ordering matches EdgeCase's: real
destinations always exist because `validate_backup_location` (called
by `create_full_backup` / `create_incremental_backup`) and the
pre-restore safety path both create the folder before the zip is
written, and `save_manifest` runs after the zip.

### Regression test

`TestManifestSidecar.test_vanished_destination_is_not_resurrected` in
`tests/test_disaster_recovery.py`: one manifest entry whose
`backup_dir` is a non-existent path under `tmp_path`; after
`save_manifest` the path must still not exist and must be absent from
`get_known_locations()`. Proved red against the pre-fix code (`git
stash` on `utils/backup.py` only, run, `stash pop`, `cmp` against a
snapshot to confirm the fix came back intact) and green after.

### Cleanup on the MacBook

Nothing to clean. Every one of the 190 manifest entries points at the
iCloud folder, which is live. `backup_locations.json` (which lives
under `~/Library/Application Support/MailRepo/`, not Preferences)
holds two entries, both live: the canonical `backups/` dir and iCloud.
`~/apps/` does not exist. The canonical `backups/` dir contains only
`manifest.json`, which is expected — it is the canonical manifest, not
a sidecar, and all zips go to iCloud.

### Housekeeping

`ruff check` flagged three pre-existing unused imports (two in
`test_disaster_recovery.py`, one in `test_unverified_restore.py`);
cleared. `ruff format --check` reports 12 files it would reformat;
formatting is not enforced in this project and was left alone.

646 tests, all green (~19s). ruff check clean.

Code commit: `6752383`.
