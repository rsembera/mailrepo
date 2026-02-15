/**
 * MailRepo - Move Email Modal
 * 
 * Handles moving archived emails to different folders.
 */

import { escapeHtml } from '../utils.js';
import { state, loadFolders } from '../state.js';
import { closeModal, showAlert } from '../modals.js';
import { renderEmailList } from './email-list.js';

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
    
    // Get current folder (to exclude from selection but show in tree for children access)
    const currentFolderId = state.currentView?.id;
    
    // Build tree of non-deleted, non-vault folders
    const folders = state.folders.filter(f => !f.deleted_at && !f.retention_date);
    const topLevel = folders.filter(f => !f.parent_id);
    
    if (folders.length === 0) {
        listEl.innerHTML = '<p class="empty-state">No other folders available</p>';
        return;
    }
    
    let html = '';
    
    function renderFolder(folder, depth = 0) {
        const indent = depth * 20;
        const children = folders.filter(f => f.parent_id == folder.id);
        const isCurrent = folder.id == currentFolderId;
        
        html += `
            <div class="folder-select-item ${isCurrent ? 'disabled' : ''}" data-id="${folder.id}" ${isCurrent ? '' : `onclick="selectMoveEmailFolder(${folder.id})"`} style="padding-left: ${indent + 12}px">
                <i data-lucide="folder" class="folder-icon"></i>
                <span>${escapeHtml(folder.name)}${isCurrent ? ' (current)' : ''}</span>
            </div>
        `;
        
        children.sort((a, b) => a.name.localeCompare(b.name));
        children.forEach(child => renderFolder(child, depth + 1));
    }
    
    topLevel.sort((a, b) => a.name.localeCompare(b.name));
    topLevel.forEach(folder => renderFolder(folder));
    
    listEl.innerHTML = html;
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

/**
 * Select a folder in the move email modal.
 */
function selectMoveEmailFolder(folderId) {
    selectedFolderId = folderId;
    
    // Update visual selection
    document.querySelectorAll('#moveEmailFolderList .folder-select-item').forEach(el => {
        el.classList.toggle('selected', el.dataset.id == folderId);
    });
    
    document.getElementById('confirmMoveEmailBtn').disabled = false;
}
window.selectMoveEmailFolder = selectMoveEmailFolder;

/**
 * Confirm and execute the email move.
 */
async function confirmMoveEmail() {
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
window.confirmMoveEmail = confirmMoveEmail;
