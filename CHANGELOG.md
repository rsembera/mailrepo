# Changelog

All notable changes to MailRepo will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Changed
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
- **Session-based backup** with 7-day incremental + full cycle.
  External `data/.backup_state.json` keeps the hash baseline outside
  the encrypted DB to avoid spurious change detection from WAL
  checkpoints.
- **Configurable retention** (default 6 months).
- **Post-backup rsync hook** for replication to a remote server.
- **Persistent "Last Checked" indicator** in the Backup & Restore
  status card that updates on every Backup Now click, even on no-op.

#### UI
- **Three-pane layout:** rail / sidebar / main, with resizable sidebar.
- **Five themes:** Pine (default), Lagoon, Graphite, Midnight, Atlantic.
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
