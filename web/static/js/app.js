/**
 * MailRepo - Application Entry Point
 * 
 * Main entry point that initializes all components and handles:
 * - DOM element references
 * - Component initialization
 * - Event listener setup
 * - Left rail view switching
 * - New folder modal
 * - Search functionality
 */

// ============================================
// IMPORTS
// ============================================

import { escapeHtml, debounce } from './utils.js';
import { state, loadFolders } from './state.js';
import { closeModal, showPrompt, showConfirm, showAlert, initModalListeners } from './modals.js';
import { renderFolderTree } from './components/folder-tree.js';
import { initEmailList, renderEmailList, toggleEmailSelection, handleSelectAll, updateSelectAllState } from './components/email-list.js';
import { initSidebar, toggleSection, handleTreeItemClick, updateSidebarFolders, refreshSidebarFolders, loadAccountLabels, buildImapFolderTree, getFolderIcon } from './components/sidebar.js';
import { initMailView, selectView, loadAccountEmails, loadFolderEmails, openEmailViewer, closeEmailViewer, showLoading, showError } from './views/mail.js';
import { initStaging, openStageModal, renderFolderSelectTree, handleFolderSelect, confirmStage, updateStagedBadge, updateButtonStates, goToReview, setSelectedDestinationFolder } from './components/staging.js';
import { initFolderMgmt, showFolderManagementView, showFolderSelectionView, renameFolder, createSubfolder, openMoveFolder, confirmMoveFolder, deleteFolder, openColorPicker, handleFolderCheckbox, toggleAllFolders, stageSelectedFolders } from './views/folder-mgmt.js';
import { initTrashView, showTrashView, updateTrashBadge, restoreFolder, permanentlyDeleteFolder, emptyTrash } from './views/trash.js';
import { initSettingsView, showSettingsView } from './views/settings.js';
import { initImports, getImportEmails, getMountedImports, renderImportsSection } from './components/imports.js';

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
    // Restore staged items from sessionStorage (e.g., when returning from review page)
    restoreStagedFromSession();
    
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
    
    // Initialize trash view
    initTrashView({
        contextTitle: elements.contextTitle,
        contextMeta: elements.contextMeta,
        emailList: elements.emailList,
    });
    
    // Initialize settings view
    initSettingsView({
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
    
    // Initialize imports component
    initImports({
        onImportSelect: (importId) => loadImportEmails(importId),
        onImportFolderSelect: (importId, folder) => loadImportEmails(importId, folder),
        onImportUnmount: (importId) => handleImportUnmount(importId),
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

/**
 * Load emails from a mounted import.
 */
function loadImportEmails(importId, folderPath = null) {
    const emails = getImportEmails(importId, folderPath);
    const imports = getMountedImports();
    const imp = imports.find(i => i.id === importId);
    
    if (!imp) {
        showError('Import not found');
        return;
    }
    
    // Update header
    const title = folderPath || imp.name;
    elements.contextTitle.textContent = title;
    elements.contextMeta.textContent = `${emails.length} email${emails.length !== 1 ? 's' : ''} (imported)`;
    
    // Store current view for returning from other views
    state.currentView = { type: 'import', id: importId, folder: folderPath };
    state.currentSource = { type: 'import', importId };
    
    // Set emails in state and render
    state.emails = emails;
    renderEmailList();
    updateButtonStates();
}

/**
 * Handle import unmount - clear main pane if viewing that import.
 */
function handleImportUnmount(importId) {
    // Check if we're currently viewing this import
    if (state.currentView?.type === 'import' && state.currentView?.id === importId) {
        // Clear the view
        state.currentView = null;
        state.currentSource = null;
        state.emails = [];
        state.selectedEmails.clear();
        
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
        updateButtonStates();
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
                    // Go directly to review page
                    goToReview();
                    break;
                case 'folders':
                    showFolderManagementView();
                    break;
                case 'trash':
                    showTrashView();
                    break;
                case 'settings':
                    showSettingsView();
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
    
    // If we have a previously selected view, restore it
    if (state.currentView) {
        if (state.currentView.type === 'account') {
            loadAccountEmails(state.currentView.id, state.currentView.folder);
        } else if (state.currentView.type === 'folder') {
            loadFolderEmails(state.currentView.id);
        } else if (state.currentView.type === 'import') {
            loadImportEmails(state.currentView.id, state.currentView.folder);
        }
    } else {
        // No previous selection - show empty state
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
}

/**
 * Restore staged items from sessionStorage.
 * Called on page load to preserve staged items when navigating back from review.
 */
function restoreStagedFromSession() {
    // Restore staged emails
    const savedEmails = sessionStorage.getItem('stagedEmails');
    if (savedEmails) {
        try {
            const entries = JSON.parse(savedEmails);
            state.staged = new Map(entries);
        } catch (e) {
            console.error('Failed to restore staged emails:', e);
        }
    }
    
    // Restore staged folders
    const savedFolders = sessionStorage.getItem('stagedFolders');
    if (savedFolders) {
        try {
            const parsed = JSON.parse(savedFolders);
            // Ensure it's an array (handle old format)
            state.stagedFolders = Array.isArray(parsed) ? parsed : [];
        } catch (e) {
            console.error('Failed to restore staged folders:', e);
        }
    }
}
