# MailRepo Testing Checklist

Pre-release manual testing checklist. Run through before any public release.

---

## First Run / Setup

- [ ] Fresh start (delete `data/` folder) shows password setup screen
- [ ] Password under 12 characters is rejected
- [ ] Password mismatch is rejected
- [ ] Valid password creates database and shows "Create Archive" prompt
- [ ] Can create first archive folder (encrypted)

---

## Authentication

- [ ] Closing browser and reopening requires login
- [ ] Wrong password shows error
- [ ] 5 wrong passwords triggers rate limiting (60 second lockout)
- [ ] Correct password after lockout expires works
- [ ] Logout button works, returns to login screen
- [ ] Password change works (Settings → Security)
- [ ] Old password rejected after change
- [ ] New password works after change

---

## Accounts (IMAP)

- [ ] Add Gmail account (OAuth or app password)
- [ ] Add non-Gmail IMAP account (Fastmail, iCloud, etc.)
- [ ] Auto-detect server settings works for common providers
- [ ] Manual server entry works
- [ ] Account appears in sidebar after adding
- [ ] Can remove account
- [ ] Credentials persist after restart

---

## Email Browsing (IMAP)

- [ ] Selecting account loads folder list
- [ ] Selecting folder loads email list
- [ ] Email list shows sender, subject, date
- [ ] Clicking email shows full content in viewer
- [ ] HTML emails render correctly
- [ ] Plain text emails display correctly
- [ ] Attachments are listed
- [ ] Can download attachments
- [ ] Pagination works for large folders (if implemented)

---

## Imports

### mbox
- [ ] Can browse to and select .mbox file
- [ ] Import mounts and shows in sidebar
- [ ] Emails are browsable
- [ ] Can view individual emails
- [ ] Unmount removes from sidebar

### Apple Mail Export (.mbox directory)
- [ ] Can select .mbox directory
- [ ] Nested folders appear correctly
- [ ] Emails load from both `mbox` file and `Messages/*.emlx` formats
- [ ] Unmount works

### PST (if libpst installed)
- [ ] PST support check shows correct status
- [ ] Can select and convert .pst file
- [ ] Converted folders appear
- [ ] Emails are viewable
- [ ] Temp files cleaned up on unmount
- [ ] Password-protected .pst file imports without issue (password is UI-level only, not encryption)

### EML Directory
- [ ] Can select directory of .eml files
- [ ] Individual emails load correctly

---

## Archive Folders

- [ ] Can create new folder at root level
- [ ] Can create nested subfolder
- [ ] Can rename folder
- [ ] Can move folder (drag or menu)
- [ ] Can delete folder (moves to Trash)
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

Test date: _______________

Tested by: _______________

Version: _______________

Issues found:


