# MailRepo - Session Notes

## Session 14 (January 25, 2026)

### Completed Today

**Code Cleanup:**
- [x] Removed old standalone Review and Settings pages (~2,755 lines deleted)
  - Deleted `web/static/js/review.js`, `web/static/js/settings.js`
  - Deleted `web/static/css/review.css`, `web/static/css/settings.css`
  - Deleted `web/templates/main/review.html`, `web/templates/main/settings.html`
  - Removed `/review` and `/settings` routes from `main.py`

**Import Improvements:**
- [x] Auto-display import contents after mounting (no need to click import name)
- [x] Show emails directly for imports without folder structure (EML dirs, flat mbox)
- [x] Show folder selection only if import has actual hierarchy
- [x] Indent first-level import folders below mbox name in sidebar
- [x] Clear toolbar when unmounting viewed import

**Folder Selection Checkbox Logic (Major Fix):**
- [x] Fixed escaping issue with folder paths containing quotes (e.g., "Peter O'Connor")
- [x] Checking a child does NOT auto-check/stage the parent
- [x] Checking a parent does NOT auto-check/stage children
- [x] Unchecking a parent DOES uncheck all children (cascade down)
- [x] Parent shows indeterminate when children are staged but parent is not
- [x] Select All state based on staging set, not visual checkbox state
- [x] Stage button enables correctly based on actual selections

**UI Fixes:**
- [x] Unstage All uses confirmation modal instead of browser alert
- [x] New Folder button in sidebar uses selected app font
- [x] Stage button now enables for import views (not just IMAP)
- [x] Select All toggle works correctly (uncheck was broken)

### In Progress

**Folder Staging Hierarchy Logic:**
- Frontend: `computeArchivePaths()` added to staging.js
- Frontend: `archivePath` now sent with folder commit data
- Backend: NOT YET IMPLEMENTED - see IMPLEMENTATION_PLAN.md

### Current State

- Individual email staging: WORKS (IMAP and imports)
- Individual email commit: WORKS (IMAP and imports)
- Folder staging UI: WORKS (IMAP and imports)
- Folder commit: PARTIALLY IMPLEMENTED (IMAP only, no hierarchy logic)
- Import folder commit: NOT IMPLEMENTED

---

## Session 13 (January 24, 2026)

### Completed

**UI/UX Improvements:**
- [x] Welcome state for main page
- [x] Remove "Review & Commit" button from header
- [x] Fix Review page logout
- [x] Add "Unstage All" button to Review page
- [x] Staged rail button navigates to review even when empty
- [x] Fix archive folder alignment
- [x] Collapse child folders when parent collapses
- [x] Reorder left rail icons
- [x] Add divider line above Settings/Logout
- [x] Add max-width to Manage Folders view
- [x] Move New Folder button to top toolbar

**Settings Redesign:**
- [x] Settings now renders inside main app
- [x] Fixed font and font size selectors

**Review View Conversion:**
- [x] Converted Review from separate page to client-side view
- [x] View selection preserved when switching views

---

## Quick Start

```bash
cd /home/rick/Applications/mailrepo
./venv/bin/python main.py
# Open http://localhost:5050
# Master password: Alkahest131!
```
