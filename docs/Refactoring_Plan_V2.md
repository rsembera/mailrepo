# MailRepo Refactoring Plan V2

**Created:** January 27, 2026  
**Status:** Planned (for future session)  
**Priority:** Low - Non-blocking for release

---

## Overview

The initial refactoring (V1) successfully modularized the codebase. However, after continued development, several files have grown large again and some patterns could be improved. This plan addresses technical debt while maintaining stability.

### Current File Sizes (Lines of Code)

**Backend (Python):**
| File | Lines | Notes |
|------|-------|-------|
| `progress.py` | 1,202 | ⚠️ Too large - handles streaming, commit, parsing |
| `filesystem.py` | 621 | File picker logic |
| `imap.py` | 620 | IMAP operations |
| `database.py` | 363 | Database layer |
| `staging.py` | 324 | Staging routes |
| `folders.py` | 312 | Folder routes |

**Frontend (JavaScript):**
| File | Lines | Notes |
|------|-------|-------|
| `folder-mgmt.js` | 1,200 | ⚠️ Too large - folder mgmt + bulk selection |
| `imports.js` | 983 | ⚠️ Large - file picker + import logic |
| `review.js` | 883 | ⚠️ Large - complex rendering logic |
| `sidebar.js` | 573 | IMAP tree + archive tree |
| `staging.js` | 561 | Destination modal + staging |
| `mail.js` | 547 | Email loading + navigation |
| `settings.js` | 530 | Settings view |
| `app.js` | 500 | Entry point |

---

## Priority 1: Split progress.py (~1,200 lines)

The largest backend file handles too many responsibilities.

### Current Responsibilities
1. SSE message formatting
2. Email cache management
3. IMAP email streaming
4. Import email streaming
5. Commit workflow (emails + folders)
6. Post-commit actions (archive/trash/delete)
7. Email parsing (mbox, Apple mbox, emlx, EML)

### Proposed Split

```
web/blueprints/api/
├── progress.py          # Keep: SSE helpers, stream routes (slim coordinator)
├── streaming.py         # NEW: Email streaming logic (IMAP + imports)
├── commit.py            # NEW: Commit workflow + post-actions
└── email_parser.py      # NEW: Email parsing utilities
```

**streaming.py** (~300 lines):
- `_get_cached_emails()`
- `_get_highest_cached_uid()`
- `_clear_folder_cache()`
- `_cache_email()`
- IMAP streaming generator
- Import streaming generator

**commit.py** (~400 lines):
- `stream_commit()` route
- Email commit logic
- Folder commit logic
- Post-commit actions (archive, trash, delete)

**email_parser.py** (~200 lines):
- `_get_emails_from_import_folder()`
- `_get_raw_email_from_import()`
- mbox parsing
- Apple mbox parsing
- emlx parsing
- EML file reading

**progress.py** (~300 lines):
- `sse_message()` helper
- Route definitions (thin wrappers)
- Coordination logic

---

## Priority 2: Split folder-mgmt.js (~1,200 lines)

This file handles two distinct views that could be separated.

### Proposed Split

```
web/static/js/views/
├── folder-mgmt.js       # Keep: Folder management (rename, move, delete, color)
└── folder-select.js     # NEW: Bulk folder selection for staging
```

**folder-select.js** (~500 lines):
- `showFolderSelectionView()`
- `showImportFolderSelectionView()`
- `renderFolderSelectionList()`
- Selection state management
- Toolbar rendering

**folder-mgmt.js** (~700 lines):
- `showFolderManagementView()`
- `renderFolderManagementList()`
- Move folder modal
- Color picker
- Rename/delete operations

---

## Priority 3: Consolidate Shared Utilities

### 3.1: Move `escapeForOnclick()` to utils.js

Currently duplicated in:
- `folder-mgmt.js`
- `mail.js`

Move to `utils.js` and export.

### 3.2: Create `tree-renderer.js` Component

Folder tree rendering is duplicated across:
- `sidebar.js` (archive folders)
- `staging.js` (destination modal)
- `folder-mgmt.js` (folder selection)
- `folder-mgmt.js` (move modal)

Create shared tree renderer with configuration:
```javascript
renderFolderTree(folders, {
    selectable: boolean,      // Click to select
    checkable: boolean,       // Show checkboxes
    expandable: boolean,      // Show chevrons
    showIcons: boolean,       // Folder/lock icons
    onSelect: callback,
    onCheck: callback,
    filter: function,
    disabledIds: Set,
});
```

---

## Priority 4: Simplify imports.js (~983 lines)

### Proposed Split

```
web/static/js/components/
├── imports.js           # Keep: Import management, sidebar rendering
└── file-picker.js       # NEW: File picker modal logic
```

**file-picker.js** (~400 lines):
- `openFilePicker()`
- `initFilePicker()`
- Directory navigation
- File selection
- Modal rendering

**imports.js** (~580 lines):
- `initImports()`
- `mountImport()`
- `unmountImport()`
- `loadImportEmails()`
- Sidebar section rendering

---

## Priority 5: review.js Cleanup (~883 lines)

This file is large but cohesive - it handles the review view. Rather than splitting, focus on:

1. Extract dropdown rendering to a helper
2. Extract source group rendering to a helper
3. Reduce inline HTML template complexity
4. Add JSDoc comments

---

## Non-Priorities (Leave As-Is)

These files are reasonably sized and well-organized:

- `sidebar.js` (573 lines) - Complex but cohesive
- `staging.js` (561 lines) - Destination modal is self-contained
- `mail.js` (547 lines) - Recently refactored
- `settings.js` (530 lines) - Single-purpose view
- `app.js` (500 lines) - Entry point, appropriately sized

---

## Implementation Order

1. **Priority 1**: Split `progress.py` (biggest impact, reduces bug surface in parsing)
2. **Priority 3.1**: Move `escapeForOnclick()` (quick win, removes duplication)
3. **Priority 2**: Split `folder-mgmt.js` (cleaner separation of concerns)
4. **Priority 4**: Extract `file-picker.js` (isolates complex modal logic)
5. **Priority 3.2**: Create `tree-renderer.js` (requires careful testing)
6. **Priority 5**: Clean up `review.js` (polish, not urgent)

---

## Testing Checklist

After each change:
- [ ] Server starts without errors
- [ ] Login works
- [ ] IMAP folder browsing works
- [ ] Archive folder browsing works
- [ ] Email staging works (IMAP + imports)
- [ ] Folder staging works (bulk selection)
- [ ] Destination modal tree works
- [ ] Review page renders correctly
- [ ] Commit works (emails + folders)
- [ ] Post-commit actions work (archive/trash/delete)
- [ ] File picker works (mbox + EML import)
- [ ] Folder management works (rename, move, delete, color)
- [ ] Trash view works

---

## Time Estimate

| Priority | Effort | Risk |
|----------|--------|------|
| 1 (progress.py) | 2-3 hours | Medium - Core functionality |
| 2 (folder-mgmt.js) | 1-2 hours | Low - Clear separation |
| 3.1 (escapeForOnclick) | 15 minutes | Very Low |
| 3.2 (tree-renderer) | 3-4 hours | High - Shared component |
| 4 (file-picker.js) | 1-2 hours | Low - Isolated logic |
| 5 (review.js cleanup) | 1 hour | Low - No structural changes |

**Total: 8-12 hours** (spread across multiple sessions)

---

## Notes

- This refactoring is **non-blocking** for release
- All changes should be incremental with commits after each step
- Consider automated tests for `email_parser.py` after extraction (parsing is bug-prone)
- The shared tree renderer (Priority 3.2) has the highest risk - defer if time-constrained
