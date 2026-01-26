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
- [ ] ZIP export for archived folders (endpoint exists, returns 501)
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
- [ ] Create subfolders in destination modal (drill down, not just expand)
- [ ] Review parent/child folder selection when staging folders (checkboxes)
- [ ] Selecting parent folder (when collapsed) should select all children?

### Error Handling
- [ ] Duplicate names: folders/emails with identical names in same archive folder
- [ ] Duplicate names: if email/folder already exists; if part of same commit
- [ ] If folder X in Trash, can't create new folder with same name

## Medium Priority

### IMAP UX
- [ ] Clicking chevron on IMAP folder should load emails in Inbox

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

## Completed (Session 15 - January 25, 2026)

- [x] Dropdown to Leave/Archive/Trash emails on server after commit
- [x] Progress indicator during commit (phases, per-email, periodic DB commits)
- [x] "After commit" action dropdown (restored, styled, added for folders)
- [x] Subfolder navigation pills with sidebar sync
- [x] "Unstage all" & Commit buttons persist in main view - FIXED (Mail view reset)
- [x] Select All checkbox and Search field persist - FIXED (Mail view reset)
- [x] When folder deleted, chevron still in main view - FIXED (Mail view reset)

## Completed (Session 14 - January 24, 2026)

- [x] Folder commit feature (all 8 implementation chunks)
- [x] Fix email commit data structure mismatches
- [x] Fix review view displaying email/account data
- [x] Fix EML sourcePath for commit
- [x] Fix dropdown overflow/positioning in review view
- [x] Load account names properly in review view
