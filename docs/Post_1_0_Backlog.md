# MailRepo — Post-1.0 Backlog

Created May 30, 2026 after the 1.0 feature set shipped. Things deferred
from earlier work plus items identified during the road-to-1.0 push that
aren\'t blocking ship but should be tracked.

Organized by category, roughly priority-ordered within each.

---

## Release & distribution

### Packaging (.dmg for macOS, .deb for Linux)
**Priority:** Next major milestone after dogfooding.

Currently MailRepo ships as a `git clone` + `python -m venv` + `pip install`
setup. For solo practitioners (lawyers, therapists, journalists — the
target audience), that\'s a barrier. The unlock for actual adoption is a
double-click installer.

- macOS `.dmg`: PyInstaller or py2app to bundle the Python runtime +
  dependencies + a launcher. Sign with a developer ID so Gatekeeper
  doesn\'t scare people off. Notarization optional but recommended.
- Linux `.deb`: dh_virtualenv or pyinstaller, target Debian/Ubuntu LTS.
- Both should include SQLCipher and libpst (for PST import).
- Auto-update path: not in v1 of packaging. Manual reinstall is fine
  for now.

Rick is dogfooding 1.0 for an unspecified period before tagging a
release and starting on packaging.

### `git tag v1.0.0`
Not yet tagged. Will happen after dogfooding settles.

### Website update (mailrepo.ca on Sentinel)
Announce 1.0, list current crypto stack, link to docs / repo. Rick\'s
own task; will be done outside of these working sessions.

### CHANGELOG.md
Not yet created. Worth doing as part of the 1.0 announce push so users
landing on the repo can see what\'s changed.

---

## Documentation

### CHANGELOG.md
See above.

### docs/ cleanup
Several plan docs are now historical artifacts of completed work:
- `Crypto_Refactor_Plan.md` — work shipped, plan superseded
- `Bulk_Export_Plan.md` — feature shipped
- `Stage_Thread_Plan.md` — old plan, status unclear
- `Refactoring_Plan.md` and `Refactoring_Plan_V2.md` — appears legacy

Could be moved to `docs/archive/` or annotated with completion status.
Low priority but tidiness has its own value when the repo is FOSS.

---

## Test coverage gaps

### Unit tests for `core/password_change.py`
The v2-native password change was production-tested on Rick\'s archive
but never got the unit test scaffolding that `core/migration.py` had
(before deletion). The function `change_master_password()` works the
same shape as `Migration.run_phase_1` and could be tested the same
way: build a v2 archive, change password, verify new unlocks + old
doesn\'t, verify content equivalence across files.

Not urgent — the production path works. But future maintenance is
safer with the test scaffold in place.

### `is_api_request()` regression check
The broadening of `is_api_request()` in commit `39e0ce2` was smoke-
tested for `/migration/api/*` only. Other endpoints (`/backups/api/*`,
`/auth/api/*`) weren\'t re-exercised. The global CSRF auto-injection
in `base.html` should make this transparent, but worth confirming the
backup flow specifically after the change.

---

## Architectural items deferred from earlier reviews

These all come from `docs/Code_Quality_Review.md` (Jan 26 / Feb 17, 2026)
where they were explicitly deferred to post-1.0:

### `progress.py` size (1,114 lines)
The progress UI / SSE wiring module grew large during the IMAP commit
flow work. Worth splitting into focused modules — possibly:
- `progress/streams.py` — SSE generator logic
- `progress/state.py` — progress state machines
- `progress/handlers.py` — Flask route handlers

Refactor; no behavior change.

### Global `window` function pollution
Several views (legacy chunks of `app.js`, modals, etc.) attach handlers
as `window.functionName = ...` for use by inline `onclick` HTML attrs.
Modernize to `addEventListener` + delegated handlers.

### Inline `onclick` / event handler pattern mix
Same root cause as the previous item. Some views use proper event
delegation; others use inline `onclick="..."` attributes. Standardize
on event delegation.

### Mixed event handling patterns
Catch-all for the above two. Sweep through the JS and converge on one
pattern.

---

## Performance items (only act on if symptoms appear)

### Per-thread DB connection pool
Currently every DB operation serializes through the class-level RLock.
For a single-user local app this is invisible. If contention becomes
noticeable (UI lag during long-running SSE streams, slow searches
while a commit is running), switch to a per-thread connection pool
with WAL-mode concurrent readers.

Cost: more complex connection lifecycle, per-connection SQLCipher key
setup, separate transaction state per thread. Don\'t pay this cost
until measurements justify it.

---

## Future major work (separately documented)

### `docs/Future_Backup_Refactor.md`
Aligning MailRepo\'s backup state management with the Libram approach.
Spec exists; implementation deferred. Read that doc for details.

### Future crypto migration (hypothetical v2 → v3)
If/when AES-256-GCM or Argon2id need replacing (post-quantum, some
hypothetical weakness), the migration would follow the same pattern
that ran on May 29, 2026: per-file version byte, two-phase walk +
DB rekey, marker-file resumability, halt-loud on corruption. The
already-deleted v1→v2 migration code is preserved in git history at
commit `353ae2f` (immediately before the v1 cleanup) as a reference
template.

The `MRC2` salt magic and `0x02` per-file version byte are forward
infrastructure for this — a future v3 KDF would write `MRC3` and
0x03 with HKDF info strings updated to `.v3` so it derives crypto-
graphically distinct keys even if the master collides.

---

## Done — listed here for traceability

These were on earlier post-1.0 lists but turned out to already be done:

- **Gmail auto-detection + Gmail-specific post-commit options.** Confirmed
  May 30, 2026: `web/blueprints/api/accounts.py:49-56` sets `is_gmail`
  based on IMAP host; `web/static/js/views/review.js:601-619` hides the
  "Delete emails" option for Gmail accounts (since Gmail\'s IMAP delete
  just archives, which is misleading). Memory was stale; implementation
  was already in place.
