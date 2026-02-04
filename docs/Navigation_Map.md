# MailRepo — Navigation Map

**Last Updated:** February 4, 2026

---

## Project Status: Pre-Release Testing

All features built. Security audit passed (see Security_Audit.md). Ready for manual testing per TESTING_CHECKLIST.md.

---

## Key Documents

| Document | Purpose |
|----------|---------|
| `docs/Navigation_Map.md` | This file — codebase overview and context recovery |
| `docs/Session_Log.md` | Chronological record of all sessions and decisions |
| `docs/SESSION_NOTES.md` | Quick-reference notes for current/recent sessions |
| `docs/Security_Audit.md` | Feb 4, 2026 pre-release security review |
| `docs/TESTING_CHECKLIST.md` | Manual testing checklist for release |
| `docs/Code_Quality_Review.md` | Jan 26 code quality findings (historical) |
| `docs/Refactoring_Plan.md` | Phase 1 refactoring — ✅ Complete |
| `docs/Refactoring_Plan_V2.md` | Phase 2 refactoring — ✅ Complete |
| `docs/MailRepo_Project_Plan.md` | Original planning document (Jan 2026) |

---

## Codebase Overview (~20,100 lines of code)

Per `cloc` (excluding blanks, comments, markdown, and vendored libraries):

| Language | Files | Code | Blank | Comment |
|----------|-------|------|-------|---------|
| JavaScript | 20 | 7,828 | 1,463 | 1,551 |
| Python | 29 | 5,551 | 1,629 | 1,745 |
| CSS | 19 | 4,404 | 847 | 357 |
| HTML | 5 | 1,033 | 105 | 48 |
| **Total** | **76** | **20,113** | | |

## Backend (Python)

### Core (`/core/`)

| File | Lines | What It Does |
|------|-------|--------------|
| `config.py` | 113 | Paths, constants, Flask config |
| `database.py` | 391 | SQLCipher connection, schema v3, FTS5, migrations |
| `encryption.py` | 339 | Fernet encryption, PBKDF2 key derivation, password management |
| `imap.py` | 623 | IMAP client: connect, auth, folders, email fetch, SSL/TLS |
| `importer.py` | 274 | mbox, Apple mbox, EML, PST import handling |
| `pending_commit.py` | 214 | Commit resume: save/restore interrupted commits |
| `__init__.py` | 30 | Module exports |

### Web App (`/web/`)

| File | Lines | What It Does |
|------|-------|--------------|
| `app.py` | 149 | Flask factory, blueprint registration, auth/CSRF middleware |

### Blueprints (`/web/blueprints/`)

| File | Lines | What It Does |
|------|-------|--------------|
| `auth.py` | 396 | Setup, login, logout, rate limiting, session management |
| `main.py` | 83 | Page routes: index, create_archive, review, settings |
| `backups.py` | 276 | Backup/restore endpoints, folder picker |

### API (`/web/blueprints/api/`)

| File | Lines | What It Does |
|------|-------|--------------|
| `accounts.py` | 394 | IMAP account CRUD, folder listing, email fetching |
| `commit.py` | 580 | Email/folder commit workflow, SSE progress |
| `email_parser.py` | 314 | Email parsing: headers, body, attachments, body text extraction |
| `emails.py` | 442 | Archived email operations: view, move, delete, batch, download |
| `filesystem.py` | 796 | File browser for imports, path validation, PST conversion |
| `folders.py` | 352 | Archive folder CRUD, trash, restore, permanent delete |
| `imports.py` | 616 | Mount/unmount imports, browse imported emails/folders |
| `progress.py` | 624 | SSE streaming for commit, import, and folder operations |
| `settings.py` | 189 | App settings: timeout, retention, keepalive |
| `staging.py` | 324 | Stage/unstage emails and folders, review data |
| `streaming.py` | 156 | SSE helpers, heartbeat, connection management |

### Utilities (`/utils/`)

| File | Lines | What It Does |
|------|-------|--------------|
| `backup.py` | 987 | Full/incremental backup, restore, retention, manifest |
| `log.py` | 51 | Logging setup, polling filter |
| `__init__.py` | 48 | Shell command runner, path utilities |

## Frontend (JavaScript)

### Entry Point & Shared

| File | Lines | What It Does |
|------|-------|--------------|
| `app.js` | 643 | Initialization, event listeners, rail navigation, nav guards |
| `state.js` | 106 | Central state object, session persistence |
| `utils.js` | 82 | escapeHtml, formatDate, debounce, extractName |
| `modals.js` | 131 | Alert, confirm, prompt modal helpers |

### Components (`/js/components/`)

| File | Lines | What It Does |
|------|-------|--------------|
| `sidebar.js` | 576 | Sidebar: archive folders, IMAP folders, imports, resize |
| `email-list.js` | 543 | Email list rendering, selection, toolbar |
| `staging.js` | 509 | Staging workflow, destination picker, stage/unstage |
| `imports.js` | 647 | Import mount/unmount, browse, folder/email display |
| `file-picker.js` | 438 | Filesystem browser modal for import file selection |
| `progress.js` | 338 | SSE progress modal for commit/import operations |
| `folder-tree.js` | 255 | Reusable folder tree renderer (configurable) |
| `custom-select.js` | 212 | Custom dropdown select component |
| `move-email-modal.js` | 126 | Modal for moving archived emails between folders |

### Views (`/js/views/`)

| File | Lines | What It Does |
|------|-------|--------------|
| `mail.js` | 1,108 | Email viewing: IMAP, archive, import, viewer panel |
| `settings.js` | 1,030 | Settings page: appearance, accounts, security, backup |
| `review.js` | 970 | Review staged items, destination editing, commit |
| `backups.js` | 924 | Backup/restore UI, restore points, settings |
| `folder-selection.js` | 855 | Bulk folder staging from IMAP/imports |
| `trash.js` | 694 | Trash view: deleted folders, emails, restore, purge |
| `folder-mgmt.js` | 655 | Manage folders: rename, color, create, delete, ZIP export |

## CSS

| File | Lines | What It Does |
|------|-------|--------------|
| `shared.css` | 601 | Design tokens, buttons, forms, utilities |
| `themes.css` | 308 | Lagoon, Graphite, Midnight, Bloom, Rose themes |
| `main.css` | 19 | Import hub for all module CSS |

### CSS Modules (`/css/modules/`)

| File | Lines |
|------|-------|
| `settings-view.css` | 606 |
| `backups-view.css` | 577 |
| `modals.css` | 507 |
| `email-list.css` | 497 |
| `sidebar.css` | 320 |
| `folder-mgmt.css` | 320 |
| `review-view.css` | 323 |
| `email-viewer.css` | 270 |
| `folder-selection.css` | 250 |
| `trash.css` | 248 |
| `folder-tree.css` | 198 |
| `content.css` | 127 |
| `layout.css` | 123 |
| `progress.css` | 122 |
| `custom-select.css` | 108 |
| `responsive.css` | 84 |

---

## Templates (`/web/templates/`)

| File | Lines | What It Does |
|------|-------|--------------|
| `base.html` | 423 | Base layout, left rail, sidebar, content area, modals |
| `main/index.html` | 575 | Main dashboard (three-pane layout) |
| `main/create_archive.html` | 63 | First-run archive creation |
| `auth/setup.html` | 68 | Master password setup |
| `auth/login.html` | 57 | Login form |

## Data & Storage

```
/home/rick/Applications/mailrepo/
├── data/
│   ├── mailrepo.db          # SQLCipher-encrypted database
│   ├── .salt                # PBKDF2 salt (32 bytes)
│   └── .secret_key          # Flask session key (0o600 permissions)
├── archive/
│   └── {folder_id}/
│       └── {account}_{uid}.eml.enc   # Fernet-encrypted .eml files
├── backups/
│   ├── manifest.json        # Backup history and metadata
│   ├── full_*.zip           # Full backups
│   └── incr_*.zip           # Incremental backups
└── config/                  # Reserved for future use
```

---

## Database Schema (v3)

```sql
accounts    (id, name, email, provider, server, port, credentials_encrypted,
             cached_folders, cached_folders_at, created_at, last_sync)
folders     (id, name, parent_id, color, retention_days, created_at,
             deleted_at, original_parent_id)
messages    (id, folder_id, source_account_id, message_id, subject, sender,
             recipients, date, filepath, filed_at, body_text, deleted_at)
messages_fts (subject, sender, body_text)  -- FTS5 virtual table
settings    (key, value)
pending_commit (id, batch_id, item_type, item_data, destination_folder_id,
                source_action, status, created_at, updated_at)
```

---

## How to Run

```bash
cd /home/rick/Applications/mailrepo
source venv/bin/activate
python main.py
# Opens at http://127.0.0.1:5050
```

### First Run

1. Create master password (12+ characters)
2. Create first archive folder
3. Go to Settings → Add IMAP account
4. Browse emails, stage to folders, review, commit

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `MAILREPO_DATA_DIR` | `./data` | Database and salt location |
| `MAILREPO_DEBUG` | `False` | Enable Flask debug mode |

---

## If Chat Context Disappears

1. Read this file first
2. Read `SESSION_NOTES.md` for current state
3. Read `Session_Log.md` for full history
4. Read `Security_Audit.md` for security review results
5. Run `python main.py` to see current state
