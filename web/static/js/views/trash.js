/**
 * MailRepo - Trash View
 * 
 * Handles:
 * - Trash view display
 * - Folder restore
 * - Permanent deletion
 * - Empty trash
 */

import { escapeHtml, formatDate } from '../utils.js';
import { state, loadFolders } from '../state.js';
import { showConfirm, showAlert } from '../modals.js';
import { updateSidebarFolders } from '../components/sidebar.js';

// DOM references
let contextTitle = null;
let contextMeta = null;
let emailList = null;

/**
 * Get folders that should appear in Trash view.
 * Shows trashed folders that are either:
 * - Top-level (no parent), OR
 * - Their parent is NOT trashed (child was deleted independently)
 */
function getVisibleTrashedFolders() {
    return state.folders.filter(f => {
        if (!f.deleted_at) return false;
        if (!f.parent_id) return true;
        const parent = state.folders.find(p => p.id == f.parent_id);
        return !parent || !parent.deleted_at;
    });
}

/**
 * Initialize trash view.
 */
export function initTrashView(config) {
    contextTitle = config.contextTitle;
    contextMeta = config.contextMeta;
    emailList = config.emailList;
}

/**
 * Show the trash view.
 */
export async function showTrashView() {
    const sidebar = document.getElementById('sidebar');
    const toolbar = document.querySelector('.content-toolbar');
    const headerActions = document.querySelector('.header-actions');
    
    sidebar.style.display = 'none';
    if (toolbar) toolbar.style.display = 'none';
    if (headerActions) headerActions.style.display = 'none';
    
    if (contextTitle) contextTitle.textContent = 'Trash';
    if (contextMeta) contextMeta.textContent = '';
    
    await loadFolders();
    
    const trashedFolders = getVisibleTrashedFolders()
        .sort((a, b) => b.deleted_at - a.deleted_at);
    
    if (trashedFolders.length === 0) {
        emailList.innerHTML = `
            <div class="empty-state">
                <i data-lucide="trash-2" class="empty-icon"></i>
                <h3>Trash is Empty</h3>
                <p>Items you delete will appear here.</p>
            </div>
        `;
    } else {
        renderTrashList(trashedFolders);
    }
    
    updateTrashBadge();
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function renderTrashList(trashedFolders) {
    let html = `
        <div class="trash-management-list">
            <div class="trash-management-toolbar">
                <h2>${trashedFolders.length} Deleted Folder${trashedFolders.length !== 1 ? 's' : ''}</h2>
                <button class="btn btn-danger" onclick="emptyTrash()">
                    <i data-lucide="trash-2"></i>
                    Empty Trash
                </button>
            </div>
            <div class="trash-management-header">
                <span>Folder</span>
                <span>Deleted</span>
                <span>Actions</span>
            </div>
    `;
    
    trashedFolders.forEach(folder => {
        html += renderTrashItem(folder);
    });
    
    html += `
        </div>
    `;
    
    emailList.innerHTML = html;
}

function renderTrashItem(folder) {
    const deletedDate = new Date(folder.deleted_at * 1000);
    const children = state.folders.filter(f => f.parent_id == folder.id);
    
    return `
        <div class="trash-management-item" data-id="${folder.id}">
            <div class="trash-management-name">
                <i data-lucide="folder" class="folder-icon"></i>
                <span class="folder-label">${escapeHtml(folder.name)}</span>
                ${children.length > 0 ? `<span class="subfolder-count">(+${children.length})</span>` : ''}
            </div>
            <div class="trash-management-date">
                ${formatDate(deletedDate)}
            </div>
            <div class="trash-management-actions">
                <button class="btn btn-sm btn-icon" onclick="restoreFolder(${folder.id})" title="Restore">
                    <i data-lucide="undo-2"></i>
                </button>
                <button class="btn btn-sm btn-icon btn-danger-subtle" onclick="permanentlyDeleteFolder(${folder.id})" title="Delete permanently">
                    <i data-lucide="x"></i>
                </button>
            </div>
        </div>
    `;
}

export async function restoreFolder(folderId) {
    try {
        const response = await fetch(`/api/folders/${folderId}/restore`, {
            method: 'POST',
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            showAlert('Error', data.error || 'Failed to restore folder');
            return;
        }
        
        const folder = state.folders.find(f => f.id == folderId);
        if (folder) {
            folder.deleted_at = null;
            if (data.folder && data.folder.name) {
                folder.name = data.folder.name;
            }
            state.folders.filter(f => f.parent_id == folderId).forEach(c => c.deleted_at = null);
        }
        
        showTrashView();
        if (folder) updateSidebarFolders(folder);
        
        if (data.folder && data.folder.renamed) {
            showAlert('Folder Restored', `Folder restored as "${data.folder.name}" to avoid a naming conflict.`);
        }
    } catch (error) {
        console.error('Error restoring folder:', error);
        showAlert('Error', 'Failed to restore folder');
    }
}
window.restoreFolder = restoreFolder;

export async function permanentlyDeleteFolder(folderId) {
    const folder = state.folders.find(f => f.id == folderId);
    if (!folder) return;
    
    const children = state.folders.filter(f => f.parent_id == folderId);
    
    let message = `Permanently delete "${folder.name}"? This cannot be undone.`;
    if (children.length > 0) {
        message = `Permanently delete "${folder.name}" and ${children.length} subfolder${children.length > 1 ? 's' : ''}? This cannot be undone.`;
    }
    
    const confirmed = await showConfirm('Permanent Delete', message, { okText: 'Delete Forever', danger: true });
    if (!confirmed) return;
    
    try {
        const response = await fetch(`/api/folders/${folderId}/permanent`, {
            method: 'DELETE',
        });
        
        if (!response.ok) {
            const data = await response.json();
            showAlert('Error', data.error || 'Failed to delete folder');
            return;
        }
        
        state.folders = state.folders.filter(f => f.id != folderId && f.parent_id != folderId);
        showTrashView();
    } catch (error) {
        console.error('Error deleting folder:', error);
        showAlert('Error', 'Failed to delete folder');
    }
}
window.permanentlyDeleteFolder = permanentlyDeleteFolder;

export async function emptyTrash() {
    const trashedFolders = getVisibleTrashedFolders();
    if (trashedFolders.length === 0) return;
    
    const message = `Permanently delete ${trashedFolders.length} folder${trashedFolders.length > 1 ? 's' : ''} and all their contents? This cannot be undone.`;
    
    const confirmed = await showConfirm('Empty Trash', message, { okText: 'Empty Trash', danger: true });
    if (!confirmed) return;
    
    try {
        const response = await fetch('/api/trash/empty', {
            method: 'POST',
        });
        
        if (!response.ok) {
            const data = await response.json();
            showAlert('Error', data.error || 'Failed to empty trash');
            return;
        }
        
        state.folders = state.folders.filter(f => !f.deleted_at);
        showTrashView();
    } catch (error) {
        console.error('Error emptying trash:', error);
        showAlert('Error', 'Failed to empty trash');
    }
}
window.emptyTrash = emptyTrash;

export function updateTrashBadge() {
    const badge = document.getElementById('trashBadge');
    if (!badge) return;
    
    const trashedCount = getVisibleTrashedFolders().length;
    badge.textContent = trashedCount;
    badge.classList.toggle('hidden', trashedCount === 0);
}
