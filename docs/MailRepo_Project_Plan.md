# MailRepo — Project Plan

**Created:** January 16, 2026  
**Updated:** January 21, 2026  
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
| Folder System | ✅ Done | Create/manage archive folders (unified across accounts) |
| Stage → Review → Commit | ✅ Done | Batch filing workflow with review step |
| Full Encryption | ✅ Done | SQLCipher database + Fernet email files |
| Full-Text Search | ✅ Done | FTS5 search across subject, sender, body |
| Duplicate Detection | ✅ Done | Skip emails already in destination folder |
| Multi-Account | ✅ Done | Support multiple IMAP accounts |

### Phase 2 — Next

| Feature | Description |
|---------|-------------|
| .mbox Import | Import existing email archives (backend ready) |
| ZIP Export | Export archives/folders as unencrypted ZIP files |
| Unstage UI | View and manage staged emails |
| Attachments | View/download email attachments |

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
| Encryption | Fernet (cryptography library) + SQLCipher (AES-256) |
| Email Access | imaplib (IMAP) |
| Frontend | HTML, CSS, vanilla JavaScript |
| Search | FTS5 (inside encrypted database) |
| .mbox Parsing | Python `mailbox` module (stdlib) |

### Storage Structure

```
~/mailrepo/
├── data/
│   ├── mailrepo.db          # SQLCipher encrypted database
│   ├── .salt                # Password salt + verification token
│   └── .secret_key          # Flask session key
├── archive/
│   └── {folder_id}/
│       └── *.eml.enc        # Fernet encrypted .eml files
├── config/                  # (reserved for future use)
└── backups/
```

**Note:** All emails are encrypted. The database stores metadata (subject, sender, body text for search) and is fully encrypted with SQLCipher. Email files are encrypted with Fernet.

### Database Schema

```sql
-- Email accounts (IMAP)
CREATE TABLE accounts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,           -- "Work Gmail", "Personal"
    email TEXT NOT NULL,
    provider TEXT NOT NULL,       -- 'imap'
    credentials_encrypted TEXT,   -- Fernet-encrypted IMAP credentials
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

**Reuse from EdgeCase/Synesius:**
- CSS custom properties (colors, spacing, shadows)
- Button styles (.btn, .btn-primary, .btn-secondary, .btn-danger)
- Form elements (inputs, selects, textareas with consistent styling)
- Modal system
- Card components
- Responsive breakpoints

**Theme support:** Start with EdgeCase's "Tutti-Frutti" or "Slate" theme, can add more later.

**Typography:** Lexend for UI, Inter for body text (same as EdgeCase).

### First-Run Experience

1. **Master Password Setup**
   - User creates master password
   - Explanation: "This password encrypts your OAuth tokens and any encrypted archives"

2. **Create First Archive**
   - "Create an Archive" page appears after password setup
   - User names their first archive folder
   - Chooses: Encrypted or Unencrypted
   - Helper text explains the difference:
     - Encrypted: "For client correspondence, sensitive materials. Requires password to view."
     - Unencrypted: "For personal emails, newsletters. Faster access, no decryption needed."

3. **Connect First Account**
   - Prompt to connect Gmail (or skip for now)
   - OAuth flow

### Main Layout

```
┌─────────────────────────────────────────────────────────────┐
│  [Account Dropdown ▼]           [Stage (12)] [Review]       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  FOLDERS              │  EMAIL LIST                         │
│  ────────────────     │  ──────────────────────────────     │
│  🔒 Client: Smith     │  ☐ From: alice@example.com          │
│  🔒 Client: Jones     │    Subject: Re: Meeting notes       │
│  📁 Personal          │    Jan 15, 2026                     │
│  + New Folder         │                                     │
│                       │  ☐ From: bob@corp.com               │
│                       │    Subject: Invoice attached        │
│                       │    Jan 14, 2026                     │
│                       │                                     │
│                       │  [Select All ☐]                     │
│                       │                                     │
└───────────────────────┴─────────────────────────────────────┘
```

**Folder icons:** 🔒 for encrypted, 📁 for unencrypted.

### Account Dropdown Options

- Work Gmail
- Personal Gmail
- (divider)
- **Archive** ← Switch to archive browsing mode
- (divider)
- Import .mbox...
- Export Archive...
- Settings

### Staging Workflow

1. **Browse & Select**
   - User views email list from selected account/folder
   - Checkboxes next to each email
   - "Select All" checkbox at top
   - Persistent badge shows "12 emails staged" (always visible)

2. **Stage to Folder**
   - Click "Stage" button
   - Modal shows folder tree with search
   - "+ New Folder" option at top of list (can create encrypted or unencrypted)
   - Select destination folder
   - Emails are greyed out, remain in list
   - Can continue browsing/staging from other folders

3. **Navigation Warning**
   - If navigating away with staged emails, show warning:
   - "You have 12 staged emails. Clear selections or stay here?"
   - Options: [Clear & Navigate] [Stay]

4. **Review Page**
   - Click "Review" button
   - Shows all staged emails grouped by source account/folder
   - Each email shows: Subject, From, Date, Destination Folder
   - Can change destination folder inline (dropdown)
   - Can unstage individual emails (uncheck)
   - Per-source-folder action dropdown: "After commit..."
     - Leave in place
     - Archive (Gmail)
     - Trash
     - Delete permanently
     - Move to folder... (Gmail labels)

5. **Commit**
   - Click "Commit" button
   - Progress indicator: "Copying 12 of 50..."
   - For each email:
     - Download as .eml
     - Encrypt with Fernet (if destination folder is encrypted)
     - Save to archive folder
     - Add metadata to database
     - Execute source action (archive/trash/etc.)
   - Error handling:
     - Continue on individual failures
     - Show summary: "47 filed successfully. 3 failed."
     - Keep failed emails staged for retry
     - "Retry Failed" button

### Archive View

When "Archive" is selected in dropdown:
- Folder tree shows archive folders (with 🔒/📁 icons)
- Email list shows archived emails in selected folder
- Actions available:
  - View email (modal or panel)
  - Download as .eml
  - Print
  - Re-file to different folder
  - Delete from archive

### Export Archive

**Export Options (from dropdown or right-click folder):**

1. **Export as ZIP (Unencrypted)**
   - Decrypts all .eml.enc files on the fly
   - Produces standard .eml files anyone can open
   - Warning: "This will create unencrypted copies of your emails"
   - Use case: Moving to another system, sharing with lawyer, etc.

2. **Export as Backup (Encrypted)** — Phase 2
   - Keeps encryption intact
   - Produces .zip with .eml.enc files + metadata
   - Can be restored to another MailRepo installation

**Scope:**
- Entire archive
- Selected folder tree
- Individual folder

### Settings View

- **Accounts:** Add/remove Gmail accounts, IMAP accounts
- **Security:** Change master password (always required, even if only unencrypted folders exist)
- **Backup:** Configure backup location, manual backup button
- **Import:** Import .mbox file (also accessible from dropdown)

### Empty States

- **First launch (no password):** Master password setup
- **After password (no archives):** "Create an Archive" page
- **No emails in folder:** "No emails in this folder"
- **No staged emails:** Review button disabled, "Stage" badge hidden

### Responsive Design

- **Desktop (>1024px):** Full two-column layout
- **Tablet (768-1024px):** Collapsible folder sidebar
- **Mobile (<768px):** 
  - Hamburger menu for folders
  - Single-column email list
  - Bottom sheet for staging actions

---

## .mbox Import Flow

1. User selects "Import .mbox..." from dropdown
2. File picker opens
3. Parse .mbox file using Python `mailbox.mbox()`
4. Show preview: "Found 1,247 emails from 'Archive.mbox'"
5. Options:
   - Import all to new folder (name it, choose encrypted/unencrypted)
   - Import all to existing folder
   - Import to staging area (then file manually)
6. Progress bar during import
7. Success: "Imported 1,247 emails to 'Old Archive'"

```python
import mailbox

mbox = mailbox.mbox('/path/to/archive.mbox')
for message in mbox:
    subject = message['subject']
    sender = message['from']
    raw_eml = message.as_bytes()  # Ready to encrypt (or not) and store
```

---

## Security Model

### Encryption

| Data | Protection |
|------|------------|
| Database | SQLCipher (AES-256) — entire DB encrypted at rest |
| Archived emails | Fernet encryption (AES-128-CBC) |
| IMAP credentials | Fernet encrypted in database |
| FTS index | Inside SQLCipher — encrypted with database |
| In transit | TLS (IMAP) |

### Master Password

- **Always required** on startup (modal before anything loads)
- Derives two separate keys via PBKDF2 (480,000 iterations):
  - Fernet key for email/credential encryption
  - SQLCipher key for database encryption
- Password never stored; only verification token

### Access Control

- Runs on localhost only (by default)
- Optional: Tailscale for remote access
- No multi-user support (solo practitioner tool)

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
| Encryption scope | Everything encrypted | SQLCipher DB + Fernet files; no unencrypted option |
| Password requirement | Always required | Needed to decrypt database |
| First-run flow | Create archive first | Forces deliberate decision before filing |
| Email protocol | IMAP only | Simpler than OAuth; works with any provider |
| Search | FTS5 in SQLCipher | Full-text search inside encrypted database |

---

## Domain Status

| Domain | Status | Notes |
|--------|--------|-------|
| mailrepo.com | ❌ TAKEN | "The Mail Repository" — private mail service |
| mailrepo.io | ❓ Check | Likely available |
| mailrepo.app | ❓ Check | Likely available |
| getmailrepo.com | ❓ Check | Alternative |

**Action:** Check Namecheap/Cloudflare for .io and .app availability before building.

---

## Development Timeline

### Phase 1: MVP (3-4 weeks)

| Week | Goals |
|------|-------|
| Week 1 | Flask app structure, Gmail OAuth, basic inbox view, folder sidebar |
| Week 2 | Staging system, folder selection modal, navigation warnings |
| Week 3 | Review page, commit workflow, encryption options, error handling |
| Week 4 | Archive view, .mbox import, ZIP export, search, settings, polish |

### Phase 2: IMAP + Polish (1-2 weeks)

| Week | Goals |
|------|-------|
| Week 5 | IMAP support, auto-suggest folders |
| Week 6 | Export options (PDF, encrypted backup), retention rules, documentation |

### Phase 3: Distribution

- GitHub release
- README with setup instructions
- Optional: Website for non-technical users

---

## Comparison: MailRepo vs Alternatives

| Feature | MailRepo | Thunderbird | MailSafe.co.uk | Enterprise |
|---------|----------|-------------|----------------|------------|
| Local storage | ✅ | ✅ | ❌ Cloud | ❌ Cloud |
| Encryption at rest | ✅ Optional | ❌ | ❓ | ✅ |
| Easy filing UI | ✅ | ❌ Clunky | ✅ | ✅ |
| Batch filing | ✅ | ❌ | ❓ | ✅ |
| Gmail support | ✅ | ✅ | ✅ | ✅ |
| IMAP support | ✅ | ✅ | ❓ | ✅ |
| Price | Free | Free | £££ | ££££ |
| Self-hosted | ✅ | N/A | ❌ | ❌ |
| Solo practitioner focus | ✅ | ❌ | ❌ | ❌ |

---

## Success Criteria

1. **Works for you** — Can archive Light in Extension correspondence
2. **Simple to use** — Filing a batch of emails takes < 2 minutes
3. **Secure** — Encrypted at rest, no cloud dependency
4. **Reliable** — Search finds what you need
5. **Portable** — Backup = copy the folder

---

## Notes

- Don't overbuild — start with Gmail only, add IMAP if needed
- Don't compete with enterprise — different market, different values
- Don't require cloud — local-first, Tailscale for remote
- Don't forget Sentinel — backup archive to home server
- Reuse EdgeCase/Synesius CSS patterns — don't reinvent the wheel

---

*"Email archiving, done right."*
