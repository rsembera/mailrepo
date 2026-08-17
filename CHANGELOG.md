# Changelog

All notable changes to MailRepo will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Changed
- **Nothing about the app itself — a development change worth recording
  (Session 81).** The automated test suite now runs its cryptography at
  a reduced work factor (a technique ported from a sibling project), so
  a full run takes seconds instead of ten minutes. Your archive is not
  affected: the production password-hashing strength is unchanged,
  pinned by dedicated tests, and unreachable from the fast path by
  design — an installed copy of MailRepo cannot be switched to the
  cheap parameters even by misconfiguration.

### Security
- **A restored archive now has a way back if its password turns out to
  be lost (Session 80).** A backup opens with the credentials that were
  in use when it was made, and after a restore the login screen now
  says so: it shows the restore date and which password the archive
  wants, and the message stays up even after a failed attempt — which
  is exactly when you need it. Until you log in once, the restore is
  treated as unverified: the pre-login restore screen stays available,
  with a "Restore a different backup" link right on the login page, so
  you can go back and try another backup — including the safety copy
  MailRepo made of what was there before. The first successful login
  (with the password, or with a verified recovery key) confirms the
  restore and closes that door again, so an archive in normal use is
  never affected. Previously, restoring a backup you could not open
  left no way back at all.
- **Finding backups after a disaster is now remember-or-ask, never
  guess (Session 79).** MailRepo already keeps its own note of every
  folder it sends backups to, stored safely outside the archive; after
  a loss it offers those backups straight away. If that note is gone
  too (a brand-new computer), it checks only its own default backups
  folder and otherwise asks you to choose the folder with a picker.
  The automatic disk search from earlier this week has been removed:
  it guessed at cloud folder locations that vary between systems and
  could surface another application's backups. Nothing you could do
  before has been lost -- choosing a folder yourself covers every case
  the search did, without the guessing.
- **MailRepo now keeps its own record of where your backups are
  (Session 78).** That record used to live inside the encrypted
  database — the one file certain to be missing when you need it. It is
  now kept separately from the archive, so after a total loss MailRepo
  can offer your backups straight away instead of hunting for them.
- **Backups are marked as MailRepo's own.** Other applications can write
  backup files that look identical from the outside, and restoring one
  of those by mistake would leave an archive that opens with nothing.
  MailRepo now labels its own backups and will not offer anyone else's.
  Backups made before this change are still recognised.
- **The restore screen no longer asks you to type a folder path.** It
  opens by showing the backups it already knows about. If you are on a
  new machine it looks for them, and there is a folder picker if you
  want to point at somewhere specific.
- **A machine with no archive now offers to restore first.** Previously
  it opened the "create a master password" screen, where the obvious
  next step starts an empty archive over the top of a recoverable
  situation. There is still a link for genuinely starting fresh.
- **You can now restore from a backup when there is no archive to log in
  to (Session 77).** If this machine lost its data, MailRepo used to send
  you to a "create a master password" screen with no mention of your
  backups — so the obvious next step started an empty archive over the
  top of a recoverable situation. There is now a restore screen reachable
  before login, linked from that setup page. It is available only when
  there is no archive on the machine, and restoring does not open
  anything: the recovered mail is still encrypted with the password and
  recovery key that were in use when the backup was made.
- **Backup folders now describe themselves.** The record of which backup
  belongs to which chain used to live only inside the application folder.
  If you kept backups in iCloud Drive or another synced folder and lost
  the machine, the backup files survived but nothing left could
  interpret them. A copy of that record is now kept alongside the backups
  themselves. If it is ever missing, MailRepo works out what it can from
  the filenames and tells you plainly that it has done so.
- **MailRepo now says which password opens a backup after total loss.**
  Previously the restore screen went quiet in exactly that case, having
  nothing on the machine to compare against.
- **A missing database is no longer silent.** If your encryption key file
  survives but the database does not, logging in used to create a new
  empty archive with no warning. MailRepo now says so at startup, and
  leaves the decision to you — that is also what a genuine first run
  looks like.
- **MailRepo now proves a new password or recovery key actually works
  before it writes it (Session 76).** Setting up an archive, changing a
  password and rotating a recovery key all end by rewriting the small
  key file that holds your keys. That file was checked for the right
  shape and size, which cannot tell a working key from a dead one. It is
  now opened and verified before it is allowed to replace the old one,
  and the write is refused outright if anything is wrong. In practice
  nothing looks different — this exists so that a printed recovery key
  can never be one that quietly does not work, discovered on the day you
  need it.

### Added
- **The Retention Vault now accepts any retention period, not just the
  presets (Session 75).** The quick-select buttons (1/3/5/7/10 years)
  are shortcuts, but statutory retention varies by jurisdiction and
  profession — 15 years is common for medical records, and some
  obligations run longer than any preset. There is now a field beside
  them for typing any number of years up to 100. The date picker always
  accepted an arbitrary date; this is a faster way to reach one.
- **You can now check your recovery key without using it (Session 73).**
  Settings → Security → Check Recovery Key confirms whether the copy you
  have on file opens this archive. It changes nothing — not your
  password, not your recovery key. Previously the only way to find out
  was to run the recovery flow, which now sets a new password by design,
  so testing the key cost you the password you were testing it against.

### Changed
- **The recovery key now resets your password instead of opening the
  archive (Session 72).** Previously it logged you straight in and
  offered a password reset you could skip. That made it a second
  password — and since anyone using it has by definition forgotten
  theirs, skipping meant reaching for the printed key at every login,
  which is how a key meant for a drawer ends up photographed or pasted
  into a notes app. Now the key verifies, you choose a new password, and
  you sign in with it. Your recovery key still works afterwards and is
  unchanged. Supersedes the Session 70 gating below, which protected a
  session that no longer exists on this path.

### Security
- **The post-recovery password reset is now gated to the recovery login
  (Session 70).** The screen that sets a new password after a recovery-key
  login deliberately asks for no old password — the recovery key entered
  at login is the proof. But the route never checked *how* the session was
  established, so any logged-in session could reach it and replace the
  master password without proving any credential, and the form carried no
  CSRF token. The route now requires a session created by the recovery
  login itself and verifies a CSRF token; the upgrade form's POST now
  verifies one as well. Found in a code review of Sessions 68–69; no
  release ever shipped without the fix.

### Added
- **Restore points now say which credentials they need (Session 69).**
  Restoring replaces your key file, so a backup taken before a password
  change opens with the password you used then, not your current one —
  and one taken before recovery keys existed leaves the archive without
  one. Both were silent. Each restore point is now labelled, and the
  warning is repeated on the confirmation dialog before you commit.
  Backups from before the May 2026 encryption upgrade are marked as
  unopenable, because this version cannot read them at all.
- **Recovery keys (envelope encryption) — Session 68.** MailRepo can now
  protect an archive with a printable recovery key alongside the master
  password, so a forgotten password no longer means a lost archive. The
  master key becomes 32 random bytes wrapped twice — once under the
  password, once under the recovery key — and either one opens the
  archive. The recovery key is 32 characters in eight groups, drawn from
  an alphabet with no 0, 1 or 8 so the common transcription mistakes
  cannot happen; typing it back in tolerates lowercase, missing hyphens
  and spaces. It is shown once and never stored.

  New archives get a recovery key during setup. Existing archives are
  offered a one-time upgrade on the way in, which re-encrypts under a new
  random master — measured at roughly 850 messages per second, so seconds
  for a typical archive. A fresh backup is taken automatically first. The
  upgrade is resumable: if it is interrupted, log in and run it again.

  Because the master key no longer depends on the password, **changing
  your password on an upgraded archive is instant** — MailRepo rewrites
  61 bytes instead of re-encrypting every message, and the interruption
  risk that made password changes require a fresh backup disappears.

  If you forget your password, "Use your recovery key" on the login
  screen opens the archive and offers to set a new password immediately.
  Recovery keys can be regenerated from Settings, which revokes the old
  one at once — worth doing if a printed copy may have been seen.

  A recovery key opens your archive without the password, so treat it
  like a spare key to your office: somewhere physical, somewhere private,
  not filed next to the password. `docs/Security_Audit.md` covers what
  this does and does not protect against.

### Security
- **The password-change backup gate now verifies the backup on disk
  instead of trusting the manifest (Session 67).** The non-overridable
  "backup must be <=24h old" check read `manifest.json` and believed
  it. A manifest entry says nothing about whether the file still
  exists, was fully written, or — for backups kept in iCloud Drive —
  has been evicted to a cloud placeholder that still looks present.
  The gate could therefore open the non-resumable database rekey
  window with no real recovery path behind it. The gate now walks the
  entire newest restore chain and opens every file in it: existence,
  non-zero size, valid zip, `testzip()`. Opening forces cloud
  materialisation, so an evicted backup fails the check rather than
  failing at restore time. If verification fails, the password change
  is refused and names what broke; MailRepo does not silently
  substitute an older backup.
- **Interrupted password changes are now detected and explained
  (Session 67).** The database rekey and salt-file rewrite form a
  window that cannot be resumed. If MailRepo was killed inside it, the
  archive could be left half-re-encrypted, and the symptom was an
  "invalid master password" error — misleading, because the password
  was correct and the data was recoverable. A marker is now written
  before the window and cleared after it. On the next launch MailRepo
  reports what happened, tells you to try both your old and new
  password before assuming anything is lost, and names the backup that
  was verified immediately beforehand.

- **MailRepo now refuses to open or create the archive if SQLCipher is
  missing, instead of silently writing it unencrypted (Session 64).**
  `core/database.py` fell back to plain `sqlite3` when `sqlcipher3`
  failed to import, and the only consequence was that the `PRAGMA key`
  line was skipped. Everything else — passphrase prompt, UI, success
  path — behaved identically, so the archive was written in plaintext
  with no error and nothing in the logs. A new `require_sqlcipher()`
  guard runs before the database file is created, so no unencrypted
  file can come into existence, and `main.py` now reports the problem
  and exits at launch. This was most likely to bite in a packaged
  build shipped without the native extension correctly bundled.

### Fixed
- **Restoring a backup could silently lose a message you had deleted and
  later re-archived (Session 74).** If a message was permanently deleted
  in one backup and the same message archived again in a later one,
  restoring dropped it — and reported success. Deletions are now applied
  in the correct order as each backup is replayed.
- **A backup missing from the middle of a chain was ignored instead of
  reported (Session 74).** If one incremental backup went missing — a
  cloud file evicted, a sync interrupted — MailRepo quietly built a
  restore from the ones either side of it and showed no problem. That
  restore would have been missing everything the absent backup contained.
  Missing backups are now reported, and MailRepo refuses to change your
  password or upgrade your archive until the chain is whole.
- **Old backups could be deleted while the newest one was unusable
  (Session 74).** Cleanup kept the most recent backup without checking it
  could actually be opened. It now verifies first, and does nothing if
  the backup it would keep is damaged.
- **Two backups made in the same second overwrote each other
  (Session 74).** Backup filenames now include enough precision that this
  cannot happen.
- **Only the most recent safety backup was offered for restore
  (Session 74).** MailRepo takes a safety backup before every restore,
  but only the newest appeared in the list — and the moment you want an
  older one is right after a restore that went wrong. All of them are now
  listed.
- **Safety backups were written where your other backups aren't
  (Session 74).** They went to a folder inside the application rather
  than your configured backup location, so they never reached iCloud, a
  sync target, or any other machine.
- **An interrupted password change now explains itself (Session 74).**
  Stopping partway through re-encrypting left an archive that opened
  normally and then failed on scattered messages, with nothing on screen
  to say why. MailRepo now tells you what happened and that re-running
  the password change with the same passwords will finish the job.
- **Logging out is no longer possible by accident from another site
  (Session 74)**, and creating an archive folder now carries the same
  cross-site request protection as the rest of the application.
- **A damaged key file no longer reports "invalid master password"
  (Session 74).** It says the file appears truncated and to restore from
  backup, which is the actual problem.
- **Creating a folder from the stage-email destination picker reported a
  failure even though it worked (Session 73).** The folder was created,
  but the screen said "Failed to create folder" and didn't select it, so
  the obvious response was to try again and end up with duplicates. A
  JavaScript error stopped the code just after the folder was saved.
  Found by linting the frontend for the first time.
- **Backup retention was never applied to automatic backups
  (Session 69).** Old backups were only cleaned up when you pressed
  "Backup Now" by hand. Scheduled backups — which is nearly all of them
  — skipped the cleanup entirely, so a retention setting other than
  "Keep forever" quietly did almost nothing.
- **The recovery-key upgrade refused to run after promising to take a
  backup (Session 68).** The upgrade page says a fresh backup will be
  taken first, but asked for an automatic backup — which does nothing
  when no mail has changed since the last one. The upgrade then refused
  because the existing backup was too old, and the error appeared under
  the password field, so it looked like the password was being rejected.
  It now takes a full backup, which always produces one.
- **Buttons using the `hidden` attribute were displayed anyway
  (Session 68).** A styling rule overrode the browser's built-in
  hiding, so the Settings screen showed both "Add a Recovery Key" and
  "Generate New Recovery Key" at once even though only one applies.
- **Finishing the recovery-key upgrade landed on "Create New Archive"
  (Session 68)**, which looked alarmingly like the upgrade had erased
  the archive. It had not. That screen is only correct after first-run
  setup; after an upgrade you now return to your archive.
- **Malformed backup manifest entries no longer crash the restore
  screen (Session 67).** An entry missing `chain_id` raised a
  `KeyError` out of `get_restore_points()`, turning a backup-health
  check into a crash. Such entries are now skipped with a warning.
- **Post-backup commands are stopped honestly on timeout (Session 63).**
  The 300s timeout previously killed only the spawned shell; children
  (e.g. an rsync) survived as orphans and kept running after the UI
  reported failure. The command now runs in its own process group and
  the whole group is killed on timeout, with stdout captured and logged
  from both the logout and Backup Now paths.
- **Staging a conversation now deselects its individually-selected
  messages (Session 63)**, ending the spurious "selected but not staged"
  warning on navigation after Stage conversation.
- **Post-commit failure counts can no longer double-count (Session 57).**
  If a connection died between a batched Gmail delete completing and
  the re-select of the source folder — or any unexpected error escaped
  mid-folder — the folder/account failure handlers added the full item
  count over items already counted, producing summaries like
  "3 succeeded, 3 failed" for 3 items. Accounting is now tracked with
  an account-scoped set and the handlers count only unaccounted items.
- **`list_folders()` returns copies of its cached result (Session 57)**,
  so a caller mutating the returned list can't poison the
  per-connection cache.

### Changed
- **Bulk Gmail deletes are batched (Session 54).** Deleting several Gmail
  messages from a folder now issues one UID-set MOVE to Trash plus a
  single scoped EXPUNGE, instead of the full ~7-command per-message
  sequence — collapsing ~7×N commands to ~5 and cutting the round-trip
  latency that made multi-deletes slow (a two-email delete had been
  taking 60–90s). Single deletes and non-Gmail servers keep their
  existing path; partial failures are reported per-message.
- **Faster folder resolution during Gmail deletes (Session 53).** The
  IMAP client now caches its folder list for the connection's lifetime,
  so resolving the Trash/Spam folders no longer issues a fresh full LIST
  on every message. Removes redundant round-trips from Gmail's
  (inherently chatty) permanent-delete path; no behavioural change.
- **All destination-folder pickers now use one shared tree component
  (Session 51).** The move-emails and vault-restore pickers rendered
  their own flat, fully-expanded folder lists; both now use the same
  collapsible `renderFolderTree` (chevrons, collapse, color dots) as the
  commit/stage modal. Added a reusable `isSelectable` option to the
  component for per-picker target restrictions (e.g. can't move emails
  into the folder they're already in). Also removed a dead legacy
  folder-select handler.

### Fixed
- **Staging a thread no longer shows a hybrid Inbox/Staged screen (Session 55).**
  If you navigated to the Staged Items screen while a thread was still
  staging, the completion step repainted the inbox list into the shared
  content area, leaving the Staged Items chrome wrapped around inbox rows.
  The app now tracks which screen is active and repaints that one on
  completion, so the staged emails appear on the Staged Items screen
  immediately.
- **Moving emails no longer hides failures (Session 52).** If some moves
  in a batch failed, every selected email still vanished from the
  current view — the failures silently reappeared in their old folder
  on the next reload, and the user was never told. Now only
  successfully moved emails leave the view, failed moves are logged
  with full detail (email ID, target folder, HTTP status, server error
  text), and a "Move Incomplete" alert reports the failed/total count.
- **Bulk export was silently failing (Session 50).** Clicking Export in
  the export modal threw a runtime `TypeError` and never reached the
  server: `_exportPrefs` was declared `const` but `_startExport`
  reassigns it wholesale. Changed the binding to `let`. A frontend
  ESLint sweep (`no-const-assign` and related read-only-binding rules)
  confirmed there were no other instances of this class of bug.
- **Viewer action buttons are now gated on email load (Session 49).**
  The email viewer's always-on action buttons (copy-as-reply,
  view-source, download, print) had no visibility gating, so during the
  multi-second IMAP fetch they were clickable against a
  `currentViewerContext` that was either `null` (the click silently
  no-op'd) or still the previously-viewed email (the action applied to
  the *wrong* message). The whole action group is now hidden via a
  `loading` class on the viewer overlay until the email has rendered;
  the close button stays available throughout. The viewer context is
  also cleared at load-start, so keyboard shortcuts (j/k/s)
  short-circuit during the load as well. Side benefit: the "Stage
  thread" button no longer appears in sync with the body, which had
  looked like a background evaluation was gating it.

### Removed
- **Dead `refresh_hash_baseline()` and its callers (Session 48).** With
  the backup system now frequency-first (calendar-based), the hash
  baseline never gates whether a backup runs. The two surviving
  `refresh_hash_baseline()` calls — both in the no-backup branch of the
  auto-backup flow, in `web/blueprints/auth.py` and root `main.py` —
  and the deprecated function itself (`utils/backup.py`) are removed.
  No behavioural change; full suite green (345 tests).

### Added
- **Post-commit server action failures are now logged (Session 47).**
  All six failure paths in the post-commit action phase
  (`progress_commit.py`) previously swallowed errors silently — a
  failed commit reported "N server updates failed" with no
  diagnostics. Each path now logs a warning with the action, UID,
  folder/account, and the server's actual error text. `main.py` adds
  a console logging config (WARNING+, timestamps); deliberately no
  log file, since error strings can contain folder names.

### Fixed
- **"Server not responding" notice can now actually fire on connect
  failures (Session 47).** The SSE notice checked
  `isinstance(e, (socket.timeout, OSError))`, but `connect()` wraps
  all exceptions into `IMAPError`, so a connect timeout — the exact
  scenario the message was written for — never matched. `connect()`
  and `login()` now chain the cause (`raise ... from e`) and the
  check inspects `e.__cause__`.
- **Gmail-aware delete now runs in the live commit path (Session 46).**
  The Session 45 provider-aware delete had been wired into a dispatch
  function (`apply_post_commit_actions`) that no route called; the live
  `/api/commit/stream` workflow still ran a plain `delete_email()` on
  Gmail, which only strips the folder label and leaves the message in
  All Mail. Post-commit server actions now go through a single shared
  dispatcher, `apply_email_action()`, used by both live call sites in
  `progress_commit.py`; the dead duplicate dispatch code was removed.
- **`delete_email()` no longer issues a bare EXPUNGE (Session 46).**
  It now uses the UID-scoped expunge (`UID EXPUNGE` under UIDPLUS), so
  messages that *other* clients have flagged `\Deleted` but not yet
  expunged are left untouched.
- **Stale COPYUID can no longer be misattributed (Session 46).**
  `_parse_copyuid()` reads the COPYUID response code via
  `connection.response()`, which consumes the entry; previously a
  leftover COPYUID from an earlier command could be returned for a
  later move (worst case: expunging the wrong message in Trash).

### Added
- **Permanent delete for Gmail accounts (Session 45).** The Delete
  post-commit action is now available for Gmail/Google Workspace
  accounts. Gmail's IMAP delete only removes a folder label rather than
  the message, so it had been hidden for Gmail; it is now routed through
  a provider-aware path (`delete_email_via_trash`) that deletes in place
  when the source is already Trash/Spam, and otherwise moves the message
  to Trash and expunges it there. If the message reaches Trash but cannot
  be expunged, it is left for Gmail's ~30-day auto-purge. Added a `spam`
  folder type to `get_special_folder` and a shared `is_gmail_host` helper
  (`core/account_utils.py`).

### Tests
- **IMAP move/delete + dispatch coverage (Session 45).** Test suite
  320 → 346. First direct unit coverage of `core/imap.py`
  (`test_imap.py`, 20) — MOVE-vs-COPY selection, UID-scoped vs bare
  expunge, COPYUID parsing in both response forms, delete-via-trash
  (in-place Trash/Spam, move failure, expunge-fail-after-move,
  Message-ID fallback), and the call-site contract. Mocks the
  connection object only (no real IMAP, no Argon2id). Plus
  `test_account_utils.py` (4) and `test_commit_dispatch.py` (2 —
  provider routing and the per-iteration source re-select that
  single-call tests can't catch). Stays within the "no real IMAP
  protocol tests" principle: these exercise MailRepo's dispatch/parsing
  logic, not the protocol against a server.
- **Tier 3 + IMAP-helper coverage (Session 42).** Test suite 238 → 320.
  Added the export pipeline (`test_api_exports.py`, 39 — scope
  resolution, job state machine, plain + AES-256 ZIP decrypt
  round-trips), the importer (`test_importer.py`, 29 — driven by the
  `test_files/` edge cases, pinning that mail is archived byte-for-byte
  and a corrupt mbox is handled per-message), and the connection-free
  IMAP helpers (`test_sync_cache.py`, 14 — sync-cache TTL +
  `detect_server`). PDF/WeasyPrint and live IMAP connect/fetch remain
  intentionally uncovered (dogfooding territory).
- **Tier 2 API-surface coverage (Session 41).** Test suite 126 → 238.
  Added blueprint tests for emails (`test_api_emails.py`, 28), imports +
  export (`test_api_imports.py`, 19), accounts incl. runtime `is_gmail`
  detection (`test_api_accounts.py`, 23), the commit workflow —
  `commit.py` helpers + the SSE `/api/commit/stream` endpoint —
  (`test_commit.py`, 22), and threads + settings (`test_api_threads.py`,
  6; `test_api_settings.py`, 14). Data-integrity and security paths are
  exercised against real AES-256-GCM fixtures (decrypt-and-parse viewer,
  unencrypted-ZIP export round-trip, atomic save-to-archive with
  orphan-file cleanup, SSE import round-trip); live-IMAP paths are
  covered only at their pre-connection validation boundary.

### Changed
- **`move_email` hardened (Session 45).** Now prefers IMAP MOVE
  (RFC 6851, atomic) when the server supports it, falling back to
  COPY + STORE + EXPUNGE; the expunge is UID-scoped (RFC 4315/UIDPLUS)
  when available instead of a bare EXPUNGE that sweeps every
  `\Deleted`-flagged message in the folder (bare expunge preserved as
  the no-UIDPLUS fallback — no behaviour change on older servers). It
  now returns the moved message's new UID (from the COPYUID response)
  rather than a bool. Benefits the existing Archive and Trash
  post-commit actions, not just the new Gmail delete.
- **Search view (Archive Search).** Reworked the search interface to
  match the rest of the app's filter-input pattern. Live search with a
  300ms debounce replaces the explicit "Search" button; an X clear
  button inside the input field replaces the separate "Clear" button.
  The Export button is now always visible (disabled when there are no
  results) instead of appearing on first result, so the toolbar no
  longer reflows when a search returns. Helper text and the no-results
  state both surface the `*` prefix-matching syntax explicitly, since
  FTS5's default is whole-word matching.

### Refactored (no behavior change)
- **Repo-wide formatter pass (Session 44, `ruff format`).** First
  application of the formatter on the codebase: 51 of 59 files
  reformatted, 8 already conformant. Changes are stylistic only —
  quote normalization, dict/call literal layout, argument formatting.
  One manual fix in `core/pdf_export.py` to preserve py3.11
  compatibility where the formatter would have created same-quote
  f-string nesting (only valid on py3.12+ per PEP 701).
  `.git-blame-ignore-revs` added so the reformat doesn't obscure
  `git blame`. Suite green at 320 throughout.
- **Final whitespace cleanup (Session 44, ruff W291/W293).** The 171
  trailing-whitespace findings inside docstrings and multi-line SQL
  strings that Session 43 left as "would edit string contents":
  applied. Dry-run `--diff` confirmed the changes are pure
  whitespace-only and SQL is whitespace-insensitive at token
  boundaries. `ruff check` now reports zero errors.
- **Repo-wide lint pass (Session 43, ruff E/F/W/I).** Converted all 32
  bare `except:` to `except Exception:` (also stops the SSE generators
  swallowing `GeneratorExit`), removed unused imports/locals and empty
  f-strings, split a semicolon idiom, and applied whitespace + import
  ordering. Intentional patterns (route-registration imports, the
  `sys.path` entry point and dev scripts) are documented via
  `per-file-ignores` rather than altered. Suite green at 320; codebase
  is ruff-clean apart from intentional whitespace inside string literals.
- **Frontend dispatch model unified.** Replaced every inline
  `onclick="..."` attribute (in render-generated HTML and the
  `index.html` template) and every cross-module `window.X = X`
  assignment with a uniform delegation model: per-view
  `bindActions(container, handlers)` for view-scoped clicks, plus a
  single `template-bindings.js` delegated handler on `document.body`
  for template-level actions. 11 files converted across sessions on
  May 30–31, 2026. Closes the three "global `window` pollution",
  "inline onclick", and "mixed event handling patterns" items from
  `docs/Code_Quality_Review.md`.
- **`closeModal` consolidated.** Three modules each defined their own
  `closeModal` and assigned to `window.closeModal`; load order
  determined which won. Replaced with a single canonical
  implementation in `modals.js` plus a
  `registerModalCloseHandler(modalId, callback)` extension point for
  per-modal cleanup (used by `settings.js` for the Add Account form
  reset).

### Security
- **Master passwords no longer transit the session cookie.** The
  change-password flow previously stashed the current and new master
  password in the Flask session — a signed-but-unencrypted client
  cookie. They are now held only in server-side memory keyed by an
  opaque one-time job id (the same model the export pipeline uses) and
  consumed exactly once by the progress stream.
- **Folder color is validated server-side.** The folder-update endpoint
  accepts only a null/empty value or a `#rgb` / `#rrggbb` hex string,
  since the color is interpolated into a `style` attribute on render.

### Fixed
- **Atomic backup-state and manifest writes.** `data/.backup_state.json`
  and `backups/manifest.json` are now written via the same crash-safe
  `temp + fsync + os.replace + fsync(dir)` pattern as the salt file, so
  an interrupted write can't truncate the change-detection baseline.
- **JSON error responses on API failures.** Uncaught exceptions on
  `/api/` paths now return a JSON 500 instead of Flask's HTML error
  page, so the frontend always receives a parseable response. Non-API
  routes are unaffected.
- **Modal pickers no longer stack click listeners.** The Move-Email and
  Restore-destination pickers re-bound a delegated listener on every
  modal open; they now bind exactly once.

---

## [1.0.0] — Unreleased (dogfooding)

The first stable release. Local-first encrypted email archiving for solo
practitioners (lawyers, therapists, journalists, etc.) who need local
control over sensitive client correspondence without cloud dependency.

Rick is dogfooding 1.0 before tagging. This section captures what 1.0
is; the date and tag will land when dogfooding settles.

### Added

#### Encryption
- **AES-256-GCM file encryption** for every archived email and every
  stored IMAP credential. Per-file random 96-bit nonce. Wire format:
  `[0x02 version byte][12-byte nonce][ciphertext][16-byte GCM tag]`,
  with the version byte bound into GCM AAD so tampering breaks the
  auth check.
- **Argon2id key derivation** at memory-hard parameters
  (m=256 MiB, t=6, p=1), measured ~750 ms per derivation on Apple M4.
  A single Argon2id master feeds HKDF-Expand with domain-separated
  `info` strings (`mailrepo.file.v2`, `mailrepo.db.v2`) into the file
  key and the SQLCipher DB key, keeping the slow derivation single per
  unlock.
- **SQLCipher AES-256 database** with class-level `threading.RLock`
  serializing all access and a `_migration_active` flag that grants
  exclusive ownership during rekey windows.
- **Forward-compatible salt file** with `MRC2` magic and a per-file 0x02
  version byte so any future crypto migration can detect "this archive
  is on v2" and act accordingly.
- **Atomic salt file writes** via `temp + fsync(file) + os.replace +
  fsync(directory)` — crash-safe against power loss during rekey.

#### Workflow
- **Stage → Review → Commit pipeline** with SSE progress streaming.
  Resumable commits via the `pending_commit` table: if an SSE stream is
  interrupted, the next call with `resumeCommitId` picks up from where
  it left off.
- **IMAP integration** with auto-detection for Gmail (incl. Google
  Workspace), iCloud, Outlook / Hotmail / Live, and Fastmail.
- **Gmail-aware post-commit options.** "Delete" is hidden for Gmail
  accounts because Gmail's IMAP delete just archives — misleading
  semantics. "Archive" maps to `[Gmail]/All Mail` at the IMAP layer.
- **Master password change** with file-walk re-encryption + SQLCipher
  rekey + new salt file write. Non-overridable backup-≤24h check
  before the irreversible DB rekey window.
- **Encrypted bulk export** to per-export-password ZIP archives via
  pyzipper (AES-256). Non-PDF attachments included as sibling files in
  the wrapper ZIP. First-use friction modal explaining the encryption
  boundary.
- **Archived email file operations:** move, soft delete, restore,
  permanent delete; batch select with "X of Y selected" counter;
  dedicated Trash view with Folders + Emails tabs.

#### Backup
- **Scheduled backups** (every session / daily / weekly / manual;
  default daily) with 7-day incremental + full cycle.
  External `data/.backup_state.json` keeps the hash baseline outside
  the encrypted DB to avoid spurious change detection from WAL
  checkpoints.
- **Configurable retention** (1 month / 6 months / 1 year / forever;
  default forever).
- **Post-backup rsync hook** for replication to a remote server.
- **Persistent "Last Checked" indicator** in the Backup & Restore
  status card that updates on every Backup Now click, even on no-op.

#### UI
- **Three-pane layout:** rail / sidebar / main, with resizable sidebar.
- **Five themes:** Pine (default), Graphite, Atlantic, Ember, Obsidian.
- **Right-click context menu** for folder operations.
- **Collapsible search tips** and subfolder breadcrumbs.
- **Full-text search** via FTS5 with native column operators
  (`sender:`, `recipients:`, `subject:`, `body_text:`).
- **IMAP folder list caching** with a two-layer approach (TTL
  short-circuit + CONDSTORE/HIGHESTMODSEQ) and a manual refresh button.

#### Tooling
- **126 unit tests** across the auth boundary (login, rate-limit lockout,
  CSRF, password-change job-id handoff), encryption (v2 wire format + AAD
  binding), database (thread safety), email parser, API folders, password
  change, the backup system (change detection, WAL-checkpoint no-op,
  interrupted-backup safety), and the commit-resume state machine.

[Unreleased]: https://github.com/rsembera/mailrepo/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/rsembera/mailrepo/releases/tag/v1.0.0
