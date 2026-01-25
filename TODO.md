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

### Commit UX
- [ ] **Progress indicator during commit** - Show progress bar similar to IMAP folder loading, not just "Committing..." spinner
- [ ] **Sidebar auto-refresh after commit** - Currently requires manual page refresh to see new folders/chevrons
- [ ] **"After commit" action dropdown** - LOST during review page conversion! Was in old review.js. Options: Leave in place, Move to trash, Delete permanently. Per-source-folder setting.

### Folder Selection UX
- [ ] **Grey out staged folders** - On folder selection pages, staged folders should be greyed out similar to how staged emails are greyed out
- [ ] **Create subfolder in destination modal** - Allow creating nested folders in "Select destination folder" modal, not just root-level folders

### IMAP UX
- [ ] **Chevron click loads inbox** - Clicking chevron on IMAP account in sidebar should load emails in that account's Inbox

## Medium Priority

### Error Handling
- [ ] **Duplicate folder name handling** - What happens if two folders with same name land in same archive destination? Need graceful handling (rename, merge, or error)

### Caching
- [ ] **Investigate email cache clearing** - Email cache was unexpectedly cleared during testing, forcing reload from IMAP. Determine why and fix if it's a bug.

## Low Priority / Cleanup

### Code Cleanup
- [ ] **Remove debug logging** - Remove `[COMMIT ERROR]` print statements from progress.py once commit is stable

### Future Enhancements
- [ ] Progress bars with Server-Sent Events for long-running operations (partially done for commit, need for other operations)
- [ ] Improve IMAP folder caching to reduce slow repeated calls

---

## Completed (Session 14)

- [x] Folder commit feature (all 8 implementation chunks)
- [x] Fix email commit data structure mismatches
- [x] Fix review view displaying email/account data
- [x] Fix EML sourcePath for commit
- [x] Fix dropdown overflow/positioning in review view
- [x] Load account names properly in review view
