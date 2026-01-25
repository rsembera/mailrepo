# Folder Commit Implementation Plan

## Overview

Folder staging allows users to select entire folders (IMAP or imported mbox) and commit all emails within them to archive folders. The key complexity is **hierarchy preservation**: when both a parent and child folder are staged, the archive should preserve that structure.

## Current State

### What Works
- **Email staging/commit (IMAP)**: Individual emails can be staged and committed ✅
- **Email staging/commit (imports)**: Individual emails from mbox/eml can be staged and committed ✅
- **Folder staging UI**: Users can select folders to stage (both IMAP and imports) ✅
- **Folder commit (IMAP basic)**: `/api/commit-folders` endpoint exists but creates full IMAP path, doesn't respect hierarchy logic

### What's Missing
1. **Import folder commit**: No backend support for committing imported mbox folders
2. **Hierarchy logic**: Backend doesn't use `archivePath` to determine folder structure
3. **Streaming support**: Folder commits don't use SSE progress streaming
4. **Integration**: `/api/commit/stream` ignores the `folders` array sent from frontend

## Hierarchy Rules

When committing folders:
- **Child only staged** → `destination/ChildName/` (flat)
- **Parent only staged** → `destination/ParentName/` (only parent's direct emails)
- **Both staged** → `destination/ParentName/ChildName/` (preserve hierarchy)

The frontend computes `archivePath` for each folder based on these rules.

---

## Implementation Chunks

### Chunk 1: Create Archive Folder Helper
**File:** `web/blueprints/api/progress.py`

Add a helper function to create archive folder from `archivePath`:

```python
def _create_archive_folder_from_path(archive_path: str, parent_folder_id: int) -> int:
    """
    Create archive folder(s) from a path string.
    
    Args:
        archive_path: Path like "Parent/Child" or just "Child"
        parent_folder_id: Destination folder ID
        
    Returns:
        ID of the deepest folder created
    """
```

This handles creating nested folders (e.g., "Fan Mail/2024" creates both).

**Test:** Unit test or manual test creating folders from paths.

---

### Chunk 2: Import Folder Email Retrieval Helper  
**File:** `web/blueprints/api/progress.py`

Add helper to get all emails from an imported folder:

```python
def _get_emails_from_import_folder(import_data: dict, folder_path: str) -> list:
    """
    Get all emails belonging to a specific folder in an import.
    
    For mbox: filter by folder path
    For Apple mbox: traverse tree to find folder, get its emails
    
    Returns list of (uid, raw_email_bytes) tuples
    """
```

**Test:** Import an Apple mbox, verify we can retrieve emails for a specific subfolder.

---

### Chunk 3: Add Folder Processing to Stream Commit
**File:** `web/blueprints/api/progress.py`

Modify `stream_commit()` to handle the `folders` array:

```python
# After processing emails...
folders = data.get("folders", [])
if folders:
    # Process folder commits
    for folder_item in folders:
        source_type = folder_item.get("sourceType")
        archive_path = folder_item.get("archivePath")
        dest_folder_id = folder_item.get("destinationFolderId")
        
        if source_type == "import":
            # Handle import folder commit
            pass
        else:
            # Handle IMAP folder commit  
            pass
```

**Test:** Stage a folder, commit, verify SSE events are sent.

---

### Chunk 4: Implement Import Folder Commit
**File:** `web/blueprints/api/progress.py`

Inside the folder processing loop, handle import folders:

1. Get import data from request (need to pass import info from frontend)
2. Create archive folder using `archivePath`
3. Get emails for this folder from the mbox
4. For each email: encrypt, save, insert to DB
5. Yield progress events

**Test:** Import Apple mbox with hierarchy, stage child only, commit, verify flat structure. Stage both parent and child, verify hierarchy preserved.

---

### Chunk 5: Implement IMAP Folder Commit (with archivePath)
**File:** `web/blueprints/api/progress.py`

Update IMAP folder commit to use `archivePath`:

1. Connect to IMAP
2. Create archive folder using `archivePath` (not full IMAP path)
3. Select IMAP folder
4. Fetch and archive all emails
5. Yield progress events

**Test:** Stage IMAP subfolder only, commit, verify it creates just the subfolder name (not full path).

---

### Chunk 6: Frontend - Pass Import Data for Folder Commits
**File:** `web/static/js/views/review.js`

When committing import folders, we need to send enough info for the backend to find the emails:

```javascript
const foldersToCommit = stagedFolders.map(sf => ({
    sourceType: sf.sourceType,
    accountId: sf.accountId,
    importId: sf.importId,
    importPath: sf.importPath,  // Path to mbox file
    folder: sf.folder,          // Folder within the import
    archivePath: sf.archivePath,
    destinationFolderId: sf.destinationFolderId,
}));
```

Also need to store `importPath` when staging folders.

**Test:** Verify commit request includes all necessary data.

---

### Chunk 7: Clear Staged Folders After Commit
**File:** `web/static/js/views/review.js`

After successful folder commit:
1. Clear the staged folder from state
2. Update badge count
3. Re-render review view

**Test:** Commit folders, verify they disappear from staged items.

---

### Chunk 8: Handle Only Direct Emails (Parent Without Children)
**File:** Backend

When staging just a parent folder (not children), we should only archive emails that are directly in that folder, not emails in subfolders.

For IMAP: This is automatic (IMAP folders don't include subfolder emails)
For imports: Need to filter - only emails where `email.folder === folder_path` exactly

**Test:** Stage parent only of Apple mbox with children, verify only parent's direct emails are archived.

---

## Testing Plan

After implementation:

1. **IMAP folder staging**
   - Stage single folder → commits with folder name
   - Stage parent + child → preserves hierarchy
   - Stage child only → flat (just child name)

2. **Import folder staging (Apple mbox)**
   - Stage single folder → commits with folder name
   - Stage parent + child → preserves hierarchy  
   - Stage child only → flat

3. **Import folder staging (flat mbox)**
   - Stage folder → commits all emails to named folder

4. **EML directory**
   - Stage → commits all emails to named folder

5. **Mixed staging**
   - Stage emails + folders together
   - Verify both commit correctly

---

## Files to Modify

| File | Changes |
|------|---------|
| `web/blueprints/api/progress.py` | Add folder commit handling to stream endpoint |
| `web/static/js/components/staging.js` | Store importPath when staging import folders |
| `web/static/js/views/review.js` | Send importPath, clear folders after commit |

## Estimated Effort

- Chunk 1-2: ~30 min (helpers)
- Chunk 3-5: ~1-2 hours (main implementation)
- Chunk 6-7: ~30 min (frontend updates)
- Chunk 8: ~30 min (edge case)
- Testing: ~30 min

Total: ~3-4 hours
