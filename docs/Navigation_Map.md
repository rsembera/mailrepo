# MailRepo — Navigation Map

**Last Updated:** January 18, 2026, 10:30 PM

---

## Project Status: MVP Backend Complete, UI Functional

Gmail integration is working. The full Stage → Review → Commit workflow is implemented. Main remaining work is polish and .mbox import.

---

## Key Documents

| Document | Location | Purpose |
|----------|----------|---------|
| Project Plan | `/Users/rick/apps/mailrepo/docs/MailRepo_Project_Plan.md` | Full spec, architecture, UI design |
| Navigation Map | `/Users/rick/apps/mailrepo/docs/Navigation_Map.md` | This file — context recovery |
| Session Log | `/Users/rick/apps/mailrepo/docs/Session_Log.md` | Chronological record of decisions |

---

## What's Built

### Core Module (`/core/`)

| File | Status | What It Does |
|------|--------|--------------|
| `config.py` | ✅ Done | Paths, constants, Flask config |
| `database.py` | ✅ Done | SQLite connection, schema |
| `encryption.py` | ✅ Done | Fernet encryption, PBKDF2 key derivation |
| `gmail.py` | ✅ Done | OAuth flow, email fetching, archive/trash/delete |

### Web Module (`/web/`)

| File | Status | What It Does |
|------|--------|--------------|
| `app.py` | ✅ Done | Flask factory, blueprint registration |
| `blueprints/auth.py` | ✅ Done | Setup, login, logout |
| `blueprints/main.py` | ✅ Done | Index, create_archive, review, settings routes |
| `blueprints/api.py` | ✅ Done | Full API: folders, accounts, Gmail, commit |

### Templates (`/web/templates/`)

| File | Status | What It Does |
|------|--------|--------------|
| `base.html` | ✅ Done | Base layout |
| `auth/setup.html` | ✅ Done | Password setup |
| `auth/login.html` | ✅ Done | Login form |
| `main/index.html` | ✅ Done | Dashboard with folder tree, email list |
| `main/create_archive.html` | ✅ Done | First-run archive creation |
| `main/review.html` | ✅ Done | Review staged emails, commit |

### Static Assets (`/web/static/`)

| File | Status | What It Does |
|------|--------|--------------|
| `css/shared.css` | ✅ Done | Buttons, forms, modals, cards |
| `css/main.css` | ✅ Done | App layout, email list, folder tree |
| `js/main.js` | ✅ Done | Staging workflow, folder selection |

---

## What's NOT Built Yet

- [ ] Settings page UI (template exists but is minimal)
- [ ] .mbox import
- [ ] ZIP export
- [ ] Search functionality (client-side filtering exists)

---

## How to Run

```bash
cd /Users/rick/apps/mailrepo
python main.py
# Opens at http://127.0.0.1:5050
```

### First Run Setup

1. Create master password
2. Create first archive folder (choose encrypted/unencrypted)
3. Go to Settings → Add Gmail account
4. Authorize via OAuth (opens browser)
5. Select account in dropdown → see inbox
6. Check emails → Stage → pick folder
7. Click Review → verify → Commit

### Prerequisites

1. Python 3.13+ with requirements installed: `pip install -r requirements.txt`
2. Gmail API credentials: Download `credentials.json` from Google Cloud Console, place in `~/mailrepo/config/`

---

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/folders` | List all archive folders |
| POST | `/api/folders` | Create folder |
| DELETE | `/api/folders/<id>` | Delete folder |
| GET | `/api/folders/<id>/emails` | Get archived emails |
| GET | `/api/accounts` | List accounts |
| POST | `/api/accounts` | Create account |
| POST | `/api/accounts/<id>/authorize` | Run Gmail OAuth |
| GET | `/api/accounts/<id>/emails` | Fetch emails from Gmail |
| GET | `/api/accounts/<id>/labels` | Get Gmail labels |
| POST | `/api/commit` | Commit staged emails |

---

## Database Schema

```sql
accounts (id, name, email, provider, credentials_encrypted, created_at, last_sync)
folders (id, name, parent_id, encrypted, retention_days, created_at)
messages (id, folder_id, source_account_id, message_id, subject, sender, recipients, date, filepath, encrypted, filed_at)
settings (key, value)
```

---

## If Chat Context Disappears

1. Read this file first
2. Read `Session_Log.md` for recent work
3. Run `python main.py` to see current state
4. Ask Rick what to work on next
