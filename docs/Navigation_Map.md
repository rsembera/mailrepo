# MailRepo — Navigation Map

**Last Updated:** January 19, 2026, 10:00 PM

---

## Project Status: MVP Complete, UI Polished

Gmail integration working. Stage → Review → Commit workflow complete. Settings page with theme/font customization done. Codebase refactored and tidy.

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

| File | Lines | Status | What It Does |
|------|-------|--------|--------------|
| `config.py` | 112 | ✅ Done | Paths, constants, Flask config |
| `database.py` | 248 | ✅ Done | SQLite connection, schema |
| `encryption.py` | 234 | ✅ Done | Fernet encryption, PBKDF2 key derivation |
| `gmail.py` | 340 | ✅ Done | OAuth flow, email fetching, archive/trash/delete |

### Web Module (`/web/`)

| File | Lines | Status | What It Does |
|------|-------|--------|--------------|
| `app.py` | 97 | ✅ Done | Flask factory, blueprint registration |
| `blueprints/auth.py` | 92 | ✅ Done | Setup, login, logout |
| `blueprints/main.py` | 98 | ✅ Done | Index, create_archive, review, settings routes |
| `blueprints/api.py` | 527 | ✅ Done | Full API: folders, accounts, Gmail, commit |

### Templates (`/web/templates/`)

| File | Lines | Status | What It Does |
|------|-------|--------|--------------|
| `base.html` | 78 | ✅ Done | Base layout, theme/font init |
| `auth/setup.html` | 65 | ✅ Done | Password setup |
| `auth/login.html` | 50 | ✅ Done | Login form |
| `main/index.html` | 217 | ✅ Done | Dashboard with folder tree, email list |
| `main/create_archive.html` | 78 | ✅ Done | First-run archive creation |
| `main/review.html` | 69 | ✅ Done | Review staged emails, commit |
| `main/settings.html` | 240 | ✅ Done | Appearance, accounts, security, import |

### Static Assets (`/web/static/`)

| File | Lines | Status | What It Does |
|------|-------|--------|--------------|
| `css/shared.css` | 558 | ✅ Done | Design tokens, buttons, forms, utilities |
| `css/themes.css` | 240 | ✅ Done | Teal, Slate, Dark themes |
| `css/main.css` | 680 | ✅ Done | App layout, email list, folder tree |
| `css/settings.css` | 434 | ✅ Done | Settings page styles |
| `css/review.css` | 263 | ✅ Done | Review page styles |
| `js/main.js` | 680 | ✅ Done | Staging workflow, folder selection |
| `js/settings.js` | 231 | ✅ Done | Theme/font switching, account management |
| `js/review.js` | 324 | ✅ Done | Review page logic, commit workflow |

### Fonts (`/web/static/fonts/`)

| Font | Files | Usage |
|------|-------|-------|
| Lexend | 4 | Default UI font (Regular, Medium, SemiBold, Bold) |
| Libre Baskerville | 3 | Serif option (Regular, Bold, Italic) |
| Source Sans 3 | 3 | Sans-serif option (Regular, Bold, Italic) |

---

## What's NOT Built Yet

- [ ] .mbox import
- [ ] ZIP export
- [ ] Search functionality (basic client-side filtering exists)
- [ ] Change master password

---

## How to Run

```bash
cd /Users/rick/apps/mailrepo
source venv/bin/activate
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

1. Python 3.13+ with venv: `source venv/bin/activate && pip install -r requirements.txt`
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
| DELETE | `/api/accounts/<id>` | Remove account |
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
