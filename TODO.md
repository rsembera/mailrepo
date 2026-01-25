# MailRepo - TODO

## Before Starting Any Feature

**READ FIRST, CODE SECOND:**
1. Trace the existing similar code path end-to-end before making changes
2. Verify field names and data structures actually exist - don't assume
3. Test after each change, not after batching multiple fixes

Key files to check for data structures:
- `web/static/js/components/staging.js` - staged email/folder structure
- `web/static/js/views/review.js` - what review view expects
- `web/blueprints/api/progress.py` - what backend expects in commit request

---

## High Priority

### Folder Selection UX
- [ ] **Grey out staged folders** - On folder selection pages, staged folders should be greyed out similar to how staged emails are greyed out
- [ ] **Create subfolder in destination modal** - Allow creating nested folders in "Select destination folder" modal, not just root-level folders

### IMAP UX
- [ ] **Chevron click loads inbox** - Clicking chevron on IMAP account in sidebar should load emails in that account's Inbox

## Medium Priority

### Error Handling
- [ ] **Duplicate folder name handling** - What happens if two folders with same name land in same archive destination? Need graceful handling (rename, merge, or error)

### Export Feature
- [ ] **ZIP export** - Export archived folders as ZIP files (endpoint exists but returns 501 Not Implemented)

## Low Priority / Cleanup

### Code Cleanup
- [ ] **Remove debug logging** - Remove `[COMMIT ERROR]` print statements from progress.py once commit is stable

### Future Enhancements
- [ ] Progress bars for other long-running operations (folder loading, exports)
- [ ] Settings screen polish

---

## Completed (Session 15 - January 25, 2026)

- [x] **Progress indicator during commit** - Full streaming progress with Phase 1 (emails) / Phase 2 (folders), per-email subjects, and periodic DB commits for durability
- [x] **"After commit" action dropdown** - Restored with styled icon-select component, added to both email groups AND folder groups
- [x] **Subfolder navigation pills** - Compact pill bar between header and toolbar for navigating subfolders
- [x] **"Up" pill** - Navigate to parent folder from subfolder view  
- [x] **Sidebar auto-sync** - Sidebar expands/collapses to match current folder location when using pills
- [x] Sidebar auto-refresh after commit (was already working)

## Completed (Session 14 - January 24, 2026)

- [x] Folder commit feature (all 8 implementation chunks)
- [x] Fix email commit data structure mismatches
- [x] Fix review view displaying email/account data
- [x] Fix EML sourcePath for commit
- [x] Fix dropdown overflow/positioning in review view
- [x] Load account names properly in review view
