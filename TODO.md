# MailRepo - TODO

## Before Starting Any Feature

**READ FIRST, CODE SECOND:**
1. Trace the existing similar code path end-to-end before making changes
2. Verify field names and data structures actually exist - don't assume
3. Test after each change, not after batching multiple fixes

---

## High Priority

### Import/Export
- [ ] Test Apple mbox imports thoroughly; test full import workflow
- [ ] Add .pst import support
- [x] ZIP export for archived folders
- [ ] PDF export for emails
- [ ] View/download attachments in emails (server and archive)

### Core Features
- [ ] Show remote content button in emails
- [ ] Indexed search of all email content (FTS)
- [ ] Operations on archived emails: move/delete/export
- [ ] Backup system (copy from EdgeCase)
- [ ] Automatic timeout (security)
- [ ] Settings → reset database option

### Staging/Commit UX
- [x] Grey out staged folders on folder selection pages (like emails)
- [ ] Support staging emails/folders from multiple accounts simultaneously
- [x] Create subfolders in destination modal (drill-down approach)

### Error Handling
- [ ] Duplicate names: folders/emails with identical names in same archive folder
- [ ] Duplicate names: if email/folder already exists; if part of same commit
- [ ] If folder X in Trash, can't create new folder with same name

## Medium Priority

### IMAP UX
- [x] Clicking chevron on IMAP account should load emails in Inbox

### Trash View
- [ ] Sort/search in Trash
- [ ] Table in Trash is too wide
- [ ] Scrolling not right in Trash - folders don't appear, seem to persist when deleted
- [ ] Auto-empty Trash bin (configurable?)

### Archive View

## Low Priority

### Security
- [ ] Security audit

### Infrastructure
- [ ] mailrepo.ca placeholder on Sentinel

### Code Cleanup
- [ ] Remove debug logging from progress.py

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

## Completed (Session 14 - January 24, 2026)

- [x] Folder commit feature (all 8 implementation chunks)
- [x] Fix email commit data structure mismatches
- [x] Fix review view displaying email/account data
- [x] Fix EML sourcePath for commit
- [x] Fix dropdown overflow/positioning in review view
- [x] Load account names properly in review view
