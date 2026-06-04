# Changelog

All notable changes to MailRepo will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Tests
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
