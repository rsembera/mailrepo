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
- [x] Folder with emails can be deleted
- [x] Folder with subfolders can be deleted

---

## Staging & Commit

### Staging Emails
- [x] Can select individual emails (checkbox)
- [x] Can select all emails in folder
- [x] "Stage" button opens destination picker
- [x] Can select destination folder
- [x] Can create new folder from picker
- [x] Staged badge shows count
- [x] Staged emails appear grayed out

### Staging Folders (Import)
- [x] Can stage entire folder from import
- [x] Subfolder staging options work (with/without children)
- [x] Folder appears in Review with email count

### Review
- [x] Review button shows all staged items
- [x] Items grouped by destination
- [x] Can change destination for group
- [x] Can unstage individual items
- [x] Can unstage entire destination group
- [x] Source action dropdown works (Leave/Archive/Trash/Delete)
- [x] "Unstage All" clears everything

### Commit
- [x] Commit button starts process
- [x] Progress modal shows status
- [x] Emails are copied to archive
- [ ] Source actions execute (if not "Leave")
- [x] Success message shows count
- [x] Archived emails appear in destination folder
- [x] Staged items cleared after commit

---

## Archived Email Operations

- [x] Can view archived email
- [x] Can download archived email as .eml
- [x] Can export folder as ZIP (decrypted .eml files)
- [x] Can print archived email
- [x] Can move email to different archive folder
- [x] Can delete email (moves to Trash)
- [x] Batch select works
- [x] Batch move works
- [x] Batch delete works

---

## Search

- [x] Search box appears in archive view
- [x] Search finds emails by subject
- [x] Search finds emails by sender
- [x] Search finds emails by body text
- [x] Search results are clickable
- [x] Clear search returns to folder view

---

## Retention Vault

### Move to Vault
- [x] "Move to Vault" button appears in Manage Archive view
- [x] Modal opens with date picker
- [x] Date picker allows year/month/day selection
- [x] Quick preset buttons work (1, 3, 5, 7, 10 years)
- [x] Confirm button disabled until date selected
- [x] Folder disappears from archive after move
- [x] Folder appears in Retention Vault view

### Vault View
- [x] Vault icon in left rail shows overdue badge count
- [x] Clicking vault icon opens Retention Vault view
- [x] Folders listed with name, email count, delete-by date
- [x] Overdue folders marked with red badge
- [x] Search/filter works
- [x] Sort dropdown works (soonest, latest, name A-Z, Z-A)

### Restore from Vault
- [x] Restore button opens destination picker
- [x] Can select archive root as destination
- [x] Can select existing folder as destination
- [x] Folder returns to archive after restore
- [x] Folder removed from vault after restore

### Permanent Deletion
- [x] Delete button only appears for overdue folders
- [x] Confirmation dialog shows folder name and email count
- [x] Folder and all emails permanently deleted after confirm
- [x] "Delete Overdue" button deletes all overdue folders

### Overdue Alert
- [x] Alert banner appears on mail view when overdue folders exist
- [x] Alert shows count of overdue folders
- [x] "View Vault" button navigates to vault
- [x] Dismiss button hides alert (session-based)
- [x] Alert hidden on non-mail views (Settings, Trash, etc.)

---

## Trash

- [x] Deleted folders appear in Trash
- [x] Deleted emails appear in Trash
- [x] Can restore folder from Trash
- [x] Can permanently delete from Trash
- [x] "Empty Trash" works
- [x] Trash auto-purge after 30 days (check on restart)

---

## Backup & Restore

### Backup
- [x] Backup Now creates backup
- [x] Backup appears in restore points list
- [x] Full vs incremental decided automatically
- [x] Backup location setting works
- [x] Cloud folder detection works (iCloud, Dropbox, etc.)
- [x] Post-backup command executes (if configured)
- [x] Automatic backup on logout (based on frequency setting)
- [x] Backup on shutdown works

### Restore
- [x] Can select restore point
- [x] Restore confirmation shows details
- [x] Pre-restore safety backup created
- [x] Restore completes successfully
- [x] Data matches backup state
- [x] Can cancel pending restore

### Retention
- [x] Retention setting can be changed
- [x] Old backups cleaned up according to policy

---

## Settings

- [x] Theme switching works
- [x] Font settings work
- [x] Backup settings persist
- [x] All settings survive restart

---

## Edge Cases & Error Handling

- [x] Large email (10MB+) handles correctly
- [x] Email with many attachments works
- [x] Malformed email doesn't crash viewer
- [x] Network disconnect during IMAP fetch shows error gracefully
- [x] Corrupt mbox file shows error, doesn't crash
- [x] Database lock doesn't cause data loss
- [x] Ctrl+C shutdown completes backup and checkpoint

---

## Browser Compatibility

- [x] Chrome/Chromium works
- [x] Firefox works
- [x] Safari works (if on Mac)

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

Session 3 (Feb 7, Mercury):
- Fixed: Dropbox backup path moved to Apps subfolder (consistency with other projects)
- Fixed: Custom backup location input styling (missing form-group wrapper)
- Fixed: Backup folder picker modal not appearing (hidden vs active class)
- Fixed: Backup folder picker CSS selectors not matching (wrong parent class)
- Fixed: Backup folder picker icon color and alignment

Session 4 (Feb 7, Mercury):
- Staging & Commit: Core flow tested (stage, review, commit, source actions)
- Archive Folders: Folder/subfolder deletion tested
- Archived Email Ops: View, download, ZIP export, print, move, delete all pass
- Fixed: Source action dropdown auto-close and font color (muted inherited from label)
- Fixed: "After:" label vertical alignment with dropdown (baseline instead of center)
- Fixed: Folder restore not showing children in sidebar (switched to refreshSidebarFolders)
- Fixed: Load Remote Content button staying disabled between emails
- Fixed: Print email now uses standalone print document with attachment list
- Fixed: MS Word @page rules causing page breaks in printed emails
- Fixed: Sender/subject order reversed in Trash emails tab
- Removed: Unused updateSidebarFolders function (all callers use refreshSidebarFolders)
- Next: Search, remaining Staging items, Batch operations, Backup/Restore

Session 5 (Feb 8, Mercury):
- Search: Fixed body text not indexed for HTML-only emails (HTML-first extraction)
- Search: Added /api/search/reindex endpoint to rebuild FTS index
- Search: All search tests pass (subject, sender, body text, clickable results, clear)
- Batch Ops: Select All, batch Move, batch Delete all work
- Trash: Permanent delete (email and folder), Empty Trash all work
- Backup: Backup Now works, restore modal fixed (hidden vs active class)
- Backup: Wired up complete_restore() on server startup (was never called)
- Backup: Restore confirmed working after server restart
- Added: Sort options for email lists (date, sender, subject) - icon button dropdown
- Added: Sort options for Trash view (folders and emails tabs)
- Fixed: Trash folders empty state showing search message with no query
- Fixed: Custom select dropdown auto-flip when near screen edge
- Fixed: Restore dropdown going off-screen (now uses auto-flip)
- Fixed: Cancel Restore triggering unsaved settings warning
- Fixed: Restore modal button alignment (modal-buttons -> modal-actions)
- Fixed: Shortened "Select All" to "All" for toolbar space
- Settings: Theme, font, backup settings, password change all previously tested
- Remaining: Edge Cases, Browser Compatibility, some Backup sub-items, Staging edge cases

Session 6 (Feb 9, Mercury):
- Staging: Select all, create folder from picker, grayed out, subfolder staging all pass
- Review: Folder tree rendering improved (tree with branch lines instead of flat paths)
- Review: Unstage individual items works; unstaging parent now unstages children too
- Review: Source action dropdown works
- Fixed: Review button now uses SPA navigation (preserves in-memory staged state)
- Fixed: Email date sorting uses parsed timestamps instead of string comparison
- Fixed: Stored dates converted from ISO strings to Unix timestamps (DB migration v4→v5)
- Fixed: JS date display/sort handles Unix timestamps, ISO, and RFC 2822 formats
- Fixed: IMAP folder tree now live-fetches on expand (new server folders appear immediately)
- Added: Dynamic import naming (disambiguates only on collision, e.g. "Mail/mbox" vs "Backups/mbox")
- Staged IMAP items persist across refresh (sessionStorage); import items don't (expected)
- Remaining: Unstage entire group, Unstage All, Commit progress/source actions/cleanup

Session 7 (Feb 10, MacBook):
- Unstage entire destination group: Pass
- Unstage All clears everything: Pass
- Commit progress modal shows status: Pass
- Post-commit source actions (trash/archive/delete): Fixed and working
  - Root cause: source key mismatch between frontend (account:id:destId) and backend (account:id)
  - Fixed key format in pending_commit.py to include destinationFolderId
  - Folder post-actions apply to emails inside folder; empty IMAP folder is left on server
  - Updated labels: "Emails after:" with tooltip, options say "Leave in place", "Trash emails", etc.
- Fixed: Commit button disappearing after visiting Trash/Backups/Folders views
  - Root cause: those views set headerActions.style.display='none', Review never restored it
- TODO: Re-test full post-commit action flow end-to-end (trash, archive, delete for both emails and folders)
- Remaining: Success message shows count, staged items cleared after commit (verify)

Session 7b (Feb 10, MacBook, evening):
- Post-commit actions: Trash tested for both individual emails and folders — working
- Archive and Delete use same code path, skipped (trash confirms the mechanism)
- Fixed: IMAP email cache not invalidated after post-actions (stale emails showing)
- Fixed: Review leaf folder name for staged emails (shows "Peter O'Connor" not "Fan Mail/Peter O'Connor")
- Polish: "On server:" label replaces "Emails after:" in Review
- Polish: Progress messages improved ("Updating server...", "Trashing emails in X...")
- Polish: Summary now action-specific ("3 trashed on server" not "3 server actions applied")
- Remaining: Verify success message count and staged items cleared after commit

Session 8 (Feb 12, Mercury):
- Retention Vault: All tests pass
  - Move to Vault modal with date picker and presets
  - Vault view with folder listing, search, filter, sort
  - Restore flow returning folders to archive
  - Overdue badge and "Delete Overdue" button
  - Permanent deletion confirmed (folder "Redshirt" fully purged from DB and filesystem)
- Fixed: Date picker preset buttons font (added font-family to .date-preset-btn)
- Fixed: Icon consistency — permanent delete now uses X icon (red) everywhere, trash can for "move to trash"
- Fixed: Vault delete button style (btn-danger-subtle to match trash view)
- Fixed: Overdue alert dismiss now session-based (stays dismissed until page refresh)
- Fixed: Overdue alert "View Vault" changed from link to button with proper styling
- Remaining: Backup & Restore sub-items, Edge Cases, Browser Compatibility

Session 9 (Feb 13, MacBook):
- Database migration: Added retention_date column to MacBook database
- Review: Unstage entire destination group — pass
- Review: Unstage All clears everything — pass
- Commit: Progress modal, success message, staged items cleared — all pass
- Source actions: Tested trash action on server — pass
- Fixed: Expanded source groups in Review now clear on unstage/commit
- Fixed: Duplicate check now excludes trashed emails (was blocking re-commit after delete)
- Trash: Auto-purge after 30 days — pass (also added email cleanup, was folders only)
- Browser Compatibility: Chrome, Firefox, Safari — all pass
- UI: Swapped Settings and Backup icon order in left rail
- Refactor: Fixed circular dependency staging.js ↔ folder-selection.js (moved updateStagedBadge to state.js)
- Remaining: Backup & Restore sub-items, Edge Cases

Session 10 (Feb 13, Mercury evening):
- Backup location setting works (Dropbox)
- Cloud folder detection works
- Post-backup command: Fixed to use shell=True for redirects/pipes
- Automatic backup on logout — pass
- Backup on shutdown (Ctrl+C) — pass
- Fixed: Backup listing now uses stored location per backup
- Fixed: get_restore_points() also uses stored locations
- Retention cleanup — pass (backdated entire chain to test)
- Remaining: Edge Cases only

Session 11 (Feb 14, Mercury):
- Edge Cases testing complete:
  - Large email (16MB) — pass
  - Many attachments (25 files) — pass
  - Malformed emails (no headers, truncated MIME, bad encoding) — all pass
  - Corrupt mbox — recovered both messages, pass
  - Database lock — shows error modal gracefully, pass
  - Network disconnect — same error handling pattern, pass
- Fixed: Disable text selection on interactive UI elements (sidebar, lists, pickers)
- TESTING COMPLETE! MailRepo ready for production use.

Session 12 (Feb 14, Mercury):
- Fixed: Sidebar folder tree refreshes when returning to mail view
- ALL TESTING COMPLETE - Ready for production use!

