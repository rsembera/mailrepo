# MailRepo — Project Plan

**Created:** January 16, 2026  
**Updated:** January 22, 2026  
**Status:** In Development

---

## What Is MailRepo?

MailRepo is an encrypted email archiving application for solo practitioners who need to file client correspondence securely. It provides a simple web interface for browsing Gmail/IMAP accounts and filing emails into organized, encrypted folders.

**Philosophy:** Your correspondence, your machine, your control.

---

## The Problem

Solo practitioners (therapists, lawyers, accountants, doctors, consultants) need to:
- Archive client correspondence for compliance and reference
- Keep archives encrypted and local (not in the cloud)
- File emails by client/matter without manual drag-and-drop
- Access archives from any device on their network

**Current solutions fail because:**
- Thunderbird/Mail.app: No encryption at rest, clunky filing
- Enterprise archiving: Overkill, expensive, cloud-based
- Manual export: Tedious, no organization, no search

---

## Target Users

| Profession | Why They Need It |
|------------|------------------|
| Therapists | PHIPA/HIPAA compliance, client correspondence records |
| Lawyers | Matter files, privilege protection, retention requirements |
| Accountants | Client file organization, CRA correspondence |
| Doctors | Patient correspondence, referral letters |
| Consultants | Project correspondence, client records |
| Journalists | Source protection, research archives |

**Common thread:** Solo or small practice, handles sensitive correspondence, needs local control.

---

## Core Features

### MVP (Phase 1) — Current

| Feature | Status | Description |
|---------|--------|-------------|
| IMAP Support | ✅ Done | Connect to any IMAP server (Gmail, iCloud, Fastmail, etc.) |
| Inbox Browser | ✅ Done | View emails in a clean web interface |
| Folder System | ✅ Done | Create/manage archive folders with hierarchy |
| Stage → Review → Commit | ✅ Done | Batch filing workflow with review step |
| Full Encryption | ✅ Done | SQLCipher database + AES-256-GCM email files |
| Full-Text Search | ✅ Done | FTS5 search across subject, sender, body |
| Duplicate Detection | ✅ Done | Skip emails already in destination folder |
| Multi-Account | ✅ Done | Support multiple IMAP accounts |
| Folder Management | ✅ Done | Rename, move, color-code, delete folders |
| Trash System | ✅ Done | Soft-delete with restore capability |
| Theme Support | ✅ Done | 5 themes including dark mode |

### Phase 2 — Next

| Feature | Description |
|---------|-------------|
| .mbox Import | Import existing email archives (backend ready) |
| ZIP Export | Export archives/folders as unencrypted ZIP files |
| Attachments | View/download email attachments |
| Archive View | Browse and manage archived emails |

### Phase 3 — Future

| Feature | Description |
|---------|-------------|
| Auto-Suggest | Suggest folder based on sender/subject patterns |
| Retention | Auto-archive or delete based on folder rules |
| AI Categorization | Suggest folder based on content analysis |
| EdgeCase Integration | Link MailRepo folders to EdgeCase client files |

---

## Technical Architecture

### Stack

| Component | Technology |
|-----------|------------|
| Backend | Python 3.13, Flask |
| Database | SQLCipher (encrypted SQLite) |
| Encryption | AES-256-GCM (cryptography library) + SQLCipher (AES-256), keys via Argon2id + HKDF |
| Email Access | imaplib (IMAP) |
| Frontend | HTML, CSS, vanilla JavaScript |
| Search | FTS5 (inside encrypted database) |
| .mbox Parsing | Python `mailbox` module (stdlib) |

### Storage Structure

```
mailrepo/                    # Application directory
├── data/
│   ├── mailrepo.db          # SQLCipher encrypted database
│   ├── .salt                # Password salt + verification token
│   └── .secret_key          # Flask session key
├── archive/
│   └── {folder_id}/
│       └── *.eml.enc        # AES-256-GCM encrypted .eml files
├── config/                  # (reserved for future use)
└── backups/
```

Data location can be overridden with `MAILREPO_DATA_DIR` environment variable.

**Note:** All emails are encrypted. The database stores metadata (subject, sender, body text for search) and is fully encrypted with SQLCipher. Email files are encrypted with AES-256-GCM.

### Database Schema

```sql
-- Email accounts (IMAP)
CREATE TABLE accounts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,           -- "Work Gmail", "Personal"
    email TEXT NOT NULL,
    provider TEXT NOT NULL,       -- 'imap'
    credentials_encrypted TEXT,   -- AES-256-GCM-encrypted IMAP credentials
    cached_folders TEXT,          -- JSON array of folder names
    cached_folders_at INTEGER,    -- Cache timestamp
    created_at INTEGER,
    last_sync INTEGER
);

-- Archive folders (unified across accounts)
CREATE TABLE folders (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,           -- "Client: John Smith"
    parent_id INTEGER,            -- For nested folders
    color TEXT,                   -- Hex color for folder dot
    deleted_at INTEGER,           -- Soft-delete timestamp (NULL = active)
    retention_days INTEGER,       -- NULL = keep forever
    created_at INTEGER,
    FOREIGN KEY (parent_id) REFERENCES folders(id)
);

-- Archived messages
CREATE TABLE messages (
    id INTEGER PRIMARY KEY,
    folder_id INTEGER NOT NULL,
    source_account_id INTEGER,    -- Which account it came from (NULL for imports)
    message_id TEXT NOT NULL,     -- Email Message-ID header
    subject TEXT,
    sender TEXT,
    recipients TEXT,              -- JSON array
    date INTEGER,                 -- Email date timestamp
    filepath TEXT NOT NULL,       -- Path to .eml.enc file
    body_text TEXT,               -- Plain text for FTS indexing
    deleted_at INTEGER,           -- Soft-delete timestamp
    filed_at INTEGER,
    FOREIGN KEY (folder_id) REFERENCES folders(id),
    FOREIGN KEY (source_account_id) REFERENCES accounts(id)
);

-- Full-text search index
CREATE VIRTUAL TABLE messages_fts USING fts5(
    subject, sender, body_text,
    content='messages', content_rowid='id'
);

-- Application settings (key-value store)
CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

---

## User Interface

### Design System

**Reuse from EdgeCase:**
- CSS custom properties (colors, spacing, shadows)
- Button styles (.btn, .btn-primary, .btn-secondary, .btn-danger)
- Form elements (inputs, selects, textareas with consistent styling)
- Modal system
- Card components
- Lucide icons

**Theme support:** 5 themes — Lagoon (default), Graphite, Bloom, Rose, Midnight (dark)

**Typography:** Lexend for UI, Inter for body text (same as EdgeCase).

### Main Layout (Three-Pane)

```
┌────┬──────────────┬─────────────────────────────────────────┐
│    │              │  Context Header          [Stage] [Review]│
│ R  │  SIDEBAR     ├─────────────────────────────────────────┤
│ A  │              │                                         │
│ I  │  Accounts    │  EMAIL LIST                             │
│ L  │  > Gmail     │  ──────────────────────────────────     │
│    │    INBOX     │  ☐ From: alice@example.com              │
│ 📧 │    Sent      │    Subject: Re: Meeting notes           │
│ 📦 │              │    Jan 15, 2026                         │
│ 📁 │  Archive     │                                         │
│ 🗑  │  > Client A  │  ☐ From: bob@corp.com                   │
│    │    > Sub     │    Subject: Invoice attached            │
│ ⚙  │  > Client B  │    Jan 14, 2026                         │
│ ↪  │  + New       │                                         │
└────┴──────────────┴─────────────────────────────────────────┘
```

**Left Rail:** Mail view, Staged emails, Folder Management, Trash, Settings, Logout

### Folder Management View

- Full-width view (sidebar hidden)
- Zebra-striped rows for easy tracking
- Columns: Folder (with hierarchy), Color, Actions
- Actions: Rename, Move, Add Subfolder, Delete
- Color picker with 9 preset colors
- "New Folder" button at bottom

### Trash View

- Shows soft-deleted folders
- Restore or permanently delete
- "Empty Trash" for bulk deletion
- Auto-rename on restore if name conflict exists

### Staging Workflow

1. **Browse & Select** — Checkboxes on emails, "Select All" option
2. **Stage to Folder** — Modal with folder tree, can create new folders
3. **Review & Commit** — Shows staged emails, destination folders, commit button
4. **Progress** — Shows archiving progress with duplicate detection

### Settings View

- **Accounts:** Add/edit/remove IMAP accounts with auto-detection
- **Appearance:** Theme selection with live preview
- **Security:** Change master password

---

## Security Model

### Encryption

| Data | Protection |
|------|------------|
| Database | SQLCipher (AES-256) — entire DB encrypted at rest |
| Archived emails | AES-256-GCM (authenticated encryption) |
| IMAP credentials | AES-256-GCM encrypted in database |
| FTS index | Inside SQLCipher — encrypted with database |
| In transit | TLS (IMAP) |

### Master Password

- **Always required** on startup (modal before anything loads)
- Derives two separate keys via Argon2id (m=256 MiB, t=6) + HKDF-Expand:
  - File key for email/credential encryption (AES-256-GCM)
  - SQLCipher raw key for database encryption
- Password never stored; only verification token

### Access Control

- Runs on localhost only (by default)
- Optional: Tailscale for remote access
- No multi-user support (solo practitioner tool)
- CSRF tokens on all state-changing API requests
- Session timeout with configurable duration
- Login rate limiting (5 attempts, 60s lockout)

### Email Rendering

- HTML emails rendered in sandboxed iframe (no script execution)
- CSP blocks remote content (images, fonts) by default
- "Load Remote Content" button for explicit user opt-in

---

## Resolved Design Decisions

| Question | Decision | Rationale |
|----------|----------|-----------|
| Archive structure | Unified folder tree | Client might email from multiple accounts |
| Deduplication | Skip duplicates | Check Message-ID before archiving |
| Attachment handling | Keep in .eml | Simplicity; extract on view |
| EdgeCase integration | Build later | Standalone first |
| Filing UX | Stage → Review → Commit | Batch-first, matches real workflow |
| Folder creation | Modal-in-modal | Stay in flow when staging |
| Encryption scope | Everything encrypted | SQLCipher DB + AES-256-GCM files; no unencrypted option |
| Password requirement | Always required | Needed to decrypt database |
| First-run flow | Create archive first | Forces deliberate decision before filing |
| Email protocol | IMAP only | Simpler than OAuth; works with any provider |
| Search | FTS5 in SQLCipher | Full-text search inside encrypted database |
| Folder hierarchy | Unlimited nesting | Subfolders with expand/collapse in sidebar |
| Folder deletion | Soft-delete to trash | Recoverable with auto-rename on conflict |
| Folder organization | Move via modal | Simpler than drag-and-drop, works on mobile |

---

## Success Criteria

1. **Works for you** — Can archive Light in Extension correspondence
2. **Simple to use** — Filing a batch of emails takes < 2 minutes
3. **Secure** — Encrypted at rest, no cloud dependency
4. **Reliable** — Search finds what you need
5. **Portable** — Backup = copy the folder

---

## Notes

- Don't overbuild — IMAP works, no need for OAuth complexity
- Don't compete with enterprise — different market, different values
- Don't require cloud — local-first, Tailscale for remote
- Don't forget Sentinel — backup archive to home server
- Reuse EdgeCase patterns — CSS, icons, components

---

*"Email archiving, done right."*
