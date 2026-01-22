# MailRepo Refactoring Plan

**Created:** January 22, 2026  
**Status:** In Progress

---

## Overview

The codebase has grown to a point where single-file architecture is becoming unwieldy:
- `main.js`: 2,514 lines, 85 functions
- `main.css`: 1,446 lines
- `api.py`: 1,442 lines

This plan breaks the code into logical modules while maintaining functionality.

---

## Guiding Principles

1. **Small chunks** - Each change should be committable and testable
2. **No build step** - Use native ES modules, CSS imports
3. **Preserve functionality** - Refactor only, no new features until complete
4. **Test after each phase** - Start server, verify nothing broke

---

## Phase 1: JavaScript Modules

### Target Structure

```
web/static/js/
├── app.js                 # Entry point, initialization
├── state.js               # Central state management
├── utils.js               # Utility functions
├── modals.js              # Modal helpers (showAlert, showConfirm, etc.)
├── components/
│   ├── folder-tree.js     # Reusable folder tree renderer
│   ├── email-list.js      # Email list rendering
│   └── sidebar.js         # Sidebar management
└── views/
    ├── mail.js            # Mail view (account/folder email loading)
    ├── staging.js         # Staging workflow
    ├── folder-mgmt.js     # Folder management view
    └── trash.js           # Trash view
```

### Step 1.1: Create utils.js
Extract from main.js:
- `escapeHtml()`
- `extractName()`
- `formatDate()`
- `debounce()`

### Step 1.2: Create state.js
Extract:
- `state` object
- State initialization

### Step 1.3: Create modals.js
Extract:
- `closeModal()`
- `showPrompt()`, `resolvePrompt()`
- `showConfirm()`, `resolveConfirm()`
- `showAlert()`

### Step 1.4: Create components/folder-tree.js
Create unified tree renderer that handles:
- Sidebar archive folders
- Folder selection view (with checkboxes)
- Destination folder modal
- Move folder modal

Configuration options:
- `selectable`: boolean (click to select)
- `checkboxes`: boolean (show checkboxes)
- `expandable`: boolean (show chevrons)
- `onSelect`: callback
- `onCheck`: callback
- `filter`: function to filter folders

### Step 1.5: Create components/email-list.js
Extract:
- `renderEmailList()`
- `toggleEmailSelection()`
- `handleSelectAll()`
- `updateSelectAllState()`

### Step 1.6: Create components/sidebar.js
Extract:
- `toggleSection()`
- `handleTreeItemClick()`
- `loadAccountLabels()`
- `buildImapFolderTree()`
- `renderImapFolderTree()`
- `updateSidebarFolders()`
- `refreshSidebarFolders()`
- Sidebar resize logic

### Step 1.7: Create views/mail.js
Extract:
- `selectView()`
- `loadAccountEmails()`
- `loadFolderEmails()`
- `showMailView()`
- Email viewer functions

### Step 1.8: Create views/staging.js
Extract:
- `openStageModal()`
- `renderFolderSelectTree()` (use folder-tree.js)
- `handleFolderSelect()`
- `confirmStage()`
- `updateStagedBadge()`
- `showStagedView()`
- `renderStagedList()`
- `unstageEmail()`
- Folder staging functions

### Step 1.9: Create views/folder-mgmt.js
Extract:
- `showFolderManagementView()`
- `renderFolderManagementList()`
- `renameFolder()`
- `createSubfolder()`
- `openMoveFolder()`
- `confirmMoveFolder()`
- `deleteFolder()`
- Color picker functions

### Step 1.10: Create views/trash.js
Extract:
- `showTrashView()`
- `renderTrashList()`
- `restoreFolder()`
- `permanentlyDeleteFolder()`
- `emptyTrash()`
- `updateTrashBadge()`

### Step 1.11: Create app.js
- Import all modules
- `initEventListeners()`
- `DOMContentLoaded` handler
- Rail button view switching
- Navigation warning

---

## Phase 2: CSS Modules

### Target Structure

```
web/static/css/
├── main.css               # Imports only
├── base/
│   ├── layout.css         # App container, three-pane layout
│   └── responsive.css     # Media queries
├── components/
│   ├── rail.css           # Left rail
│   ├── sidebar.css        # Sidebar, tree items
│   ├── email-list.css     # Email list, email items
│   ├── email-viewer.css   # Email viewer panel
│   ├── modals.css         # All modal styles
│   └── folder-tree.css    # Folder tree (shared)
└── views/
    ├── folder-mgmt.css    # Folder management view
    ├── trash.css          # Trash view
    └── staging.css        # Staging view, folder selection
```

### Step 2.1: Create base/layout.css
Extract:
- `.app-container`
- `.main-content`
- `.content-header`
- `.content-toolbar`
- `.empty-state`

### Step 2.2: Create components/rail.css
Extract:
- `.left-rail`
- `.rail-btn`
- `.rail-badge`
- `.rail-logo`

### Step 2.3: Create components/sidebar.css
Extract:
- `.sidebar`
- `.sidebar-resize-handle`
- `.sidebar-search`
- `.sidebar-section`
- `.section-header`
- `.tree-item`, `.tree-item-row`
- `.imap-tree-*`

### Step 2.4: Create components/email-list.css
Extract:
- `.email-list`
- `.email-item`
- `.email-checkbox`, `.email-content`, etc.

### Step 2.5: Create components/email-viewer.css
Extract:
- `.email-viewer-overlay`
- `.email-viewer`
- `.email-viewer-header`, etc.

### Step 2.6: Create components/modals.css
Extract:
- `.modal-overlay`
- `.modal-content`
- `.modal-header`, `.modal-actions`
- `.folder-select-*`

### Step 2.7: Create views/*.css
Extract view-specific styles to their own files.

### Step 2.8: Update main.css
Replace content with imports:
```css
@import 'base/layout.css';
@import 'components/rail.css';
/* etc. */
```

---

## Phase 3: Backend API Split

### Target Structure

```
web/blueprints/
├── __init__.py
├── auth.py                # Unchanged
├── main.py                # Unchanged
└── api/
    ├── __init__.py        # Register all API blueprints
    ├── accounts.py        # /api/accounts/* routes
    ├── folders.py         # /api/folders/* routes
    ├── emails.py          # Email-related routes
    └── staging.py         # Commit/staging routes
```

### Step 3.1: Create api/__init__.py
Blueprint factory that registers sub-blueprints.

### Step 3.2: Create api/accounts.py
Extract:
- `GET /api/accounts`
- `POST /api/accounts`
- `DELETE /api/accounts/<id>`
- `GET /api/accounts/<id>/folders`
- `GET /api/accounts/<id>/emails`
- `GET /api/accounts/<id>/emails/<uid>`

### Step 3.3: Create api/folders.py
Extract:
- `GET /api/folders`
- `POST /api/folders`
- `PATCH /api/folders/<id>`
- `DELETE /api/folders/<id>`
- `POST /api/folders/<id>/restore`
- `DELETE /api/folders/<id>/permanent`
- `GET /api/folders/<id>/emails`
- `GET /api/folders/<id>/emails/<id>`
- `POST /api/trash/empty`

### Step 3.4: Create api/staging.py
Extract:
- `POST /api/commit`
- `POST /api/commit-folders`

### Step 3.5: Update app.py
Register new API blueprint structure.

---

## Phase 4: Cleanup

- Remove dead code
- Consolidate duplicate logic
- Add JSDoc comments to exported functions
- Update any documentation

---

## Testing Checklist

After each phase, verify:
- [ ] Server starts without errors
- [ ] Login works
- [ ] Can view IMAP folders
- [ ] Can view emails
- [ ] Can stage emails
- [ ] Can stage folders (bulk)
- [ ] Destination modal shows hierarchical tree
- [ ] Can create new folder from modal
- [ ] Folder management view works
- [ ] Trash view works
- [ ] Settings page works
- [ ] Review & commit works

---

## Progress Tracking

| Phase | Step | Status | Commit |
|-------|------|--------|--------|
| 1 | 1.1 utils.js | ✅ | c08e470 |
| 1 | 1.2 state.js | ✅ | c08e470 |
| 1 | 1.3 modals.js | ✅ | c08e470 |
| 1 | 1.4 folder-tree.js | ✅ | ea49919 |
| 1 | 1.5 email-list.js | ✅ | 2270a1c |
| 1 | 1.6 sidebar.js | ✅ | 2491fde |
| 1 | 1.7 mail.js | ⬜ | |
| 1 | 1.8 staging.js | ⬜ | |
| 1 | 1.9 folder-mgmt.js | ⬜ | |
| 1 | 1.10 trash.js | ⬜ | |
| 1 | 1.11 app.js | ⬜ | |
| 2 | CSS split | ⬜ | |
| 3 | API split | ⬜ | |
| 4 | Cleanup | ⬜ | |
