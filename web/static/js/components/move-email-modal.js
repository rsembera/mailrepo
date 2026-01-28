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
    
    // Get current folder (to exclude from list)
    const currentFolderId = state.currentView?.id;
    
    // Build tree of non-deleted folders
    const folders = state.folders.filter(f => !f.deleted_at && f.id != currentFolderId);
    const topLevel = folders.filter(f => !f.parent_id);
    
    if (folders.length === 0) {
        listEl.innerHTML = '<p class="empty-state">No other folders available</p>';
        return;
    }
    
    let html = '';
    
    function renderFolder(folder, depth = 0) {
        const indent = depth * 20;
        const children = folders.filter(f => f.parent_id == folder.id);
        
        html += `
            <div class="folder-select-item" data-id="${folder.id}" onclick="selectMoveEmailFolder(${folder.id})" style="padding-left: ${indent + 12}px">
                <i data-lucide="folder" class="folder-icon"></i>
                <span>${escapeHtml(folder.name)}</span>
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
    const emailId = window.pendingMoveEmailId;
    if (!emailId || !selectedFolderId) return;
    
    try {
        const response = await fetch(`/api/messages/${emailId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ folder_id: selectedFolderId })
        });
        
        if (!response.ok) {
            const data = await response.json();
            showAlert('Error', data.error || 'Failed to move email');
            return;
        }
        
        // Remove from current view and re-render
        state.emails = state.emails.filter(e => e.id != emailId);
        renderEmailList();
        
        closeModal('moveEmailModal');
        window.pendingMoveEmailId = null;
    } catch (error) {
        console.error('Error moving email:', error);
        showAlert('Error', 'Failed to move email');
    }
}
window.confirmMoveEmail = confirmMoveEmail;
