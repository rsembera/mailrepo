/**
 * MailRepo - Central State Management
 */

import { showConfirm } from './modals.js';
import { stagedKeyInView, stagedKeyOfItem } from './staged-key.js';

// Reference to folder selection state (set by folder-mgmt.js)
let getSelectedFoldersCount = () => 0;
let clearSelectedFolders = () => {};

// Reference to backup unsaved changes checker (set by backups.js)
let checkBackupsUnsaved = () => false;
let clearBackupsUnsaved = () => {};

// Reference to staged badge element (set by staging.js)
let stagedBadgeElement = null;

export function setSelectedFoldersGetter(fn) {
    getSelectedFoldersCount = fn;
}

export function setSelectedFoldersClearer(fn) {
    clearSelectedFolders = fn;
}

export function setBackupsUnsavedChecker(fn) {
    checkBackupsUnsaved = fn;
}

export function setBackupsUnsavedClearer(fn) {
    clearBackupsUnsaved = fn;
}

export function setStagedBadgeElement(el) {
    stagedBadgeElement = el;
}

/**
 * Update the staged items badge count.
 */
export function updateStagedBadge() {
    if (!stagedBadgeElement) return;
    
    const count = state.staged.size + state.stagedFolders.length;
    stagedBadgeElement.textContent = count;
    stagedBadgeElement.classList.toggle('hidden', count === 0);
}

/**
 * Application state object.
 * @type {Object}
 */
export const state = {
    currentView: null,      // { type: 'account'|'folder', id: number, label?: string }
    // Which top-level screen currently owns the shared #emailList content area
    // ('mail' | 'review' | 'settings' | 'vault' | 'trash' | 'starred' |
    // 'backups' | 'folderSelection'). Each show*View sets this so async
    // callbacks (e.g. thread staging) can repaint the active screen instead of
    // clobbering it with another view's content.
    activeScreen: 'mail',
    emails: [],
    // Emails filed in the current archive folder's subfolders rather than in
    // the folder itself. Set when an archive folder loads; read by the empty
    // state so a folder holding only subfolders does not claim to be empty.
    nestedEmailCount: 0,
    // True while the toolbar search box is narrowing the list. The empty
    // state reads it so "no matches" is not reported as "folder is empty".
    searchFilterActive: false,
    staged: new Map(),      // Map<emailId, {email, destinationFolderId, sourceAccountId, sourceFolder}>
    stagedFolders: [],      // Array<{accountId, folder, destinationFolderId}> for bulk folder staging
    selectedEmails: new Set(),
    folders: [],
    expandedAccounts: new Set(),
    imapFolders: new Map(), // Map<accountId, {folders: [], tree: {}}>
};

/**
 * Is this email, as shown in the current view, staged?
 * @param {number|string} emailId - email.uid || email.id
 * @returns {boolean}
 */
export function isStagedInView(emailId) {
    const key = stagedKeyInView(state.currentView, emailId);
    return key !== null && state.staged.has(key);
}

/**
 * Remove this email, as shown in the current view, from the staged set.
 * @param {number|string} emailId - email.uid || email.id
 * @returns {boolean} true if it was staged
 */
export function unstageInView(emailId) {
    const key = stagedKeyInView(state.currentView, emailId);
    if (key === null || !state.staged.delete(key)) return false;
    persistStaged();
    return true;
}

/**
 * Write the staged emails and folders to sessionStorage, so they survive
 * a page load (an idle lock sends the page to the login screen). The one
 * place that writes them: an empty set removes the entry, so nothing that
 * was unstaged can come back on the next load.
 */
export function persistStaged() {
    try {
        if (state.staged.size > 0) {
            sessionStorage.setItem('stagedEmails', JSON.stringify([...state.staged.entries()]));
        } else {
            sessionStorage.removeItem('stagedEmails');
        }
        if (state.stagedFolders.length > 0) {
            sessionStorage.setItem('stagedFolders', JSON.stringify(state.stagedFolders));
        } else {
            sessionStorage.removeItem('stagedFolders');
        }
    } catch (e) {
        // Storage full or unavailable: the staged set still lives in
        // memory for this page.
        console.warn('Could not persist staged items:', e);
    }
}

/**
 * Remove everything staged from one import. Used when a PST import is
 * unmounted: its converted files are deleted with it, so what was staged
 * from it could no longer be read.
 * @param {string} importId
 * @returns {number} how many staged emails and folders were removed
 */
export function unstageImport(importId) {
    let removed = 0;
    for (const [key, item] of [...state.staged.entries()]) {
        if (item.sourceType === 'import' && item.sourceImportId === importId) {
            state.staged.delete(key);
            removed += 1;
        }
    }
    const kept = state.stagedFolders.filter(
        sf => !(sf.sourceType === 'import' && sf.importId === importId)
    );
    removed += state.stagedFolders.length - kept.length;
    state.stagedFolders = kept;
    if (removed > 0) persistStaged();
    return removed;
}

/** A PST import: its files exist only while the page that mounted it does. */
function isPstImport(importId) {
    return typeof importId === 'string' && importId.startsWith('pst-');
}

/**
 * Load the staged emails and folders saved by persistStaged().
 *
 * Items staged from a PST import are not restored: a page load means the
 * import is no longer mounted, and its converted files are removed when
 * the archive locks.
 */
export function restoreStaged() {
    try {
        const savedEmails = sessionStorage.getItem('stagedEmails');
        if (savedEmails) {
            // Keys are rebuilt from the entries rather than trusted.
            const items = JSON.parse(savedEmails).map(entry => entry[1])
                .filter(item => !(item.sourceType === 'import' && isPstImport(item.sourceImportId)));
            state.staged = new Map(items.map(item => [stagedKeyOfItem(item), item]));
        }
    } catch (e) {
        console.error('Failed to restore staged emails:', e);
    }
    try {
        const savedFolders = sessionStorage.getItem('stagedFolders');
        if (savedFolders) {
            const parsed = JSON.parse(savedFolders);
            state.stagedFolders = (Array.isArray(parsed) ? parsed : [])
                .filter(sf => !(sf.sourceType === 'import' && isPstImport(sf.importId)));
        }
    } catch (e) {
        console.error('Failed to restore staged folders:', e);
    }
}

/**
 * Check if there are unsaved selections that would be lost on navigation.
 * Returns true if navigation should proceed, false if cancelled.
 */
export async function confirmNavigation() {
    const emailCount = state.selectedEmails.size;
    const folderCount = getSelectedFoldersCount();
    const hasBackupsUnsaved = checkBackupsUnsaved();
    
    // Check backup settings first (separate dialog)
    if (hasBackupsUnsaved) {
        const confirmed = await showConfirm(
            'Unsaved Settings',
            'You have unsaved backup settings. Leave without saving?',
            { confirmText: 'Leave', cancelText: 'Stay', confirmClass: 'btn-danger' }
        );
        
        if (!confirmed) {
            return false;
        }
        clearBackupsUnsaved();
    }
    
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
