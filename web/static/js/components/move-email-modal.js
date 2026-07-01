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
    const emailIds = window.pendingMoveEmailIds || [];
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
    const emailIds = window.pendingMoveEmailIds;
    if (!emailIds || emailIds.length === 0 || !selectedFolderId) return;
    
    try {
        // Move all emails
        for (const emailId of emailIds) {
            const response = await fetch(`/api/messages/${emailId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ folder_id: selectedFolderId })
            });
            
            if (!response.ok) {
                console.error(`Failed to move email ${emailId}`);
            }
        }
        
        // Remove from current view and re-render
        const movedIds = new Set(emailIds);
        state.emails = state.emails.filter(e => !movedIds.has(e.id));
        
        // Clear archived selection if any were selected
        const { clearArchivedEmailSelection } = await import('./email-list.js');
        clearArchivedEmailSelection();
        
        renderEmailList();
        
        closeModal('moveEmailModal');
        window.pendingMoveEmailIds = null;
    } catch (error) {
        console.error('Error moving emails:', error);
        showAlert('Error', 'Failed to move some emails');
    }
}
