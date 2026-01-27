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
import { initEmailList, renderEmailList, toggleEmailSelection, updateSelectAllState } from './components/email-list.js';
import { initSidebar, toggleSection, handleTreeItemClick, updateSidebarFolders, refreshSidebarFolders, loadAccountLabels, buildImapFolderTree, getFolderIcon } from './components/sidebar.js';
import { initMailView, selectView, loadAccountEmails, loadFolderEmails, openEmailViewer, closeEmailViewer, showLoading, showError, restoreDefaultHeaderActions } from './views/mail.js';
import { initStaging, openStageModal, renderFolderSelectTree, handleFolderSelect, confirmStage, updateStagedBadge, updateButtonStates, goToReview, setSelectedDestinationFolder } from './components/staging.js';
import { initFolderMgmt, showFolderManagementView, showFolderSelectionView, showImportFolderSelectionView, renameFolder, createSubfolder, openMoveFolder, confirmMoveFolder, deleteFolder, openColorPicker, stageSelectedFolders } from './views/folder-mgmt.js';
import { initTrashView, showTrashView, updateTrashBadge, restoreFolder, permanentlyDeleteFolder, emptyTrash } from './views/trash.js';
import { initSettingsView, showSettingsView } from './views/settings.js';
import { initReviewView, showReviewView } from './views/review.js';
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
    
    // Initialize review view
    initReviewView({
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
        onImportSelect: (importId) => handleImportSelect(importId),
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

// Expose globally for inline onclick handlers
window.openNewFolderModal = openNewFolderModal;

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
 * Handle click on import name - decide whether to show folder selection or emails.
 * Shows folder selection only if the import has a folder hierarchy.
 * Otherwise shows emails directly.
 */
function handleImportSelect(importId) {
    const imports = getMountedImports();
    const imp = imports.find(i => i.id === importId);
    
    if (!imp) {
        showError('Import not found');
        return;
    }
    
    // Check if import has meaningful folder structure:
    // - Multiple top-level folders, OR
    // - Any folder with children (nested structure)
    const hasFolderStructure = imp.folders && imp.folders.length > 0 && (
        imp.folders.length > 1 || 
        imp.folders.some(f => f.children && f.children.length > 0)
    );
    
    if (hasFolderStructure) {
        // Has folder hierarchy - show folder selection for bulk staging
        showImportFolderSelectionView(importId);
    } else {
        // Flat structure (eml directory or flat mbox) - show emails directly
        loadImportEmails(importId);
    }
}

/**
 * Load emails from a mounted import.
 */
function loadImportEmails(importId, folderPath = null) {
    // Restore default header actions and toolbar
    restoreDefaultHeaderActions();
    
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
    // Check if we're currently viewing this import (either emails or folder selection)
    const viewingThisImport = state.currentView?.id === importId && 
        (state.currentView?.type === 'import' || state.currentView?.type === 'importFolders');
    
    if (viewingThisImport) {
        // Clear the view
        state.currentView = null;
        state.currentSource = null;
        state.emails = [];
        state.selectedEmails.clear();
        
        // Hide toolbar since nothing is selected
        const toolbar = document.querySelector('.content-toolbar');
        if (toolbar) toolbar.style.display = 'none';
        
        // Clear header actions
        const headerActions = document.querySelector('.header-actions');
        if (headerActions) headerActions.innerHTML = '';
        
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
                    showReviewView();
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
    // Reset to clean state
    state.currentView = null;
    state.selectedEmails.clear();
    state.emails = [];
    
    // Restore normal mail view layout
    const sidebar = document.getElementById('sidebar');
    const toolbar = document.querySelector('.content-toolbar');
    const headerActions = document.querySelector('.header-actions');
    const subfoldersBar = document.getElementById('subfoldersBar');
    
    sidebar.style.display = '';
    if (toolbar) toolbar.style.display = 'none'; // Hide until emails are loaded
    if (headerActions) {
        headerActions.style.display = '';
        headerActions.innerHTML = ''; // Clear any leftover buttons
    }
    if (subfoldersBar) {
        subfoldersBar.style.display = 'none';
        subfoldersBar.innerHTML = '';
    }
    
    // Show empty state prompt
    elements.contextTitle.textContent = 'MailRepo';
    elements.contextMeta.textContent = '';
    elements.emailList.innerHTML = `
        <div class="empty-state">
            <i data-lucide="inbox" class="empty-icon"></i>
            <h3>No Folder Selected</h3>
            <p>Select a folder from the sidebar to view emails.</p>
        </div>
    `;
    if (typeof lucide !== 'undefined') lucide.createIcons();
    
    // Remove active state from sidebar items
    document.querySelectorAll('.tree-item-row').forEach(r => r.classList.remove('active'));
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
