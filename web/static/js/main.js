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
import { initStaging, openStageModal, renderFolderSelectTree, handleFolderSelect, confirmStage, updateStagedBadge, updateButtonStates, goToReview, setSelectedDestinationFolder } from './components/staging.js';
import { initFolderMgmt, showFolderManagementView, showFolderSelectionView, renameFolder, createSubfolder, openMoveFolder, confirmMoveFolder, deleteFolder, openColorPicker, handleFolderCheckbox, toggleAllFolders, stageSelectedFolders } from './views/folder-mgmt.js';

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
    
    // Initialize staging component
    initStaging({
        stageModal: elements.stageModal,
        stagedBadge: elements.stagedBadge,
        stageBtn: elements.stageBtn,
        reviewBtn: elements.reviewBtn,
        onOpenNewFolderModal: openNewFolderModal,
        beforeUnloadHandler: handleBeforeUnload,
    });
    
    // Initialize folder management views
    initFolderMgmt({
        contextTitle: elements.contextTitle,
        contextMeta: elements.contextMeta,
        emailList: elements.emailList,
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
