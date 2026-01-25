# MailRepo - Session Notes

## Session 15 (January 25, 2026)

### Completed

**Commit Progress Streaming:**
- ✅ Phase 1/2 indicators for emails vs folders
- ✅ Per-email progress with subjects during folder commits
- ✅ Periodic DB commits every 10 emails for durability on interruption
- ✅ "Folder X of Y" display for multi-folder commits
- ✅ Summary shows "skipped (duplicates)" for clarity

**Subfolder Navigation:**
- ✅ Compact pill bar between header and toolbar
- ✅ "Up" pill to navigate to parent folder
- ✅ Sidebar auto-expands/collapses to match current folder

**Review View:**
- ✅ "After commit" dropdown uses styled icon-select (was native select)
- ✅ "After commit" dropdown added for staged folders (was emails only)
- ✅ Options: Leave in place, Move to Trash, Delete permanently

### Files Modified
- `web/blueprints/api/progress.py` - Phase indicators, periodic commits
- `web/static/css/modules/email-list.css` - Subfolder pill styles
- `web/static/css/modules/progress.css` - Progress detail styling
- `web/static/css/modules/review-view.css` - Source action dropdown styles
- `web/static/js/components/progress.js` - Phase/folder info display
- `web/static/js/components/sidebar.js` - selectFolderInSidebar with expand/collapse
- `web/static/js/views/mail.js` - Subfolder pills, navigateToSubfolder
- `web/static/js/views/review.js` - Styled dropdowns, folder groups
- `web/templates/main/index.html` - Subfolders bar container

---

## Session 14 (January 24-25, 2026)

### Completed

**Folder Commit Feature (All 8 Chunks):**
- ✅ Backend helpers for folder creation and email retrieval
- ✅ Streaming commit endpoint handles both emails and folders
- ✅ Archive path computation preserves folder hierarchy
- ✅ Frontend passes import data (path, type) with commits
- ✅ Clears staged items after successful commit

**Bug Fixes:**
- ✅ Fixed `staged` vs `emails` key mismatch in commit request
- ✅ Fixed nested email object access in review view
- ✅ Fixed `sourceAccountId` field name for IMAP grouping  
- ✅ Fixed account names showing as "Account undefined"
- ✅ Fixed EML imports missing `sourcePath` for commit
- ✅ Fixed duplicate import causing JS syntax error
- ✅ Fixed `imports.get()` vs `imports.find()` for array lookup
- ✅ Folder names now show `archivePath` not full filesystem path

**UI Improvements:**
- ✅ Smart dropdown positioning (flips up when near viewport bottom)
- ✅ Removed overflow:hidden that was clipping dropdowns

---

## Quick Reference

```bash
cd /home/rick/Applications/mailrepo
./venv/bin/python main.py
# Open http://localhost:5050
# Master password: Alkahest131!
```

## Recent Commits
- `433f4a7` - Add commit progress streaming, subfolder navigation pills, and UI improvements
- `5e0200a` - Fix: Add sourcePath to EML email parsing response
- `698ba6f` - Debug: Add error logging to email commit
- `b0278e9` - Fix: Review view displaying email/account data correctly
