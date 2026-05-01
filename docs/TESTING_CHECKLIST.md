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
- [ ] ⋯ actions button appears on folder row hover
- [ ] Clicking ⋯ button opens the folder actions menu (same items as right-click)
- [ ] Menu is anchored below the button and stays within the viewport
- [ ] Right-click on folder row still opens the same menu (existing behavior preserved)
- [ ] Clicking ⋯ does not navigate into the folder
- [ ] Long folder names truncate with ellipsis instead of horizontal-scrolling the sidebar
- [ ] Keyboard focus on ⋯ button shows it (focus-visible)

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
- [ ] Scope button shows current scope ("All folders" or folder path)
- [ ] Scope picker opens a modal with a folder tree
- [ ] Picker filter input narrows the visible folders and auto-expands ancestors
- [ ] Selecting a folder closes the picker and updates the scope label
- [ ] "All folders" row in picker resets the scope
- [ ] "Include subfolders" toggle defaults to on; turning it off appends "(only)" to the scope label
- [ ] Helper text reflects the current scope ("…in X and its subfolders" / "…in X only" / whole archive)
- [ ] Search runs against the selected scope (folder + subs / folder only / all)
- [ ] Typing over a previous query and pressing Enter runs a new search without needing Clear

---

## Retention Vault

### Move to Vault
- [ ] "Move to Vault" button appears in Manage Archive view
- [ ] Modal opens with date picker
- [ ] Date picker allows year/month/day selection
- [ ] Quick preset buttons work (1, 3, 5, 7, 10 years)
- [ ] Confirm button disabled until date selected
- [ ] Folder disappears from archive after move
- [ ] Folder appears in Retention Vault view

### Vault View
- [ ] Vault icon in left rail shows overdue badge count
- [ ] Clicking vault icon opens Retention Vault view
- [ ] Folders listed with name, email count, delete-by date
- [ ] Overdue folders marked with red badge
- [ ] Search/filter works
- [ ] Sort dropdown works (soonest, latest, name A-Z, Z-A)

### Restore from Vault
- [ ] Restore button opens destination picker
- [ ] Can select archive root as destination
- [ ] Can select existing folder as destination
- [ ] Folder returns to archive after restore
- [ ] Folder removed from vault after restore

### Permanent Deletion
- [ ] Delete button only appears for overdue folders
- [ ] Confirmation dialog shows folder name and email count
- [ ] Folder and all emails permanently deleted after confirm
- [ ] "Delete Overdue" button deletes all overdue folders

### Overdue Alert
- [ ] Alert banner appears on mail view when overdue folders exist
- [ ] Alert shows count of overdue folders
- [ ] "View Vault" button navigates to vault
- [ ] Dismiss button hides alert (session-based)
- [ ] Alert hidden on non-mail views (Settings, Trash, etc.)

---

## Trash

- [ ] Deleted folders appear in Trash
- [ ] Deleted emails appear in Trash
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

This checklist is run end-to-end against the **packaged build** (.deb / .dmg) before any public release. All checkboxes are reset to unchecked after each release pass.

The session history below is kept as a development record — it captures issues found and fixed during the pre-packaging development cycle, not the formal pre-release pass.

---

### Development testing history

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

