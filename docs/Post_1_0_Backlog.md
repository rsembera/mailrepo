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

---

## Documentation

### docs/ cleanup
Several plan docs are now historical artifacts of completed work:
- `Crypto_Refactor_Plan.md` — work shipped, plan superseded
- `Bulk_Export_Plan.md` — feature shipped
- `Stage_Thread_Plan.md` — old plan, status unclear
- `Refactoring_Plan.md` and `Refactoring_Plan_V2.md` — appears legacy

Could be moved to `docs/archive/` or annotated with completion status.
Low priority but tidiness has its own value when the repo is FOSS.

### `docs/Navigation_Map.md` refresh
Last updated Feb 4, 2026 with status "Pre-Release Testing — all features
built." Predates the May 2026 crypto refactor and a lot of post-Feb UX
work. Either refresh to reflect the 1.0 codebase (preferred) or move to
`docs/archive/` if no longer worth maintaining. Left in place during the
May 30 docs cleanup pass because removing a navigation map without
replacement would leave a hole.

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

These were on earlier post-1.0 lists but turned out to already be done,
or were closed out during a working session:

- **Gmail auto-detection + Gmail-specific post-commit options.** Confirmed
  May 30, 2026: `web/blueprints/api/accounts.py:49-56` sets `is_gmail`
  based on IMAP host; `web/static/js/views/review.js:601-619` hides the
  "Delete emails" option for Gmail accounts (since Gmail\'s IMAP delete
  just archives, which is misleading). Memory was stale; implementation
  was already in place.

- **Backup state refactor (Libram-style external state file).** The
  planning doc `Future_Backup_Refactor.md` was removed May 30, 2026
  (`c090c4f`) because the work had been shipped earlier in
  `42e2951 Refactor: External backup state file (Libram-style)`. The
  phantom backlog entry was also struck in `75b1cca`.

- **`progress.py` size refactor.** Done Session 37, May 30, 2026
  (`2a9f880`). Split 1,114-line `progress.py` into a 61-line entry
  point plus three focused modules: `progress/streams.py` (SSE
  generator logic), `progress/state.py` (state machines), and
  `progress/handlers.py` (route handlers).

- **`core/password_change.py` unit tests.** Done Session 37, May 30,
  2026 (`5fdf7f1`). 15 new tests added; suite went from 53 to 68 tests.
  Tests build a v2 archive, change password, verify new unlocks and
  old does not, verify content equivalence across files — same shape
  as the deleted `Migration.run_phase_1` tests.

- **CHANGELOG.md.** Done Session 37, May 30, 2026 (`0ff4c67`). Keep a
  Changelog format. Currently has the 1.0.0 entry under "Unreleased
  (dogfooding)" pending `git tag v1.0.0`.

- **docs/ archive cleanup.** Done Session 37, May 30, 2026 (`0ff4c67`).
  Legacy plan docs (`Crypto_Refactor_Plan.md`, `Bulk_Export_Plan.md`,
  `Refactoring_Plan*.md`, etc.) moved to `docs/archive/`.

- **Frontend cleanup pass: window pollution, inline onclicks, mixed
  event handling.** Done across Sessions 37–38, May 30–31, 2026. The
  three architectural items in `Code_Quality_Review.md` are all
  closed. Net effect: zero inline `onclick` attributes anywhere in
  the codebase (including render-generated HTML and the index.html
  template), zero `window.X` assignments for cross-module function
  dispatch. The dispatch model is uniform end-to-end: per-view
  `bindActions(container, handlers)` for view-scoped clicks, plus a
  single `template-bindings.js` delegated handler on `document.body`
  for template-level actions. Eleven files converted plus a final
  template pass. See Session 38 for the full file list and the
  `template-bindings.js` design.
