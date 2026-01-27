# MailRepo — Session Log

Running record of planning sessions and decisions. Most recent first.

---

## January 27, 2026 — Morning Session (Session 19)

**Participants:** Rick, Claude

**Work Done:**

### Code Cleanup
- Removed all debug print statements from `progress.py` (10 statements)

### Destination Modal Polish
- Breadcrumbs now wrap to next line instead of horizontal scrolling
- Removed redundant back arrow button (breadcrumb links handle navigation)
- Added "Archive" root link to breadcrumbs, then removed it (root folders are distinct entities)

### Archive Folder Navigation Redesign
- Full breadcrumb trail in main view (e.g., "Client A > 2024 > Q1")
- Breadcrumbs only appear when in nested folders
- Replaced awkward subfolder pills with inline text links ("Subfolders: January, February, March")
- Design decision: Root folders are distinct archives; navigate between them via sidebar, not breadcrumbs

### Verified
- Multi-account staging already works (emails from different accounts can be staged together)

**Commits:**
- `50a5f40` — UI polish: remove debug logging, breadcrumb wrapping, remove redundant back button
- `7e9764c` — Add full breadcrumb trail to archive folder navigation
- `dd4ccd9` — Replace subfolder pills with inline links, remove Archive root from breadcrumbs

**Status:** UI polish complete. Ready for comprehensive testing.

---

## January 26, 2026 — Afternoon/Evening Session (Session 16)

**Participants:** Rick, Claude

**Work Done:**

### Features Implemented

1. **Grey out staged folders** (`bda9a6d`)
   - Folders already staged now appear greyed out with disabled checkboxes in folder selection view
   - Matches existing behavior for staged emails (visual consistency)

2. **ZIP export for archive folders** (`719291b`, `fa7efcc`)
   - Full implementation of folder export feature
   - Backend endpoint decrypts `.eml.enc` files on the fly
   - Builds ZIP with folder structure preserved
   - Sanitizes filenames and handles duplicates
   - Added download icon button to each folder row in Manage Folders view
   - Fixed SQLCipher Row object `.get()` compatibility issue

### Folder Selection UI Redesign
- Replaced checkboxes with select/clear icon buttons per folder
- Added "Select All", "Clear Selected", and "Stage (N)" toolbar buttons
- Fixed selection state persistence (was being cleared on refresh)
- Fixed scroll position reset after staging/selecting
- Fixed onclick handlers breaking with special characters in folder paths (escapeForOnclick helper)

### Email List UI Redesign
- Redesigned to match folder selection pattern - table-style layout
- Added same toolbar buttons (Select All, Clear Selected, Stage)
- Action buttons aligned to right in Actions column
- Removed search bar from toolbar

### Commit Logic Review
- Confirmed full folder path preservation works correctly
- Both `staging.py` and `progress.py` use the same approach - creates full hierarchy under destination

### Sidebar/Navigation Cleanup
- Removed Import button from left rail
- Replaced "New Folder" button in sidebar with "Import" button
- Import button now last item in sidebar (after Imports section)
- Welcome message restored to original (links to Settings for adding accounts)

### CSS Fixes
- Fixed email list grid column alignment with increased specificity
- Added inline-icon class for icons in links

**Commits:**
- `bda9a6d` — Fix: Grey out already-staged folders in folder selection view
- `719291b` — Add: ZIP export for archive folders
- `fa7efcc` — Fix: SQLCipher Row object doesn't support .get() in ZIP export
- `148ac47` — Change: Selecting a parent folder now auto-selects all children
- `6a11ac4` — Remove dead checkbox-based folder selection code
- (additional commits for UI redesign work)

**Status:** ZIP export working. Folder selection now cascades to children. Dead code removed (~115 lines).

---

## TODO Before Release

- [x] ~~**Migrate to SQLCipher**~~ ✅ Done Jan 21, 2026
- [x] ~~**Implement full-text search**~~ ✅ Done Jan 21, 2026 (FTS5)
- [x] ~~**Consolidate database migrations**~~ ✅ Schema v3 is now the base
- [ ] **Unstage emails** — Click staged rail button to view/manage staged emails
- [ ] **Archive folder management** — Rename, delete, create subfolders in Settings
- [ ] **Attachments** — View/download attachments from emails
- [ ] **Archived email operations** — Move, delete, export as .eml
- [ ] **Import UI** — File picker for .eml and .mbox import (backend ready)
- [ ] **ZIP export** — Export folders as unencrypted ZIP

---

## January 21, 2026 — Afternoon Session (Continued)

**Participants:** Rick, Claude

**Work Done:**

1. **Cloned repo to Mercury (Linux dev machine):**
   - Set up development environment on Mercury ThinkPad
   - Configured git user for commits
   - All dependencies installed including SQLCipher

2. **UI/UX improvements for Add Account flow:**
   - Removed redundant "Connect Gmail Account" button from main view
   - Added `?accounts` URL parameter to auto-expand Email Accounts section
   - Replaced Google "Learn more" link with app-specific password info modal
   - Cleaned up import dropdown (removed old encrypted emoji references)

3. **Fixed button styling:**
   - Fixed `a.btn` elements getting link underline on hover
   - Changed btn-secondary text color from muted to normal for better visibility

4. **Dark mode fixes:**
   - Fixed theme switching to update both `<html>` and `<body>` elements
   - Replaced hardcoded `white` backgrounds with CSS variables in settings.css
   - Fixed theme swatch borders in dark mode
   - Decided to keep theme/font selector cards light for consistent swatch visibility

5. **New theme system - 5 themes:**
   - Renamed Teal → **Lagoon** (`#1F8F74`)
   - Renamed Slate → **Graphite** (`#475569`)
   - Renamed Dark → **Midnight** (`#1e1e2e`)
   - Added **Bloom** (`#3B6EA5`) - muted navy blue
   - Added **Rose** (`#A65568`) - dusty rose
   - Inspired by Zoom's theme naming (Bloom, Agave, Rose, Classic)

**Commits:**
- `2ce9c2a` — Improve add account UX and remove Gmail-specific references
- `01e21fc` — Fix dark mode theme switching
- `2c23258` — Fix theme/font option swatches in dark mode
- `d2dc810` — Fix theme swatch borders in dark mode
- `ce8cf27` — Remove shadow/border from theme swatches in dark mode
- `2d58cde` — Fix dark mode CSS variable specificity
- `17b225e` — Keep theme/font selectors light for consistent swatch visibility
- `4a6ccb5` — Add Bloom and Rose themes, rename existing themes

**Status:** Development environment working on Mercury. Theme system expanded with 5 professional themes.

---

## January 21, 2026 — Afternoon Session

**Participants:** Rick, Claude

**Work Done:**

1. **Migrated to SQLCipher for full database encryption:**
   - Replaced standard SQLite with SQLCipher (`sqlcipher3` package)
   - Database now fully encrypted at rest using master password
   - Added `_derive_db_key()` in encryption.py for separate DB key derivation
   - Database initialization deferred until after authentication

2. **Implemented FTS5 full-text search:**
   - Added `messages_fts` virtual table for subject, sender, body_text
   - Created triggers to keep FTS index in sync with messages table
   - Added `extract_body_text()` helper to parse email content for indexing
   - Added `/api/search` endpoint for searching archived emails

3. **Removed per-folder encryption choice:**
   - All emails now encrypted (database + files)
   - Removed `encrypted` column references throughout codebase
   - Simplified folder creation UI (no encryption radio buttons)
   - Updated `create_archive.html` with security note instead

4. **Schema updated to v3:**
   - Added `body_text` column to messages table
   - Migration path from v2 preserved for existing installs
   - Fresh installs get complete schema with FTS

5. **Updated documentation:**
   - README.md rewritten with current feature set
   - Session_Log.md updated with completed TODOs

**Files Changed:**
- `core/database.py` — SQLCipher support, FTS5 schema, v3 migration
- `core/encryption.py` — Added `_derive_db_key()` and `get_db_key()`
- `core/importer.py` — Removed encrypted parameter (always encrypt)
- `web/app.py` — Deferred DB init until after auth
- `web/blueprints/auth.py` — Init DB after login/setup
- `web/blueprints/api.py` — Removed encrypted refs, added search endpoint
- `web/blueprints/main.py` — Removed encrypted handling
- `web/templates/main/index.html` — Removed lock icons from folder list
- `web/templates/main/create_archive.html` — Replaced encryption choice with security note
- `web/static/css/shared.css` — Added security-note styling
- `requirements.txt` — Added sqlcipher3
- `README.md` — Complete rewrite

**Commits:**
- `9f136c6` — Migrate to SQLCipher for full database encryption

**Status:** Core security model complete. Database and all emails encrypted at rest. Full-text search working.

---

## January 20, 2026 — Evening Session (~9:00 PM)

**Participants:** Rick, Claude

**Work Done:**

1. **Fixed beforeunload warning:**
   - "Review & Commit" button was triggering "Are you sure you want to leave?" alert
   - Fixed by removing the listener before intentional navigation

2. **Fixed sidebar folder update:**
   - Creating folder from stage modal now updates sidebar immediately
   - Added `updateSidebarFolders()` function

3. **Redesigned Review page:**
   - Now uses three-pane layout consistent with main view
   - Shows actual account names instead of "Account 2"
   - Fixed date formatting (was showing "Invalid Date")
   - Fixed checkbox alignment
   - Replaced native select with custom icon-select dropdowns for "After commit" action

4. **Added duplicate detection:**
   - Checks Message-ID before archiving
   - Skips emails already in destination folder
   - Shows "X skipped (already archived)" in results

5. **Added archive email viewing:**
   - Click archive folder → loads archived emails
   - Click archived email → opens viewer with decrypted content
   - Added `/api/folders/<id>/emails/<id>` endpoint

6. **Fixed JSON serialization error:**
   - SQLite Row objects weren't JSON serializable for accounts data
   - Convert to dicts before passing to template

**Commits:**
- `12ada1e` — Fix: disable beforeunload warning when navigating to Review page
- `f9a64f7` — Update sidebar when creating folder from stage modal
- `43fd722` — Redesign Review page: three-pane layout, account names, fix date/alignment, custom dropdowns
- `5f84dc1` — Add duplicate detection - skip emails already in destination folder
- `0f50dbc` — Fix: convert Row objects to dicts for JSON serialization in review page
- `e0f4b48` — Add ability to view archived emails with decryption support

**Discussion — Security & Search:**
- Identified that subject/sender are stored unencrypted in SQLite — security gap
- Discussed full-text search options; FTS5 needs plaintext which conflicts with encryption
- Decision: Migrate to SQLCipher for full database encryption, then implement FTS5 inside the encrypted DB
- This maintains security promise while enabling full content search

**Status:** Core archiving workflow complete and tested. Security enhancement (SQLCipher) is next priority.

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
2. ~~Viewing archived emails~~ ✅ Working!
3. **Migrate to SQLCipher** — Full database encryption (security priority)
4. **Full-text search** — FTS5 indexing inside encrypted DB
5. **Unstage emails** — Click staged rail button to view/manage staged emails, unstage individually or clear all
6. **Archive folder management** — In Settings: rename, delete, create subfolders (parent_id already exists)
7. **Attachments** — View/download attachments from emails (server and archived)
8. **Archived email operations** — Move, delete, export as .eml, print (open in new window)
9. Import UI for .eml and .mbox files (backend ready in `core/importer.py`)
10. ZIP export for folders

---

## Terminology

- **Archive** — The root container; the entire local email archive system
- **Folder** — Top-level container within the archive (e.g., "Client: Smith", "Personal")
- **Subfolder** — Nested folder within a folder (e.g., "2024", "Litigation")
- **Stage** — Select emails to be included in the next commit (Git analogy)
- **Commit** — File staged emails to the archive permanently

---

## Parking Lot (Future Ideas)

- **Import folder structure options:**
  - Import multiple .mbox files, mirror as folder tree
  - Parse folder hints from headers (X-Mozilla-Status, etc.) to auto-suggest structure
  - Bulk .eml import from directory with folder mirroring
- Auto-suggest folders based on sender/subject patterns
- AI categorization
- EdgeCase integration (link folders to client files)
- Encrypted backup export (keep .eml.enc intact)
