/**
 * MailRepo - Folder Management Views
 * 
 * Handles:
 * - Folder management view (rename, move, delete, color)
 * - Folder selection view (bulk IMAP folder staging)
 * - Move folder modal
 * - Color picker
 */

import { escapeHtml } from '../utils.js';
import { state, loadFolders, setSelectedFoldersGetter, setSelectedFoldersClearer } from '../state.js';
import { closeModal, showPrompt, showConfirm, showAlert } from '../modals.js';
import { refreshSidebarFolders, buildImapFolderTree, getFolderIcon } from '../components/sidebar.js';
import { updateStagedBadge } from '../components/staging.js';
import { getMountedImports } from '../components/imports.js';
import { updateTrashBadge } from './trash.js';

/**
 * Escape a string for use in an onclick attribute.
 * Handles quotes and backslashes.
 */
function escapeForOnclick(str) {
    return str.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
}

// Module state
let movingFolderId = null;
let moveDestinationId = null;

// For folder selection view (bulk staging)
let selectedFoldersForStaging = new Set();
let currentFolderSelectionAccountId = null;
let currentFolderSelectionImportId = null;
let folderSelectionTree = [];

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
    
    // Register getter and clearer for selected folders (for navigation guard)
    setSelectedFoldersGetter(() => selectedFoldersForStaging.size);
    setSelectedFoldersClearer(() => selectedFoldersForStaging.clear());
}

/**
 * Show the folder management view.
 */
export async function showFolderManagementView() {
    const sidebar = document.getElementById('sidebar');
    const toolbar = document.querySelector('.content-toolbar');
    const headerActions = document.querySelector('.header-actions');
    
    sidebar.style.display = 'none';
    if (toolbar) toolbar.style.display = 'none';
    if (headerActions) headerActions.style.display = 'none';
    
    if (contextTitle) contextTitle.textContent = 'Manage Archive';
    if (contextMeta) contextMeta.textContent = '';
    
    await loadFolders();
    
    if (state.folders.length === 0) {
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
    const topLevelFolders = state.folders.filter(f => !f.parent_id && !f.deleted_at);
    const totalFolders = state.folders.filter(f => !f.deleted_at).length;
    
    let html = `
        <div class="folder-management-list">
            <div class="folder-management-toolbar">
                <h2>${totalFolders} Folder${totalFolders !== 1 ? 's' : ''}</h2>
                <button class="btn btn-primary" onclick="openNewFolderModal(false)">
                    <i data-lucide="plus"></i>
                    New Folder
                </button>
            </div>
            <div class="folder-management-header">
                <span>Folder</span>
                <span>Color</span>
                <span>Actions</span>
            </div>
    `;
    
    function renderFolderWithChildren(folder, depth) {
        html += renderFolderManagementItem(folder, depth);
        const children = state.folders.filter(f => f.parent_id == folder.id && !f.deleted_at);
        children.forEach(child => renderFolderWithChildren(child, depth + 1));
    }
    
    topLevelFolders.forEach(folder => renderFolderWithChildren(folder, 0));
    
    html += `
        </div>
    `;
    
    emailList.innerHTML = html;
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function renderFolderManagementItem(folder, depth = 0) {
    const colorDot = folder.color ? 
        `<span class="color-dot" style="background: ${folder.color}"></span>` : 
        `<span class="color-dot color-dot-none"></span>`;
    
    return `
        <div class="folder-management-item" data-id="${folder.id}" style="padding-left: ${20 + depth * 24}px">
            <div class="folder-management-name">
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
    
    const newName = await showPrompt('Rename folder:', folder.name);
    if (!newName || newName.trim() === '' || newName === folder.name) return;
    
    try {
        const response = await fetch(`/api/folders/${folderId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: newName.trim() }),
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
    const name = await showPrompt('New subfolder name:', '');
    if (!name || name.trim() === '') return;
    
    try {
        const response = await fetch('/api/folders', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name.trim(), parent_id: parentId }),
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
    
    const children = state.folders.filter(f => f.parent_id == folderId && !f.deleted_at);
    
    let message = `Move "${folder.name}" to trash?`;
    if (children.length > 0) {
        message = `Move "${folder.name}" and ${children.length} subfolder${children.length > 1 ? 's' : ''} to trash?`;
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
        
        folder.deleted_at = Date.now() / 1000;
        children.forEach(c => c.deleted_at = Date.now() / 1000);
        
        showFolderManagementView();
        updateTrashBadge();
        updateSidebarFoldersAfterDelete(folderId);
    } catch (error) {
        console.error('Error deleting folder:', error);
        showAlert('Error', 'Failed to delete folder');
    }
}
window.deleteFolder = deleteFolder;

export async function exportFolder(folderId) {
    const folder = state.folders.find(f => f.id == folderId);
    if (!folder) return;
    
    try {
        const response = await fetch(`/api/folders/${folderId}/export`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ include_subfolders: true }),
        });
        
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
        console.error('Error exporting folder:', error);
        showAlert('Error', 'Failed to export folder');
    }
}
window.exportFolder = exportFolder;

function updateSidebarFoldersAfterDelete(folderId) {
    const archiveSection = document.getElementById('archiveSection');
    if (!archiveSection) return;
    
    const folderEl = archiveSection.querySelector(`.tree-item-row[data-id="${folderId}"]`);
    if (folderEl) folderEl.closest('.tree-item')?.remove();
    
    const countEl = document.getElementById('folderCount');
    if (countEl) {
        const visibleFolders = state.folders.filter(f => !f.deleted_at);
        countEl.textContent = visibleFolders.length;
    }
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
 * Show folder selection view for bulk IMAP folder staging.
 */
export async function showFolderSelectionView(accountId) {
    currentFolderSelectionAccountId = accountId;
    selectedFoldersForStaging.clear();
    
    // Track this view so it can be restored
    state.currentView = { type: 'accountFolders', id: accountId };
    
    const accountRow = document.querySelector(`.tree-item-row[data-type="account"][data-id="${accountId}"]`);
    const accountName = accountRow?.querySelector('.tree-label')?.textContent || 'Account';
    
    if (contextTitle) contextTitle.textContent = accountName;
    if (contextMeta) contextMeta.textContent = 'Select folders to archive';
    
    const toolbar = document.querySelector('.content-toolbar');
    if (toolbar) toolbar.style.display = 'none';
    
    const headerActions = document.querySelector('.header-actions');
    if (headerActions) {
        headerActions.innerHTML = ''; // No bulk action button needed - each folder has its own Stage button
    }
    
    emailList.innerHTML = '<div class="loading-indicator">Loading folders...</div>';
    
    try {
        const response = await fetch(`/api/accounts/${accountId}/folders`);
        if (!response.ok) {
            const data = await response.json();
            emailList.innerHTML = `<div class="empty-state"><p>Error: ${data.error || 'Failed to load folders'}</p></div>`;
            return;
        }
        
        const data = await response.json();
        folderSelectionTree = buildImapFolderTree(data.folders || []);
        renderFolderSelectionView(folderSelectionTree, accountId);
    } catch (error) {
        console.error('Error loading folders:', error);
        emailList.innerHTML = '<div class="empty-state"><p>Error loading folders</p></div>';
    }
}

/**
 * Show folder selection view for bulk import folder staging.
 */
export function showImportFolderSelectionView(importId) {
    currentFolderSelectionImportId = importId;
    currentFolderSelectionAccountId = null;
    selectedFoldersForStaging.clear();
    
    // Track this view so it can be restored
    state.currentView = { type: 'importFolders', id: importId };
    
    const imports = getMountedImports();
    const imp = imports.find(i => i.id === importId);
    
    if (!imp) {
        emailList.innerHTML = '<div class="empty-state"><p>Import not found</p></div>';
        return;
    }
    
    if (contextTitle) contextTitle.textContent = imp.name;
    if (contextMeta) contextMeta.textContent = 'Select folders to archive';
    
    const toolbar = document.querySelector('.content-toolbar');
    if (toolbar) toolbar.style.display = 'none';
    
    const headerActions = document.querySelector('.header-actions');
    if (headerActions) {
        headerActions.innerHTML = ''; // No bulk action button needed - each folder has its own Stage button
    }
    
    // Build folder tree for import
    if (imp.type === 'eml') {
        // Single email - just show one item to stage
        folderSelectionTree = [{ name: imp.name, fullPath: '', children: [], emailCount: imp.emails.length }];
    } else if (imp.folders && imp.folders.length > 0) {
        // Has folder structure
        folderSelectionTree = imp.folders;
    } else {
        // Flat list of emails - show as single root
        folderSelectionTree = [{ name: imp.name, fullPath: '', children: [], emailCount: imp.emails.length }];
    }
    
    renderImportFolderSelectionView(folderSelectionTree, importId);
}

function renderImportFolderSelectionView(tree, importId) {
    const selectedCount = selectedFoldersForStaging.size;
    
    let html = `
        <div class="folder-management-list">
            <div class="folder-management-toolbar">
                <h2>Select Folders to Archive</h2>
                <div class="toolbar-actions">
                    <button class="btn btn-secondary" onclick="selectAllFolders()">
                        <i data-lucide="check-square"></i>
                        Select All
                    </button>
                    <button class="btn btn-secondary" onclick="clearAllSelected()" ${selectedCount === 0 ? 'disabled' : ''}>
                        <i data-lucide="x"></i>
                        Clear Selected
                    </button>
                    <button class="btn btn-primary" id="stageSelectedBtn" onclick="stageSelectedFoldersFromSelection()" ${selectedCount === 0 ? 'disabled' : ''}>
                        <i data-lucide="archive"></i>
                        Stage${selectedCount > 0 ? ` (${selectedCount})` : ''}
                    </button>
                </div>
            </div>
            <div class="folder-management-header folder-selection-header">
                <span>Folder</span>
                <span>Actions</span>
            </div>
            ${renderImportFolderSelectionTree(tree, importId, 0)}
        </div>
    `;
    
    emailList.innerHTML = html;
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function renderImportFolderSelectionTree(nodes, importId, depth) {
    let html = '';
    
    nodes.forEach(node => {
        const hasChildren = node.children && node.children.length > 0;
        const folderPath = node.fullPath;
        
        // Check if this folder is already staged
        const isStaged = state.stagedFolders.some(
            sf => sf.sourceType === 'import' && sf.importId == importId && sf.folder === folderPath
        );
        
        // Check if this folder is selected (pending)
        const isSelected = selectedFoldersForStaging.has(folderPath);
        
        let rowClass = 'folder-management-item folder-selection-item';
        if (isStaged) rowClass += ' staged';
        if (isSelected) rowClass += ' selected';
        
        const escapedPath = escapeForOnclick(folderPath);
        let actionsHtml = '';
        
        if (isStaged) {
            actionsHtml = `
                <button class="btn btn-sm btn-icon" disabled title="Already staged">
                    <i data-lucide="circle"></i>
                </button>
                <button class="btn btn-sm btn-icon" onclick="clearFolder('${escapedPath}')" title="Unstage">
                    <i data-lucide="x"></i>
                </button>
            `;
        } else if (isSelected) {
            actionsHtml = `
                <button class="btn btn-sm btn-icon btn-selected" disabled title="Selected">
                    <i data-lucide="check"></i>
                </button>
                <button class="btn btn-sm btn-icon" onclick="clearFolder('${escapedPath}')" title="Deselect">
                    <i data-lucide="x"></i>
                </button>
            `;
        } else {
            actionsHtml = `
                <button class="btn btn-sm btn-icon" onclick="selectFolder('${escapedPath}')" title="Select">
                    <i data-lucide="circle"></i>
                </button>
                <button class="btn btn-sm btn-icon" disabled title="Not selected">
                    <i data-lucide="x"></i>
                </button>
            `;
        }
        
        html += `
            <div class="${rowClass}" data-folder="${escapeHtml(folderPath)}">
                <div class="folder-management-name" style="padding-left: ${depth * 24}px">
                    <i data-lucide="folder" class="folder-icon"></i>
                    <span class="folder-label">${escapeHtml(node.name)}</span>
                </div>
                <div class="folder-management-actions">
                    ${actionsHtml}
                </div>
            </div>
        `;
        
        // Recursively render children (always expanded)
        if (hasChildren) {
            html += renderImportFolderSelectionTree(node.children, importId, depth + 1);
        }
    });
    
    return html;
}

function renderFolderSelectionView(tree, accountId) {
    const selectedCount = selectedFoldersForStaging.size;
    
    let html = `
        <div class="folder-management-list">
            <div class="folder-management-toolbar">
                <h2>Select Folders to Archive</h2>
                <div class="toolbar-actions">
                    <button class="btn btn-secondary" onclick="selectAllFolders()">
                        <i data-lucide="check-square"></i>
                        Select All
                    </button>
                    <button class="btn btn-secondary" onclick="clearAllSelected()" ${selectedCount === 0 ? 'disabled' : ''}>
                        <i data-lucide="x"></i>
                        Clear Selected
                    </button>
                    <button class="btn btn-primary" id="stageSelectedBtn" onclick="stageSelectedFoldersFromSelection()" ${selectedCount === 0 ? 'disabled' : ''}>
                        <i data-lucide="archive"></i>
                        Stage${selectedCount > 0 ? ` (${selectedCount})` : ''}
                    </button>
                </div>
            </div>
            <div class="folder-management-header folder-selection-header">
                <span>Folder</span>
                <span>Actions</span>
            </div>
            ${renderFolderSelectionTree(tree, accountId, 0)}
        </div>
    `;
    
    emailList.innerHTML = html;
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function renderFolderSelectionTree(nodes, accountId, depth) {
    let html = '';
    
    nodes.forEach(node => {
        const hasChildren = node.children && node.children.length > 0;
        const folderPath = node.fullPath;
        
        // Check if this folder is already staged
        const isStaged = state.stagedFolders.some(
            sf => sf.sourceType === 'account' && sf.accountId == accountId && sf.folder === folderPath
        );
        
        // Check if this folder is selected (pending)
        const isSelected = selectedFoldersForStaging.has(folderPath);
        
        let rowClass = 'folder-management-item folder-selection-item';
        if (isStaged) rowClass += ' staged';
        if (isSelected) rowClass += ' selected';
        
        let actionsHtml = '';
        const canClear = isStaged || isSelected;
        const escapedPath = escapeForOnclick(folderPath);
        
        if (isStaged) {
            // Staged: select button disabled, clear active
            actionsHtml = `
                <button class="btn btn-sm btn-icon" disabled title="Already staged">
                    <i data-lucide="circle"></i>
                </button>
                <button class="btn btn-sm btn-icon" onclick="clearFolder('${escapedPath}')" title="Unstage">
                    <i data-lucide="x"></i>
                </button>
            `;
        } else if (isSelected) {
            // Selected: show checkmark, clear active
            actionsHtml = `
                <button class="btn btn-sm btn-icon btn-selected" disabled title="Selected">
                    <i data-lucide="check"></i>
                </button>
                <button class="btn btn-sm btn-icon" onclick="clearFolder('${escapedPath}')" title="Deselect">
                    <i data-lucide="x"></i>
                </button>
            `;
        } else {
            // Default: select active, clear disabled
            actionsHtml = `
                <button class="btn btn-sm btn-icon" onclick="selectFolder('${escapedPath}')" title="Select">
                    <i data-lucide="circle"></i>
                </button>
                <button class="btn btn-sm btn-icon" disabled title="Not selected">
                    <i data-lucide="x"></i>
                </button>
            `;
        }
        
        html += `
            <div class="${rowClass}" data-folder="${escapeHtml(folderPath)}">
                <div class="folder-management-name" style="padding-left: ${depth * 24}px">
                    <i data-lucide="${getFolderIcon(node.name)}" class="folder-icon"></i>
                    <span class="folder-label">${escapeHtml(node.name)}</span>
                </div>
                <div class="folder-management-actions">
                    ${actionsHtml}
                </div>
            </div>
        `;
        
        // Recursively render children (always expanded)
        if (hasChildren) {
            html += renderFolderSelectionTree(node.children, accountId, depth + 1);
        }
    });
    
    return html;
}

/**
 * Refresh the current folder selection view (after staging/selecting).
 * Preserves scroll position and selection state.
 */
export function refreshFolderSelectionView() {
    // Save scroll position
    const scrollTop = emailList?.scrollTop || 0;
    
    // Re-render without clearing selection (don't call full show functions)
    if (currentFolderSelectionAccountId && folderSelectionTree) {
        renderFolderSelectionView(folderSelectionTree, currentFolderSelectionAccountId);
    } else if (currentFolderSelectionImportId && folderSelectionTree) {
        renderImportFolderSelectionView(folderSelectionTree, currentFolderSelectionImportId);
    }
    
    // Restore scroll position after render
    requestAnimationFrame(() => {
        if (emailList) emailList.scrollTop = scrollTop;
    });
}

function updateStageFoldersButton() {
    const btn = document.getElementById('stageFoldersBtn');
    if (btn) {
        btn.disabled = selectedFoldersForStaging.size === 0;
        const count = selectedFoldersForStaging.size;
        btn.querySelector('span').textContent = count > 0 
            ? `Stage ${count} Folder${count > 1 ? 's' : ''}` 
            : 'Stage Selected Folders';
    }
}

// Track folders being staged in current modal session
let pendingFolderStaging = null;

/**
 * Find all descendant folder paths from a tree node.
 */
function getDescendantPaths(nodes, parentPath) {
    let paths = [];
    for (const node of nodes) {
        // Check if this node is a descendant of parentPath
        if (node.fullPath && node.fullPath.startsWith(parentPath + '/')) {
            paths.push(node.fullPath);
        }
        // Also check children recursively
        if (node.children && node.children.length > 0) {
            paths = paths.concat(getDescendantPaths(node.children, parentPath));
        }
    }
    return paths;
}

/**
 * Find all paths in tree that start with given prefix (descendants).
 */
function findAllDescendants(tree, folderPath) {
    let descendants = [];
    
    function traverse(nodes) {
        for (const node of nodes) {
            // If this node's path starts with folderPath + '/', it's a descendant
            if (node.fullPath && node.fullPath.startsWith(folderPath + '/')) {
                descendants.push(node.fullPath);
            }
            if (node.children && node.children.length > 0) {
                traverse(node.children);
            }
        }
    }
    
    traverse(tree);
    return descendants;
}

/**
 * Select a folder and all its children (archive the whole branch).
 */
export function selectFolder(folderPath) {
    selectedFoldersForStaging.add(folderPath);
    
    // Also select all descendants
    const descendants = findAllDescendants(folderSelectionTree, folderPath);
    descendants.forEach(path => selectedFoldersForStaging.add(path));
    
    refreshFolderSelectionView();
}
window.selectFolder = selectFolder;

/**
 * Clear a folder and all its children - deselects if selected, unstages if staged.
 */
export function clearFolder(folderPath) {
    // Get all descendants to also clear
    const descendants = findAllDescendants(folderSelectionTree, folderPath);
    const allPathsToClear = [folderPath, ...descendants];
    
    // Check if any are selected (pending) - clear them
    let clearedSelected = false;
    allPathsToClear.forEach(path => {
        if (selectedFoldersForStaging.has(path)) {
            selectedFoldersForStaging.delete(path);
            clearedSelected = true;
        }
    });
    
    if (clearedSelected) {
        refreshFolderSelectionView();
        return;
    }
    
    // Check if staged - find and remove all matching
    let clearedStaged = false;
    allPathsToClear.forEach(path => {
        const index = state.stagedFolders.findIndex(sf => {
            if (currentFolderSelectionAccountId) {
                return sf.sourceType === 'account' && sf.accountId == currentFolderSelectionAccountId && sf.folder === path;
            } else if (currentFolderSelectionImportId) {
                return sf.sourceType === 'import' && sf.importId == currentFolderSelectionImportId && sf.folder === path;
            }
            return false;
        });
        
        if (index !== -1) {
            state.stagedFolders.splice(index, 1);
            clearedStaged = true;
        }
    });
    
    if (clearedStaged) {
        sessionStorage.setItem('stagedFolders', JSON.stringify(state.stagedFolders));
        updateStagedBadge();
        refreshFolderSelectionView();
    }
}
window.clearFolder = clearFolder;

/**
 * Select all unstaged folders.
 */
export function selectAllFolders() {
    const allFolderPaths = collectAllFolderPaths(folderSelectionTree);
    
    // Add all unstaged folders to selection
    allFolderPaths.forEach(path => {
        const isStaged = state.stagedFolders.some(sf => {
            if (currentFolderSelectionAccountId) {
                return sf.sourceType === 'account' && sf.accountId == currentFolderSelectionAccountId && sf.folder === path;
            } else if (currentFolderSelectionImportId) {
                return sf.sourceType === 'import' && sf.importId == currentFolderSelectionImportId && sf.folder === path;
            }
            return false;
        });
        
        if (!isStaged) {
            selectedFoldersForStaging.add(path);
        }
    });
    
    refreshFolderSelectionView();
}
window.selectAllFolders = selectAllFolders;

/**
 * Clear all selected folders.
 */
export function clearAllSelected() {
    selectedFoldersForStaging.clear();
    refreshFolderSelectionView();
}
window.clearAllSelected = clearAllSelected;

/**
 * Stage all currently selected folders.
 */
export function stageSelectedFoldersFromSelection() {
    if (selectedFoldersForStaging.size === 0) return;
    
    const folderPaths = Array.from(selectedFoldersForStaging);
    
    if (currentFolderSelectionAccountId) {
        pendingFolderStaging = {
            sourceType: 'account',
            accountId: currentFolderSelectionAccountId,
            folders: folderPaths
        };
    } else if (currentFolderSelectionImportId) {
        const imports = getMountedImports();
        const imp = imports.find(i => i.id === currentFolderSelectionImportId);
        
        pendingFolderStaging = {
            sourceType: 'import',
            importId: currentFolderSelectionImportId,
            importPath: imp?.path || '',
            importType: imp?.type || 'mbox',
            folders: folderPaths
        };
    } else {
        console.error('No account or import selected for folder staging');
        return;
    }
    
    // Clear selection - they'll become staged after destination is chosen
    selectedFoldersForStaging.clear();
    
    openStageFoldersModal();
}
window.stageSelectedFoldersFromSelection = stageSelectedFoldersFromSelection;

/**
 * Stage a single folder (called from per-row Stage button).
 */
export function stageSingleFolder(folderPath) {
    // Store pending folder - will be added to stagedFolders after destination is chosen
    if (currentFolderSelectionAccountId) {
        pendingFolderStaging = {
            sourceType: 'account',
            accountId: currentFolderSelectionAccountId,
            folders: [folderPath]
        };
    } else if (currentFolderSelectionImportId) {
        const imports = getMountedImports();
        const imp = imports.find(i => i.id === currentFolderSelectionImportId);
        
        pendingFolderStaging = {
            sourceType: 'import',
            importId: currentFolderSelectionImportId,
            importPath: imp?.path || '',
            importType: imp?.type || 'mbox',
            folders: [folderPath]
        };
    } else {
        console.error('No account or import selected for folder staging');
        return;
    }
    
    openStageFoldersModal();
}
window.stageSingleFolder = stageSingleFolder;

/**
 * Stage all folders in the current view.
 */
export function stageAllFolders() {
    // Collect all folder paths from the current tree
    const allFolderPaths = collectAllFolderPaths(folderSelectionTree);
    
    // Filter out already-staged folders
    const unstagedPaths = allFolderPaths.filter(path => {
        if (currentFolderSelectionAccountId) {
            return !state.stagedFolders.some(
                sf => sf.sourceType === 'account' && sf.accountId == currentFolderSelectionAccountId && sf.folder === path
            );
        } else if (currentFolderSelectionImportId) {
            return !state.stagedFolders.some(
                sf => sf.sourceType === 'import' && sf.importId == currentFolderSelectionImportId && sf.folder === path
            );
        }
        return true;
    });
    
    if (unstagedPaths.length === 0) {
        showAlert('All Staged', 'All folders are already staged.');
        return;
    }
    
    // Store pending folders
    if (currentFolderSelectionAccountId) {
        pendingFolderStaging = {
            sourceType: 'account',
            accountId: currentFolderSelectionAccountId,
            folders: unstagedPaths
        };
    } else if (currentFolderSelectionImportId) {
        const imports = getMountedImports();
        const imp = imports.find(i => i.id === currentFolderSelectionImportId);
        
        pendingFolderStaging = {
            sourceType: 'import',
            importId: currentFolderSelectionImportId,
            importPath: imp?.path || '',
            importType: imp?.type || 'mbox',
            folders: unstagedPaths
        };
    }
    
    openStageFoldersModal();
}
window.stageAllFolders = stageAllFolders;

/**
 * Collect all folder paths from a tree structure.
 */
function collectAllFolderPaths(nodes, paths = []) {
    nodes.forEach(node => {
        paths.push(node.fullPath);
        if (node.children && node.children.length > 0) {
            collectAllFolderPaths(node.children, paths);
        }
    });
    return paths;
}

/**
 * Unstage a single folder.
 */
export function unstageSingleFolder(folderPath) {
    // Find and remove the staged folder
    const index = state.stagedFolders.findIndex(sf => {
        if (currentFolderSelectionAccountId) {
            return sf.sourceType === 'account' && sf.accountId == currentFolderSelectionAccountId && sf.folder === folderPath;
        } else if (currentFolderSelectionImportId) {
            return sf.sourceType === 'import' && sf.importId == currentFolderSelectionImportId && sf.folder === folderPath;
        }
        return false;
    });
    
    if (index !== -1) {
        state.stagedFolders.splice(index, 1);
        sessionStorage.setItem('stagedFolders', JSON.stringify(state.stagedFolders));
        
        // Update badge and refresh view
        updateStagedBadge();
        refreshFolderSelectionView();
    }
}
window.unstageSingleFolder = unstageSingleFolder;

export function stageSelectedFolders() {
    if (selectedFoldersForStaging.size === 0) return;
    
    // Store pending folders - will be added to stagedFolders after destination is chosen
    // Supports both IMAP accounts and imports
    if (currentFolderSelectionAccountId) {
        pendingFolderStaging = {
            sourceType: 'account',
            accountId: currentFolderSelectionAccountId,
            folders: Array.from(selectedFoldersForStaging)
        };
    } else if (currentFolderSelectionImportId) {
        // Get import data to include path and type
        const imports = getMountedImports();
        const imp = imports.find(i => i.id === currentFolderSelectionImportId);
        
        pendingFolderStaging = {
            sourceType: 'import',
            importId: currentFolderSelectionImportId,
            importPath: imp?.path || '',
            importType: imp?.type || 'mbox',
            folders: Array.from(selectedFoldersForStaging)
        };
    } else {
        console.error('No account or import selected for folder staging');
        return;
    }
    
    openStageFoldersModal();
}
window.stageSelectedFolders = stageSelectedFolders;

export function getPendingFolderStaging() {
    return pendingFolderStaging;
}

export function clearPendingFolderStaging() {
    pendingFolderStaging = null;
}

function openStageFoldersModal() {
    const modal = document.getElementById('stageModal');
    if (!modal || !pendingFolderStaging) return;
    
    const count = pendingFolderStaging.folders.length;
    
    // Set modal for folder staging
    const title = document.getElementById('stageModalTitle');
    if (title) {
        title.textContent = `Stage ${count} Folder${count > 1 ? 's' : ''} to...`;
    }
    
    const desc = document.getElementById('stageModalDesc');
    if (desc) {
        desc.innerHTML = `Select destination for <strong>${count}</strong> folder${count > 1 ? 's' : ''} (folder structure will be preserved)`;
    }
    
    // Import renderFolderSelectTree dynamically to avoid circular dependency
    import('../components/staging.js').then(staging => {
        staging.renderFolderSelectTree();
    });
    
    document.getElementById('confirmStageBtn').disabled = true;
    modal.dataset.stagingMode = 'folders';
    modal.classList.add('active');
}
