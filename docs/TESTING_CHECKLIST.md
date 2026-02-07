# MailRepo Testing Checklist

Pre-release manual testing checklist. Run through before any public release.

---

## First Run / Setup

- [x] Fresh start (delete `data/` folder) shows password setup screen
- [x] Password under 12 characters is rejected
- [x] Password mismatch is rejected
- [x] Valid password creates database and shows "Create Archive" prompt
- [x] Can create first archive folder (encrypted)

---

## Authentication

- [x] Closing browser and reopening requires login
- [x] Wrong password shows error
- [x] 5 wrong passwords triggers rate limiting (60 second lockout)
- [x] Correct password after lockout expires works
- [x] Logout button works, returns to login screen
- [x] Password change works (Settings → Security)
- [x] Old password rejected after change
- [x] New password works after change

---

## Accounts (IMAP)

- [x] Add Gmail account (OAuth or app password)
- [x] Add non-Gmail IMAP account (Fastmail, iCloud, etc.)
- [x] Auto-detect server settings works for common providers
- [x] Manual server entry works
- [x] Account appears in sidebar after adding
- [x] Can remove account
- [x] Credentials persist after restart

---

## Email Browsing (IMAP)

- [x] Selecting account loads folder list
- [x] Selecting folder loads email list
- [x] Email list shows sender, subject, date
- [x] Clicking email shows full content in viewer
- [x] HTML emails render correctly
- [x] Plain text emails display correctly
- [x] Attachments are listed
- [x] Can download attachments
- [ ] Pagination works for large folders (if implemented)

---

## Imports

### mbox
- [x] Can browse to and select .mbox file
- [x] Import mounts and shows in sidebar
- [x] Emails are browsable
- [x] Can view individual emails
- [x] Unmount removes from sidebar

### Apple Mail Export (.mbox directory)
- [x] Can select .mbox directory
- [x] Nested folders appear correctly
- [x] Emails load from both `mbox` file and `Messages/*.emlx` formats
- [x] Unmount works

### PST (if libpst installed)
- [x] PST support check shows correct status
- [x] Can select and convert .pst file
- [x] Converted folders appear
- [x] Emails are viewable
- [x] Temp files cleaned up on unmount
- [x] Password-protected .pst file imports without issue (password is UI-level only, not encryption)

### EML Directory
- [x] Can select directory of .eml files
- [x] Individual emails load correctly

---

## Archive Folders

- [x] Can create new folder at root level
- [x] Can create nested subfolder
- [x] Can rename folder
- [x] Can move folder (drag or menu)
- [x] Can delete folder (moves to Trash)
- [ ] Folder with emails can be deleted
- [ ] Folder with subfolders can be deleted

---

## Staging & Commit

### Staging Emails
- [ ] Can select individual emails (checkbox)
- [ ] Can select all emails in folder
- [ ] "Stage" button opens destination picker
- [ ] Can select destination folder
- [ ] Can create new folder from picker
- [ ] Staged badge shows count
- [ ] Staged emails appear grayed out

### Staging Folders (Import)
- [ ] Can stage entire folder from import
- [ ] Subfolder staging options work (with/without children)
- [ ] Folder appears in Review with email count

### Review
- [ ] Review button shows all staged items
- [ ] Items grouped by destination
- [ ] Can change destination for group
- [ ] Can unstage individual items
- [ ] Can unstage entire destination group
- [ ] Source action dropdown works (Leave/Archive/Trash/Delete)
- [ ] "Unstage All" clears everything

### Commit
- [ ] Commit button starts process
- [ ] Progress modal shows status
- [ ] Emails are copied to archive
- [ ] Source actions execute (if not "Leave")
- [ ] Success message shows count
- [ ] Archived emails appear in destination folder
- [ ] Staged items cleared after commit

---

## Archived Email Operations

- [ ] Can view archived email
- [ ] Can download archived email as .eml
- [ ] Can export folder as ZIP (decrypted .eml files)
- [ ] Can print archived email
- [ ] Can move email to different archive folder
- [ ] Can delete email (moves to Trash)
- [ ] Batch select works
- [ ] Batch move works
- [ ] Batch delete works

---

## Search

- [ ] Search box appears in archive view
- [ ] Search finds emails by subject
- [ ] Search finds emails by sender
- [ ] Search finds emails by body text
- [ ] Search results are clickable
- [ ] Clear search returns to folder view

---

## Trash

- [ ] Deleted folders appear in Trash
- [ ] Deleted emails appear in Trash (if viewing deleted folder)
- [ ] Can restore folder from Trash
- [ ] Can permanently delete from Trash
- [ ] "Empty Trash" works
- [ ] Trash auto-purge after 30 days (check on restart)

---

## Backup & Restore

### Backup
- [ ] Backup Now creates backup
- [ ] Backup appears in restore points list
- [ ] Full vs incremental decided automatically
- [ ] Backup location setting works
- [ ] Cloud folder detection works (iCloud, Dropbox, etc.)
- [ ] Post-backup command executes (if configured)
- [ ] Automatic backup on logout (based on frequency setting)
- [ ] Backup on shutdown works

### Restore
- [ ] Can select restore point
- [ ] Restore confirmation shows details
- [ ] Pre-restore safety backup created
- [ ] Restore completes successfully
- [ ] Data matches backup state
- [ ] Can cancel pending restore

### Retention
- [ ] Retention setting can be changed
- [ ] Old backups cleaned up according to policy

---

## Settings

- [ ] Theme switching works
- [ ] Font settings work
- [ ] Backup settings persist
- [ ] All settings survive restart

---

## Edge Cases & Error Handling

- [ ] Large email (10MB+) handles correctly
- [ ] Email with many attachments works
- [ ] Malformed email doesn't crash viewer
- [ ] Network disconnect during IMAP fetch shows error gracefully
- [ ] Corrupt mbox file shows error, doesn't crash
- [ ] Database lock doesn't cause data loss
- [ ] Ctrl+C shutdown completes backup and checkpoint

---

## Browser Compatibility

- [ ] Chrome/Chromium works
- [ ] Firefox works
- [ ] Safari works (if on Mac)

---

## Notes

Test date: February 6, 2026

Tested by: Richard Sembera

Version: 0.1.0

Tested on: MacBook Air M4 (macOS), Safari/Chrome

Issues found:
- Rate limit lockout had no countdown timer (fixed: a65acc4)
- Progress bar count text clipped (fixed: fa2687a)

Next: Imports section (requires Mercury for test files)

Session 2 (Feb 6, Mercury):
- Imports: All formats tested (mbox, Apple Mail, PST, EML)
- Archive Folders: Create, subfolder, rename, color, move, delete all pass
- Fixed: mbox file selection in import picker (is_mbox flag missing)
- Fixed: File picker Apple Mail option text alignment
- Fixed: New folder sidebar alignment (switched to full tree rebuild)
- Next: Staging & Commit

