# MailRepo — Navigation Map

**Last Updated:** September 1, 2026

---

## Project Status: 1.0.0 — Public

Feature-complete. Encryption refactor (v1 → v2) shipped May 29. v1
cleanup + 1.0 declaration on May 30. Frontend dispatch model unified
May 30–31 (zero inline onclicks, zero cross-module window dispatch
remaining).

**August 9–11:** v3 envelope encryption landed — the master key is now
32 random bytes wrapped separately under the password and under a
printable recovery key, so password changes are a 61-byte rewrap rather
than a full re-encryption, and a forgotten password is no longer fatal.
The recovery key resets the password rather than opening the archive.
Rick's live archive is migrated and verified under both credentials.
Backup hardening followed: on-disk chain verification, restore-point
credential labelling, and the fixes from the pre-tag adversarial review
(Session 74), two of which were silent data loss in the restore path.

**August 31, 2026 — launched.** `v1.0.0` is public: signed and notarized
`.dmg`, `.deb` built and GUI-tested native on Trixie, repository public
at `github.com/rsembera/mailrepo`, site live at `mailrepo.ca`. Both
artifacts verified anonymously from the public release URLs.

**September 1, 2026 — website follow-up.** Mobile pass (cropped
screenshots served via `<picture>`, collapsible docs table of contents,
phone notice on the download page, three pre-existing overflow bugs
fixed), Liwan analytics, `robots.txt`, `sitemap.xml`, canonical URLs,
and Google Search Console verification. No app code changed. See
`Session_Log.md` Session 90.

**September 2, 2026 — screenshot crop.** The four desktop screenshots
were captured 3px wider than the app window and carried a strip of the
Apollo desktop at the right edge; cropped to 1460×953. They live in
**two** places — `docs/screenshots/` here and `img/screenshots/` in the
website repo — and are kept byte-identical, so any recapture must
update both. The mobile variants are website-only. See `Session_Log.md`
Session 91.

Release artifact hashes are published in **two** places — `README.md`
and the website's `download.html`. Any rebuild must update both or they
disagree. Verified in sync on September 1, 2026.

See `docs/Session_Log.md` (Sessions 36–38 for the road to 1.0, 67–74 for
the recovery-key work and the pre-tag review) for details
and `CHANGELOG.md` for the user-facing changelog under
`[1.0.0] — Unreleased (dogfooding)`.

---

## Key Documents

| Document | Purpose |
|----------|---------|
| `docs/Navigation_Map.md` | This file — codebase overview and context recovery |
| `docs/Session_Log.md` | Chronological record of sessions and decisions |
| `docs/Known_Issues.md` | Tracked open issues (e.g. intermittent slow Sentinel backup sync) + their instrumentation |
| `docs/Post_1_0_Backlog.md` | Post-1.0 items: packaging, tag, website, deferred work |
| `docs/Test_Coverage_Plan.md` | Tiered plan for the post-1.0 test-coverage expansion |
| `CHANGELOG.md` | User-facing changelog (Keep a Changelog format) |
| `docs/TESTING_CHECKLIST.md` | Manual testing checklist for release |
| `docs/Security_Audit.md` | Feb 4, 2026 pre-release security review |
| `docs/Backup_State_Management.md` | Backup state file design (Libram-style external state) |
| `docs/Code_Quality_Review.md` | Jan 26 / Feb 17 code quality findings (most items closed) |
| `docs/Flagging_Plan.md` | Star/flag feature design |
| `docs/Stage_Thread_Plan.md` | Thread staging design |
| `docs/MailRepo_Project_Plan.md` | Original planning document (Jan 2026, historical) |
| `docs/archive/` | Completed plan docs: crypto refactor, bulk export, retention vault, V1 refactoring plans |

---

## Codebase Overview (~39,000 lines)

| Language | Files | Lines |
|----------|-------|-------|
| Python | 35 | 13,823 |
| JavaScript | 29 | 16,386 |
| CSS | 23 | 7,497 |
| HTML | 5 | 1,331 |
| **Total** | **92** | **39,037** |

Roughly doubled since the Feb 4, 2026 snapshot (was ~20,100 lines).
Largest growth: encryption refactor (Sessions 36–37), retention vault
(Session 35), PDF export pipeline (`core/pdf_export.py`), bulk export
(`api/exports.py`), and the frontend dispatch unification
(Sessions 37–38).

---

## Backend (Python — 13,929 lines)

### Root & packaging (`/`)

| File | Lines | What It Does |
|------|-------|--------------|
| `main.py` | 305 | Command-line entry: `prepare_app()` runs the pre-flight checks (SQLCipher, pending restore, interrupted-state warnings) and builds the app; `main()` serves it with waitress and wires the checkpoint-and-backup shutdown |
| `launcher.py` | 323 | Packaged-app entry (Session 88): pywebview window around the server; archive under Application Support / XDG data; free-port pick; second instance refused; shutdown on window close; DesktopApi bridge (open_bytes, print_html) for what a webview cannot do |
| `setup_app.py` | 140 | py2app manifest — first-party code declared as packages; `install_requires` cleared so py2app builds from the venv |
| `packaging/bundle_dylibs.py` | 155 | Post-py2app pass: otool closure of WeasyPrint's and readpst's Homebrew libraries into Contents/Frameworks + Helpers, install-name rewrite, re-sign, leak check |
| `assets/icon.icns`, `packaging/icons/` | — | App icons rendered from `web/static/assets/icon.svg` (macOS .icns, Linux hicolor set) |

### Core (`/core/`)

| File | Lines | What It Does |
|------|-------|--------------|
| `imap.py` | 1,535 | IMAP client: connect, auth, folders, fetch, MOVE/COPY + UID-scoped expunge, Gmail-aware delete (incl. batched set delete), CONDSTORE |
| `pdf_export.py` | 1,052 | PDF export: per-email PDFs, attachment merging, WeasyPrint |
| `encryption.py` | 912 | Argon2id KDF + HKDF + AES-256-GCM (v2) plus the v3 envelope: random master wrapped under password and recovery key, each wrapper verified to open before the key file is written; work factor via argon2_parameters() — production everywhere, cheap only when the test suite's double guard (MAILREPO_FAST_KDF + MAILREPO_DATA_DIR) is met |
| `password_change.py` | 636 | Password change — v2 full re-encryption, v3 rewrap; recovery-key password reset (needs no unlocked session), recovery-key rotation, on-disk backup gate, interruption marker |
| `database.py` | 465 | SQLCipher connection, schema v5, FTS5, migrations, threading lock, hard refusal to open unencrypted |
| `crypto_migration_v3.py` | 335 | v2 → v3 migration: re-encrypt under a random master, resumable via wrapped-master state file |
| `importer.py` | 280 | mbox, Apple mbox, EML, PST import handling |
| `pending_commit.py` | 222 | Commit resume: save/restore interrupted commits |
| `config.py` | 150 | Paths, constants, Flask config; state dir outside the app folder for the backup-location record |
| `sync_cache.py` | 111 | Two-layer IMAP folder cache (TTL + CONDSTORE/HIGHESTMODSEQ) |
| `__init__.py` | 30 | Module exports |
| `account_utils.py` | 18 | Shared account helpers (`is_gmail_host` — Gmail provider detection) |

### Web App (`/web/`)

| File | Lines | What It Does |
|------|-------|--------------|
| `app.py` | 212 | Flask factory, blueprint registration, auth/CSRF middleware |

### Blueprints (`/web/blueprints/`)

| File | Lines | What It Does |
|------|-------|--------------|
| `auth.py` | 1,292 | Setup, login, logout, rate limiting, session management; recovery-key verification + server-side handoff to a mandatory password reset (no session granted), v3 upgrade flow, rotation API; pre-login disaster-recovery routes (`/auth/restore`, scan, prepare, search, browse) gated on `_recovery_door_open()` — no archive, OR an unverified restore; both login paths vouch for restored data (clear the marker) and the login screens carry the restored-from-backup banner |
| `backups.py` | 273 | Backup/restore endpoints, folder picker |
| `main.py` | 81 | Page routes: index, create_archive, settings |

### API (`/web/blueprints/api/`)

| File | Lines | What It Does |
|------|-------|--------------|
| `exports.py` | 997 | Bulk PDF/encrypted-ZIP export pipeline + SSE progress |
| `emails.py` | 839 | Archived email operations: view, move, delete, batch, download; folder listing carries per-subfolder tree counts |
| `filesystem.py` | 807 | File browser for imports, path validation, PST conversion |
| `imports.py` | 796 | Mount/unmount imports, browse imported emails/folders |
| `progress_commit.py` | 701 | SSE streaming for commit operations; batched Gmail deletes; unified post-action failure accounting + logging (Sessions 47/54/57) |
| `folders.py` | 711 | Archive folder CRUD, trash, restore, vault, retention; `tree_email_counts()` is the single roll-up behind every folder size the app shows |
| `accounts.py` | 495 | IMAP account CRUD, Gmail auto-detection, folder listing |
| `commit.py` | 488 | Email/folder commit workflow |
| `email_parser.py` | 336 | Email parsing: headers, body, attachments, body text extraction |
| `progress_emails.py` | 286 | SSE streaming for email operations |
| `settings.py` | 247 | App settings: timeout, retention, keepalive |
| `streaming.py` | 162 | SSE helpers, heartbeat, connection management |
| `threads.py` | 138 | Thread search and staging endpoints |
| `progress.py` | 63 | Progress entry point (split into streams/state/handlers in Session 37) |

### Utilities (`/utils/`)

| File | Lines | What It Does |
|------|-------|--------------|
| `backup.py` | 2,219 | Full/incremental backup, restore, retention, external state file (Libram-style), on-disk restore-chain verification, manifest sidecars stamped with the app identity and written to every backup destination, a durable record of backup locations kept outside the app folder, record-first location lookup (no disk search -- the folder picker covers unknown locations), filename-based chain reconstruction; unverified-restore marker (`data/.restore_unverified`, set by complete_restore, never inside a zip) |
| `log.py` | 51 | Logging setup, polling filter |
| `__init__.py` | 34 | Shell command runner, path utilities |

---

## Frontend (JavaScript — 16,386 lines)

### Entry Point & Shared

| File | Lines | What It Does |
|------|-------|--------------|
| `password-toggle.js` | 128 | Show/hide password toggle (Session 88): auto-wires password inputs; reserve computed inline from the button's measured band (Daybook PLAN.md 9ab — CSS reserves lose specificity fights silently); re-mask defers submit one painted frame |
| `desktop.js` | 82 | Desktop-shell bridge (Session 88): no-ops in a browser; in the packaged app routes open-in-new-tab, print, and same-origin _blank links through DesktopApi |
| `app.js` | 737 | Init, event listeners, rail nav, nav guards, template-bindings wiring |
| `template-bindings.js` | 143 | Single delegated handler for index.html data-tpl-action attrs (Session 38) |
| `delegate.js` | 116 | `bindActions(container, handlers)` helper for per-view delegation |
| `state.js` | 137 | Central state object, session persistence |
| `utils.js` | 90 | escapeHtml, formatDate, debounce, extractName |
| `modals.js` | 144 | Alert/confirm/prompt + canonical closeModal + registerModalCloseHandler |
| `recovery-key.js` | 123 | One-time recovery-key screen: copy / print / download, beforeunload guard |

### Views (`/js/views/`)

| File | Lines | What It Does |
|------|-------|--------------|
| `mail.js` | 2,319 | Email viewing (IMAP/archive/import), search, viewer, keyboard nav |
| `settings.js` | 1,468 | Settings: appearance, accounts, security, recovery-key status + check + rotation, backup, reset |
| `review.js` | 1,035 | Review staged items, destination editing, commit |
| `backups.js` | 1,004 | Backup/restore UI, restore points, settings |
| `folder-selection.js` | 897 | Bulk folder staging from IMAP/imports |
| `vault.js` | 881 | Retention vault: move to vault, restore, permanent delete; subfolder links carry tree counts |
| `trash.js` | 775 | Trash view: deleted folders, emails, restore, purge |
| `folder-mgmt.js` | 667 | Manage folders: rename, color, create, delete |
| `starred.js` | 369 | Starred email view |
| `recover.js` | 337 | Pre-login disaster recovery: scan a backup folder, list restore points, stage a restore. Deliberately talks to nothing else — there is no session, database or settings when it runs |

### Components (`/js/components/`)

| File | Lines | What It Does |
|------|-------|--------------|
| `export-modal.js` | 867 | Bulk export UI: scope picker, scope-aware password, progress |
| `email-list.js` | 793 | Email list rendering, selection, toolbar, filter input |
| `sidebar.js` | 744 | Sidebar: archive folders, IMAP folders, imports, resize |
| `imports.js` | 728 | Import mount/unmount, browse, folder/email display |
| `staging.js` | 561 | Staging workflow, destination picker, stage/unstage |
| `file-picker.js` | 438 | Filesystem browser modal for import file selection |
| `date-picker.js` | 383 | Date picker (ported from EdgeCase) for vault retention dates |
| `progress.js` | 352 | SSE progress modal for commit/import operations |
| `context-menu.js` | 288 | Right-click context menu for sidebar/folders |
| `folder-tree.js` | 265 | Reusable folder tree renderer |
| `custom-select.js` | 223 | Custom dropdown select component |
| `thread-stage.js` | 207 | Stage-entire-thread modal from email viewer |
| `move-email-modal.js` | 112 | Move archived emails between folders |

---

## CSS (7,497 lines)

| File | Lines | What It Does |
|------|-------|--------------|
| `shared.css` | 944 | Design tokens, buttons, forms, utilities, credential badges, restored-from-backup notice |
| `themes.css` | 318 | Five themes: Atlantic, Ember, Graphite, Obsidian, **Pine** (default) |
| `main.css` | 23 | Import hub for all module CSS |

Per-module stylesheets in `/css/modules/`: settings-view (606), backups-view (603),
email-list (599), modals (569), export (513), sidebar (441), vault (413),
review-view (325), email-viewer (332), folder-mgmt (320), content (293),
folder-selection (255), date-picker (242), trash (230), folder-tree (215),
layout (169), custom-select (121), progress (120), responsive (84),
context-menu (69).

---

## Templates (`/web/templates/`)

| File | Lines | What It Does |
|------|-------|--------------|
| `main/index.html` | 697 | Main dashboard (three-pane layout); all interactivity via data-tpl-action |
| `base.html` | 423 | Base layout, left rail, sidebar, content area, modals |
| `auth/login.html` | 92 | Login form; includes the restored-from-backup banner |
| `auth/setup.html` | 76 | Master password setup; links to disaster recovery so a lost archive is not mistaken for a first run |
| `auth/recover.html` | 62 | Pre-login restore: backup-folder input, restore points, credential note |
| `main/create_archive.html` | 63 | First-run archive creation |
| `auth/_restored_banner.html` | 15 | Shared partial (first in the codebase): restore date + credential note on both login screens, "Restore a different backup" while unverified |

As of Session 38, `index.html` has zero inline onclick handlers. All
template interactivity dispatches through `template-bindings.js` via
`data-tpl-action` attributes.

---

## Data & Storage

```
/Users/rick/Applications/mailrepo/
├── data/
│   ├── mailrepo.db          # SQLCipher-encrypted database (key via Argon2id+HKDF)
│   ├── .salt                # "MRC2"[32B salt][AES-256-GCM verifier]
│   ├── .secret_key          # Flask session key (0o600 permissions)
│   └── .sync_cache.db       # Plaintext SQLite for IMAP folder cache
├── archive/
│   └── {folder_id}/
│       └── {account}_{uid}.eml.enc   # AES-256-GCM encrypted (per-file nonce, version 0x02)
├── backups/
│   ├── .backup_state.json   # Backup state (mtime/size hashes, cycle position)
│   ├── full_*.zip
│   └── incr_*.zip
└── config/                  # Reserved
```

Per-file encryption format:
- Byte 0: version (0x02)
- Bytes 1–12: 12-byte random GCM nonce
- Bytes 13+: AES-256-GCM ciphertext + auth tag

Forward infrastructure for v3: bump to `MRC3` / `0x03` / HKDF info `.v3`
so a future KDF/cipher change derives cryptographically distinct keys
even if the master password collides across versions.

---

## Database Schema (v5)

```sql
accounts        (id, name, email, provider, credentials_encrypted,
                 cached_folders, cached_folders_at, created_at, last_sync,
                 UNIQUE(email, provider))
                 -- IMAP server/port live inside credentials_encrypted (JSON),
                 -- not as columns; is_gmail is derived at runtime from the
                 -- decrypted creds host (see api/accounts.py).
folders         (id, name, parent_id, retention_days, retention_date, color,
                 deleted_at, created_at)
messages        (id, folder_id, original_folder_id, source_account_id,
                 message_id, subject, sender, recipients, date, filepath,
                 body_text, deleted_at, flagged_at, filed_at)
messages_fts    -- FTS5 virtual table over (subject, sender, recipients, body_text)
settings        (key, value)
pending_commit  (id, commit_id, item_type, item_data, destination_folder_id,
                 source_action, status, created_at, updated_at)
email_cache     (id, account_id, folder_name, uid, uidvalidity, subject, sender,
                 recipients, date, message_id, cached_at,
                 UNIQUE(account_id, folder_name, uid, uidvalidity))
```

Notable indexes: `idx_folders_retention` (vault queries),
`idx_messages_message_id` (thread lookups), `idx_pending_commit_id`
(commit resume).

---

## How to Run

```bash
cd /Users/rick/Applications/mailrepo
source venv/bin/activate
python main.py
# Opens at http://127.0.0.1:5050
```

### Linting

Python is covered by `ruff check .`. The frontend has no automated tests
at all — no Python test executes any JavaScript — so ESLint's `no-undef`
is its only safety net. Run it before committing UI changes:

```bash
npx --yes eslint@9 --no-config-lookup -c eslint.config.mjs \
  "web/static/js/**/*.js" --ignore-pattern "**/lucide.min.js"
```

Baseline is 0 errors, 64 warnings. Any new **error** is a real bug; the
first run of this found a `ReferenceError` that had been shipping.

### First Run

1. Create master password (12+ characters; Argon2id-derived master key)
2. Create first archive folder
3. Settings → Add IMAP account (Gmail auto-detected from server hostname)
4. Browse emails, stage to folders, review, commit

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `MAILREPO_DATA_DIR` | `./data` | Database and salt location |
| `MAILREPO_DEBUG` | `False` | Enable Flask debug mode |

---

## Test Suite (664 tests)

| File | Coverage |
|------|----------|
| `tests/test_packaging_manifest.py` | Drift alarm for `setup_app.py`: imports the app for real and fails on any undeclared third-party package; user-data dirs never bundled; load-bearing native packages named; launcher is the entry point (13 tests, Session 88) |
| `tests/test_kdf_cost.py` | The KDF work factor: production Argon2id numbers pinned as literals, the cheap path requiring both env vars (flag alone useless, sandbox alone useless), and a full-cost v3 round trip + a timing floor proving production derivation still works and is still expensive — the two things the fast suite can no longer speak to (8 tests, Session 81) |
| `tests/test_unverified_restore.py` | The unverified-restore marker: set by complete_restore (with the credential note carried through), never inside any zip, survives a relaunch, recovery door open while it stands and closed on either side of it, both login paths clearing it (password, verified recovery key) and both failure paths not, the login banner surviving failed attempts, second restore from the unverified state taking its safety copy; isolation tripwire on the marker path; all guards proved mutation-capable (22 tests, Session 80) |
| `tests/test_recovery_key_web.py` | Recovery-key web flow end to end: setup shows the key (and never puts it in the session), recovery login, post-recovery password reset (incl. gating to recovery-login sessions and CSRF), v3 upgrade flow (incl. stale-backup-with-no-changes and CSRF), post-upgrade redirect destination, rotation API + CSRF (31 tests, Sessions 68–70) |
| `tests/test_crypto_migration_v3.py` | v2 → v3 envelope migration: content survives, readable under both credentials, interrupted migration re-runs to completion, resume state halts rather than minting a new master; v3 password change as rewrap; recovery-key rotation; wrappers verified to open before the key file is written (49 tests, Session 76) |
| `tests/test_recovery_key.py` | v3 envelope: recovery-key format and parse tolerance, wrapping structure, unlock by either credential yielding identical keys, tamper detection, independent rewrap of each wrapper (40 tests, Session 68) |
| `tests/test_restore.py` | Restore path: staged files decrypt to original plaintext, backup carries its own key material, incremental chains and deletion propagation, staging-is-not-production, complete/cancel, chain verification, restore-point credential labelling; plus Session 74 regressions — delete-then-recreate, missing mid-chain incremental, filename collisions, safety-backup visibility and location, retention refusing to prune when the kept chain is broken (41 tests, Sessions 68–74) |
| `tests/test_disaster_recovery.py` | Recovery with no archive to log in to: manifest sidecars written to every backup destination and surviving an unwritable one, folder discovery via sidecar or filename reconstruction, chain-reconstruction rules (incrementals join the preceding full, a new full starts a chain, orphans dropped, chronological not lexical ordering), credential note when no key file remains, route gates (public with no archive, closed once one is vouched for, open again for an unverified restore, CSRF), the full loop from total loss to decryptable mail, and a vanished backup destination not being recreated by the sidecar write (64 tests, Sessions 77-80, 85) |
| `tests/test_auth.py` | Auth boundary: setup, login + rate-limit lockout, logout, CSRF enforcement, password-change job-id handoff end-to-end (22 tests, Session 40) |
| `tests/test_encryption.py` | v2 `Encryption` lifecycle: init / unlock / lock / wrong-password (no v1 code remains) |
| `tests/test_encryption_v2.py` | v2 encryption: Argon2id, HKDF, AES-256-GCM, file/DB round-trip |
| `tests/test_password_change.py` | v2-native password change; on-disk backup gate (missing/truncated/zero-byte) + interruption marker lifecycle (23 tests, Session 67) |
| `tests/test_backup.py` | Backup: state-file round-trip + corruption degrade, change detection, WAL-checkpoint no-op, interrupted-backup baseline safety (17 tests, Session 39) |
| `tests/test_pending_commit.py` | Commit-resume state machine: session creation, status transitions, resume detection, post-action filtering, clear/discard (19 tests, Session 39) |
| `tests/test_database.py` | Schema, migrations, FTS5 |
| `tests/test_database_threading.py` | Concurrent access, RLock behavior |
| `tests/test_email_parser.py` | Header/body/attachment parsing |
| `tests/test_api_folders.py` | Folder CRUD via API; Retention Vault accepts arbitrary retention periods, not just the UI presets; per-subfolder tree counts so a folder holding only subfolders does not read as empty, in the archive and the vault alike (20 tests) |
| `tests/test_api_emails.py` | Emails API: FTS search (folder scoping, subfolder toggle, trash exclusion), folder listing, decrypt-and-parse viewer + raw source via real encrypted fixtures, soft-delete/restore (incl. needs-destination 409), permanent delete, flagging, move (28 tests, Session 41) |
| `tests/test_api_imports.py` | Import + export API: mbox/eml scan + import validation, single-.eml import round-trip, import-email content + attachment from disk, unencrypted-ZIP folder export decrypt round-trip (19 tests, Session 41) |
| `tests/test_api_accounts.py` | Accounts API: listing + runtime `is_gmail` detection, create/update validation, no-password update, cached-folder fast path, delete, server detection (23 tests, Session 41) |
| `tests/test_commit.py` | Commit helpers (archive-folder-from-path, duplicate detection, summary, post-action key parsing, atomic save + orphan cleanup) + SSE `/api/commit/stream` empty-guard and import round-trip (22 tests, Session 41) |
| `tests/test_api_threads.py` | Thread-discovery request validation before IMAP connect (6 tests, Session 41) |
| `tests/test_api_settings.py` | Settings API: validated retention/timeout/thread-size endpoints, session-status, keepalive, reset-database guards (14 tests, Session 41) |
| `tests/test_api_exports.py` | Export pipeline: scope resolution (folder/messages/search + subfolders + FTS), job state machine (save-to-disk, disambiguation, TTL GC), plain + AES-256 ZIP decrypt round-trips, endpoint contracts (39 tests, Session 42) |
| `tests/test_importer.py` | Importer: header decode + metadata, mbox/eml import driven by `test_files/` edge cases; malformed mail archived byte-for-byte, corrupt mbox handled per-message (29 tests, Session 42) |
| `tests/test_sync_cache.py` | Sync-cache state + TTL freshness logic, and the pure `IMAP.detect_server` domain lookup (14 tests, Session 42) |
| `tests/test_imap.py` | `core/imap.py` dispatch logic via a mocked connection (no real IMAP): MOVE-vs-COPY, UID-scoped vs bare expunge, COPYUID parsing, Gmail delete-via-trash, spam-folder resolution, call-site contract (20 tests, Session 45) |
| `tests/test_account_utils.py` | `is_gmail_host` host detection (4 tests, Session 45) |
| `tests/test_commit_dispatch.py` | Post-commit dispatch: Gmail vs standard delete routing, per-iteration source re-select over multiple UIDs (2 tests, Session 45) |

Run with `pytest -q` from project root.

---

## Frontend Dispatch Model

As of Session 38 the codebase uses a uniform two-layer dispatch model:

1. **Per-view delegation** via `bindActions(container, handlers, eventTypes)`
   in `web/static/js/delegate.js`. Each view binds its handlers on a
   view-specific child wrapper (e.g. `.starred-view-root`, `.trash-view-root`)
   so the listener dies with the view when another render replaces
   `emailList`'s `innerHTML`. Resolves nested clickables via
   `closest('[data-action]')`.

2. **Template-level delegation** via `template-bindings.js`. A single
   click listener on `document.body` resolves `data-tpl-action` attributes
   in `index.html` to ES-imported functions. Args via data attributes:
   `data-modal-id` (closeModal), `data-direction` (viewerNavigate),
   `data-confirm` (resolveConfirm), `data-prompt-cancel` (resolvePrompt
   cancel branch), `data-rail-view` (jump to a rail tab).

No remaining inline `onclick` attributes anywhere in the codebase.
Two intentional `window.X` assignments remain: `getMountedImports`
(cross-module lazy reference) and `skipBeforeUnloadWarning` (internal
self-reference in app.js). Plus `mailrepoLogout` in base.html, which is
a template-scoped helper rather than a module export — logout is
POST-only, so the template needs a way to submit it.

`pendingMoveEmailIds` was a third cross-module global until Session 74;
it is now a module-local in `move-email-modal.js` with an exported
setter, the `staging.js` pattern.

---

## If Chat Context Disappears

1. Read this file first.
2. Read `docs/Session_Log.md` — most recent sessions are 67–68 (Aug 9,
   restore drill + v3 envelope encryption with recovery keys), 69–71
   (Aug 9–10, restore-point credential labelling, retention fix,
   recovery-key design), 72–73 (Aug 11, recovery key becomes a password
   reset rather than a credential; verify-without-using), and 74
   (Aug 11, pre-tag adversarial review and fixes).
3. Read `docs/Post_1_0_Backlog.md` for what's still open.
4. `git log --oneline -20` to see recent commits.
5. Run `python main.py` to see current state.
