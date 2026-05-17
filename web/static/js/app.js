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
import { state, loadFolders, confirmNavigation } from './state.js';
import { closeModal, showPrompt, showConfirm, showAlert, initModalListeners } from './modals.js';
import { renderFolderTree } from './components/folder-tree.js';
import { initEmailList, renderEmailList, toggleEmailSelection, updateSelectAllState } from './components/email-list.js';
import { initSidebar, toggleSection, handleTreeItemClick, refreshSidebarFolders, refreshSidebarAccounts, loadAccountLabels, buildImapFolderTree, getFolderIcon } from './components/sidebar.js';
import { initMailView, selectView, loadAccountEmails, loadFolderEmails, openEmailViewer, closeEmailViewer, showLoading, showError, restoreDefaultHeaderActions } from './views/mail.js';
import { initStaging, openStageModal, renderFolderSelectTree, handleFolderSelect, confirmStage, updateStagedBadge, updateButtonStates, setSelectedDestinationFolder } from './components/staging.js';
import { initFolderMgmt, renameFolder, createSubfolder, openMoveFolder, confirmMoveFolder, deleteFolder, openColorPicker } from './views/folder-mgmt.js';
import { initFolderSelection, showFolderSelectionView, showImportFolderSelectionView, stageSelectedFolders } from './views/folder-selection.js';
import { initTrashView, showTrashView, updateTrashBadge, restoreFolder, permanentlyDeleteFolder, emptyTrash } from './views/trash.js';
import { initStarredView, showStarredView, updateStarredBadge } from './views/starred.js';
import { initVault, showVaultView, updateVaultBadge, checkOverdueFolders, hideOverdueAlert } from './views/vault.js';
import { initSettingsView, showSettingsView } from './views/settings.js';
import { initBackupsView, showBackupsView } from './views/backups.js';
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
        onFilterChange: (filteredCount, totalCount, selectedCount = 0) => {
            if (!elements.contextMeta) return;
            const isArchiveView = state.currentView?.type === 'folder';
            const label = isArchiveView ? 'archived emails' : 'emails';
            
            if (selectedCount > 0) {
                // Show selection count
                elements.contextMeta.textContent = `${selectedCount} of ${totalCount} ${label} selected`;
            } else if (filteredCount === totalCount) {
                elements.contextMeta.textContent = `${totalCount} ${label}`;
            } else {
                elements.contextMeta.textContent = `${filteredCount} of ${totalCount} ${label}`;
            }
        },
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
    
    // Initialize folder selection view
    initFolderSelection({
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
    
    // Initialize starred view
    initStarredView({
        contextTitle: elements.contextTitle,
        contextMeta: elements.contextMeta,
        emailList: elements.emailList,
    });

    
    // Initialize vault view
    initVault({
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
    
    // Initialize backups view
    initBackupsView({
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
        updateStarredBadge();
        checkOverdueFolders(true); // Update badge AND show alert on initial load (mail view)
        refreshSidebarFolders();
    });
    updateStagedBadge();
    
    // Check for interrupted commits that can be resumed
    checkPendingCommit();
    
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
    elements.reviewBtn?.addEventListener('click', () => showReviewView());
    
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
    
    // Account changes from settings
    window.addEventListener('accountsChanged', () => refreshSidebarAccounts());
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
        showAlert('Invalid Name', 'Folder name cannot be empty.');
        document.getElementById('newFolderName').focus();
        return;
    }
    
    // Check for invalid characters/names
    if (/^[.\s]+$/.test(name) || /[\/\\]/.test(name)) {
        showAlert('Invalid Name', 'Folder name contains invalid characters.');
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
        refreshSidebarFolders();
        
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
            // Refresh sidebar to show new folder
            refreshSidebarFolders();
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

// Flag to skip beforeunload warning on intentional navigation (logout)
let skipBeforeUnload = false;

function handleBeforeUnload(e) {
    if (skipBeforeUnload) return;
    if (state.staged.size > 0) {
        e.preventDefault();
        e.returnValue = '';
        return '';
    }
}

// Allow other modules to set the skip flag
window.skipBeforeUnloadWarning = function() {
    skipBeforeUnload = true;
};

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
        btn.addEventListener('click', async () => {
            const view = btn.dataset.view;
            
            // Navigation guard - check for unsaved selections
            if (!await confirmNavigation()) return;
            
            // Update active state
            railBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            // Switch view
            switch(view) {
                case 'mail':
                    showMailView();
                    break;
                case 'staged':
                    hideOverdueAlert();
                    showReviewView();
                    break;
                case 'starred':
                    hideOverdueAlert();
                    showStarredView();
                    break;
                case 'trash':
                    hideOverdueAlert();
                    showTrashView();
                    break;
                case 'vault':
                    hideOverdueAlert();
                    showVaultView();
                    break;
                case 'backups':
                    hideOverdueAlert();
                    showBackupsView();
                    break;
                case 'settings':
                    hideOverdueAlert();
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
    
    // Refresh folder tree in case folders were created/modified in other views
    loadFolders().then(() => refreshSidebarFolders());
    
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
    
    // Show overdue alert if there are overdue folders
    checkOverdueFolders(true);
    
    // Show empty state prompt
    elements.contextTitle.textContent = 'Browse & Stage';
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

/**
 * Check for interrupted commits that can be resumed.
 * Shows a modal prompt if a pending commit is found.
 */
async function checkPendingCommit() {
    try {
        const response = await fetch('/api/commit/pending');
        if (!response.ok) return;
        
        const data = await response.json();
        if (!data.hasPending) return;
        
        // If everything was committed but the process was interrupted during
        // post-commit server actions, just clean up silently — nothing to resume.
        if (data.pending === 0) {
            await fetch('/api/commit/discard', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ commitId: data.commitId }),
            });
            return;
        }
        
        // Format the timestamp
        const createdDate = new Date(data.createdAt * 1000);
        const timeAgo = formatTimeAgo(createdDate);
        
        // Show resume prompt
        const { showConfirm } = await import('./modals.js');
        const resume = await showConfirm(
            'Resume Interrupted Commit',
            `A commit was interrupted ${timeAgo}. ` +
            `${data.committed} of ${data.total} items were committed before the interruption.\n\n` +
            `Would you like to resume and commit the remaining ${data.pending} item${data.pending !== 1 ? 's' : ''}?`,
            {
                confirmText: 'Resume',
                cancelText: 'Discard',
                confirmClass: 'btn-primary',
            }
        );
        
        if (resume) {
            // Open review page and trigger resume
            const { showReviewView } = await import('./views/review.js');
            await showReviewView();
            resumeCommit(data.commitId);
        } else {
            // Discard the pending commit
            await fetch('/api/commit/discard', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ commitId: data.commitId }),
            });
        }
    } catch (e) {
        console.error('Failed to check for pending commit:', e);
    }
}

/**
 * Resume an interrupted commit.
 */
async function resumeCommit(commitId) {
    const modal = document.getElementById('commitProgressModal');
    const progressContainer = document.getElementById('commitProgressContent');
    modal.classList.add('active');
    
    const { createProgress } = await import('./components/progress.js');
    const progress = createProgress(progressContainer);
    
    try {
        await progress.startPostStream('/api/commit/stream', {
            resumeCommitId: commitId,
        }, {
            onComplete: async (data) => {
                modal.classList.remove('active');
                const { showAlert } = await import('./modals.js');
                showAlert('Commit Complete', data.message || 'Commit resumed and completed.');
            },
            onError: async (err) => {
                modal.classList.remove('active');
                const { showAlert } = await import('./modals.js');
                showAlert('Commit Failed', err.error || 'An error occurred during commit.');
            },
        });
    } catch (e) {
        console.error('Resume commit error:', e);
        modal.classList.remove('active');
    }
}

/**
 * Format a date as relative time (e.g., "5 minutes ago", "2 hours ago").
 */
function formatTimeAgo(date) {
    const seconds = Math.floor((new Date() - date) / 1000);
    
    if (seconds < 60) return 'just now';
    if (seconds < 3600) {
        const mins = Math.floor(seconds / 60);
        return `${mins} minute${mins !== 1 ? 's' : ''} ago`;
    }
    if (seconds < 86400) {
        const hours = Math.floor(seconds / 3600);
        return `${hours} hour${hours !== 1 ? 's' : ''} ago`;
    }
    const days = Math.floor(seconds / 86400);
    return `${days} day${days !== 1 ? 's' : ''} ago`;
}

// ============================================
// LOGOUT HANDLER
// ============================================

async function handleLogout() {
    // Skip navigation warning
    window.skipBeforeUnloadWarning && window.skipBeforeUnloadWarning();
    
    // Show logout modal
    const modal = document.getElementById('logoutModal');
    const status = document.getElementById('logoutStatus');
    modal.classList.add('active');
    if (typeof lucide !== 'undefined') lucide.createIcons();
    
    status.textContent = 'Signing out...';
    
    try {
        // Call logout endpoint
        const response = await fetch('/auth/logout', { method: 'POST' });
        
        if (response.redirected) {
            window.location.href = response.url;
        } else {
            window.location.href = '/auth/login';
        }
    } catch (error) {
        console.error('Logout error:', error);
        window.location.href = '/auth/login';
    }
}

window.handleLogout = handleLogout;
