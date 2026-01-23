# MailRepo - TODO

## High Priority

### Progress Indicator for Email Loading
- Currently shows spinner for all folder loads
- Implement progress bar for folders with >50 emails
- Keep spinner for ≤50 emails (feels instant enough)
- Backend needs to return count first, then stream/batch emails
- Threshold (50) could be configurable in settings later

### IMAP Folder Sync/Caching
- Currently re-fetches all emails from IMAP on every folder click
- Store UIDVALIDITY and highest UID seen per folder
- On folder load: check UIDVALIDITY (if changed, cache invalid)
- If valid: only fetch emails with UID > last seen (new emails only)
- Cache headers locally (SQLite or in-memory for session)
- Significant performance improvement for large folders

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

---

*Last updated: January 23, 2026*
