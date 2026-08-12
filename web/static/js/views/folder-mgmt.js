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
import { updateVaultBadge } from './vault.js';
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
    
    // Check if we're currently viewing this folder
    const viewingThisFolder = state.currentView?.type === 'folder' && 
        state.currentView?.id == movingFolderId;
    
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
        
        // Re-select the folder in sidebar if we were viewing it
        if (viewingThisFolder) {
            import('../components/sidebar.js').then(m => {
                if (m.selectFolderInSidebar) {
                    m.selectFolderInSidebar(movingFolderId);
                }
            });
        }
    } catch (error) {
        console.error('Error moving folder:', error);
        showAlert('Error', 'Failed to move folder');
    }
}

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
    
    // Collect folder IDs being deleted (for view clearing check)
    function collectDescendantIds(parentId) {
        const ids = [parentId];
        const children = state.folders.filter(f => f.parent_id == parentId && !f.deleted_at && !f.retention_date);
        children.forEach(c => ids.push(...collectDescendantIds(c.id)));
        return ids;
    }
    
    const descendantCount = countDescendants(folderId);
    const deletedFolderIds = collectDescendantIds(folderId);
    
    // Check if we're currently viewing any of the folders being deleted.
    // Use loose equality (==) via .some() because state.currentView.id can
    // arrive as a string (from sidebar row's dataset.id) while
    // deletedFolderIds holds numbers from state.folders[].id. Array
    // .includes() would silently fail this comparison.
    const currentId = state.currentView?.id;
    const viewingDeletedFolder = state.currentView?.type === 'folder' &&
        deletedFolderIds.some(fid => fid == currentId);
    
    let message = `Move "${folder.name}" to trash?`;
    if (descendantCount > 0) {
        message = `Move "${folder.name}" and ${descendantCount} subfolder${descendantCount > 1 ? 's' : ''} to trash?`;
    }
    
    const confirmed = await showConfirm('Trash Folder', message, { okText: 'Move to Trash' });
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
        
        // Clear main view if we were viewing a deleted folder
        if (viewingDeletedFolder) {
            state.currentView = null;
            state.emails = [];
            state.selectedEmails.clear();
            
            const emailList = document.getElementById('emailList');
            const contextTitle = document.getElementById('contextTitle');
            const contextMeta = document.getElementById('contextMeta');
            const subfoldersBar = document.getElementById('subfoldersBar');
            
            if (contextTitle) contextTitle.textContent = 'Select a folder';
            if (contextMeta) contextMeta.textContent = '';
            if (subfoldersBar) subfoldersBar.style.display = 'none';
            if (emailList) {
                emailList.innerHTML = `
                    <div class="empty-state">
                        <i data-lucide="trash-2" class="empty-icon"></i>
                        <h3>Folder Moved to Trash</h3>
                        <p>Select another folder from the sidebar to view emails.</p>
                    </div>
                `;
                if (typeof lucide !== 'undefined') lucide.createIcons();
            }
        }
    } catch (error) {
        console.error('Error deleting folder:', error);
        showAlert('Error', 'Failed to delete folder');
    }
}

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
export function openMoveToVault(folderId) {
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
    
    // Setting a retention period in years, shared by the preset buttons
    // and the custom input so the two cannot drift apart.
    const applyYears = (years) => {
        const date = new Date();
        date.setFullYear(date.getFullYear() + years);
        vaultDatePicker.setDate(date);
        updateVaultConfirmButton();
    };

    // Set up preset buttons
    document.querySelectorAll('.date-preset-btn').forEach(btn => {
        btn.onclick = () => {
            const customEl = document.getElementById('vaultCustomYears');
            if (customEl) customEl.value = '';
            const errEl = document.getElementById('vaultCustomYearsError');
            if (errEl) errEl.textContent = '';
            applyYears(parseInt(btn.dataset.years));
        };
    });

    // Custom retention period. Statutory retention varies by jurisdiction
    // and profession — 15 years is common for medical records, and some
    // obligations run longer than any preset here — so the presets are
    // shortcuts, not the available range.
    const customEl = document.getElementById('vaultCustomYears');
    const customErrEl = document.getElementById('vaultCustomYearsError');
    if (customEl) {
        customEl.value = '';
        const applyCustom = () => {
            const raw = customEl.value.trim();
            if (raw === '') {
                customErrEl.textContent = '';
                return;
            }
            const years = Number(raw);
            if (!Number.isInteger(years) || years < 1 || years > 100) {
                // Don't touch the picker on bad input: silently leaving a
                // stale date selected while the field shows something else
                // is how a folder gets the wrong deletion date.
                customErrEl.textContent = 'Enter a whole number of years between 1 and 100.';
                return;
            }
            customErrEl.textContent = '';
            applyYears(years);
        };

        customEl.oninput = applyCustom;
        customEl.onkeydown = (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                applyCustom();
            }
        };
    }
    
    // Set up confirm button
    const confirmBtn = document.getElementById('vaultConfirmBtn');
    confirmBtn.disabled = true;
    confirmBtn.onclick = confirmMoveToVault;
    
    document.getElementById('vaultModal').classList.add('active');
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

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
    
    // Check if we're currently viewing this folder
    const viewingThisFolder = state.currentView?.type === 'folder' && 
        state.currentView?.id == vaultFolderId;
    
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
        updateVaultBadge();
        
        // Clear main view if we were viewing the moved folder
        if (viewingThisFolder) {
            state.currentView = null;
            state.emails = [];
            state.selectedEmails.clear();
            
            // Clear the display
            const emailList = document.getElementById('emailList');
            const contextTitle = document.getElementById('contextTitle');
            const contextMeta = document.getElementById('contextMeta');
            const subfoldersBar = document.getElementById('subfoldersBar');
            
            if (contextTitle) contextTitle.textContent = 'Select a folder';
            if (contextMeta) contextMeta.textContent = '';
            if (subfoldersBar) subfoldersBar.style.display = 'none';
            if (emailList) {
                emailList.innerHTML = `
                    <div class="empty-state">
                        <i data-lucide="archive" class="empty-icon"></i>
                        <h3>Folder Moved to Vault</h3>
                        <p>Select another folder from the sidebar to view emails.</p>
                    </div>
                `;
                if (typeof lucide !== 'undefined') lucide.createIcons();
            }
        }
        
    } catch (error) {
        console.error('Error moving folder to vault:', error);
        showAlert('Error', 'Failed to move folder to vault');
    }
}
