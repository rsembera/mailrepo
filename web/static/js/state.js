/**
 * MailRepo - Central State Management
 */

import { showConfirm } from './modals.js';

// Reference to folder selection state (set by folder-mgmt.js)
let getSelectedFoldersCount = () => 0;
let clearSelectedFolders = () => {};

export function setSelectedFoldersGetter(fn) {
    getSelectedFoldersCount = fn;
}

export function setSelectedFoldersClearer(fn) {
    clearSelectedFolders = fn;
}

/**
 * Application state object.
 * @type {Object}
 */
export const state = {
    currentView: null,      // { type: 'account'|'folder', id: number, label?: string }
    emails: [],
    staged: new Map(),      // Map<emailId, {email, destinationFolderId, sourceAccountId, sourceFolder}>
    stagedFolders: [],      // Array<{accountId, folder, destinationFolderId}> for bulk folder staging
    selectedEmails: new Set(),
    folders: [],
    expandedAccounts: new Set(),
};

/**
 * Check if there are unsaved selections that would be lost on navigation.
 * Returns true if navigation should proceed, false if cancelled.
 */
export async function confirmNavigation() {
    const emailCount = state.selectedEmails.size;
    const folderCount = getSelectedFoldersCount();
    
    if (emailCount === 0 && folderCount === 0) {
        return true; // No selections, proceed
    }
    
    const parts = [];
    if (emailCount > 0) parts.push(`${emailCount} email${emailCount !== 1 ? 's' : ''}`);
    if (folderCount > 0) parts.push(`${folderCount} folder${folderCount !== 1 ? 's' : ''}`);
    
    const confirmed = await showConfirm(
        'Unsaved Selections',
        `You have ${parts.join(' and ')} selected but not staged. Leave anyway?`,
        { confirmText: 'Leave', cancelText: 'Stay', confirmClass: 'btn-danger' }
    );
    
    if (confirmed) {
        // Clear selections
        state.selectedEmails.clear();
        clearSelectedFolders();
    }
    
    return confirmed;
}

/**
 * Load folders from the server into state.
 * @returns {Promise<void>}
 */
export async function loadFolders() {
    try {
        const response = await fetch('/api/folders');
        if (response.ok) {
            const data = await response.json();
            state.folders = data.folders || [];
        }
    } catch (e) {
        console.error('Failed to load folders:', e);
    }
}
