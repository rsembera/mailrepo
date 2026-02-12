# Retention Vault Implementation Plan

**Created:** February 11, 2026  
**Status:** ✅ Implemented  
**Implemented:** February 11, 2026 (Session 35)

---

## Overview

The Retention Vault provides a separate archive area for folders with scheduled deletion dates. Folders are moved here when their contents should be preserved until a specific date, then permanently deleted after manual review.

**Use Case:** Solo practitioners (lawyers, therapists, accountants) with retention requirements who need to keep records for a specified period (e.g., 7 years) then securely destroy them.

**Design Philosophy:** MailRepo is an email archiving tool, not a full records management system. The audit trail for file destruction belongs in the user's broader practice management workflow (paper records, EdgeCase, etc.), not duplicated here. The Retention Vault is purely functional: hold folders until a date, then prompt for deletion.

---

## User Flow

### Moving a Folder to Retention Vault

1. User is in **Manage Archive** view
2. Clicks new **"Move to Vault"** button (next to existing folder actions)
3. **Date picker modal** appears:
   - Header: "Set Retention Date"
   - Subtext: "This folder will be held until this date, then flagged for permanent deletion."
   - Date picker (borrowed from EdgeCase's `pickers.js`)
   - Preset buttons: "1 Year", "3 Years", "5 Years", "7 Years", "10 Years"
   - Cancel / Confirm buttons
4. Folder disappears from main archive, appears in Retention Vault

### Retention Vault View

1. New icon in **left rail** (narrow icon bar): vault/archive-box icon
2. Clicking shows **Retention Vault** view:
   - Header: "Retention Vault"
   - Search/filter box
   - Sort dropdown: "Name (A-Z)", "Name (Z-A)", "Deletion Date (Soonest)", "Deletion Date (Latest)"
   - Default sort: **Deletion Date (Soonest)**
   - Folder list showing:
     - Folder name (with color dot if set)
     - Deletion date (formatted nicely: "March 15, 2033")
     - Days remaining or "OVERDUE" badge
     - Restore button
     - Permadelete button (only visible when overdue)

### Restore Flow

1. User clicks **Restore** on a vault folder
2. **Destination modal** appears (reuse existing move folder modal)
3. User selects destination (root or inside another folder)
4. Folder returns to main archive, retention date cleared

### Permadelete Flow

1. On app login, if any folders are past their deletion date, show **alert banner**:
   - "3 folders in Retention Vault are ready for deletion review"
   - Link to Retention Vault
2. In Retention Vault, overdue folders show:
   - "OVERDUE" badge (red)
   - **Permadelete** button visible
3. User clicks **Permadelete**:
   - Confirmation modal: "Permanently delete '{folder name}' and all {N} emails? This cannot be undone."
   - On confirm:
     - Delete all email files from disk
     - Delete all message records from database
     - Delete folder record from database
4. **Batch permadelete:**
   - Checkbox selection on overdue folders
   - "Delete Selected" button appears when any checked
   - Single confirmation: "Permanently delete {N} folders containing {M} total emails?"

---

## Database Changes

### Schema Version: 6

### Modified Table: `folders`

Add column:

```sql
ALTER TABLE folders ADD COLUMN retention_date INTEGER;
```

**Column meaning:**
- `NULL` = Normal archive folder
- Unix timestamp = In Retention Vault, scheduled for deletion review on this date

### Index

```sql
CREATE INDEX IF NOT EXISTS idx_folders_retention ON folders(retention_date);
```

---

## Migration (Version 5 → 6)

```python
def _migrate_5_to_6(cls, conn):
    """Add retention_date to folders."""
    cursor = conn.cursor()
    
    # Add retention_date column to folders
    cursor.execute("ALTER TABLE folders ADD COLUMN retention_date INTEGER")
    
    # Index for quick vault queries
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_folders_retention ON folders(retention_date)"
    )
```

---

## API Endpoints

### Move folder to vault

```
POST /api/folders/{id}/vault
Body: { "retention_date": 1893456000 }  // Unix timestamp
Response: { "success": true }
```

### Restore folder from vault

```
POST /api/folders/{id}/restore
Body: { "destination_id": 5 }  // or null for root
Response: { "success": true }
```

### Permadelete folder

```
DELETE /api/folders/{id}/permadelete
Response: { "success": true, "emails_deleted": 47 }
```

### Batch permadelete

```
POST /api/folders/batch-permadelete
Body: { "folder_ids": [1, 2, 3] }
Response: { "success": true, "folders_deleted": 3, "emails_deleted": 142 }
```

### Get vault folders

```
GET /api/folders/vault
Response: {
    "folders": [
        {
            "id": 1,
            "name": "Client: Smith",
            "color": "#e53935",
            "retention_date": 1893456000,
            "email_count": 47,
            "is_overdue": true
        }
    ],
    "overdue_count": 2
}
```

### Check for overdue folders (for login alert)

```
GET /api/folders/vault/overdue-count
Response: { "count": 3 }
```

---

## Frontend Components

### New Files

1. **`web/static/js/views/vault.js`**
   - `showVaultView()` - Render vault folder list
   - `renderVaultList()` - Build folder list HTML
   - `handleVaultSort()` - Sort change handler
   - `handleVaultFilter()` - Filter input handler
   - `restoreFolder(id)` - Open destination modal, call API
   - `permadeleteFolder(id)` - Confirm and delete single folder
   - `batchPermadelete()` - Confirm and delete selected folders

2. **`web/static/js/components/date-picker.js`**
   - Copy and adapt from EdgeCase's `pickers.js`
   - Just the `DatePicker` class and initialization helper
   - CSS in `pickers.css`

3. **`web/static/css/pickers.css`**
   - Copy from EdgeCase's picker styles
   - Adjust colors to match MailRepo theme

### Modified Files

1. **`web/static/js/views/folder-mgmt.js`**
   - Add "Move to Vault" button to folder actions
   - Add `openMoveToVaultModal(folderId)` function

2. **`web/static/js/components/sidebar.js`**
   - Add Vault icon to left rail
   - Show badge with overdue count (if > 0)

3. **`web/static/js/state.js`**
   - Add `vaultFolders` to state
   - Add `loadVaultFolders()` function
   - Add `overdueCount` to state

4. **`web/static/js/modals.js`**
   - Add date picker modal support

5. **`web/static/js/app.js`**
   - Import and initialize vault view
   - Check overdue count on load, show banner if needed

---

## UI Details

### Left Rail Icon

- Icon: `archive` (Lucide) - represents long-term storage
- Position: Below existing icons, above settings
- Badge: Red dot/number when overdue folders exist

### Vault List Item

```
┌────────────────────────────────────────────────────────────────┐
│ 🔴 Client: Smith                                               │
│     Delete by: March 15, 2033 (2,557 days)              [Restore] │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│ ☑ 🟠 Client: Jones                                    OVERDUE │
│     Delete by: January 10, 2026 (32 days ago)   [Restore] [Delete] │
└────────────────────────────────────────────────────────────────┘
```

### Date Picker Modal

```
┌─────────────────────────────────────────┐
│ Set Retention Date                    X │
├─────────────────────────────────────────┤
│                                         │
│ Hold until this date, then review       │
│ for permanent deletion.                 │
│                                         │
│  [────── Date Picker ──────]            │
│                                         │
│  Quick select:                          │
│  [1 Year] [3 Years] [5 Years] [7 Years] │
│                                         │
│                   [Cancel] [Confirm]    │
└─────────────────────────────────────────┘
```

### Deletion Log

```
(Removed - audit trail belongs in user's broader records management system)
```

---

## Implementation Order

### Phase 1: Database & Backend (1 session)
1. Add migration for schema v6
2. Add `retention_date` column handling
3. Implement all API endpoints

### Phase 2: Date Picker Component (1 session)
1. Port DatePicker from EdgeCase
2. Create picker CSS
3. Create "Move to Vault" modal

### Phase 3: Vault View (1-2 sessions)
1. Add left rail icon + badge
2. Implement vault view with sorting/filtering
3. Implement restore flow
4. Implement single permadelete
5. Implement batch permadelete

### Phase 4: Polish (0.5 session)
1. Add login overdue alert
2. Test all flows
3. Edge cases and error handling

---

## Testing Checklist

- [ ] Move folder to vault (with date picker)
- [ ] Move folder to vault (with preset buttons)
- [ ] Vault displays correct folder count
- [ ] Sort by name ascending
- [ ] Sort by name descending
- [ ] Sort by deletion date soonest
- [ ] Sort by deletion date latest
- [ ] Filter folders by name
- [ ] Restore folder to root
- [ ] Restore folder to subfolder destination
- [ ] Permadelete single folder
- [ ] Batch select multiple folders
- [ ] Batch permadelete
- [ ] Login alert shows when overdue folders exist
- [ ] Left rail badge shows overdue count
- [ ] Cannot permadelete non-overdue folder
- [ ] Subfolder tree moves together with parent

---

## Design Decision: Subfolders

**Decision:** When moving a folder with children to Retention Vault, the entire tree moves together with the same retention date.

**Rationale:** Keeps file organization intact and maintains a simple mental model — a "folder" in the Retention Vault represents a complete client file, subfolders and all. When restored or deleted, the entire tree is handled as a unit.

---

## Notes

- Retention Vault is folder-level only (not individual emails) - keeps it simple
- No auto-delete - always requires manual review (compliance safety)
- No deletion log - audit trail belongs in user's broader records management system
- Consider: export before permadelete option? (Future enhancement)
