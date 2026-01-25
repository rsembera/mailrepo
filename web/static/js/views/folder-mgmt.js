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
import { state, loadFolders } from '../state.js';
import { closeModal, showPrompt, showConfirm, showAlert } from '../modals.js';
import { refreshSidebarFolders, buildImapFolderTree, getFolderIcon } from '../components/sidebar.js';
import { updateStagedBadge } from '../components/staging.js';
import { updateTrashBadge } from './trash.js';
import { getMountedImports } from '../components/imports.js';

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
    
    if (contextTitle) contextTitle.textContent = 'Manage Folders';
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
    
    let html = `
        <div class="folder-management-list">
            <div class="folder-management-toolbar">
                <h2>Manage Folders</h2>
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
        headerActions.innerHTML = `
            <button class="btn btn-primary" id="stageFoldersBtn" disabled onclick="stageSelectedFolders()">
                <i data-lucide="archive"></i>
                <span>Stage Selected Folders</span>
            </button>
        `;
        if (typeof lucide !== 'undefined') lucide.createIcons();
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
        headerActions.innerHTML = `
            <button class="btn btn-primary" id="stageFoldersBtn" disabled onclick="stageSelectedFolders()">
                <i data-lucide="archive"></i>
                <span>Stage Selected Folders</span>
            </button>
        `;
        if (typeof lucide !== 'undefined') lucide.createIcons();
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
    let html = `
        <div class="folder-selection-view">
            <div class="folder-selection-toolbar">
                <label class="select-all-folders">
                    <input type="checkbox" id="selectAllFolders" onchange="toggleAllFolders(this.checked)">
                    <span>Select All</span>
                </label>
            </div>
            <div class="folder-selection-list">
                ${renderImportFolderSelectionTree(tree, importId, 0)}
            </div>
        </div>
    `;
    
    emailList.innerHTML = html;
    if (typeof lucide !== 'undefined') lucide.createIcons();
    
    document.querySelectorAll('.folder-selection-chevron').forEach(chevron => {
        chevron.addEventListener('click', (e) => {
            e.stopPropagation();
            const item = chevron.closest('.folder-selection-item');
            const children = item.querySelector('.folder-selection-children');
            if (children) {
                const isExpanded = children.style.display !== 'none';
                children.style.display = isExpanded ? 'none' : 'block';
                chevron.style.transform = isExpanded ? 'rotate(0deg)' : 'rotate(90deg)';
            }
        });
    });
}

function renderImportFolderSelectionTree(nodes, importId, depth) {
    let html = '';
    
    nodes.forEach(node => {
        const hasChildren = node.children && node.children.length > 0;
        const indent = depth * 20;
        const folderPath = node.fullPath;
        
        html += `<div class="folder-selection-item" data-folder="${escapeHtml(folderPath)}">`;
        html += `<div class="folder-selection-row" style="padding-left: ${indent}px">`;
        
        if (hasChildren) {
            html += `<i data-lucide="chevron-right" class="folder-selection-chevron"></i>`;
        } else {
            html += `<span class="chevron-spacer"></span>`;
        }
        
        html += `<label class="folder-checkbox">`;
        html += `<input type="checkbox" data-folder="${escapeHtml(folderPath)}" onchange="handleFolderCheckbox(this)">`;
        html += `</label>`;
        html += `<i data-lucide="folder" class="tree-icon"></i>`;
        html += `<span class="folder-selection-name">${escapeHtml(node.name)}</span>`;
        html += `</div>`;
        
        if (hasChildren) {
            html += `<div class="folder-selection-children" style="display: none;">`;
            html += renderImportFolderSelectionTree(node.children, importId, depth + 1);
            html += `</div>`;
        }
        
        html += `</div>`;
    });
    
    return html;
}

function renderFolderSelectionView(tree, accountId) {
    let html = `
        <div class="folder-selection-view">
            <div class="folder-selection-toolbar">
                <label class="select-all-folders">
                    <input type="checkbox" id="selectAllFolders" onchange="toggleAllFolders(this.checked)">
                    <span>Select All</span>
                </label>
            </div>
            <div class="folder-selection-list">
                ${renderFolderSelectionTree(tree, accountId, 0)}
            </div>
        </div>
    `;
    
    emailList.innerHTML = html;
    if (typeof lucide !== 'undefined') lucide.createIcons();
    
    document.querySelectorAll('.folder-selection-chevron').forEach(chevron => {
        chevron.addEventListener('click', (e) => {
            e.stopPropagation();
            const item = chevron.closest('.folder-selection-item');
            const children = item.querySelector('.folder-selection-children');
            if (children) {
                const isExpanded = children.style.display !== 'none';
                children.style.display = isExpanded ? 'none' : 'block';
                chevron.style.transform = isExpanded ? 'rotate(0deg)' : 'rotate(90deg)';
            }
        });
    });
}

function renderFolderSelectionTree(nodes, accountId, depth) {
    let html = '';
    
    nodes.forEach(node => {
        const hasChildren = node.children && node.children.length > 0;
        const indent = depth * 20;
        const folderPath = node.fullPath;
        
        html += `<div class="folder-selection-item" data-folder="${escapeHtml(folderPath)}">`;
        html += `<div class="folder-selection-row" style="padding-left: ${indent}px">`;
        
        if (hasChildren) {
            html += `<i data-lucide="chevron-right" class="folder-selection-chevron"></i>`;
        } else {
            html += `<span class="chevron-spacer"></span>`;
        }
        
        html += `<label class="folder-checkbox">`;
        html += `<input type="checkbox" data-folder="${escapeHtml(folderPath)}" onchange="handleFolderCheckbox(this)">`;
        html += `</label>`;
        html += `<i data-lucide="${getFolderIcon(node.name)}" class="tree-icon"></i>`;
        html += `<span class="folder-selection-name">${escapeHtml(node.name)}</span>`;
        html += `</div>`;
        
        if (hasChildren) {
            html += `<div class="folder-selection-children" style="display: none;">`;
            html += renderFolderSelectionTree(node.children, accountId, depth + 1);
            html += `</div>`;
        }
        
        html += `</div>`;
    });
    
    return html;
}

export function handleFolderCheckbox(checkbox) {
    const folderPath = checkbox.dataset.folder;
    const isChecked = checkbox.checked;
    
    console.log('handleFolderCheckbox:', { folderPath, isChecked });
    
    if (isChecked) {
        selectedFoldersForStaging.add(folderPath);
        // Don't auto-check children - user might want just the parent's direct emails
    } else {
        selectedFoldersForStaging.delete(folderPath);
        // Uncheck all children when parent is unchecked (cascade down)
        const item = checkbox.closest('.folder-selection-item');
        const childCheckboxes = item.querySelectorAll('.folder-selection-children input[type="checkbox"]');
        childCheckboxes.forEach(child => {
            child.checked = false;
            child.indeterminate = false;
            const childPath = child.dataset.folder;
            selectedFoldersForStaging.delete(childPath);
        });
    }
    
    updateParentCheckboxes();
    updateSelectAllCheckbox();
    updateStageFoldersButton();
    
    console.log('After update, selectedFoldersForStaging:', Array.from(selectedFoldersForStaging));
}
window.handleFolderCheckbox = handleFolderCheckbox;

function updateParentCheckboxes() {
    // Only update visual state of parent checkboxes, NOT the staging set.
    // The staging set should only contain folders explicitly clicked by the user.
    // Process from deepest to shallowest so parent states cascade correctly.
    const items = Array.from(document.querySelectorAll('.folder-selection-item')).reverse();
    
    items.forEach(item => {
        const children = item.querySelector('.folder-selection-children');
        if (!children) return;
        
        const checkbox = item.querySelector(':scope > .folder-selection-row input[type="checkbox"]');
        if (!checkbox) return;
        
        const childCheckboxes = children.querySelectorAll('input[type="checkbox"]');
        const checkedCount = Array.from(childCheckboxes).filter(c => c.checked).length;
        
        // Only update visual state - don't modify selectedFoldersForStaging
        if (checkedCount === 0) {
            checkbox.checked = false;
            checkbox.indeterminate = false;
        } else if (checkedCount === childCheckboxes.length) {
            // All children checked - show parent as checked visually
            // but DON'T add to staging set (user must explicitly click parent)
            checkbox.checked = true;
            checkbox.indeterminate = false;
        } else {
            // Some children checked - show indeterminate
            checkbox.checked = false;
            checkbox.indeterminate = true;
        }
    });
}

function updateSelectAllCheckbox() {
    const selectAll = document.getElementById('selectAllFolders');
    if (!selectAll) return;
    
    const allCheckboxes = document.querySelectorAll('.folder-selection-list input[type="checkbox"]');
    const checkedCount = Array.from(allCheckboxes).filter(c => c.checked).length;
    
    if (checkedCount === 0) {
        selectAll.checked = false;
        selectAll.indeterminate = false;
    } else if (checkedCount === allCheckboxes.length) {
        selectAll.checked = true;
        selectAll.indeterminate = false;
    } else {
        selectAll.checked = false;
        selectAll.indeterminate = true;
    }
}

export function toggleAllFolders(checked) {
    document.querySelectorAll('.folder-selection-list input[type="checkbox"]').forEach(cb => {
        cb.checked = checked;
        cb.indeterminate = false;
        const folderPath = cb.dataset.folder;
        if (checked) {
            selectedFoldersForStaging.add(folderPath);
        } else {
            selectedFoldersForStaging.delete(folderPath);
        }
    });
    updateStageFoldersButton();
}
window.toggleAllFolders = toggleAllFolders;

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
        pendingFolderStaging = {
            sourceType: 'import',
            importId: currentFolderSelectionImportId,
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
