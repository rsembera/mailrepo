/**
 * MailRepo - Folder Management Views
 * 
 * Handles:
 * - Folder management view (rename, move, delete, color)
 * - Folder selection view (bulk IMAP folder staging)
 * - Move folder modal
 * - Color picker
 */

import { escapeHtml, escapeForOnclick } from '../utils.js';
import { state, loadFolders, setSelectedFoldersGetter, setSelectedFoldersClearer } from '../state.js';
import { closeModal, showPrompt, showConfirm, showAlert } from '../modals.js';
import { refreshSidebarFolders, buildImapFolderTree, getFolderIcon } from '../components/sidebar.js';
import { updateStagedBadge } from '../components/staging.js';
import { getMountedImports } from '../components/imports.js';
import { updateTrashBadge } from './trash.js';
import { DatePicker } from '../components/date-picker.js';

// Module state
let movingFolderId = null;
let moveDestinationId = null;
let archiveFilter = '';
let vaultFolderId = null;
let vaultDatePicker = null;

// DOM references
let contextTitle = null;
let contextMeta = null;
let emailList = null;

// Folder colors
const FOLDER_COLORS = [
    { name: 'Gray', value: null },
    { name: 'Red', value: '#e53935' },
    { name: 'Orange', value: '#fb8c00' },
    { name: 'Yellow', value: '#fdd835' },
    { name: 'Green', value: '#43a047' },
    { name: 'Teal', value: '#00897b' },
    { name: 'Blue', value: '#1e88e5' },
    { name: 'Purple', value: '#8e24aa' },
    { name: 'Pink', value: '#d81b60' },
];

/**
 * Initialize folder management views.
 */
export function initFolderMgmt(config) {
    contextTitle = config.contextTitle;
    contextMeta = config.contextMeta;
    emailList = config.emailList;
}

/**
 * Filter folders by name (keeps parent chain visible).
 * Excludes deleted folders and folders in the retention vault.
 */
function filterFolders(folders, query) {
    // Helper to check if folder is available (not deleted, not in vault)
    const isAvailable = f => !f.deleted_at && !f.retention_date;
    
    if (!query) return folders.filter(isAvailable);
    
    const lowerQuery = query.toLowerCase();
    const matchingIds = new Set();
    
    // Find all folders that match
    folders.forEach(f => {
        if (isAvailable(f) && f.name.toLowerCase().includes(lowerQuery)) {
            matchingIds.add(f.id);
            // Also include all ancestors
            let parentId = f.parent_id;
            while (parentId) {
                matchingIds.add(parentId);
                const parent = folders.find(p => p.id === parentId);
                parentId = parent?.parent_id;
            }
        }
    });
    
    return folders.filter(f => isAvailable(f) && matchingIds.has(f.id));
}

/**
 * Show the folder management view.
 */
export async function showFolderManagementView() {
    archiveFilter = '';
    
    const sidebar = document.getElementById('sidebar');
    const toolbar = document.querySelector('.content-toolbar');
    const headerActions = document.querySelector('.header-actions');
    const subfoldersBar = document.getElementById('subfoldersBar');
    
    sidebar.style.display = 'none';
    if (toolbar) toolbar.style.display = 'none';
    if (headerActions) headerActions.style.display = 'none';
    if (subfoldersBar) subfoldersBar.style.display = 'none';
    
    if (contextTitle) contextTitle.textContent = 'Manage Archive';
    if (contextMeta) contextMeta.textContent = '';
    
    await loadFolders();
    
    // Check for active (non-deleted) folders
    const activeFolders = state.folders.filter(f => !f.deleted_at);
    
    if (activeFolders.length === 0) {
        emailList.innerHTML = `
            <div class="empty-state">
                <i data-lucide="folder" class="empty-icon"></i>
                <h3>No Folders</h3>
                <p>Create your first folder to start archiving emails.</p>
                <button class="btn btn-primary" onclick="openNewFolderModal(false)">
                    <i data-lucide="plus"></i> New Folder
                </button>
            </div>
        `;
    } else {
        renderFolderManagementList();
    }
    
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function renderFolderManagementList() {
    const totalFolders = state.folders.filter(f => !f.deleted_at).length;
    const filteredFolders = filterFolders(state.folders, archiveFilter);
    const filteredCount = filteredFolders.length;
    const topLevelFolders = filteredFolders.filter(f => !f.parent_id);
    topLevelFolders.sort((a, b) => a.name.localeCompare(b.name));
    
    // Update context meta
    if (contextMeta) {
        if (archiveFilter && filteredCount !== totalFolders) {
            contextMeta.textContent = `${filteredCount} of ${totalFolders} folders`;
        } else {
            contextMeta.textContent = `${totalFolders} folder${totalFolders !== 1 ? 's' : ''}`;
        }
    }
    
    let html = `
        <div class="folder-management-list">
            <div class="folder-management-toolbar">
                <div class="archive-filter">
                    <i data-lucide="search" class="search-icon"></i>
                    <input type="text" 
                           id="archiveFilterInput" 
                           placeholder="Filter folders..." 
                           value="${escapeHtml(archiveFilter)}"
                           oninput="handleArchiveFilter(this.value)">
                    ${archiveFilter ? '<button class="search-clear" onclick="clearArchiveFilter()"><i data-lucide="x"></i></button>' : ''}
                </div>
                <button class="btn btn-primary" onclick="openNewFolderModal(false)">
                    <i data-lucide="plus"></i>
                    New Folder
                </button>
            </div>
    `;
    
    if (filteredCount === 0 && archiveFilter) {
        html += `
            <div class="empty-state" style="padding: var(--space-xl);">
                <p>No folders match "${escapeHtml(archiveFilter)}"</p>
            </div>
        `;
    } else {
        html += `
            <div class="folder-management-header">
                <span>Folder</span>
                <span>Color</span>
                <span>Actions</span>
            </div>
        `;
        
        // ancestry is an array of booleans - true if that ancestor is the last child at its level
        function renderFolderWithChildren(folder, depth, ancestry = []) {
            const siblings = depth === 0 
                ? topLevelFolders 
                : filteredFolders.filter(f => f.parent_id == folder.parent_id);
            const isLast = siblings[siblings.length - 1].id === folder.id;
            
            html += renderFolderManagementItem(folder, depth, ancestry, isLast);
            
            const children = filteredFolders.filter(f => f.parent_id == folder.id);
            children.sort((a, b) => a.name.localeCompare(b.name));
            children.forEach(child => renderFolderWithChildren(child, depth + 1, [...ancestry, isLast]));
        }
        
        topLevelFolders.forEach(folder => renderFolderWithChildren(folder, 0, []));
    }
    
    html += `</div>`;
    
    emailList.innerHTML = html;
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function renderFolderManagementItem(folder, depth = 0, ancestry = [], isLast = false) {
    const colorDot = folder.color ? 
        `<span class="color-dot" style="background: ${folder.color}"></span>` : 
        `<span class="color-dot color-dot-none"></span>`;
    
    // Build tree lines
    let treePrefix = '';
    if (depth > 0) {
        // Draw vertical lines for ancestors that aren't last at their level
        for (let i = 0; i < ancestry.length; i++) {
            if (ancestry[i]) {
                treePrefix += '<span class="tree-spacer"></span>';
            } else {
                treePrefix += '<span class="tree-line-vertical"></span>';
            }
        }
        // Draw branch for this item
        treePrefix += isLast 
            ? '<span class="tree-line-last"></span>' 
            : '<span class="tree-line-branch"></span>';
    }
    
    return `
        <div class="folder-management-item" data-id="${folder.id}">
            <div class="folder-management-name">
                ${treePrefix}
                ${colorDot}
                <i data-lucide="folder" class="folder-icon"></i>
                <span class="folder-label" data-id="${folder.id}">${escapeHtml(folder.name)}</span>
            </div>
            <div class="folder-management-color">
                <button class="color-picker-btn" onclick="openColorPicker(${folder.id}, event)" title="Change color">
                    ${folder.color ? `<span class="color-swatch" style="background: ${folder.color}"></span>` : '<i data-lucide="palette"></i>'}
                </button>
            </div>
            <div class="folder-management-actions">
                <button class="btn btn-sm btn-icon" onclick="renameFolder(${folder.id})" title="Rename">
                    <i data-lucide="pencil"></i>
                </button>
                <button class="btn btn-sm btn-icon" onclick="openMoveFolder(${folder.id})" title="Move">
                    <i data-lucide="folder-input"></i>
                </button>
                <button class="btn btn-sm btn-icon" onclick="createSubfolder(${folder.id})" title="Add subfolder">
                    <i data-lucide="folder-plus"></i>
                </button>
                <button class="btn btn-sm btn-icon" onclick="openMoveToVault(${folder.id})" title="Move to Retention Vault">
                    <i data-lucide="archive"></i>
                </button>
                <button class="btn btn-sm btn-icon" onclick="exportFolder(${folder.id})" title="Export as ZIP">
                    <i data-lucide="download"></i>
                </button>
                <button class="btn btn-sm btn-icon btn-danger-subtle" onclick="deleteFolder(${folder.id})" title="Delete">
                    <i data-lucide="trash-2"></i>
                </button>
            </div>
        </div>
    `;
}

export async function renameFolder(folderId) {
    const folder = state.folders.find(f => f.id == folderId);
    if (!folder) return;
    
    const newName = await showPrompt('Rename Folder', folder.name);
    
    // Validate
    if (newName === null) return; // User cancelled
    
    const trimmedName = newName.trim();
    if (!trimmedName) {
        showAlert('Invalid Name', 'Folder name cannot be empty.');
        return;
    }
    if (trimmedName === folder.name) return; // No change
    
    // Check for invalid characters/names
    if (/^[.\s]+$/.test(trimmedName) || /[\/\\]/.test(trimmedName)) {
        showAlert('Invalid Name', 'Folder name contains invalid characters.');
        return;
    }
    
    try {
        const response = await fetch(`/api/folders/${folderId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: trimmedName }),
        });
        
        if (!response.ok) {
            const data = await response.json();
            showAlert('Error', data.error || 'Failed to rename folder');
            return;
        }
        
        folder.name = newName.trim();
        showFolderManagementView();
        refreshSidebarFolders();
    } catch (error) {
        console.error('Error renaming folder:', error);
        showAlert('Error', 'Failed to rename folder');
    }
}
window.renameFolder = renameFolder;

export async function createSubfolder(parentId) {
    const name = await showPrompt('New Subfolder Name', '', { placeholder: 'e.g., 2025 Correspondence' });
    
    // Validate folder name
    if (name === null) return; // User cancelled
    
    const trimmedName = name.trim();
    if (!trimmedName) {
        showAlert('Invalid Name', 'Folder name cannot be empty.');
        return;
    }
    
    // Check for invalid characters/names
    if (/^[.\s]+$/.test(trimmedName) || /[\/\\]/.test(trimmedName)) {
        showAlert('Invalid Name', 'Folder name contains invalid characters.');
        return;
    }
    
    try {
        const response = await fetch('/api/folders', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: trimmedName, parent_id: parentId }),
        });
        
        if (!response.ok) {
            const data = await response.json();
            showAlert('Error', data.error || 'Failed to create folder');
            return;
        }
        
        const data = await response.json();
        state.folders.push(data.folder);
        showFolderManagementView();
        refreshSidebarFolders();
    } catch (error) {
        console.error('Error creating subfolder:', error);
        showAlert('Error', 'Failed to create subfolder');
    }
}
window.createSubfolder = createSubfolder;

export function openMoveFolder(folderId) {
    const folder = state.folders.find(f => f.id == folderId);
    if (!folder) return;
    
    movingFolderId = folderId;
    moveDestinationId = null;
    
    document.getElementById('moveFolderName').textContent = folder.name;
    document.getElementById('confirmMoveBtn').disabled = true;
    
    const descendants = getDescendantIds(folderId);
    const list = document.getElementById('moveFolderList');
    
    let html = `
        <div class="folder-select-item" data-id="root">
            <i data-lucide="home"></i>
            <span>Root level (no parent)</span>
        </div>
    `;
    
    const validFolders = state.folders.filter(f => 
        !f.deleted_at && f.id != folderId && !descendants.includes(f.id)
    );
    
    function renderFolderOption(f, depth) {
        const indent = depth * 16;
        const isCurrentParent = (folder.parent_id === f.id) || (folder.parent_id === null && f.id === 'root');
        html += `
            <div class="folder-select-item ${isCurrentParent ? 'current-location' : ''}" data-id="${f.id}" style="padding-left: ${12 + indent}px">
                <i data-lucide="folder"></i>
                <span>${escapeHtml(f.name)}</span>
                ${isCurrentParent ? '<span class="current-badge">current</span>' : ''}
            </div>
        `;
        const children = validFolders.filter(c => c.parent_id == f.id);
        children.forEach(child => renderFolderOption(child, depth + 1));
    }
    
    validFolders.filter(f => !f.parent_id).forEach(f => renderFolderOption(f, 0));
    list.innerHTML = html;
    
    if (folder.parent_id === null) {
        list.querySelector('[data-id="root"]')?.classList.add('current-location');
        const rootItem = list.querySelector('[data-id="root"]');
        if (rootItem && !rootItem.querySelector('.current-badge')) {
            rootItem.innerHTML += '<span class="current-badge">current</span>';
        }
    }
    
    list.querySelectorAll('.folder-select-item').forEach(item => {
        item.addEventListener('click', () => {
            list.querySelectorAll('.folder-select-item').forEach(i => i.classList.remove('selected'));
            item.classList.add('selected');
            moveDestinationId = item.dataset.id;
            document.getElementById('confirmMoveBtn').disabled = false;
        });
    });
    
    document.getElementById('moveFolderModal').classList.add('active');
    if (typeof lucide !== 'undefined') lucide.createIcons();
}
window.openMoveFolder = openMoveFolder;

function getDescendantIds(folderId) {
    const descendants = [];
    function collect(parentId) {
        state.folders.filter(f => f.parent_id == parentId && !f.deleted_at).forEach(child => {
            descendants.push(child.id);
            collect(child.id);
        });
    }
    collect(folderId);
    return descendants;
}

export async function confirmMoveFolder() {
    if (!movingFolderId || moveDestinationId === null) return;
    
    const newParentId = moveDestinationId === 'root' ? null : parseInt(moveDestinationId);
    const folder = state.folders.find(f => f.id == movingFolderId);
    
    if (folder.parent_id === newParentId) {
        closeModal('moveFolderModal');
        return;
    }
    
    try {
        const response = await fetch(`/api/folders/${movingFolderId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ parent_id: newParentId }),
        });
        
        if (!response.ok) {
            const data = await response.json();
            showAlert('Error', data.error || 'Failed to move folder');
            return;
        }
        
        folder.parent_id = newParentId;
        closeModal('moveFolderModal');
        showFolderManagementView();
        refreshSidebarFolders();
    } catch (error) {
        console.error('Error moving folder:', error);
        showAlert('Error', 'Failed to move folder');
    }
}
window.confirmMoveFolder = confirmMoveFolder;

export async function deleteFolder(folderId) {
    const folder = state.folders.find(f => f.id == folderId);
    if (!folder) return;
    
    // Count ALL descendants recursively
    function countDescendants(parentId) {
        const children = state.folders.filter(f => f.parent_id == parentId && !f.deleted_at);
        let count = children.length;
        children.forEach(c => count += countDescendants(c.id));
        return count;
    }
    
    const descendantCount = countDescendants(folderId);
    
    let message = `Move "${folder.name}" to trash?`;
    if (descendantCount > 0) {
        message = `Move "${folder.name}" and ${descendantCount} subfolder${descendantCount > 1 ? 's' : ''} to trash?`;
    }
    
    const confirmed = await showConfirm('Delete Folder', message, { okText: 'Move to Trash' });
    if (!confirmed) return;
    
    try {
        const response = await fetch(`/api/folders/${folderId}`, { method: 'DELETE' });
        
        if (!response.ok) {
            const data = await response.json();
            showAlert('Error', data.error || 'Failed to delete folder');
            return;
        }
        
        // Mark folder and ALL descendants as deleted
        function markDeleted(parentId) {
            const children = state.folders.filter(f => f.parent_id == parentId);
            children.forEach(c => {
                c.deleted_at = Date.now() / 1000;
                markDeleted(c.id);
            });
        }
        folder.deleted_at = Date.now() / 1000;
        markDeleted(folderId);
        
        showFolderManagementView();
        updateTrashBadge();
        updateSidebarFoldersAfterDelete();
    } catch (error) {
        console.error('Error deleting folder:', error);
        showAlert('Error', 'Failed to delete folder');
    }
}
window.deleteFolder = deleteFolder;

export async function exportFolder(folderId) {
    const folder = state.folders.find(f => f.id == folderId);
    if (!folder) return;
    
    // Show progress modal
    const modal = document.getElementById('exportProgressModal');
    const content = document.getElementById('exportProgressContent');
    if (modal && content) {
        content.innerHTML = `
            <div class="progress-display">
                <div class="progress-status">
                    <i data-lucide="loader" class="progress-icon spin"></i>
                    <span class="progress-message">Preparing export...</span>
                </div>
                <div class="progress-detail">
                    <span class="progress-subject">Decrypting and packaging "${folder.name}"</span>
                </div>
            </div>
        `;
        if (typeof lucide !== 'undefined') lucide.createIcons();
        modal.classList.add('active');
    }
    
    try {
        const response = await fetch(`/api/folders/${folderId}/export`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ include_subfolders: true }),
        });
        
        // Hide progress modal
        if (modal) modal.classList.remove('active');
        
        if (!response.ok) {
            const data = await response.json();
            showAlert('Error', data.error || 'Failed to export folder');
            return;
        }
        
        // Get filename from Content-Disposition header
        const contentDisposition = response.headers.get('Content-Disposition');
        let filename = `${folder.name}_export.zip`;
        if (contentDisposition) {
            const match = contentDisposition.match(/filename="?([^";\n]+)"?/);
            if (match) filename = match[1];
        }
        
        // Download the file
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    } catch (error) {
        // Hide progress modal on error
        if (modal) modal.classList.remove('active');
        console.error('Error exporting folder:', error);
        showAlert('Error', 'Failed to export folder');
    }
}
window.exportFolder = exportFolder;

function updateSidebarFoldersAfterDelete() {
    refreshSidebarFolders();
}

export function openColorPicker(folderId, event) {
    event.stopPropagation();
    document.querySelector('.color-picker-popup')?.remove();
    
    const folder = state.folders.find(f => f.id == folderId);
    const btn = event.currentTarget;
    const rect = btn.getBoundingClientRect();
    
    const popup = document.createElement('div');
    popup.className = 'color-picker-popup';
    popup.style.top = `${rect.bottom + 4}px`;
    popup.style.left = `${rect.left}px`;
    
    popup.innerHTML = FOLDER_COLORS.map(c => `
        <button class="color-option ${folder?.color === c.value ? 'selected' : ''}" 
                data-color="${c.value || ''}" title="${c.name}">
            ${c.value ? `<span style="background: ${c.value}"></span>` : '<i data-lucide="x"></i>'}
        </button>
    `).join('');
    
    document.body.appendChild(popup);
    if (typeof lucide !== 'undefined') lucide.createIcons();
    
    popup.addEventListener('click', async (e) => {
        const option = e.target.closest('.color-option');
        if (!option) return;
        const color = option.dataset.color || null;
        await setFolderColor(folderId, color);
        popup.remove();
    });
    
    setTimeout(() => {
        document.addEventListener('click', function closePopup(e) {
            if (!popup.contains(e.target)) {
                popup.remove();
                document.removeEventListener('click', closePopup);
            }
        });
    }, 10);
}
window.openColorPicker = openColorPicker;

async function setFolderColor(folderId, color) {
    try {
        const response = await fetch(`/api/folders/${folderId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ color: color }),
        });
        
        if (!response.ok) {
            const data = await response.json();
            showAlert('Error', data.error || 'Failed to update color');
            return;
        }
        
        const folder = state.folders.find(f => f.id == folderId);
        if (folder) folder.color = color;
        
        showFolderManagementView();
        refreshSidebarFolders();
    } catch (error) {
        console.error('Error updating folder color:', error);
    }
}

/**
 * Handle archive filter input.
 */
function handleArchiveFilter(query) {
    archiveFilter = query;
    renderFolderManagementList();
    
    // Refocus the input and restore cursor position
    const input = document.getElementById('archiveFilterInput');
    if (input) {
        input.focus();
        input.setSelectionRange(query.length, query.length);
    }
}
window.handleArchiveFilter = handleArchiveFilter;

/**
 * Clear archive filter.
 */
function clearArchiveFilter() {
    archiveFilter = '';
    renderFolderManagementList();
    const input = document.getElementById('archiveFilterInput');
    if (input) input.focus();
}
window.clearArchiveFilter = clearArchiveFilter;

// ============================================================
// RETENTION VAULT FUNCTIONS
// ============================================================

/**
 * Open the Move to Vault modal for a folder.
 */
function openMoveToVault(folderId) {
    vaultFolderId = folderId;
    
    // Initialize date picker if not already done
    const container = document.getElementById('vaultDatePicker');
    container.innerHTML = ''; // Clear any previous picker
    
    vaultDatePicker = new DatePicker(container, {
        initialDate: null,
        onSelect: (date) => {
            updateVaultConfirmButton();
        }
    });
    
    // Set up preset buttons
    document.querySelectorAll('.date-preset-btn').forEach(btn => {
        btn.onclick = () => {
            const years = parseInt(btn.dataset.years);
            const date = new Date();
            date.setFullYear(date.getFullYear() + years);
            vaultDatePicker.setDate(date);
            updateVaultConfirmButton();
        };
    });
    
    // Set up confirm button
    const confirmBtn = document.getElementById('vaultConfirmBtn');
    confirmBtn.disabled = true;
    confirmBtn.onclick = confirmMoveToVault;
    
    document.getElementById('vaultModal').classList.add('active');
    if (typeof lucide !== 'undefined') lucide.createIcons();
}
window.openMoveToVault = openMoveToVault;

/**
 * Update the vault confirm button state.
 */
function updateVaultConfirmButton() {
    const confirmBtn = document.getElementById('vaultConfirmBtn');
    confirmBtn.disabled = !vaultDatePicker.getDate();
}

/**
 * Confirm moving folder to vault.
 */
async function confirmMoveToVault() {
    const date = vaultDatePicker.getDate();
    if (!date || !vaultFolderId) return;
    
    const timestamp = Math.floor(date.getTime() / 1000);
    
    try {
        const response = await fetch(`/api/folders/${vaultFolderId}/vault`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ retention_date: timestamp }),
        });
        
        if (!response.ok) {
            const data = await response.json();
            showAlert('Error', data.error || 'Failed to move folder to vault');
            return;
        }
        
        closeModal('vaultModal');
        
        // Refresh the folder list
        await loadFolders();
        showFolderManagementView();
        refreshSidebarFolders();
        
    } catch (error) {
        console.error('Error moving folder to vault:', error);
        showAlert('Error', 'Failed to move folder to vault');
    }
}
