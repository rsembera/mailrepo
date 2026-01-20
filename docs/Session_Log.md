# MailRepo — Session Log

Running record of planning sessions and decisions. Most recent first.

---

## TODO Before Release

- [ ] **Consolidate database migrations** — Push all migrations into the base schema in `database.py` so fresh installs don't need to run migrations. Currently schema v2 with migration from v1.

---

## January 20, 2026 — Afternoon Session (~2:00 PM)

**Participants:** Rick, Claude

**Work Done:**

1. **Fixed IMAP folder selection bug:**
   - Folder names with spaces (e.g., "Rabbit Vets") failed with parse error
   - Root cause: IMAP SELECT command requires quoted folder names
   - Fix: Changed `self.connection.select(folder)` to `self.connection.select(f'"{folder}"')` in `core/imap.py`

2. **Added horizontal scroll to sidebar:**
   - Long folder names now scrollable instead of truncated
   - Updated `.section-content` to `overflow-x: auto`

3. **Improved account selection UX:**
   - Clicking account name now auto-selects INBOX (previously just expanded/collapsed)
   - More intuitive - one click to see your mail

**Commits:**
- `48e810e` — Fix IMAP folder quoting for names with spaces
- `64fcb0c` — Add horizontal scroll to sidebar for long folder names
- `4f0e6b6` — Auto-select INBOX when clicking account name

**Status:** All fixes complete. Ready for continued testing.

---

## January 20, 2026 — Lunch Session (~12:00 PM)

**Participants:** Rick, Claude

**Work Done:**

1. **Replaced Gmail OAuth with IMAP:**
   - Deleted `core/gmail.py`
   - Created `core/imap.py` — full IMAP client with connection, auth, folder listing, email fetching
   - Created `core/importer.py` — mbox and .eml import functionality
   - Updated `api.py` — all Gmail endpoints replaced with IMAP + import endpoints
   - Removed Google dependencies from `requirements.txt`

2. **Updated Settings Page for IMAP:**
   - IMAP credentials form instead of OAuth
   - Auto-detect server from email domain
   - Added import section for .mbox and .eml files
   - Replaced all browser `alert()` and `confirm()` with styled modals

3. **Fixed Main View for IMAP:**
   - Changed "labels" to "folders" throughout
   - Updated folder loading to use IMAP folder list
   - Fixed email ID handling (uid vs id)

4. **Added Folder Caching:**
   - Database migration v1→v2: added `cached_folders` and `cached_folders_at` columns
   - Cache folder list for 1 hour, return stale cache on connection errors
   - First load slow, subsequent loads instant

5. **Added Email Viewer:**
   - Slide-out panel when clicking on an email
   - Displays full headers, text/HTML body, attachment list
   - HTML content rendered in sandboxed iframe

**Commits:**
- `cf5fdda` — Replace Gmail OAuth with IMAP, add mbox/eml import, styled modals
- `5209eb3` — Fix IMAP folder loading in main view
- `2e2a37e` — Add folder caching, email viewer panel

**Status:** IMAP working, folder caching in place, email viewer functional. Ready for testing.

---

## January 19, 2026 — Evening Session (~9:30 PM)

**Participants:** Rick, Claude

**Work Done:**

1. **Settings Page Polish:**
   - Made About modal logo larger (240px), removed redundant "MailRepo" text
   - Tightened About modal spacing
   - All settings sections start collapsed

2. **Simplified Appearance Options:**
   - Reduced themes from 5 to 3: Teal (default), Slate, Dark
   - Removed Plum and Amber themes (too bright, not adding value)
   - Reduced fonts from 5 to 3: Lexend, Libre Baskerville, Source Sans
   - Removed Lora and Literata fonts
   - Updated font sizes to match Synesius: S=16px, M=18px, L=20px

3. **Major Refactoring — Extracted Inline CSS/JS:**
   - `settings.html`: 916 → 240 lines (extracted to `settings.css` + `settings.js`)
   - `review.html`: 654 → 69 lines (extracted to `review.css` + `review.js`)
   - Deleted 6 unused font files (Lora-*.ttf, Literata-*.ttf)
   - Removed dead theme code from `themes.css`
   - Removed dead font declarations from `shared.css`

4. **Final Codebase Stats:**
   - All templates under 250 lines (clean HTML only)
   - CSS/JS properly separated into static files
   - No dead code remaining

**Commits:**
- `61886c2` — Simplify appearance settings
- `e4d8e76` — Start with all sections collapsed  
- `964c237` — Refactor settings.html
- `2459638` — Refactor review.html

**Status:** Codebase is clean and well-organized. Ready for next phase of work.

---

## January 18, 2026 — Late Evening Session (~10:00 PM)

**Participants:** Rick, Claude

**Work Done:**

1. **Created `core/gmail.py`** — Complete Gmail API integration module:
   - OAuth flow with `InstalledAppFlow`
   - Encrypted credential storage
   - Token refresh handling
   - Email listing and fetching
   - Message operations (archive, trash, delete, move)
   - Raw RFC 2822 download for .eml export

2. **Updated `web/blueprints/api.py`** — Added working Gmail endpoints:
   - `POST /api/accounts` — Create account record
   - `POST /api/accounts/<id>/authorize` — Run OAuth flow
   - `GET /api/accounts/<id>/emails` — Fetch emails from Gmail
   - `GET /api/accounts/<id>/labels` — Get Gmail labels
   - `DELETE /api/accounts/<id>` — Remove account
   - Updated `POST /api/commit` — Downloads emails, encrypts if needed, saves to archive, executes source actions

3. **Updated `core/__init__.py`** — Export Gmail classes

4. **Created `web/templates/main/review.html`** — Full review page:
   - Displays staged emails grouped by source account
   - Inline destination folder dropdown
   - Per-account "after commit" action dropdown (leave/archive/trash/delete)
   - Progress modal during commit
   - Results modal with success/failure counts
   - Retry failed button

5. **Updated `web/blueprints/main.py`** — Added `/review` route

**Status:** The app is now functionally complete for the core workflow:
- ✅ Password setup and login
- ✅ Create encrypted/unencrypted folders
- ✅ Connect Gmail via OAuth
- ✅ Browse inbox
- ✅ Stage emails to folders
- ✅ Review staged emails
- ✅ Commit (download, encrypt, save, update Gmail)

**Still TODO:**
- Settings page UI improvements
- .mbox import
- ZIP export
- Polish and testing

---

## January 18, 2026 — Evening Session (~9:30 PM)

**Participants:** Rick, Claude

**New Decisions:**

1. **First-run flow:** After master password setup, take users to a "Create an Archive" page before anything else. Forces a deliberate decision about folder structure.

2. **Encrypted vs. unencrypted folder trees:** Users can create either encrypted or unencrypted root folders. Encryption flag is set at folder creation and inherited by all children. Use case: personal emails/newsletters don't need encryption overhead.

3. **ZIP export:** Allow users to export entire archives or selected folder trees as unencrypted ZIP files. Decrypts .eml.enc files on the fly. Essential for portability and "your data, your control" promise.

4. **Password always required:** Even if user only has unencrypted folders, master password is still required on startup. Rationale: OAuth tokens are always encrypted, so password is needed regardless.

**Code Discovery:**

Realized significant code already exists from previous sessions:
- Flask app structure complete (`main.py`, `web/app.py`)
- Core module done (`config.py`, `database.py`, `encryption.py`)
- Auth blueprint working (setup, login, logout)
- Main blueprint started (index, create_archive, settings)
- Database schema implemented (accounts, folders, messages, settings tables)
- Templates exist but need UI work

**Housekeeping:**

- Updated Navigation_Map.md to reflect actual code state
- Created Session_Log.md for context recovery

---

## Previous Sessions (Date Unknown)

**What Was Built:**

1. **Core infrastructure:**
   - `core/config.py` — Paths, constants, FlaskConfig class
   - `core/database.py` — SQLite connection, schema creation, migration support
   - `core/encryption.py` — Fernet encryption, PBKDF2 key derivation, password verification

2. **Flask app:**
   - `main.py` — Entry point, runs on port 5050
   - `web/app.py` — Factory pattern, blueprint registration, auth middleware
   - `web/blueprints/auth.py` — `/auth/setup`, `/auth/login`, `/auth/logout`
   - `web/blueprints/main.py` — `/`, `/archive/create`, `/settings`
   - `web/blueprints/api.py` — API endpoints (contents not verified)

3. **Templates:**
   - `base.html` — Base layout
   - `auth/setup.html` — Password setup
   - `auth/login.html` — Login form
   - `main/index.html` — Main dashboard
   - `main/create_archive.html` — First-run folder creation

4. **Static assets:**
   - `css/shared.css`, `css/main.css`
   - `js/main.js`
   - `fonts/` directory

---

## January 18, 2026 — Afternoon Session

**Participants:** Rick, Claude

**Topic:** UI design deep-dive

**Key Decisions:**

1. **Stage → Review → Commit workflow:** 
   - Browse emails, check boxes, click "Stage" to pick destination folder
   - Staged emails grey out but stay visible
   - Can stage from multiple accounts/folders before reviewing
   - Review page shows all staged emails grouped by source
   - Can change destinations or unstage before committing
   - Per-source-folder dropdown: what to do with originals after commit (leave, archive, trash, delete, move)

2. **Navigation warning:** If user tries to navigate away with staged emails, show warning modal with options to clear selections or stay.

3. **Folder creation mid-flow:** "+ New Folder" option in folder picker modal. Opens nested modal to name folder and choose encrypted/unencrypted. Returns to picker with new folder selected.

4. **Error handling on commit:** Continue on individual failures, show summary ("47 filed, 3 failed"), keep failed emails staged for retry.

5. **Archive view:** Accessed via "Archive" option in account dropdown. Shows folder tree and archived emails. Can view, download, print, re-file, or delete.

6. **.mbox import (not .pst):** Rick's existing archive is .mbox format. Python stdlib `mailbox.mbox()` makes this trivial—no external dependencies.

7. **Responsive design from the start:** Reuse EdgeCase/Synesius CSS patterns.

**UI Inspiration Sources:**
- EdgeCase: `/Users/rick/apps/edgecase/web/static/css/shared.css`
- Synesius: `/Users/rick/apps/synesius/web/static/css/shared.css`

---

## January 16, 2026 — Initial Planning

**Participants:** Rick

**Created:** Original project plan

**Initial scope:** Gmail-only MVP, encrypted local archive, simple filing UI, search, multi-account support.

---

## Open Questions (None Currently)

All major design decisions have been resolved. Ready to continue building.

---

## What's Next to Build

1. ~~Test IMAP workflow end-to-end~~ ✅ Working!
2. Import UI for .eml and .mbox files (backend ready in `core/importer.py`)
3. ZIP export functionality
4. Search within archive
5. Viewing archived emails (archive folder browser)

---

## Parking Lot (Future Ideas)

- **Import folder structure options:**
  - Import multiple .mbox files, mirror as folder tree
  - Parse folder hints from headers (X-Mozilla-Status, etc.) to auto-suggest structure
  - Bulk .eml import from directory with folder mirroring
- Auto-suggest folders based on sender/subject patterns
- AI categorization
- EdgeCase integration (link folders to client files)
- Full-text search across archive
- Encrypted backup export (keep .eml.enc intact)
