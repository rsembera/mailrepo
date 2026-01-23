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

import { escapeHtml, extractName, formatDate, debounce } from './utils.js';
import { state, loadFolders } from './state.js';
import { closeModal, showPrompt, showConfirm, showAlert, initModalListeners } from './modals.js';
import { renderFolderTree } from './components/folder-tree.js';
import { initEmailList, renderEmailList, toggleEmailSelection, handleSelectAll, updateSelectAllState } from './components/email-list.js';
import { initSidebar, toggleSection, handleTreeItemClick, updateSidebarFolders, refreshSidebarFolders, loadAccountLabels, buildImapFolderTree, getFolderIcon } from './components/sidebar.js';
import { initMailView, selectView, loadAccountEmails, loadFolderEmails, openEmailViewer, closeEmailViewer, showLoading, showError } from './views/mail.js';
import { initStaging, openStageModal, renderFolderSelectTree, handleFolderSelect, confirmStage, updateStagedBadge, updateButtonStates, goToReview, setSelectedDestinationFolder } from './components/staging.js';
import { initFolderMgmt, showFolderManagementView, showFolderSelectionView, renameFolder, createSubfolder, openMoveFolder, confirmMoveFolder, deleteFolder, openColorPicker, handleFolderCheckbox, toggleAllFolders, stageSelectedFolders } from './views/folder-mgmt.js';
import { initTrashView, showTrashView, updateTrashBadge, restoreFolder, permanentlyDeleteFolder, emptyTrash } from './views/trash.js';

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
    
    const emailCount = state.staged.size;
    const folderCount = state.stagedFolders?.folders?.length || 0;
    const totalCount = emailCount + folderCount;
    
    // Set header action for staged view - commit button only
    if (headerActions) {
        headerActions.innerHTML = `
            <button class="btn btn-primary" id="commitBtnStaged" ${totalCount === 0 ? 'disabled' : ''}>
                <i data-lucide="archive"></i>
                Commit to Archive
            </button>
        `;
        if (typeof lucide !== 'undefined') lucide.createIcons();
        
        document.getElementById('commitBtnStaged')?.addEventListener('click', () => {
            import('./components/staging.js').then(m => m.goToReview());
        });
    }
    
    elements.contextTitle.textContent = 'Staged Items';
    
    let metaParts = [];
    if (emailCount > 0) metaParts.push(`${emailCount} email${emailCount !== 1 ? 's' : ''}`);
    if (folderCount > 0) metaParts.push(`${folderCount} folder${folderCount !== 1 ? 's' : ''}`);
    elements.contextMeta.textContent = metaParts.length > 0 ? metaParts.join(', ') + ' staged' : 'Nothing staged';
    
    if (totalCount === 0) {
        elements.emailList.innerHTML = `
            <div class="empty-state">
                <i data-lucide="package" class="empty-icon"></i>
                <h3>Nothing Staged</h3>
                <p>Select emails or folders to prepare them for archiving.</p>
            </div>
        `;
    } else {
        renderStagedList();
    }
    
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function renderStagedList() {
    let html = '';
    
    // Render staged folders first
    if (state.stagedFolders?.folders?.length > 0) {
        const destFolder = state.folders.find(f => f.id == state.stagedFolders.destinationFolderId);
        const destName = destFolder?.name || 'Unknown folder';
        
        html += `
            <div class="staged-section">
                <div class="staged-section-header">
                    <i data-lucide="folders"></i>
                    <span>Folders to Archive</span>
                    <button class="btn btn-sm btn-secondary" onclick="unstageFolders()">
                        <i data-lucide="x"></i> Clear
                    </button>
                </div>
                <div class="staged-folders-list">
        `;
        
        state.stagedFolders.folders.forEach(folderPath => {
            html += `
                <div class="staged-folder-item">
                    <i data-lucide="folder"></i>
                    <span class="folder-path">${escapeHtml(folderPath)}</span>
                    <span class="staged-destination">→ ${escapeHtml(destName)}</span>
                </div>
            `;
        });
        
        html += `
                </div>
            </div>
        `;
    }
    
    // Render staged emails
    if (state.staged.size > 0) {
        const stagedArray = [...state.staged.entries()];
        
        html += `<div class="staged-section">`;
        if (state.stagedFolders?.folders?.length > 0) {
            html += `
                <div class="staged-section-header">
                    <i data-lucide="mail"></i>
                    <span>Emails to Archive</span>
                </div>
            `;
        }
        
        html += stagedArray.map(([emailId, data]) => {
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
        
        html += `</div>`;
    }
    
    elements.emailList.innerHTML = html;
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function unstageFolders() {
    state.stagedFolders = null;
    updateStagedBadge();
    
    const activeBtn = document.querySelector('.rail-btn.active');
    if (activeBtn?.dataset.view === 'staged') {
        showStagedView();
    }
}
window.unstageFolders = unstageFolders;

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


window.unstageFolders = unstageFolders;

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
            state.stagedFolders = JSON.parse(savedFolders);
        } catch (e) {
            console.error('Failed to restore staged folders:', e);
        }
    }
}
