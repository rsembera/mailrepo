/**
 * MailRepo - Staging Component
 * 
 * Handles:
 * - Email staging workflow
 * - Folder staging workflow
 * - Stage modal and destination selection
 * - Staged item badges and counts
 */

import { state } from '../state.js';
import { closeModal, showAlert } from '../modals.js';
import { renderFolderTree } from '../components/folder-tree.js';
import { renderEmailList } from '../components/email-list.js';
import { getPendingFolderStaging, clearPendingFolderStaging } from '../views/folder-mgmt.js';
import { getMountedImports } from '../components/imports.js';

// Module state
let selectedDestinationFolder = null;

// DOM references
let stageModal = null;
let stagedBadge = null;
let stageBtn = null;
let reviewBtn = null;

// Callbacks
let onOpenNewFolderModal = null;
let beforeUnloadHandler = null;

/**
 * Initialize the staging component.
 * @param {Object} config
 * @param {HTMLElement} config.stageModal - Stage modal element
 * @param {HTMLElement} config.stagedBadge - Staged count badge element
 * @param {HTMLElement} config.stageBtn - Stage button element
 * @param {HTMLElement} config.reviewBtn - Review button element
 * @param {Function} config.onOpenNewFolderModal - Callback to open new folder modal
 * @param {Function} config.beforeUnloadHandler - beforeunload handler to remove on navigation
 */
export function initStaging(config) {
    stageModal = config.stageModal;
    stagedBadge = config.stagedBadge;
    stageBtn = config.stageBtn;
    reviewBtn = config.reviewBtn;
    onOpenNewFolderModal = config.onOpenNewFolderModal;
    beforeUnloadHandler = config.beforeUnloadHandler;
}

/**
 * Open the stage modal for email staging.
 */
export function openStageModal() {
    if (state.selectedEmails.size === 0) return;
    
    const modal = document.getElementById('stageModal');
    if (!modal) return;
    
    // Reset modal for email staging
    const title = document.getElementById('stageModalTitle');
    if (title) {
        title.innerHTML = `Stage <span id="stageCount">${state.selectedEmails.size}</span> Email(s)`;
    }
    
    const desc = document.getElementById('stageModalDesc');
    if (desc) {
        desc.textContent = 'Select destination folder:';
    }
    
    selectedDestinationFolder = null;
    modal.dataset.stagingMode = '';
    
    renderFolderSelectTree();
    
    document.getElementById('confirmStageBtn').disabled = true;
    modal.classList.add('active');
}

/**
 * Render hierarchical folder tree in the stage modal.
 */
export function renderFolderSelectTree() {
    const list = document.getElementById('folderSelectList');
    if (!list) return;
    
    renderFolderTree(list, {
        showNewFolder: true,
        itemClass: 'folder-select-item',
        onSelect: (id) => {
            selectedDestinationFolder = id;
            document.getElementById('confirmStageBtn').disabled = false;
        },
        onNewFolder: () => {
            if (onOpenNewFolderModal) onOpenNewFolderModal(true);
        },
    });
}

/**
 * Legacy handler for folder selection (inline onclick compatibility).
 */
export function handleFolderSelect(e) {
    const item = e.target.closest('.folder-select-item');
    if (!item) return;
    
    if (item.dataset.action === 'new') {
        if (onOpenNewFolderModal) onOpenNewFolderModal(true);
        return;
    }
    
    document.querySelectorAll('.folder-select-item').forEach(i => i.classList.remove('selected'));
    item.classList.add('selected');
    
    selectedDestinationFolder = item.dataset.id;
    document.getElementById('confirmStageBtn').disabled = false;
}

/**
 * Get folder name from full path.
 * Handles both filesystem paths and IMAP folder names.
 */
function getFolderName(fullPath) {
    // Handle Apple mbox paths like "/path/to/Folder.mbox"
    if (fullPath.includes('/')) {
        const name = fullPath.split('/').pop();
        // Remove .mbox extension if present
        return name.replace(/\.mbox$/, '');
    }
    // Handle IMAP folder paths like "INBOX/Subfolder"
    if (fullPath.includes('.')) {
        return fullPath.split('.').pop();
    }
    return fullPath;
}

/**
 * Compute archive paths for staged folders.
 * 
 * For each folder, determines the archive path based on whether its ancestors
 * are also being staged to the same destination:
 * - If ancestor is staged: preserve relative hierarchy (Parent/Child)
 * - If no ancestor staged: just the folder name (Child)
 * 
 * @param {string[]} folderPaths - All folder paths being staged
 * @param {string} sourceType - 'import' or 'account'
 * @param {string} importId - Import ID (for imports)
 * @returns {Object} Map of fullPath -> archivePath
 */
function computeArchivePaths(folderPaths, sourceType, importId) {
    const archivePaths = {};
    
    // Sort by path length (shortest first) to process ancestors before descendants
    const sorted = [...folderPaths].sort((a, b) => a.length - b.length);
    
    for (const path of sorted) {
        const folderName = getFolderName(path);
        
        // Find if any ancestor path is also being staged
        let ancestorPath = null;
        for (const otherPath of sorted) {
            if (otherPath !== path && path.startsWith(otherPath + '/')) {
                // otherPath is an ancestor of path
                // Use the longest matching ancestor (most immediate parent)
                if (!ancestorPath || otherPath.length > ancestorPath.length) {
                    ancestorPath = otherPath;
                }
            }
        }
        
        if (ancestorPath && archivePaths[ancestorPath]) {
            // Ancestor is staged - build relative path
            archivePaths[path] = archivePaths[ancestorPath] + '/' + folderName;
        } else {
            // No ancestor staged - just use folder name
            archivePaths[path] = folderName;
        }
    }
    
    return archivePaths;
}

/**
 * Confirm staging - handles both email and folder staging.
 */
export function confirmStage() {
    if (!selectedDestinationFolder) return;
    
    const modal = document.getElementById('stageModal');
    const stagingMode = modal?.dataset.stagingMode;
    
    if (stagingMode === 'folders') {
        // Staging entire folders
        const pending = getPendingFolderStaging();
        if (!pending) return;
        
        // Compute archive paths based on hierarchy
        const archivePaths = computeArchivePaths(
            pending.folders, 
            pending.sourceType, 
            pending.importId
        );
        
        // Add each folder as a separate entry with its destination and archive path
        pending.folders.forEach(folder => {
            // Check for duplicates based on source type
            let exists = false;
            if (pending.sourceType === 'import') {
                exists = state.stagedFolders.some(
                    sf => sf.sourceType === 'import' && sf.importId === pending.importId && sf.folder === folder
                );
            } else {
                exists = state.stagedFolders.some(
                    sf => sf.sourceType !== 'import' && sf.accountId === pending.accountId && sf.folder === folder
                );
            }
            
            if (!exists) {
                const archivePath = archivePaths[folder] || getFolderName(folder);
                
                if (pending.sourceType === 'import') {
                    state.stagedFolders.push({
                        sourceType: 'import',
                        importId: pending.importId,
                        folder: folder,
                        archivePath: archivePath,
                        destinationFolderId: selectedDestinationFolder
                    });
                } else {
                    state.stagedFolders.push({
                        sourceType: 'account',
                        accountId: pending.accountId,
                        folder: folder,
                        archivePath: archivePath,
                        destinationFolderId: selectedDestinationFolder
                    });
                }
            }
        });
        
        clearPendingFolderStaging();
        modal.dataset.stagingMode = '';
        closeModal('stageModal');
        updateStagedBadge();
        updateButtonStates();
        showAlert('Folders Staged', `${pending.folders.length} folder(s) staged for archiving. Go to Staged Items to commit.`);
        return;
    }
    
    // Normal email staging
    if (!state.currentView) return;
    
    state.selectedEmails.forEach(emailId => {
        const email = state.emails.find(e => (e.uid || e.id) === emailId);
        if (email) {
            const stagedItem = {
                email,
                destinationFolderId: selectedDestinationFolder,
            };
            
            // Track source based on view type
            if (state.currentView.type === 'account') {
                stagedItem.sourceType = 'imap';
                stagedItem.sourceAccountId = state.currentView.id;
                stagedItem.sourceFolder = state.currentView.folder || 'INBOX';
            } else if (state.currentView.type === 'import') {
                stagedItem.sourceType = 'import';
                stagedItem.sourceImportId = state.currentView.id;
                stagedItem.sourceFolder = state.currentView.folder || null;
            }
            
            state.staged.set(emailId, stagedItem);
        }
    });
    
    state.selectedEmails.clear();
    closeModal('stageModal');
    
    updateStagedBadge();
    updateButtonStates();
    renderEmailList();
}

/**
 * Update the staged items badge count.
 */
export function updateStagedBadge() {
    if (!stagedBadge) return;
    
    let count = state.staged.size + state.stagedFolders.length;
    
    stagedBadge.textContent = count;
    stagedBadge.classList.toggle('hidden', count === 0);
}

/**
 * Update stage button state and text based on current selection.
 */
export function updateButtonStates() {
    // Re-query buttons in case they were recreated
    const currentStageBtn = document.getElementById('stageBtn');
    
    if (currentStageBtn) {
        // Allow staging from account (IMAP) or import views
        const viewType = state.currentView?.type;
        const canStage = (viewType === 'account' || viewType === 'import') && state.selectedEmails.size > 0;
        currentStageBtn.disabled = !canStage;
        
        // Update button text with count
        const count = state.selectedEmails.size;
        const textSpan = currentStageBtn.querySelector('span') || currentStageBtn.lastChild;
        if (textSpan) {
            if (textSpan.nodeType === Node.TEXT_NODE) {
                textSpan.textContent = count > 0 ? ` Stage ${count} Email${count !== 1 ? 's' : ''}` : ' Stage Selected';
            } else {
                textSpan.textContent = count > 0 ? `Stage ${count} Email${count !== 1 ? 's' : ''}` : 'Stage Selected';
            }
        }
    }
}

/**
 * Navigate to review page with staged items.
 * Always navigates, even if nothing is staged (shows empty state).
 */
export function goToReview() {
    const hasEmails = state.staged.size > 0;
    const hasFolders = state.stagedFolders.length > 0;
    
    if (hasEmails) {
        sessionStorage.setItem('stagedEmails', JSON.stringify([...state.staged.entries()]));
    }
    
    if (hasFolders) {
        sessionStorage.setItem('stagedFolders', JSON.stringify(state.stagedFolders));
    }
    
    if (beforeUnloadHandler) {
        window.removeEventListener('beforeunload', beforeUnloadHandler);
    }
    window.location.href = '/review';
}

/**
 * Get the currently selected destination folder ID.
 */
export function getSelectedDestinationFolder() {
    return selectedDestinationFolder;
}

/**
 * Set the selected destination folder ID (used by new folder creation).
 */
export function setSelectedDestinationFolder(id) {
    selectedDestinationFolder = id;
}

/**
 * Get the staged emails Map.
 */
export function getStagedEmails() {
    return state.staged;
}

/**
 * Get the staged folders array.
 */
export function getStagedFolders() {
    return state.stagedFolders;
}

/**
 * Clear a staged email by ID.
 */
export function clearStagedEmail(emailId) {
    state.staged.delete(emailId);
    sessionStorage.setItem('stagedEmails', JSON.stringify([...state.staged.entries()]));
}

/**
 * Clear a staged folder by index.
 */
export function clearStagedFolder(index) {
    state.stagedFolders.splice(index, 1);
    sessionStorage.setItem('stagedFolders', JSON.stringify(state.stagedFolders));
}

/**
 * Clear all staged items.
 */
export function clearAllStaged() {
    state.staged.clear();
    state.stagedFolders = [];
    sessionStorage.removeItem('stagedEmails');
    sessionStorage.removeItem('stagedFolders');
}
