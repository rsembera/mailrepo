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
import { renderFolderTree } from '../components/folder-tree.js';

// Module state
let movingFolderId = null;
let moveDestinationId = null;
let moveFolderTreeController = null;
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
        
        refreshSidebarFolders();
    } catch (error) {
        console.error('Error renaming folder:', error);
        showAlert('Error', 'Failed to rename folder');
    }
}
window.renameFolder = renameFolder;

export async function createSubfolder(parentId) {
    const isRoot = parentId === null || parentId === undefined;
    const title = isRoot ? 'New Folder' : 'New Subfolder';
    const name = await showPrompt(title, '', { placeholder: 'e.g., 2025 Correspondence' });
    
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
    
    // Build structure: root option + tree container
    const isCurrentlyRoot = folder.parent_id === null;
    list.innerHTML = `
        <div class="folder-select-item root-option ${isCurrentlyRoot ? 'current-location' : ''}" data-id="root">
            <i data-lucide="home"></i>
            <span>Root level (no parent)</span>
            ${isCurrentlyRoot ? '<span class="current-badge">current</span>' : ''}
        </div>
        <div class="folder-tree-container" id="moveFolderTreeContainer"></div>
    `;
    
    // Attach root option click handler
    const rootOption = list.querySelector('.root-option');
    rootOption.addEventListener('click', () => {
        // Deselect tree selection
        if (moveFolderTreeController) {
            moveFolderTreeController.setSelected(null);
        }
        list.querySelectorAll('.folder-select-item').forEach(i => i.classList.remove('selected'));
        rootOption.classList.add('selected');
        moveDestinationId = 'root';
        document.getElementById('confirmMoveBtn').disabled = false;
    });
    
    // Render folder tree
    const container = document.getElementById('moveFolderTreeContainer');
    moveFolderTreeController = renderFolderTree(container, {
        filter: f => !f.deleted_at && !f.retention_date && f.id != folderId && !descendants.includes(f.id),
        selectable: true,
        selectedId: null,
        showChevrons: true,
        showColorDots: true,
        showAddButtons: false,
        onSelect: (selectedFolderId) => {
            // Deselect root option
            rootOption.classList.remove('selected');
            moveDestinationId = selectedFolderId;
            document.getElementById('confirmMoveBtn').disabled = false;
        }
    });
    
    // Mark current parent in tree
    if (folder.parent_id !== null) {
        const currentParentRow = container.querySelector(`.folder-tree-row[data-id="${folder.parent_id}"]`);
        if (currentParentRow) {
            currentParentRow.classList.add('current-location');
            // Add badge if not present
            if (!currentParentRow.querySelector('.current-badge')) {
                const badge = document.createElement('span');
                badge.className = 'current-badge';
                badge.textContent = 'current';
                currentParentRow.appendChild(badge);
            }
        }
    }
    
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
    
    // Count ALL descendants recursively (excluding retention vault folders)
    function countDescendants(parentId) {
        const children = state.folders.filter(f => f.parent_id == parentId && !f.deleted_at && !f.retention_date);
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
        
        // Mark folder and ALL descendants as deleted (excluding retention vault folders)
        function markDeleted(parentId) {
            const children = state.folders.filter(f => f.parent_id == parentId && !f.retention_date);
            children.forEach(c => {
                c.deleted_at = Date.now() / 1000;
                markDeleted(c.id);
            });
        }
        folder.deleted_at = Date.now() / 1000;
        markDeleted(folderId);
        
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

/**
 * Show color picker for a folder, positioned near the folder row in sidebar.
 * Used by context menu.
 */
export function showColorPickerForFolder(folderId) {
    document.querySelector('.color-picker-popup')?.remove();
    
    const folder = state.folders.find(f => f.id == folderId);
    
    // Find the folder row in the sidebar to position near it
    const folderRow = document.querySelector(`.tree-item-row[data-id="${folderId}"]`);
    let top = 100, left = 100;
    
    if (folderRow) {
        const rect = folderRow.getBoundingClientRect();
        top = rect.bottom + 4;
        left = rect.left + 20;
    }
    
    const popup = document.createElement('div');
    popup.className = 'color-picker-popup';
    popup.style.top = `${top}px`;
    popup.style.left = `${left}px`;
    
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
window.showColorPickerForFolder = showColorPickerForFolder;

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
        
        refreshSidebarFolders();
    } catch (error) {
        console.error('Error updating folder color:', error);
    }
}

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
        refreshSidebarFolders();
        
    } catch (error) {
        console.error('Error moving folder to vault:', error);
        showAlert('Error', 'Failed to move folder to vault');
    }
}
