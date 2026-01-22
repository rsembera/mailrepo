/**
 * MailRepo - Main Application JavaScript
 * 
 * Handles:
 * - Three-pane navigation
 * - Account/folder tree interactions
 * - Email list rendering
 * - Staging workflow
 */

// ============================================
// IMPORTS
// ============================================

import { escapeHtml, extractName, formatDate, debounce } from './utils.js';
import { state, loadFolders } from './state.js';
import { closeModal, showPrompt, showConfirm, showAlert, initModalListeners } from './modals.js';
import { renderFolderTree } from './components/folder-tree.js';
import { initEmailList, renderEmailList, toggleEmailSelection, handleSelectAll, updateSelectAllState } from './components/email-list.js';
import { initSidebar, toggleSection, handleTreeItemClick, updateSidebarFolders, refreshSidebarFolders, loadAccountLabels, buildImapFolderTree, getFolderIcon } from './components/sidebar.js';
import { initMailView, selectView, loadAccountEmails, loadFolderEmails, openEmailViewer, closeEmailViewer, showLoading, showError } from './views/mail.js';

// ============================================
// DOM ELEMENTS
// ============================================

const elements = {
    // Sidebar
    accountsSection: document.getElementById('accountsSection'),
    archiveSection: document.getElementById('archiveSection'),
    sidebarFilter: document.getElementById('sidebarFilter'),
    
    // Main content
    contextTitle: document.getElementById('contextTitle'),
    contextMeta: document.getElementById('contextMeta'),
    emailList: document.getElementById('emailList'),
    selectAll: document.getElementById('selectAll'),
    searchInput: document.getElementById('searchInput'),
    
    // Buttons
    stageBtn: document.getElementById('stageBtn'),
    reviewBtn: document.getElementById('reviewBtn'),
    stagedBadge: document.getElementById('stagedBadge'),
    newFolderBtn: document.getElementById('newFolderBtn'),
    addFolderBtn: document.getElementById('addFolderBtn'),
    
    // Modals
    stageModal: document.getElementById('stageModal'),
    newFolderModal: document.getElementById('newFolderModal'),
};

// ============================================
// INITIALIZATION
// ============================================

document.addEventListener('DOMContentLoaded', () => {
    // Initialize email list component
    initEmailList({
        emailList: elements.emailList,
        selectAll: elements.selectAll,
        onSelectionChange: updateButtonStates,
    });
    
    // Initialize mail view component
    initMailView({
        contextTitle: elements.contextTitle,
        contextMeta: elements.contextMeta,
        emailList: elements.emailList,
        onButtonStatesUpdate: updateButtonStates,
    });
    
    // Initialize sidebar component
    initSidebar({
        onFolderSelect: (id) => selectView({ type: 'folder', id }),
        onAccountSelect: (id) => showFolderSelectionView(id),
        onImapFolderSelect: (accountId, folder) => selectView({ type: 'account', id: accountId, folder }),
    });
    
    initEventListeners();
    initModalListeners();
    loadFolders().then(() => {
        updateTrashBadge();
        refreshSidebarFolders();
    });
    updateStagedBadge();
    
    // Load labels for each account
    document.querySelectorAll('.account-item').forEach(item => {
        const accountId = item.dataset.accountId;
        loadAccountLabels(accountId);
    });
});

function initEventListeners() {
    // Section headers (collapse/expand)
    document.querySelectorAll('.section-header').forEach(header => {
        header.addEventListener('click', () => toggleSection(header));
    });
    
    // Tree item clicks
    document.querySelectorAll('.tree-item-row[data-type]').forEach(row => {
        row.addEventListener('click', (e) => handleTreeItemClick(e, row));
    });
    
    // Stage/Review buttons
    elements.stageBtn?.addEventListener('click', openStageModal);
    elements.reviewBtn?.addEventListener('click', goToReview);
    
    // Select all
    elements.selectAll?.addEventListener('change', handleSelectAll);
    
    // Search
    elements.searchInput?.addEventListener('input', debounce(handleSearch, 300));
    
    // New folder buttons
    elements.newFolderBtn?.addEventListener('click', () => openNewFolderModal(false));
    elements.addFolderBtn?.addEventListener('click', () => openNewFolderModal(false));
    
    // Folder select in stage modal
    document.getElementById('folderSelectList')?.addEventListener('click', handleFolderSelect);
    document.getElementById('confirmStageBtn')?.addEventListener('click', confirmStage);
    
    // New folder modal
    document.getElementById('createFolderBtn')?.addEventListener('click', () => createFolder(false));
    
    // Navigation warning
    window.addEventListener('beforeunload', handleBeforeUnload);
// ============================================
// STAGING
// ============================================

let selectedDestinationFolder = null;

function openStageModal() {
    if (state.selectedEmails.size === 0) return;
    
    document.getElementById('stageCount').textContent = state.selectedEmails.size;
    selectedDestinationFolder = null;
    
    // Render hierarchical folder tree
    renderFolderSelectTree();
    
    document.getElementById('confirmStageBtn').disabled = true;
    
    elements.stageModal.classList.add('active');
}

/**
 * Render hierarchical folder tree in the stage modal.
 */
function renderFolderSelectTree() {
    const list = document.getElementById('folderSelectList');
    if (!list) return;
    
    renderFolderTree(list, {
        showNewFolder: true,
        itemClass: 'folder-select-item',
        onSelect: (id) => {
            selectedDestinationFolder = id;
            document.getElementById('confirmStageBtn').disabled = false;
        },
        onNewFolder: () => openNewFolderModal(true),
    });
}

function handleFolderSelect(e) {
    // Legacy handler - keeping for backward compatibility with inline onclick handlers
    const item = e.target.closest('.folder-select-item');
    if (!item) return;
    
    if (item.dataset.action === 'new') {
        openNewFolderModal(true);
        return;
    }
    
    document.querySelectorAll('.folder-select-item').forEach(i => i.classList.remove('selected'));
    item.classList.add('selected');
    
    selectedDestinationFolder = item.dataset.id;
    document.getElementById('confirmStageBtn').disabled = false;
}

function confirmStage() {
    if (!selectedDestinationFolder) return;
    
    const modal = document.getElementById('stageModal');
    const stagingMode = modal?.dataset.stagingMode;
    
    if (stagingMode === 'folders') {
        // Staging entire folders
        if (!state.stagedFolders) return;
        
        state.stagedFolders.destinationFolderId = selectedDestinationFolder;
        
        // Clear modal mode
        modal.dataset.stagingMode = '';
        closeModal('stageModal');
        
        // Update badge to show folders are staged
        updateStagedBadge();
        
        // Show feedback
        showAlert('Folders Staged', `${state.stagedFolders.folders.length} folder(s) staged for archiving. Click "Review & Commit" to proceed.`);
        return;
    }
    
    // Normal email staging
    if (!state.currentView) return;
    
    state.selectedEmails.forEach(emailId => {
        const email = state.emails.find(e => (e.uid || e.id) === emailId);
        if (email) {
            state.staged.set(emailId, {
                email,
                destinationFolderId: selectedDestinationFolder,
                sourceAccountId: state.currentView.type === 'account' ? state.currentView.id : null,
                sourceFolder: state.currentView.folder || 'INBOX',
            });
        }
    });
    
    state.selectedEmails.clear();
    closeModal('stageModal');
    
    updateStagedBadge();
    updateButtonStates();
    renderEmailList();
}

function updateStagedBadge() {
    if (!elements.stagedBadge) return;
    
    // Count staged emails plus staged folders
    let count = state.staged.size;
    if (state.stagedFolders?.destinationFolderId) {
        count += state.stagedFolders.folders.length;
    }
    
    elements.stagedBadge.textContent = count;
    elements.stagedBadge.classList.toggle('hidden', count === 0);
}

function updateButtonStates() {
    if (elements.stageBtn) {
        // Only enable stage for account views (not archive)
        const canStage = state.currentView?.type === 'account' && state.selectedEmails.size > 0;
        elements.stageBtn.disabled = !canStage;
    }
    if (elements.reviewBtn) {
        // Enable if we have staged emails OR staged folders
        const hasEmails = state.staged.size > 0;
        const hasFolders = state.stagedFolders?.destinationFolderId;
        elements.reviewBtn.disabled = !hasEmails && !hasFolders;
    }
}

function goToReview() {
    // Check if we have staged emails or staged folders
    const hasEmails = state.staged.size > 0;
    const hasFolders = state.stagedFolders?.destinationFolderId;
    
    if (!hasEmails && !hasFolders) return;
    
    // Store staged emails
    if (hasEmails) {
        sessionStorage.setItem('stagedEmails', JSON.stringify([...state.staged.entries()]));
    }
    
    // Store staged folders
    if (hasFolders) {
        sessionStorage.setItem('stagedFolders', JSON.stringify(state.stagedFolders));
    }
    
    window.removeEventListener('beforeunload', handleBeforeUnload);
    window.location.href = '/review';
}

// ============================================
// NEW FOLDER
// ============================================

function openNewFolderModal(fromStageModal = false) {
    elements.newFolderModal.dataset.fromStage = fromStageModal;
    document.getElementById('newFolderName').value = '';
    elements.newFolderModal.classList.add('active');
    document.getElementById('newFolderName').focus();
}

async function createFolder(returnToStage) {
    const name = document.getElementById('newFolderName').value.trim();
    const fromStage = elements.newFolderModal.dataset.fromStage === 'true';
    
    if (!name) {
        document.getElementById('newFolderName').focus();
        return;
    }
    
    try {
        const response = await fetch('/api/folders', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name }),
        });
        
        if (!response.ok) {
            const data = await response.json();
            showAlert('Error', data.error || 'Failed to create folder');
            return;
        }
        
        const data = await response.json();
        state.folders.push(data.folder);
        
        closeModal('newFolderModal');
        
        // Update sidebar archive section
        updateSidebarFolders(data.folder);
        
        if (fromStage) {
            // Re-render the hierarchical folder tree and select the new folder
            renderFolderSelectTree();
            
            // Select the newly created folder
            const newItem = document.querySelector(`.folder-select-item[data-id="${data.folder.id}"]`);
            if (newItem) {
                newItem.classList.add('selected');
            }
            
            selectedDestinationFolder = data.folder.id;
            document.getElementById('confirmStageBtn').disabled = false;
        } else {
            // Check if we're in folder management view
            const activeView = document.querySelector('.rail-btn.active')?.dataset.view;
            if (activeView === 'folders') {
                showFolderManagementView();
            } else {
                location.reload();
            }
        }
        
    } catch (error) {
        console.error('Error creating folder:', error);
        showAlert('Error', 'Failed to create folder');
    }
}

// ============================================
// UTILITIES
// ============================================

function showLoading() {
    if (!elements.emailList) return;
    elements.emailList.innerHTML = `
        <div class="empty-state">
            <i data-lucide="loader" class="empty-icon spin"></i>
            <h3>Loading...</h3>
        </div>
    `;
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function showError(message) {
    if (!elements.emailList) return;
    elements.emailList.innerHTML = `
        <div class="empty-state">
            <i data-lucide="alert-triangle" class="empty-icon"></i>
            <h3>Error</h3>
            <p>${escapeHtml(message)}</p>
        </div>
    `;
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function handleSearch(e) {
    const query = e.target.value.toLowerCase().trim();
    
    if (!query) {
        renderEmailList();
        return;
    }
    
    const filtered = state.emails.filter(email =>
        email.subject?.toLowerCase().includes(query) ||
        email.sender?.toLowerCase().includes(query) ||
        email.snippet?.toLowerCase().includes(query)
    );
    
    const original = state.emails;
    state.emails = filtered;
    renderEmailList();
    state.emails = original;
}

function handleBeforeUnload(e) {
    if (state.staged.size > 0) {
        e.preventDefault();
        e.returnValue = '';
        return '';
    }
}


// ============================================
// LEFT RAIL VIEW SWITCHING
// ============================================

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

(function() {
    const railBtns = document.querySelectorAll('.rail-btn[data-view]');
    
    railBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const view = btn.dataset.view;
            
            // Update active state
            railBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            // Switch view
            switch(view) {
                case 'mail':
                    showMailView();
                    break;
                case 'staged':
                    showStagedView();
                    break;
                case 'folders':
                    showFolderManagementView();
                    break;
                case 'trash':
                    showTrashView();
                    break;
            }
        });
    });
})();

function showMailView() {
    // Restore normal mail view
    const sidebar = document.getElementById('sidebar');
    const toolbar = document.querySelector('.content-toolbar');
    const headerActions = document.querySelector('.header-actions');
    
    sidebar.style.display = '';
    if (toolbar) toolbar.style.display = '';
    if (headerActions) headerActions.style.display = '';
    
    // Clear selection and show default
    state.currentView = null;
    elements.contextTitle.textContent = 'Select a folder';
    elements.contextMeta.textContent = '';
    elements.emailList.innerHTML = `
        <div class="empty-state">
            <i data-lucide="arrow-left" class="empty-icon"></i>
            <h3>No Folder Selected</h3>
            <p>Select an account or archive folder from the sidebar to view emails.</p>
        </div>
    `;
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function showStagedView() {
    const sidebar = document.getElementById('sidebar');
    const toolbar = document.querySelector('.content-toolbar');
    const headerActions = document.querySelector('.header-actions');
    
    sidebar.style.display = 'none';
    if (toolbar) toolbar.style.display = 'none';
    if (headerActions) headerActions.style.display = '';
    
    elements.contextTitle.textContent = 'Staged Emails';
    elements.contextMeta.textContent = `${state.staged.size} email${state.staged.size !== 1 ? 's' : ''} staged`;
    
    if (state.staged.size === 0) {
        elements.emailList.innerHTML = `
            <div class="empty-state">
                <i data-lucide="package" class="empty-icon"></i>
                <h3>No Staged Emails</h3>
                <p>Select emails from your inbox and click "Stage" to prepare them for archiving.</p>
            </div>
        `;
    } else {
        renderStagedList();
    }
    
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function renderStagedList() {
    const stagedArray = [...state.staged.entries()];
    
    elements.emailList.innerHTML = stagedArray.map(([emailId, data]) => {
        const email = data.email;
        const folder = state.folders.find(f => f.id == data.destinationFolderId);
        
        return `
            <div class="email-item staged-item" data-id="${emailId}">
                <div class="email-content">
                    <div class="email-header">
                        <span class="email-sender">${escapeHtml(extractName(email.from || email.sender))}</span>
                        <span class="email-date">${formatDate(email.date)}</span>
                    </div>
                    <div class="email-subject">${escapeHtml(email.subject || '(no subject)')}</div>
                    <div class="email-preview staged-destination">
                        <i data-lucide="folder"></i>
                        <span>→ ${escapeHtml(folder?.name || 'Unknown folder')}</span>
                    </div>
                </div>
                <button class="btn btn-sm btn-secondary unstage-btn" onclick="unstageEmail('${emailId}')">
                    <i data-lucide="x"></i>
                </button>
            </div>
        `;
    }).join('');
    
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function unstageEmail(emailId) {
    state.staged.delete(emailId);
    updateStagedBadge();
    
    // Re-render if still in staged view
    const activeBtn = document.querySelector('.rail-btn.active');
    if (activeBtn?.dataset.view === 'staged') {
        showStagedView();
    }
}
window.unstageEmail = unstageEmail;

// ============================================
// FOLDER MANAGEMENT VIEW
// ============================================

async function showFolderManagementView() {
    const sidebar = document.getElementById('sidebar');
    const toolbar = document.querySelector('.content-toolbar');
    const headerActions = document.querySelector('.header-actions');
    
    sidebar.style.display = 'none';
    if (toolbar) toolbar.style.display = 'none';
    if (headerActions) headerActions.style.display = 'none';
    
    elements.contextTitle.textContent = 'Manage Folders';
    elements.contextMeta.textContent = '';
    
    // Reload folders first
    await loadFolders();
    
    if (state.folders.length === 0) {
        elements.emailList.innerHTML = `
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
    // Build folder tree
    const topLevelFolders = state.folders.filter(f => !f.parent_id && !f.deleted_at);
    
    let html = `
        <div class="folder-management-list">
            <div class="folder-management-header">
                <span>Folder</span>
                <span>Color</span>
                <span>Actions</span>
            </div>
    `;
    
    // Recursive function to render folder and all descendants
    function renderFolderWithChildren(folder, depth) {
        html += renderFolderManagementItem(folder, depth);
        
        // Render children recursively
        const children = state.folders.filter(f => f.parent_id == folder.id && !f.deleted_at);
        children.forEach(child => {
            renderFolderWithChildren(child, depth + 1);
        });
    }
    
    topLevelFolders.forEach(folder => {
        renderFolderWithChildren(folder, 0);
    });
    
    html += `
            <button class="folder-management-add" onclick="openNewFolderModal(false)">
                <i data-lucide="plus"></i>
                <span>New Folder</span>
            </button>
        </div>
    `;
    
    elements.emailList.innerHTML = html;
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

async function renameFolder(folderId) {
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

async function createSubfolder(parentId) {
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

// ============================================
// MOVE FOLDER
// ============================================

let movingFolderId = null;
let moveDestinationId = null;

function openMoveFolder(folderId) {
    const folder = state.folders.find(f => f.id == folderId);
    if (!folder) return;
    
    movingFolderId = folderId;
    moveDestinationId = null;
    
    document.getElementById('moveFolderName').textContent = folder.name;
    document.getElementById('confirmMoveBtn').disabled = true;
    
    // Get all descendants of this folder (can't move into itself or children)
    const descendants = getDescendantIds(folderId);
    
    // Build folder list
    const list = document.getElementById('moveFolderList');
    let html = `
        <div class="folder-select-item" data-id="root">
            <i data-lucide="home"></i>
            <span>Root level (no parent)</span>
        </div>
    `;
    
    // Add all valid folders (not the folder itself, not its descendants, not deleted)
    const validFolders = state.folders.filter(f => 
        !f.deleted_at && 
        f.id != folderId && 
        !descendants.includes(f.id)
    );
    
    // Render as flat list with indentation showing hierarchy
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
        // Render children
        const children = validFolders.filter(c => c.parent_id == f.id);
        children.forEach(child => renderFolderOption(child, depth + 1));
    }
    
    // Render top-level folders
    validFolders.filter(f => !f.parent_id).forEach(f => renderFolderOption(f, 0));
    
    list.innerHTML = html;
    
    // Mark root as current if folder is at root level
    if (folder.parent_id === null) {
        list.querySelector('[data-id="root"]')?.classList.add('current-location');
        const rootItem = list.querySelector('[data-id="root"]');
        if (rootItem && !rootItem.querySelector('.current-badge')) {
            rootItem.innerHTML += '<span class="current-badge">current</span>';
        }
    }
    
    // Add click handlers
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

async function confirmMoveFolder() {
    if (!movingFolderId || moveDestinationId === null) return;
    
    const newParentId = moveDestinationId === 'root' ? null : parseInt(moveDestinationId);
    const folder = state.folders.find(f => f.id == movingFolderId);
    
    // Check if actually moving
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
        
        // Update local state
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

async function deleteFolder(folderId) {
    const folder = state.folders.find(f => f.id == folderId);
    if (!folder) return;
    
    // Count children and emails
    const children = state.folders.filter(f => f.parent_id == folderId && !f.deleted_at);
    
    let message = `Move "${folder.name}" to trash?`;
    if (children.length > 0) {
        message = `Move "${folder.name}" and ${children.length} subfolder${children.length > 1 ? 's' : ''} to trash?`;
    }
    
    const confirmed = await showConfirm('Delete Folder', message, { okText: 'Move to Trash' });
    if (!confirmed) return;
    
    try {
        const response = await fetch(`/api/folders/${folderId}`, {
            method: 'DELETE',
        });
        
        if (!response.ok) {
            const data = await response.json();
            showAlert('Error', data.error || 'Failed to delete folder');
            return;
        }
        
        // Update local state
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
    if (folderEl) {
        folderEl.closest('.tree-item')?.remove();
    }
    
    // Update count
    const countEl = document.getElementById('folderCount');
    if (countEl) {
        const visibleFolders = state.folders.filter(f => !f.deleted_at);
        countEl.textContent = visibleFolders.length;
    }
}

// Color picker
function openColorPicker(folderId, event) {
    event.stopPropagation();
    
    // Remove any existing picker
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
                data-color="${c.value || ''}" 
                title="${c.name}">
            ${c.value ? `<span style="background: ${c.value}"></span>` : '<i data-lucide="x"></i>'}
        </button>
    `).join('');
    
    document.body.appendChild(popup);
    if (typeof lucide !== 'undefined') lucide.createIcons();
    
    // Handle selection
    popup.addEventListener('click', async (e) => {
        const option = e.target.closest('.color-option');
        if (!option) return;
        
        const color = option.dataset.color || null;
        await setFolderColor(folderId, color);
        popup.remove();
    });
    
    // Close on outside click
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

// ============================================
// TRASH VIEW
// ============================================

async function showTrashView() {
    const sidebar = document.getElementById('sidebar');
    const toolbar = document.querySelector('.content-toolbar');
    const headerActions = document.querySelector('.header-actions');
    
    sidebar.style.display = 'none';
    if (toolbar) toolbar.style.display = 'none';
    if (headerActions) headerActions.style.display = 'none';
    
    elements.contextTitle.textContent = 'Trash';
    elements.contextMeta.textContent = '';
    
    // Reload folders to get fresh deleted_at data
    await loadFolders();
    
    // Get trashed folders (only top-level ones that were directly deleted)
    const trashedFolders = state.folders
        .filter(f => f.deleted_at && !f.parent_id)
        .sort((a, b) => b.deleted_at - a.deleted_at);  // Most recent first
    // Also include folders whose parent is deleted
    const allTrashed = state.folders.filter(f => {
        if (f.deleted_at) return true;
        // Check if parent is deleted
        if (f.parent_id) {
            const parent = state.folders.find(p => p.id == f.parent_id);
            return parent?.deleted_at;
        }
        return false;
    });
    
    if (trashedFolders.length === 0) {
        elements.emailList.innerHTML = `
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
        <div class="trash-list">
            <div class="trash-header">
                <span>Folder</span>
                <span>Deleted</span>
                <span>Actions</span>
            </div>
    `;
    
    trashedFolders.forEach(folder => {
        const deletedDate = new Date(folder.deleted_at * 1000);
        const children = state.folders.filter(f => f.parent_id == folder.id);
        
        html += `
            <div class="trash-item" data-id="${folder.id}">
                <div class="trash-item-name">
                    <i data-lucide="folder" class="folder-icon"></i>
                    <span class="folder-name">${escapeHtml(folder.name)}</span>
                    ${children.length > 0 ? `<span class="subfolder-count">(+${children.length})</span>` : ''}
                </div>
                <div class="trash-item-date">
                    ${formatDate(deletedDate)}
                </div>
                <div class="trash-item-actions">
                    <button class="btn btn-sm btn-icon" onclick="restoreFolder(${folder.id})" title="Restore">
                        <i data-lucide="undo-2"></i>
                    </button>
                    <button class="btn btn-sm btn-icon btn-danger-subtle" onclick="permanentlyDeleteFolder(${folder.id})" title="Delete permanently">
                        <i data-lucide="x"></i>
                    </button>
                </div>
            </div>
        `;
    });
    
    // Empty Trash button at bottom
    html += `
            <div class="trash-footer">
                <button class="btn btn-sm btn-danger" onclick="emptyTrash()">
                    <i data-lucide="trash-2"></i> Empty Trash
                </button>
            </div>
        </div>
    `;
    elements.emailList.innerHTML = html;
}

async function restoreFolder(folderId) {
    try {
        const response = await fetch(`/api/folders/${folderId}/restore`, {
            method: 'POST',
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            showAlert('Error', data.error || 'Failed to restore folder');
            return;
        }
        
        // Update local state
        const folder = state.folders.find(f => f.id == folderId);
        if (folder) {
            folder.deleted_at = null;
            // Update name if it was renamed due to conflict
            if (data.folder && data.folder.name) {
                folder.name = data.folder.name;
            }
            // Also restore children
            state.folders.filter(f => f.parent_id == folderId).forEach(c => c.deleted_at = null);
        }
        
        showTrashView();
        updateSidebarAfterRestore(folder);
        
        // Notify user if folder was renamed
        if (data.folder && data.folder.renamed) {
            showAlert('Folder Restored', `Folder restored as "${data.folder.name}" to avoid a naming conflict.`);
        }
        
    } catch (error) {
        console.error('Error restoring folder:', error);
        showAlert('Error', 'Failed to restore folder');
    }
}
window.restoreFolder = restoreFolder;

function updateSidebarAfterRestore(folder) {
    if (!folder) return;
    updateSidebarFolders(folder);
}

async function permanentlyDeleteFolder(folderId) {
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
        
        // Remove from local state
        state.folders = state.folders.filter(f => f.id != folderId && f.parent_id != folderId);
        
        showTrashView();
        
    } catch (error) {
        console.error('Error deleting folder:', error);
        showAlert('Error', 'Failed to delete folder');
    }
}
window.permanentlyDeleteFolder = permanentlyDeleteFolder;

async function emptyTrash() {
    const trashedFolders = state.folders.filter(f => f.deleted_at && !f.parent_id);
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
        
        // Remove all trashed folders from state
        state.folders = state.folders.filter(f => !f.deleted_at);
        
        showTrashView();
        
    } catch (error) {
        console.error('Error emptying trash:', error);
        showAlert('Error', 'Failed to empty trash');
    }
}
window.emptyTrash = emptyTrash;

function updateTrashBadge() {
    const badge = document.getElementById('trashBadge');
    if (!badge) return;
    
    const trashedCount = state.folders.filter(f => f.deleted_at && !f.parent_id).length;
    badge.textContent = trashedCount;
    badge.classList.toggle('hidden', trashedCount === 0);
}
