/**
 * MailRepo - Move Email Modal
 * 
 * Handles moving archived emails to different folders.
 */

import { state, loadFolders } from '../state.js';
import { closeModal, showAlert } from '../modals.js';
import { renderEmailList } from './email-list.js';
import { renderFolderTree } from './folder-tree.js';

let selectedFolderId = null;

// Emails queued for the move, set by email-list.js before it opens this
// modal. Module-local with an exported setter rather than
// window.pendingMoveEmailIds: the frontend's stated model is no
// cross-module window globals, and this was the last one left.
let pendingMoveEmailIds = [];

export function setPendingMoveEmailIds(ids) {
    pendingMoveEmailIds = ids || [];
}

/**
 * Render the folder tree for the move email modal.
 */
export async function renderMoveEmailFolderTree() {
    await loadFolders();
    
    const listEl = document.getElementById('moveEmailFolderList');
    if (!listEl) return;
    
    selectedFolderId = null;
    document.getElementById('confirmMoveEmailBtn').disabled = true;
    
    // Update modal title based on count
    const emailIds = pendingMoveEmailIds || [];
    const titleEl = document.querySelector('#moveEmailModal h2');
    if (titleEl) {
        if (emailIds.length > 1) {
            titleEl.textContent = `Move ${emailIds.length} Emails`;
        } else {
            titleEl.textContent = 'Move Email';
        }
    }
    
    // Can't move emails into the folder they're already in — but its
    // subfolders are valid targets, so keep it visible/expandable.
    const currentFolderId = state.currentView?.id;

    renderFolderTree(listEl, {
        selectable: true,
        selectedId: null,
        isSelectable: (folder) => folder.id != currentFolderId,
        renderActions: (folder) =>
            folder.id == currentFolderId
                ? '<span class="folder-tree-current-tag">(current)</span>'
                : '',
        onSelect: (folderId) => {
            selectedFolderId = folderId;
            document.getElementById('confirmMoveEmailBtn').disabled = false;
        },
    });
}

/**
 * Confirm and execute the email move.
 */
export async function confirmMoveEmail() {
    const emailIds = pendingMoveEmailIds;
    if (!emailIds || emailIds.length === 0 || !selectedFolderId) return;

    // Track which moves actually succeed so the view only drops those —
    // an email whose move failed must stay visible in its current folder.
    const movedIds = new Set();
    let failedCount = 0;

    for (const emailId of emailIds) {
        try {
            const response = await fetch(`/api/messages/${emailId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ folder_id: selectedFolderId })
            });

            if (response.ok) {
                movedIds.add(emailId);
            } else {
                failedCount++;
                const errText = await response.text().catch(() => '');
                console.error(
                    `Move email ${emailId} -> folder ${selectedFolderId} failed: ` +
                    `HTTP ${response.status} ${errText}`
                );
            }
        } catch (error) {
            failedCount++;
            console.error(
                `Move email ${emailId} -> folder ${selectedFolderId} failed:`, error
            );
        }
    }

    // Remove only the successfully moved emails from the current view
    if (movedIds.size > 0) {
        state.emails = state.emails.filter(e => !movedIds.has(e.id));
        const { clearArchivedEmailSelection } = await import('./email-list.js');
        clearArchivedEmailSelection();
        renderEmailList();
    }

    closeModal('moveEmailModal');
    pendingMoveEmailIds = [];

    if (failedCount > 0) {
        showAlert(
            'Move Incomplete',
            `${failedCount} of ${emailIds.length} email${emailIds.length === 1 ? '' : 's'} ` +
            `could not be moved. See the browser console for details.`
        );
    }
}
