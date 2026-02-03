# MailRepo - TODO

## Before Starting Any Feature

**READ FIRST, CODE SECOND:**
1. Trace the existing similar code path end-to-end before making changes
2. Verify field names and data structures actually exist - don't assume
3. Test after each change, not after batching multiple fixes

---

## High Priority

### Testing
- [ ] Complete manual testing using docs/TESTING_CHECKLIST.md
- [ ] Test Apple Mail import hierarchy thoroughly

### Refactoring
- [x] Consolidate folder tree rendering (staging modal now uses unified component)
- [ ] Extract staging state to eliminate circular dependencies
- [ ] Migrate sidebar to unified folder-tree component (optional - different behavior)

---

## Medium Priority

### Infrastructure
- [ ] mailrepo.ca placeholder page on Sentinel

### Testing
- [ ] Automated test suite (start with import parsing, encryption/decryption)

---

## Low Priority

### UI/UX
- [ ] Responsive design (?)

---

## Completed (Session 29 - February 3, 2026)

### Security Review
- [x] CSRF protection for all state-changing API endpoints
- [x] Global fetch interceptor auto-injects token (zero refactoring)
- [x] Reviewed email rendering security (iframe sandbox, CSP — already solid)
- [x] Reviewed HTML sanitization (not needed — sandbox approach matches email clients)

---

## Completed (Session 28 - February 2, 2026)

### Folder Tree Refactor
- [x] Created unified renderFolderTree() in folder-tree.js
- [x] Updated staging.js to use unified component
- [x] Consolidated CSS into folder-tree.css
- [x] Removed duplicate styles from modals.css
- [x] Fixed CSS conflict (display: flex → display: block for containers)
- [x] ~140 lines of code removed

---

## Completed (Session 27 - February 1, 2026)

### Security Audit Fixes
- [x] Command injection fix (shlex.split)
- [x] Debug mode via env var (MAILREPO_DEBUG)
- [x] Increased minimum password to 12 characters
- [x] Login rate limiting (5 attempts, 60s lockout)
- [x] Replace debug print() with logging
- [x] Fix frontend memory leak (AbortController)

### Commit Resume Feature
- [x] pending_commit table for tracking progress
- [x] Save items to DB before commit starts
- [x] Detect interrupted commits on app load
- [x] Resume or discard prompt
- [x] Session timeout bypass for SSE streams

### Import Attachments
- [x] /api/import/attachment endpoint
- [x] Support all import types (mbox, apple-mbox, pst, eml)
- [x] Button styling fix

### Folder Fixes
- [x] Alphabetical sorting in sidebar and Manage Folders
- [x] Apple Mail hierarchy detection (Parent.mbox → Parent/)
- [x] Immediate commit during folder creation
- [x] Color dot spacer for alignment

### Destination Picker Fixes
- [x] Reset selection on modal open (no stale highlight)
- [x] Don't clear selections until confirm (allows cancel/retry)

### Testing
- [x] Created docs/TESTING_CHECKLIST.md

---

## Completed (Session 26 - February 1, 2026)

### Core Features (ported from EdgeCase)
- [x] Settings → Danger Zone → Reset Database
  - Password verification + "RESET" confirmation required
  - Deletes database, archive, backups, and salt file
  - Forces fresh password setup on next launch

---

## Completed (Session 24 - January 29, 2026)

### Stage Modal Folder Picker Redesign
- [x] Replace drilldown navigation with tree view
- [x] Click folder to select, chevron to expand/collapse
- [x] "ARCHIVE" header with + button (matches sidebar style)
- [x] New folder created inside selected folder (or root if none)
- [x] Parent auto-expands when subfolder created
- [x] Inline + button on each folder row for adding subfolders

### Import Behavior Fix
- [x] Importing a file no longer auto-switches view
- [x] Import mounts in sidebar only, user clicks to view
- [x] Eliminates navigation guard conflicts with unsaved selections

### Change Password Feature
- [x] Full password change workflow with progress indicator
- [x] Re-encrypts all archived emails with new key
- [x] Re-encrypts IMAP credentials
- [x] Rekeys SQLCipher database
- [x] Show/hide password toggles on form fields

### Settings UI Cleanup
- [x] Consistent button/select widths across sections
- [x] Password form limited to 350px width
- [x] Removed "master" from password references
- [x] Simplified Security section description
- [x] Replace all native alert/confirm with custom modals
- [x] showAlert now returns Promise (waits for OK click)

### UI Polish
- [x] "Review Staged" → "Staged Items" (button tooltip and context title)
- [x] "Destination" dropdown → "Change Destination"
- [x] Apple Mail text simplified: "Apple Mail folder export" → "Apple Mail folder"
- [x] Apple Mail hint: "For folders exported from Apple Mail with subfolders"
- [x] Apple Mail mode now shows only directories (not files)

### Folder Name Validation
- [x] Placeholder text in new folder prompts ("e.g., Client: Smith")
- [x] Reject empty names, ".", "..", and names with slashes

---

## Completed (Session 25 - January 29, 2026)

### PST Import Support
- [x] Backend endpoints for PST conversion via readpst
- [x] File picker PST mode with support check
- [x] Convert PST to mbox files, parse and mount
- [x] Preserve PST folder structure
- [x] Temp file cleanup on unmount
- [x] Fix readpst flags (-r -w instead of -r -M)

### Archive Search
- [x] Full-text search infrastructure (FTS5)
- [x] Search Archive in sidebar
- [x] Search results view with snippets
- [x] Highlight search terms in viewer

### Email Viewer Improvements
- [x] View Source button (shows raw email)
- [x] Print dialog (opens browser print)
- [x] Reorder buttons: Source, Download, Print, Load Images
- [x] Disable (not hide) Load Images button after click

---

## Completed (Earlier Sessions)

See git history and previous TODO.md versions for sessions 14-23.
