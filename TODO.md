# MailRepo - TODO

## Before Starting Any Feature

**READ FIRST, CODE SECOND:**
1. Trace the existing similar code path end-to-end before making changes
2. Verify field names and data structures actually exist - don't assume
3. Test after each change, not after batching multiple fixes

---

## High Priority

### Testing
- [ ] Test full import workflow from multiple sources (multiple accounts/imports) & post-commit server actions
- [ ] Create comprehensive testing doc

### Import/Export
- [ ] Test Apple mbox imports thoroughly
- [ ] Add .pst import support
- [x] ZIP export for archived folders
- [x] Progress indicator for ZIP export
- [ ] PDF export for emails
- [ ] Export to .eml

### Archived Email Management
- [ ] Load remote content (server & archive)
- [ ] View/download attachments (server & archive)
- [ ] Move/delete (archive only) - trash, not hard delete
- [ ] Indexed search of all email content (FTS)

### Core Features (from EdgeCase)
- [ ] Automatic timeout (← EdgeCase)
- [ ] Settings → reset database (← EdgeCase)
- [ ] Backup system (← EdgeCase) - new icon & page

### Trash View
- [ ] Auto-empty Trash bin (configurable in Settings?)
- [ ] Sort/search in Trash

---

## Medium Priority

### Security
- [ ] Security audit

### Infrastructure
- [ ] mailrepo.ca placeholder page on Sentinel

### Testing
- [ ] Automated test suite (start with import parsing, encryption/decryption)

---

## Low Priority

### UI/UX
- [ ] Responsive design (?)

---

## Completed (Session 21 - January 27, 2026)

### Trash View Fixes
- [x] Empty Trash button moved to top toolbar
- [x] Table width fixed (matches Manage Archive style)
- [x] Can now create folder with same name as trashed folder
- [x] Child folders trashed independently now appear in Trash
- [x] Trash badge counts independently-trashed children
- [x] Empty Trash works for child folders
- [x] Parent chevron removed when child is trashed
- [x] Recursive descendant counts in delete/trash confirmations

### UI Polish
- [x] Tree lines in Manage Archive view
- [x] Tree lines in folder selection screens (IMAP and import)
- [x] Bottom padding added to Manage Archive and Trash views

---

## Completed (Session 20 - January 27, 2026)

### Refactoring
- [x] Complete Refactoring Plan V2:
  - Split progress.py (extracted email_parser.py)
  - Split folder-mgmt.js (extracted folder-selection.js)
  - Move escapeForOnclick to utils.js
  - Extract file-picker.js from imports.js
  - Clean up review.js (JSDoc, helpers)
  - Evaluated tree-renderer consolidation (not beneficial)

### Bug Fixes
- [x] Fix review.js unstage functions (were only updating sessionStorage, not in-memory state)

### UI Polish
- [x] Progress indicator for ZIP export

---

## Completed (Session 19 - January 27, 2026)

### Code Cleanup
- [x] Remove debug logging from progress.py (10 print statements removed)

### UI Polish
- [x] Destination modal breadcrumbs now wrap instead of horizontal scroll
- [x] Remove redundant back arrow from destination modal (breadcrumbs sufficient)
- [x] Add "Archive" root link to destination modal breadcrumbs

### Archive Folder Navigation Redesign
- [x] Replace subfolder pills with full breadcrumb trail
- [x] Breadcrumbs only show when nested (root folders have no trail)
- [x] Subfolder links shown as inline text: "Subfolders: A, B, C"
- [x] Root folders treated as distinct top-level entities (no "Archive" root)

### Bug Fixes
- [x] Fix logout triggering "Changes may not be saved" browser warning
- [x] Confirm multi-account staging already works (was on TODO but already implemented)

---

## Completed (Session 18 - January 27, 2026)

### After Commit Actions
- [x] Wire up After Commit actions (archive, trash, delete on IMAP server)
- [x] IMAP methods: get_special_folder, move_email, archive_email, trash_email, delete_email
- [x] Auto-detect Archive/Trash folder names for different IMAP servers

### UI Polish
- [x] Fix page titles: "Manage Folders" → "Manage Archives", "MailRepo" → "Browse & Stage"
- [x] Change Manage Archives h2 to show folder count instead of redundant title
- [x] Fix export folder Cancel - now properly aborts instead of continuing
- [x] Remove unnecessary confirmation modal from folder export

### Destination Folder Modal Redesign
- [x] Replace chevron tree with drill-down folder selector
- [x] Click folder to drill in, back button and breadcrumb navigation
- [x] Stage button enables when drilled into a folder
- [x] New Folder creates subfolder at current level
- [x] Breadcrumbs horizontally scrollable for deep hierarchies

---

## Completed (Session 17 - January 27, 2026)

### Review Page Redesign
- [x] Redesigned Review page with destination-first grouping
- [x] Collapsible source groups (by account/import)
- [x] Alphabetical sorting of sources and items within
- [x] Bulk unstage actions at destination and source levels
- [x] "After commit" dropdown at source level (applies to all items from that source)
- [x] "No server action" label for imports (explains missing dropdown)
- [x] X buttons match folder/email selection pages (icon-only style)

### UI/UX Improvements
- [x] Remove "Folders Staged" alert modal (consistency with email staging)
- [x] Add navigation guard for unsaved selections (warns before losing selected items)
- [x] Update rail button tooltips: Mail→"Browse & Stage", Staged→"Review Staged", Manage Folders→"Manage Archives"
- [x] Auto-load INBOX when expanding IMAP account chevron
- [x] Fix archive email list view - remove staging UI (was showing Select All/Stage buttons)

---

## Completed (Session 16 - January 26, 2026)

- [x] Grey out staged folders on folder selection pages
- [x] ZIP export for archived folders (full implementation)
- [x] Fix SQLCipher Row .get() compatibility in ZIP export
- [x] Selecting parent folder now auto-selects all children
- [x] Removed dead checkbox-based folder selection code (~115 lines)

### Folder Selection UI Redesign
- [x] Replaced checkboxes with select/clear icon buttons per folder
- [x] Added "Select All", "Clear Selected", and "Stage (N)" toolbar buttons
- [x] Fixed selection state persistence (was being cleared on refresh)
- [x] Fixed scroll position reset after staging/selecting
- [x] Fixed onclick handlers breaking with special characters in folder paths (escapeForOnclick helper)

### Email List UI Redesign
- [x] Redesigned to match folder selection pattern - table-style layout
- [x] Added same toolbar buttons (Select All, Clear Selected, Stage)
- [x] Action buttons aligned to right in Actions column
- [x] Removed search bar from toolbar

### Sidebar/Navigation Cleanup
- [x] Removed Import button from left rail
- [x] Replaced "New Folder" button in sidebar with "Import" button
- [x] Import button now last item in sidebar (after Imports section)
- [x] Welcome message restored to original (links to Settings for adding accounts)

### CSS Fixes
- [x] Fixed email list grid column alignment with increased specificity
- [x] Added inline-icon class for icons in links

---

## Completed (Session 15 - January 25, 2026)

- [x] Dropdown to Leave/Archive/Trash emails on server after commit
- [x] Progress indicator during commit (phases, per-email, periodic DB commits)
- [x] "After commit" action dropdown (restored, styled, added for folders)
- [x] Subfolder navigation pills with sidebar sync
- [x] "Unstage all" & Commit buttons persist in main view - FIXED (Mail view reset)
- [x] Select All checkbox and Search field persist - FIXED (Mail view reset)
- [x] When folder deleted, chevron still in main view - FIXED (Mail view reset)
- [x] Review parent/child folder selection when staging folders (checkboxes)
- [x] Selecting parent folder (when collapsed) should select all children

---

## Completed (Session 14 - January 24, 2026)

- [x] Folder commit feature (all 8 implementation chunks)
- [x] Fix email commit data structure mismatches
- [x] Fix review view displaying email/account data
- [x] Fix EML sourcePath for commit
- [x] Fix dropdown overflow/positioning in review view
- [x] Load account names properly in review view
