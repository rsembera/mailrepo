# MailRepo — Navigation Map

**Last Updated:** May 31, 2026

---

## Project Status: 1.0 / Dogfooding

Feature-complete. Encryption refactor (v1 → v2) shipped May 29. v1
cleanup + 1.0 declaration on May 30. Frontend dispatch model unified
May 30–31 (zero inline onclicks, zero cross-module window dispatch
remaining). Currently in the dogfooding window before `git tag v1.0.0`
and the packaging milestone (.dmg / .deb).

See `docs/Session_Log.md` (Sessions 36–38) for the road-to-1.0 details
and `CHANGELOG.md` for the user-facing changelog under
`[1.0.0] — Unreleased (dogfooding)`.

---

## Key Documents

| Document | Purpose |
|----------|---------|
| `docs/Navigation_Map.md` | This file — codebase overview and context recovery |
| `docs/Session_Log.md` | Chronological record of sessions and decisions |
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

## Codebase Overview (~38,700 lines)

| Language | Files | Lines |
|----------|-------|-------|
| Python | 35 | 13,565 |
| JavaScript | 29 | 16,359 |
| CSS | 23 | 7,497 |
| HTML | 5 | 1,331 |
| **Total** | **92** | **38,752** |

Roughly doubled since the Feb 4, 2026 snapshot (was ~20,100 lines).
Largest growth: encryption refactor (Sessions 36–37), retention vault
(Session 35), PDF export pipeline (`core/pdf_export.py`), bulk export
(`api/exports.py`), and the frontend dispatch unification
(Sessions 37–38).

---

## Backend (Python — 13,565 lines)

### Core (`/core/`)

| File | Lines | What It Does |
|------|-------|--------------|
| `imap.py` | 1,356 | IMAP client: connect, auth, folders, fetch, MOVE/COPY + UID-scoped expunge, Gmail-aware delete, CONDSTORE |
| `pdf_export.py` | 1,052 | PDF export: per-email PDFs, attachment merging, WeasyPrint |
| `database.py` | 432 | SQLCipher connection, schema v5, FTS5, migrations, threading lock |
| `encryption.py` | 385 | Argon2id KDF + HKDF + AES-256-GCM file/DB encryption (v2) |
| `password_change.py` | 344 | v2-native password change with full file/DB re-encryption |
| `importer.py` | 280 | mbox, Apple mbox, EML, PST import handling |
| `pending_commit.py` | 222 | Commit resume: save/restore interrupted commits |
| `config.py` | 114 | Paths, constants, Flask config |
| `sync_cache.py` | 111 | Two-layer IMAP folder cache (TTL + CONDSTORE/HIGHESTMODSEQ) |
| `__init__.py` | 30 | Module exports |
| `account_utils.py` | 18 | Shared account helpers (`is_gmail_host` — Gmail provider detection) |

### Web App (`/web/`)

| File | Lines | What It Does |
|------|-------|--------------|
| `app.py` | 180 | Flask factory, blueprint registration, auth/CSRF middleware |

### Blueprints (`/web/blueprints/`)

| File | Lines | What It Does |
|------|-------|--------------|
| `auth.py` | 465 | Setup, login, logout, rate limiting, session management |
| `backups.py` | 273 | Backup/restore endpoints, folder picker |
| `main.py` | 81 | Page routes: index, create_archive, settings |

### API (`/web/blueprints/api/`)

| File | Lines | What It Does |
|------|-------|--------------|
| `exports.py` | 997 | Bulk PDF/encrypted-ZIP export pipeline + SSE progress |
| `emails.py` | 824 | Archived email operations: view, move, delete, batch, download |
| `filesystem.py` | 807 | File browser for imports, path validation, PST conversion |
| `imports.py` | 744 | Mount/unmount imports, browse imported emails/folders |
| `folders.py` | 670 | Archive folder CRUD, trash, restore, vault, retention |
| `progress_commit.py` | 622 | SSE streaming for commit operations; post-action failures logged with error text (Session 47) |
| `commit.py` | 488 | Email/folder commit workflow |
| `accounts.py` | 495 | IMAP account CRUD, Gmail auto-detection, folder listing |
| `email_parser.py` | 336 | Email parsing: headers, body, attachments, body text extraction |
| `progress_emails.py` | 286 | SSE streaming for email operations |
| `settings.py` | 247 | App settings: timeout, retention, keepalive |
| `streaming.py` | 162 | SSE helpers, heartbeat, connection management |
| `threads.py` | 138 | Thread search and staging endpoints |
| `progress.py` | 63 | Progress entry point (split into streams/state/handlers in Session 37) |

### Utilities (`/utils/`)

| File | Lines | What It Does |
|------|-------|--------------|
| `backup.py` | 1,211 | Full/incremental backup, restore, retention, external state file (Libram-style) |
| `log.py` | 51 | Logging setup, polling filter |
| `__init__.py` | 34 | Shell command runner, path utilities |

---

## Frontend (JavaScript — 16,359 lines)

### Entry Point & Shared

| File | Lines | What It Does |
|------|-------|--------------|
| `app.js` | 730 | Init, event listeners, rail nav, nav guards, template-bindings wiring |
| `template-bindings.js` | 143 | Single delegated handler for index.html data-tpl-action attrs (Session 38) |
| `delegate.js` | 116 | `bindActions(container, handlers)` helper for per-view delegation |
| `state.js` | 124 | Central state object, session persistence |
| `utils.js` | 90 | escapeHtml, formatDate, debounce, extractName |
| `modals.js` | 144 | Alert/confirm/prompt + canonical closeModal + registerModalCloseHandler |

### Views (`/js/views/`)

| File | Lines | What It Does |
|------|-------|--------------|
| `mail.js` | 2,299 | Email viewing (IMAP/archive/import), search, viewer, keyboard nav |
| `settings.js` | 1,217 | Settings: appearance, accounts, security, backup, reset |
| `review.js` | 1,034 | Review staged items, destination editing, commit |
| `backups.js` | 952 | Backup/restore UI, restore points, settings |
| `folder-selection.js` | 895 | Bulk folder staging from IMAP/imports |
| `vault.js` | 858 | Retention vault: move to vault, restore, permanent delete |
| `trash.js` | 774 | Trash view: deleted folders, emails, restore, purge |
| `folder-mgmt.js` | 667 | Manage folders: rename, color, create, delete |
| `starred.js` | 368 | Starred email view |

### Components (`/js/components/`)

| File | Lines | What It Does |
|------|-------|--------------|
| `export-modal.js` | 867 | Bulk export UI: scope picker, scope-aware password, progress |
| `email-list.js` | 778 | Email list rendering, selection, toolbar, filter input |
| `sidebar.js` | 744 | Sidebar: archive folders, IMAP folders, imports, resize |
| `imports.js` | 728 | Import mount/unmount, browse, folder/email display |
| `staging.js` | 561 | Staging workflow, destination picker, stage/unstage |
| `file-picker.js` | 438 | Filesystem browser modal for import file selection |
| `date-picker.js` | 383 | Date picker (ported from EdgeCase) for vault retention dates |
| `progress.js` | 352 | SSE progress modal for commit/import operations |
| `context-menu.js` | 288 | Right-click context menu for sidebar/folders |
| `folder-tree.js` | 265 | Reusable folder tree renderer |
| `custom-select.js` | 223 | Custom dropdown select component |
| `thread-stage.js` | 197 | Stage-entire-thread modal from email viewer |
| `move-email-modal.js` | 112 | Move archived emails between folders |

---

## CSS (7,497 lines)

| File | Lines | What It Does |
|------|-------|--------------|
| `shared.css` | 637 | Design tokens, buttons, forms, utilities |
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
| `main/index.html` | 693 | Main dashboard (three-pane layout); all interactivity via data-tpl-action |
| `base.html` | 423 | Base layout, left rail, sidebar, content area, modals |
| `auth/login.html` | 84 | Login form |
| `auth/setup.html` | 68 | Master password setup |
| `main/create_archive.html` | 63 | First-run archive creation |

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

## Test Suite (345 tests)

| File | Coverage |
|------|----------|
| `tests/test_auth.py` | Auth boundary: setup, login + rate-limit lockout, logout, CSRF enforcement, password-change job-id handoff end-to-end (22 tests, Session 40) |
| `tests/test_encryption.py` | v2 `Encryption` lifecycle: init / unlock / lock / wrong-password (no v1 code remains) |
| `tests/test_encryption_v2.py` | v2 encryption: Argon2id, HKDF, AES-256-GCM, file/DB round-trip |
| `tests/test_password_change.py` | v2-native password change (15 tests added Session 37) |
| `tests/test_backup.py` | Backup: state-file round-trip + corruption degrade, change detection, WAL-checkpoint no-op, interrupted-backup baseline safety (17 tests, Session 39) |
| `tests/test_pending_commit.py` | Commit-resume state machine: session creation, status transitions, resume detection, post-action filtering, clear/discard (19 tests, Session 39) |
| `tests/test_database.py` | Schema, migrations, FTS5 |
| `tests/test_database_threading.py` | Concurrent access, RLock behavior |
| `tests/test_email_parser.py` | Header/body/attachment parsing |
| `tests/test_api_folders.py` | Folder CRUD via API |
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
self-reference in app.js).

---

## If Chat Context Disappears

1. Read this file first.
2. Read `docs/Session_Log.md` — most recent sessions are 36 (May 29
   crypto refactor), 37 (May 30 1.0 ship), 38 (May 31 frontend
   cleanup).
3. Read `docs/Post_1_0_Backlog.md` for what's still open.
4. `git log --oneline -20` to see recent commits.
5. Run `python main.py` to see current state.
