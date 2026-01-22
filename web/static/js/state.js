/**
 * MailRepo - Central State Management
 */

/**
 * Application state object.
 * @type {Object}
 */
export const state = {
    currentView: null,      // { type: 'account'|'folder', id: number, label?: string }
    emails: [],
    staged: new Map(),      // Map<emailId, {email, destinationFolderId, sourceAccountId, sourceFolder}>
    stagedFolders: null,    // { accountId, folders: [], destinationFolderId } for bulk folder staging
    selectedEmails: new Set(),
    folders: [],
    expandedAccounts: new Set(),
};

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
