# MailRepo - TODO

## High Priority

### Import Folder Staging (Session 12 - Incomplete)
- Individual email staging from imports WORKS
- Folder staging for imports was attempted but reverted
- Need to REUSE existing IMAP folder selection code, not reimplement
- Key files: `views/folder-mgmt.js` has `showFolderSelectionView()`, `handleFolderCheckbox()`, etc.
- See SESSION_NOTES.md for detailed lessons learned

### Progress Indicator for Email Loading
- Currently shows spinner for all folder loads
- Implement progress bar for folders with >50 emails
- Keep spinner for ≤50 emails (feels instant enough)
- Backend needs to return count first, then stream/batch emails
- Threshold (50) could be configurable in settings later

### IMAP Folder Caching Improvements
- Basic caching with UIDVALIDITY implemented
- Could optimize for very large folders
- Consider background refresh

## Medium Priority

### Multi-Account Folder Staging (Backend)
- Frontend now supports staging folders from multiple accounts
- Backend `/api/commit-folders` still processes one account at a time
- Frontend groups and makes multiple API calls (works, but not ideal)
- Could optimize backend to accept array of account+folder+destination groups

## Low Priority / Future

### After Commit Actions for Folders
- "After commit" dropdown exists in review UI for folders
- Backend doesn't yet implement archive/trash/delete for source IMAP folders
- Currently only "Leave in place" actually works

### Review Page Polish
- Logout was hardcoded to /logout instead of /auth/logout (need to fix)
- Consider "Unstage All" button
- Group staged items by source (IMAP vs Import)
- Hide "After commit" dropdown for imports (doesn't apply)

---

*Last updated: January 23, 2026*
