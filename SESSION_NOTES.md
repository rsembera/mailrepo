# MailRepo - Session Notes

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

### Known Issues / TODO

See TODO.md for full list.

---

## Quick Reference

```bash
cd /home/rick/Applications/mailrepo
./venv/bin/python main.py
# Open http://localhost:5050
# Master password: Alkahest131!
```

## Recent Commits
- `5e0200a` - Fix: Add sourcePath to EML email parsing response
- `698ba6f` - Debug: Add error logging to email commit
- `b0278e9` - Fix: Review view displaying email/account data correctly
- `c84f90f` - Fix: Review view UI improvements
- `03ba142` - Fix: Send correct data structure for email commit
