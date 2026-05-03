# MailRepo — Session Log

Running record of planning sessions and decisions. Most recent first.

---

## May 3, 2026 — Bulk Export Phase 3 (late evening)

**Participants:** Rick, Claude (Opus 4.7)

**Work Done:**

Closed out the bulk-export plan. Three pieces in sequence:

### 3a — Encryption (AES-256 ZIP via pyzipper)

Added `pyzipper>=0.3` dependency. The export modal grew an "Encrypt this export" checkbox; when checked, password + confirm fields appear with live validation (length warning at < 8 chars, match indicator). Frontend validates before submitting; backend receives the password in the start payload, uses it once for the ZIP write, doesn\'t log it.

Format-aware encryption:
- **PDF + password** → wrapper AES ZIP containing the PDF
- **eml + password** → native AES eml ZIP (no double-wrapping; single layer)
- **both + password** → single wrapper AES ZIP with PDF + flat `emails/<folder>/<file>.eml` (no nested ZIP)

Recipient notes surfaced in the modal: macOS Archive Utility doesn\'t open AES, recommend The Unarchiver; Windows 11 (23H2+) and Linux unzip 6.0+ are native.

### 3b — One-time first-use friction modal

First time the user opens the export modal in this browser, an "About exports" screen explains the encryption-boundary issue: an export creates a regular file on disk outside MailRepo\'s encrypted database. Has a "Don\'t show again" checkbox (default on) stored under `localStorage["mailrepo.exportWarningDismissed"]`. Once dismissed, the modal opens straight to the form view. Cancel aborts without consuming the dismissal so the user can re-enter and see the warning.

### 3c — Non-PDF attachments as sibling files

`pdf_export.py` already discriminated PDF attachments (pypdf-merged onto the back) from image/other attachments (previously just listed by name). Now image and other-type attachments are returned in a separate `other_attachments` list on the `complete` event. `exports.py` packages them as `attachments/email-N/<filename>` sibling files inside a wrapper ZIP, with per-email-folder filename de-duplication. Composes cleanly with encryption: encrypted exports get the same wrapper, just AES-256.

Email body attachment list now reads "(see attachments/email-N/)" when the file is actually included alongside (vs "(image attachment)" before, which was a dead-end).

Wrapper-vs-bare logic:
- No password, no non-PDF attachments → bare PDF (preserves the original Phase 1 behavior for the simple case)
- No password, has non-PDF attachments → plain ZIP wrapper
- Password → encrypted ZIP wrapper

### Files changed

- `requirements.txt` (+pyzipper)
- `core/pdf_export.py` (other_attachments tracking + return)
- `web/blueprints/api/exports.py` (encryption helpers, wrapper-ZIP logic, attachment packaging)
- `web/static/js/components/export-modal.js` (encryption section, first-use warning)
- `web/static/css/modules/export.css` (styling for both)
- `docs/Bulk_Export_Plan.md` (Phase 3 status)
- `docs/Session_Log.md` (this entry)

### Verified offline

Plain and encrypted ZIPs round-trip correctly. Wrong-password decryption raises RuntimeError as expected. Filename sanitization handles weird characters (`tricky..name//here.png` becomes a valid ZIP entry name). De-duplication kicks in correctly for repeated filenames within the same email folder. App boots, all five export endpoints register.

### Deferred (no longer in scope of the bulk-export plan)

- Custom export filename input
- TOC for >20-email exports
- Verbose headers option
- Anchor-id collision sanitization (cosmetic warnings only)

The bulk-export plan is now complete. Future export work would be its own design conversation.

---

## May 3, 2026 — Bulk Export Phase 2 (evening)

**Participants:** Rick, Claude (Opus 4.7)

**Work Done:**

Wired two new entry points into the existing bulk-export modal:

1. **Archive batch-select → Export.** The archive folder view\'s toolbar already had All / Clear / Move / Trash for batch operations on selected archived emails. Added an "Export…" button between Move and Trash. Calls `openExportModal({source: 'messages', message_ids, label})` with a label like "12 emails from Clients/Smith" so the cover page reflects the source folder.

2. **Search results → Export results.** The search view\'s toolbar gets an "Export…" button next to Clear, conditionally visible only when results are showing (not on the initial helper screen, not on the empty-results state). Calls `openExportModal({source: 'search', query, folder_id, include_subfolders, folder_name})`, which re-runs the FTS query at export time. Re-running the query on the backend rather than embedding all the message ids is intentional — it scales to large result sets and stays consistent with what the user saw.

Backend already supported both `messages` and `search` selection sources from Phase 1; this was pure frontend wiring. The form-state-preservation fix earlier this session applies to both new entry points by construction.

### Bug fixed earlier today

**Form state lost when opening destination picker.** Switching to the picker view re-rendered the modal HTML; coming back re-read `window._export`, which only got updated in `_startExport`. Result: opening the picker after picking options reset everything to defaults. Fixed with three layers: a `_captureFormState()` helper that reads form values into `window._export`, `change` listeners on every form input that call it, and an explicit call right before `_openPickerView` tears down the form\'s DOM.

### Files changed

- `web/static/js/components/email-list.js` (Export button + handler in archive toolbar)
- `web/static/js/views/mail.js` (Export results button + handler in search toolbar)
- `web/static/js/components/export-modal.js` (form-state preservation fix from earlier today)
- `docs/Bulk_Export_Plan.md` (Phase 2 status)
- `docs/Session_Log.md` (this entry)

### Deferred to Phase 3

- AES-256 encrypted ZIP via pyzipper with one-time warning modal
- Non-PDF attachment handling (images, Office docs in sibling folder)

---

## May 3, 2026 — Bulk Export Phase 1

**Participants:** Rick, Claude (Opus 4.7)

**Work Done:**

Built the bulk PDF export feature end to end, from skeleton through polish. The bulk-export design doc had this scoped as four phases; we collapsed phases 1 + 4 into a single shippable Phase 1 covering folder-source export, PDF rendering, attachments, save-to-disk, progress UI, cover page, and a remote-content toggle. Phases 2 (search/messages sources) and 3 (encryption + non-PDF attachment handling) remain.

### What's new

**Backend (`core/pdf_export.py` ~922 lines, `web/blueprints/api/exports.py` ~700 lines):**
- WeasyPrint pipeline: combined HTML document → single render → pypdf merge for PDF attachments
- Cover page with scope, email count, date range, export date
- Email sections with header table (From/To/Cc/Date/Folder) and CSS-scoped HTML body
- Appendix page listing PDF attachments before they're merged onto the back
- 5 endpoints: `/api/export/start`, `/progress/<job_id>` (SSE), `/download/<job_id>`, `/cancel/<job_id>`, `/reveal`

**Frontend (`web/static/js/components/export-modal.js` ~520 lines, `export.css` ~340 lines):**
- Modal with form view → progress view → complete view → error view
- Custom folder picker (no native dialogs); last-used directory persisted in `localStorage`
- Sort toggle (chronological / reverse)
- Include cover page checkbox
- Include subfolders checkbox (folder source)
- "Load remote images" checkbox (default off)
- Triggered from sidebar folder context menu and ⋯ button — same `openExportModal({source:'folder', folder_id, folder_name})` entry point

### The hard problems

**CSS scoping (cream-on-cover-page bleed).** Email HTML often sets a body background via inline `<body style="background: cream">` or a `<style>body { background: cream }</style>` block, sometimes wrapped in `@media only screen`. Concatenated naively into one combined document, that cream applied to the cover page and every email afterward. Fix: rewrite `<html>`/`<body>`/`<head>` tags as scoped `<div class="email-shell">` containers, preserving attributes (including inline styles), and rewrite selectors in `<style>` blocks to be prefixed with `.email-scope-eN`. Recursive descent into `@media`/`@supports`/`@layer`/`@container`/`@scope` so nested selectors get scoped too. Verified with three real email styles plus the user's actual `.eml` files.

**WeasyPrint table-layout quirks (centering).** Two HTML attributes WeasyPrint doesn't honor like browsers do:
- `<table width="100%">` renders content-width, not container-width. Fix: `table[width="100%"] { width: 100% !important }` in base CSS.
- `<td align="center">` doesn't center block-level descendants (nested tables). Fix: `td[align="center"] > table { margin: 0 auto !important }`.

Both took several test iterations to isolate (variants A/B/C/D in `/tmp/center_*.pdf`) before landing on the right rules. Both are now in `_BASE_CSS`, scoped to `.email-body-html` so they don't affect the cover page or appendix tables.

**80% stall.** WeasyPrint's `write_pdf()` is synchronous with no progress callback, so the progress bar sat at 80% for 10–15s during a 200-email render and looked frozen. Fix: when the WeasyPrint phase starts, send `{"indeterminate": true}`; the JS modal flips the bar to a pulsing-opacity animation and changes the status to "Composing PDF (N emails)… this can take a moment." Bar resumes determinate mode at 85% once render completes.

**Log noise from blocked images.** With remote loading off, WeasyPrint logs an ERROR for every blocked `<img src="https://...">` — hundreds of lines per export. Fix: temporarily raise the `weasyprint` logger to CRITICAL during the blocked render and restore it afterward. Real WeasyPrint failures still surface via the surrounding try/except.

### Files changed

- `core/pdf_export.py` (new)
- `web/blueprints/api/exports.py` (new)
- `web/blueprints/api/__init__.py` (registered `exports` blueprint)
- `web/static/js/components/export-modal.js` (new)
- `web/static/css/modules/export.css` (new)
- `web/static/css/main.css` (registered `export.css`)
- `web/static/js/components/context-menu.js` (folder menu calls `openExportModal`, label "Export…")
- `requirements.txt` (added `weasyprint>=60.0`, `pypdf>=4.0`)
- `docs/Bulk_Export_Plan.md` (Phase 1 status section appended)
- `docs/TESTING_CHECKLIST.md` (added export tests)

### Deferred

- Custom export filename (auto-generated names sufficient for now)
- TOC for >20-email exports
- Verbose headers option (full raw headers)
- Anchor-id collision sanitization (cosmetic warnings only)
- Phase 2: batch-select toolbar and search-results toolbar wiring
- Phase 3: AES-256 encrypted ZIP via pyzipper with one-time warning

---

## May 1, 2026 — Evening Session

**Participants:** Rick, Claude (Opus 4.7)

**Work Done:**

### Folder actions ⋯ button (sidebar discoverability)

Folder management has always been right-click only on the sidebar tree, which is poorly discoverable — users don't know the menu exists, and right-click on trackpads is awkward (control-click, two-finger tap, varies by system). Added a persistent affordance: a `⋯` button that appears on row hover (always visible on touch) and opens the same context menu, anchored below the button.

**Decision on drag-to-rearrange:** discussed but deferred. Users already control folder order via numeric prefix convention (`01`, `02`, …); adding drag would introduce a competing ordering mechanism plus significant complexity (drop target ambiguity, auto-expand timing, touch gestures, accessibility, schema changes). If reordering becomes a real need, "Move up / Move down" menu items would be the simpler next step.

**Changes:**

1. **`context-menu.js`** — Factored menu-build logic into private `_showFolderMenu(folderId, folder)`. Existing `showFolderContextMenu(e, …)` retains cursor-position behavior for right-click. New `showFolderContextMenuAtElement(e, anchorEl, folderId, folder)` opens the same menu anchored just below the button's left edge; viewport edge detection still applies.

2. **`sidebar.js`** — `createFolderTreeItem` now appends a `<button class="folder-actions-btn">` (Lucide `more-horizontal`) inside the row. Click handler stops propagation and calls `showFolderContextMenuAtElement` — propagation must be stopped or (a) the row's click handler navigates into the folder and (b) the document-level "click outside" listener immediately closes the menu.

3. **`sidebar.css`** — Button is `position: absolute` at the right edge of the row (not in flex flow), `opacity: 0` by default, fades to `opacity: 1` on `.tree-item-row:hover` or `:focus-visible`. `@media (hover: none)` makes it always visible on touch devices.

### Bug fixed: horizontal scrollbar in sidebar

First-pass implementation put the `⋯` button in the row's flex flow with `margin-left`, which widened every row by ~30px. Combined with `.tree-label { white-space: nowrap }` and `.section-content.expanded { overflow-x: auto }`, long folder names spilled past the container and triggered a horizontal scrollbar on the whole archive section.

Fix:
- `.folder-item > .tree-item-row` now uses `position: relative` with 32px right padding to reserve space for the button.
- `.folder-actions-btn` is `position: absolute` at `right: 6px`, vertically centered — out of the flex flow entirely, so it contributes no width.
- `.tree-label` got `overflow: hidden; text-overflow: ellipsis; min-width: 0` — long names truncate with `…` instead of pushing the row wider. This was actually a latent issue; the dots button only made it visible.

### Files Changed

- `web/static/js/components/context-menu.js` — Refactored to share menu-build logic; new `showFolderContextMenuAtElement` for anchored opening.
- `web/static/js/components/sidebar.js` — Added `⋯` button to folder rows; wired click with stopPropagation.
- `web/static/css/modules/sidebar.css` — Absolute-positioned button, label ellipsis, touch-device handling.
- `docs/TESTING_CHECKLIST.md` — 7 new test cases for the ⋯ affordance.

---

## April 30, 2026 — Evening Session

**Participants:** Rick, Claude (Opus 4.7)

**Work Done:**

### Search scope picker overhaul

The previous session added a folder-scope dropdown to the archive search, but used a native `<select>` that dumped every folder into a flat list with no way to navigate the tree. Replaced it with a proper folder picker.

**Changes:**

1. **Scope button instead of `<select>`** — Toolbar now has `[input] [Scope: All folders ▾] [Search] [Clear]`. The scope button shows the current scope label and tints when a specific folder is selected.

2. **Folder picker modal** — Clicking the scope button opens a modal with:
   - Filter input at the top (narrows the tree, auto-expands ancestors of matches)
   - "All folders" row to reset scope
   - "Include subfolders" checkbox (defaults on)
   - Recursive folder tree with expand/collapse, reusing the existing `renderFolderTree` component

3. **Include subfolders toggle** — Backend already searched folder + descendants when `folder_id` was passed. Added `include_subfolders` query param (defaults `true`); when `false`, only the chosen folder is searched. Frontend sends the param and reflects state in the scope label as `Folder/Path (only)`.

4. **Scope-aware helper text** — Initial search-view sentence now reads:
   - "…across your entire archive." (no scope)
   - "…in **Folder** and its subfolders." (folder + subs)
   - "…in **Folder** only." (folder only)
   
   Re-renders on scope change (when no results are showing) so the sentence stays accurate.

5. **Fixed Enter-to-search after first search** — The inline `onkeydown` attribute combined with `innerHTML` re-emission was leaving the input without focus after results rendered. Replaced with a real `addEventListener('keydown')` and added focus + caret-position preservation across re-renders so subsequent searches work without clicking back into the field.

### Bugs Fixed

- **Empty folder tree in picker** — Passing `filter: undefined` into `renderFolderTree` clobbered the component's default filter via object spread, leading to `state.folders.filter(undefined)` and an empty `rootFolders` array. Fixed by only setting `treeOptions.filter` when a filter function actually exists.

- **Stale "across your entire archive" copy** — Helper text claimed whole-archive scope even when a specific folder was selected. Now scope-aware.

### Files Changed

- `web/static/js/views/mail.js` — Scope button, picker modal, tree rendering, filter, subfolder toggle, scope-aware helper, focus preservation, Enter handler. Removed `buildFolderOptions`.
- `web/static/css/modules/content.css` — Scope button styles, picker modal styles, subfolder checkbox row styles. Removed `.search-folder-select`.
- `web/blueprints/api/emails.py` — Added `include_subfolders` query param to `/api/search`.
- `docs/TESTING_CHECKLIST.md` — New test cases for picker, subfolder toggle, scope-aware helper, multi-search Enter.

---

## February 4, 2026 — Afternoon Session (Session 31)

**Participants:** Rick, Claude (Opus 4.5)

**Work Done:**

### Manual Testing Begins (TESTING_CHECKLIST.md)

Nuked database and archive for fresh start. Began working through the testing checklist from the top.

**Sections tested:**
- First Run / Setup — ✅ all pass
- Accounts (IMAP) — ✅ added two accounts (NCF Mail, Personal Gmail), both connected

### Bug Fixes

1. **Modal z-index stacking** — Error modal appeared behind Add Account modal (both at z-index 1000). Fixed by setting alert/confirm/prompt modals to z-index 1100 in modals.css.

2. **CSS syntax error (critical)** — First z-index fix accidentally broke `.modal-overlay` base rule, removing `opacity: 0; visibility: hidden; transition`. All modals became visible on page load. Root cause: stray CSS line broke the parser, preventing `.modal-overlay.active` from ever taking effect. Fixed by restoring the complete rule.

3. **Dynamic sidebar account refresh** — Adding a second account in Settings didn't update the sidebar (server-rendered at page load, never refreshed). Added `refreshSidebarAccounts()` to sidebar.js that fetches from `GET /api/accounts` and rebuilds the accounts section. Wired up the existing `accountsChanged` custom event (already dispatched by settings.js, but nobody was listening).

### UX Improvements

- **Advanced settings collapse on modal open** — IMAP server settings `<details>` now collapses each time Add Account modal opens, instead of staying expanded from previous use.
- **Default font size changed to Small** — Updated both base.html and settings.js defaults from Medium to Small.
- **IMAP folder indentation** — Top-level IMAP folders now indent 12px under their account name in the sidebar, making the hierarchy clearer.

### Files Changed

- `web/static/css/modules/modals.css` — z-index stacking fix, CSS syntax repair
- `web/static/js/views/settings.js` — Collapse advanced settings, default font size
- `web/templates/base.html` — Default font size
- `web/static/js/components/sidebar.js` — `refreshSidebarAccounts()`, IMAP folder indent
- `web/static/js/app.js` — Import and wire up `accountsChanged` listener

**Status:** Testing in progress. First Run and Accounts sections complete. Next: Authentication, Email Browsing, Imports.

---

## February 4, 2026 — Morning Session (Session 30)

**Participants:** Rick, Claude (Opus 4.5)

**Work Done:**

### Pre-Release Security Audit

Comprehensive review of all security-critical code paths. Full results in `docs/Security_Audit.md`.

**Areas reviewed:**
- Encryption implementation (PBKDF2, Fernet, SQLCipher)
- Authentication flow (rate limiting, session timeout, CSRF)
- Database security (parameterized queries, WAL, foreign keys)
- API endpoint protection (auth enforcement, CSRF validation)
- IMAP credential handling (encrypted storage, SSL/TLS)
- File system operations (path traversal protection, size limits)
- Email archive security (encryption at rest, on-access decryption)
- Settings/reset safeguards (password + "RESET" confirmation)
- Backup/restore (WAL checkpoint, path validation)
- Configuration (secret key generation, file permissions)
- Frontend XSS protection (escapeHtml, sandboxed iframes, JSON API)

**Result:** No critical issues found. Minor observations documented (SESSION_COOKIE_SECURE=False for localhost, in-memory rate limiting, duplicate logger import). All acceptable for target deployment.

**Decision — Circular dependency:** staging.js ↔ folder-selection.js circular import acknowledged but not refactored. Works correctly, causes no bugs. Refactoring at ship stage would introduce risk without meaningful benefit.

### Documentation Update

- Created `docs/Security_Audit.md` — full audit results
- Rewrote `docs/Navigation_Map.md` — was badly out of date (Mac paths, Gmail OAuth references, old file structure). Now reflects actual codebase: ~20,100 lines of code across 76 source files (per cloc).
- Updated `docs/Session_Log.md` — this entry

**Status:** Ready for manual testing per TESTING_CHECKLIST.md.

---

## February 3, 2026 — Afternoon Session (Session 29)

**Participants:** Rick, Claude

**Work Done:**

### Security Review

1. **CSRF protection for API endpoints** (`461bf6b`)
   - Added CSRF token generation at login, stored in Flask session
   - Token embedded in `<meta name="csrf-token">` tag on every page
   - Extended existing fetch interceptor in base.html to auto-inject `X-CSRF-Token` header on all POST/PUT/DELETE/PATCH requests
   - Server validates token on all state-changing `/api/*` requests, returns 403 if missing or invalid
   - Uses `secrets.compare_digest` for timing-safe comparison
   - Zero changes to existing fetch calls (47 call sites covered automatically)

2. **Security review findings:**
   - **Email rendering (no action needed):** HTML emails rendered in sandboxed iframe with `allow-same-origin allow-modals` (no `allow-scripts`). CSP blocks remote content by default. "Load Remote Content" button allows images when user explicitly requests. This matches standard email client behavior.
   - **HTML sanitization (not added):** Considered server-side sanitization (bleach/nh3) but decided against it. The iframe sandbox already prevents JS execution, and sanitization could break legitimate email rendering. Desktop email clients (Thunderbird, Apple Mail) use the same sandbox approach.
   - **Flask secret key:** Already persisted to disk with 0o600 permissions ✓
   - **Session timeout:** Already implemented with configurable duration ✓
   - **Localhost binding:** Already bound to 127.0.0.1 only ✓

**Files Changed:**
- `web/app.py` — CSRF token generation and validation
- `web/templates/base.html` — Meta tag + fetch interceptor extension

**Commits:**
- `461bf6b` — Add CSRF protection for all state-changing API requests

---

## January 30, 2026 — Evening Session (Session 25)

**Participants:** Rick, Claude

**Work Done:**

### Bug Fixes

1. **Backup directory portability fix** (`e8105a3`)
   - Backups weren't being found after moving app from `/Users/rick/apps/mailrepo` to `/Users/rick/Applications/mailrepo`
   - Root cause: manifest.json stored absolute `backup_dir` path at backup creation time
   - Fix: Always use current `get_backups_dir()` instead of stored path from manifest
   - Affected functions: `list_backups()`, `get_restore_points()`, `cleanup_old_backups()`

2. **Double scrollbar on Backups page** (`afbe57c`, `770dfbb`)
   - Backups view was showing two scrollbars
   - Fix: Added CSS `:has()` rule to disable parent scroll when showing backups view

3. **Sidebar folder tree broken** (`770dfbb`)
   - Archive folders rendering with huge spacing, children appearing inline instead of below
   - Root cause: `backups-view.css` had global `.folder-item` rule with `display: flex`
   - Fix: Scoped all folder-item rules to `.folder-picker-container .folder-item`

### Logging Improvements

1. **Suppress polling log messages** (`afbe57c`, `8edf172`)
   - Added `PollingFilter` class to filter out noisy werkzeug logs
   - Suppresses: `/api/session-status`, `/api/keepalive`, heartbeat `HEAD /` requests
   - Also suppresses static file 304 responses

2. **Backup on shutdown with logging** (`1caa02d`)
   - Added shutdown handlers (SIGINT, SIGTERM) like EdgeCase
   - Checkpoints WAL before backup
   - Checks backup frequency setting to determine if backup needed
   - Prints "Backup completed: {filename}" to terminal
   - Runs post-backup command if configured

**Commits:**
- `e8105a3` — Fix: Always use current backups directory, not stored path from manifest
- `afbe57c` — Fix: Double scrollbar on Backups page, suppress polling log messages
- `1caa02d` — Add backup on shutdown with logging (like EdgeCase)
- `8edf172` — Suppress static file 304 responses and all polling status codes from logs
- `770dfbb` — Fix: Scope folder-item styles to backup picker only

**Status:** All backup and logging issues resolved. App is now portable (can be moved to different directory).

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

### IMAP Folder Navigation
- Added breadcrumbs + subfolder links to IMAP folder browsing (consistency with archive view)
- Fixed title to show folder name only, not full path (e.g., "Comfort King" not "Home/Comfort King")
- Fixed duplicate subfolder bug (was showing each folder twice)
- Fixed IMAP cache lookup bug (string/number accountId mismatch in Map key)

### Bug Fixes
- Fixed logout triggering browser's "Changes may not be saved" warning (added skip flag for intentional navigation)

### Verified
- Multi-account staging already works (emails from different accounts can be staged together)

### Code Review & Refactoring Plan
- Full codebase scan: ~12,000 lines total across Python + JavaScript
- Created `docs/Refactoring_Plan_V2.md` with prioritized improvements
- Key targets: split `progress.py` (1,202 lines), split `folder-mgmt.js` (1,200 lines), consolidate shared utilities
- Estimated 8-12 hours total work, non-blocking for release
- Discussion: MailRepo's "curated archive" model is the right scope; don't try to compete with corporate archiving software

**Commits:**
- `50a5f40` — UI polish: remove debug logging, breadcrumb wrapping, remove redundant back button
- `7e9764c` — Add full breadcrumb trail to archive folder navigation
- `dd4ccd9` — Replace subfolder pills with inline links, remove Archive root from breadcrumbs
- `3cdfb96` — Fix: Skip beforeunload warning on logout
- `35aabf6` — Update docs for Session 19
- `72c401d` — Add IMAP folder breadcrumbs and subfolder navigation (matches archive view)
- `6f1e7c0` — Fix: Remove duplicate subfolder detection in IMAP navigation
- `0b0ab2b` — Fix: IMAP navigation cache lookup with string/number accountId

**Status:** Navigation consistency complete. Refactoring plan documented. Ready for next session.

**Next Session:** Review refactoring plan (docs/Refactoring_Plan_V2.md) or continue with feature work.

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

---

## Session 31 — February 5, 2026

**Focus:** Code quality cleanup and IMAP bug fixes

### Code Quality (-122 lines net)
- Deduplicated `decode_header_value` — 3 inline copies in filesystem.py removed, all use `decode_email_header` from email_parser.py
- Extracted `_save_email_to_archive()` and `_check_duplicate()` in commit.py — shared across all 4 commit functions (IMAP email, import email, IMAP folder, import folder)
- Removed double fetch in `commit_imap_folder()` — was calling both `fetch_full()` and `fetch_raw()`, now uses only `fetch_raw()` + `parse_email_metadata()`
- Fixed N+1 query pattern in `search_emails()` — builds folder path map from single query instead of per-result parent chain walking
- Fixed colon-in-folder-name edge case in `_find_action_for_source()`
- Added explanatory comment for in-memory rate limiting design choice in auth.py

### IMAP Bug Fixes
- **\Noselect folder support** — Parse `\Noselect` flag from IMAP LIST response. Virtual containers like `[Gmail]` now expand children instead of throwing "Failed to select folder" error. Handled in sidebar and folder-selection views (dimmed appearance, no action buttons).
- **Ghost deleted emails** — Changed default IMAP search from `ALL` to `NOT DELETED` to filter messages flagged for deletion but not yet expunged. (Gmail ghost email turned out to be a server-side sync issue unrelated to this flag.)
- **Folder cache invalidation** — Cache auto-invalidates when cached data is missing the new `noselect` field, ensuring one-time migration.

### Deferred
- filesystem.py os.path → pathlib conversion (cosmetic, low risk-reward)
- filesystem.py module split (741 lines, manageable as-is)
- Database class-level state refactor (testability only, no functional impact)

### Commits
- `2af76f6` — Code quality cleanup: DRY violations, N+1 queries, edge cases
- `622ae83` — Handle IMAP \Noselect folders (e.g. [Gmail] container)
- `f37923b` — Filter out deleted ghost messages from IMAP search results
- `b5bd662` — Invalidate folder cache when missing noselect field


---

## Session 31 (continued) — February 5, 2026

**Focus:** Database reset bug fixes (MacBook Air M4)

### Database Reset Fixes
- **Missing .secret_key cleanup** — `reset_database()` now deletes Flask session key file in addition to salt, database, archives, and backups
- **Segfault on reset** — Removed `Encryption.lock()` call from reset handler; clearing SQLCipher's in-memory key during response processing caused segfault in the C extension. Keys are naturally replaced on next password setup.
- **Stale data diagnosis** — "file is not a database" error was caused by new `.salt` (from aborted first-run) paired with old `mailrepo.db` (encrypted with different salt). Fix: delete mismatched database file.

### Commits
- `5d37375` — Fix database reset: delete .secret_key and lock encryption
- `bb20719` — Fix segfault on database reset: don't lock encryption mid-request


---

## Session 32 — February 6, 2026

**Focus:** UI fix, cross-project security audit

### UI Fix
- Progress bar count text ("61 of 62") was clipped top/bottom when displayed inline beside the bar. Moved count to its own line below the bar. Single source: progress.js component handles all progress bars with counts.

### Cross-Project Security Audit
Checked MailRepo against 5 bugs found in Synesius:
1. ✅ `verify_password` — Uses Fernet-encrypted verification token, not just SQLCipher open test
2. ✅ `change_password` — Full rekey: re-encrypts .eml.enc files, IMAP credentials, PRAGMA rekey, updates verification token
3. ⚠️ **Session race condition — FIXED.** Login didn't set `last_activity` or clear stale session. Safari/Firefox could redirect back to login after successful auth.
4. ✅ Hardcoded secret key — Auto-generates to `.secret_key` with 0o600 permissions
5. ✅ Copy-paste artifacts — Clean

### Session Race Condition Fix
- `session.clear()` before setting new session values on login
- Set `last_activity` and CSRF token during login (not just in before_request)
- `make_response()` for explicit cookie handling on redirect
- `SESSION_COOKIE_NAME = 'mailrepo_session'` to prevent localhost collision
- Applied to both login and first-run setup flows

### Commits
- `fa2687a` — Fix clipped text in progress bar count
- `20ae895` — Fix session race condition on login (Safari/Firefox double-login bug)


---

## Session 34 — February 8, 2026 (Mercury)

### Testing: Search, Batch Ops, Trash, Backup/Restore

**Search fixes:**
- Body text not indexed for HTML-only emails — refactored extract_body_text to prefer HTML-derived text
- Added /api/search/reindex endpoint to rebuild FTS for existing emails
- All search tests pass

**Sort options added:**
- Icon button dropdown for email lists (date, sender, subject)
- Applied to archive folders, IMAP folders, and Trash views
- Replaced native select in Trash with consistent icon dropdown

**Bugs fixed:**
- Trash folders empty state showing "No folders match ''" with no search query
- Custom select dropdown going off-screen — auto-flip based on viewport space
- Restore modal not appearing (toggling `hidden` class instead of `active`)
- `complete_restore()` never called on startup — wired into main.py
- Cancel Restore triggering unsaved settings warning
- Restore modal button alignment (wrong CSS class)
- Shortened "Select All" to "All" for toolbar space

### Commits
- `bb85ac7` — Fix search not finding email body text (HTML preference, reindex endpoint)
- `9035e95` — Add sort options to email list (date, sender, subject)
- `71d4e67` — Shorten Select All button label to All
- `b863783` — Replace native sort select with icon dropdown in Trash view
- `47e950f` — Fix Trash folders empty state showing search message with no query
- `742ee86` — Auto-flip custom select dropdown when near screen edge
- `754d6c8` — Fix restore modal not appearing (wrong class toggle)
- `4d58e41` — Wire up restore execution on server startup
- `683e0bd` — Fix cancel restore triggering unsaved settings warning
- `3300a4c` — Fix restore modal button alignment (modal-buttons -> modal-actions)



---

## Session 35 — February 11, 2026 (Mercury)

### Feature: Retention Vault

Implemented folder-level retention system for compliance workflows. Folders can be moved to a "vault" with a future deletion date, then permanently deleted after review when overdue.

**Database:**
- Added `retention_date` column to folders table (Unix timestamp, NULL = normal archive)
- Added index `idx_folders_retention` for vault queries

**Backend API (6 endpoints):**
- `GET /api/folders/vault` — List vault folders with email counts and overdue status
- `GET /api/folders/vault/overdue-count` — Badge count for left rail
- `POST /api/folders/{id}/vault` — Move folder tree to vault with retention date
- `POST /api/folders/{id}/vault/restore` — Restore folder tree from vault
- `DELETE /api/folders/{id}/permadelete` — Permanently delete overdue folder
- `POST /api/folders/batch-permadelete` — Batch delete overdue folders

**Frontend:**
- Date picker component (ported from EdgeCase) with year/month/day grid navigation
- "Move to Vault" modal with date picker and preset buttons (1/3/5/7/10 years)
- Vault view with grid layout matching Trash view styling
- Restore modal with folder destination picker
- Overdue alert banner (mail view only)
- Vault badge in left rail showing overdue count

**UI Polish:**
- Vault icon positioned before Trash in left rail (logical flow: archive → vault → trash)
- Alert banner only shows on mail view, not Settings/Trash/etc.
- Modal width increased to prevent calendar clipping

### Commits
- `8c7f2dc` — Add Retention Vault feature (database, API, frontend, UI)
- `0a92a23` — Align Vault view styling with Trash view
- `38f96a7` — Fix duplicate overdueCount declaration in vault.js
- `91fd117` — Move Vault icon before Trash in left rail
