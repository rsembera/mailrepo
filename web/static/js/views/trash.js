/**
 * MailRepo - Trash View
 * 
 * Handles:
 * - Trash view display (folders and emails)
 * - Folder restore
 * - Email restore
 * - Permanent deletion
 * - Empty trash
 * - Search and sort
 */

import { escapeHtml, formatDate, extractName } from '../utils.js';
import { state, loadFolders } from '../state.js';
import { showConfirm, showAlert } from '../modals.js';
import { refreshSidebarFolders } from '../components/sidebar.js';

// DOM references
let contextTitle = null;
let contextMeta = null;
let emailList = null;

// Sort/filter state
let currentSort = 'date-desc';  // 'date-desc', 'date-asc', 'name-asc', 'name-desc'
let searchQuery = '';
let currentTab = 'folders';  // 'folders' or 'emails'
let trashedEmails = [];

/**
 * Get folders that should appear in Trash view.
 * Shows trashed folders that are either:
 * - Top-level (no parent), OR
 * - Their parent is NOT trashed (child was deleted independently)
 */
function getVisibleTrashedFolders() {
    return state.folders.filter(f => {
        if (!f.deleted_at) return false;
        if (!f.parent_id) return true;
        const parent = state.folders.find(p => p.id == f.parent_id);
        return !parent || !parent.deleted_at;
    });
}

/**
 * Initialize trash view.
 */
export function initTrashView(config) {
    contextTitle = config.contextTitle;
    contextMeta = config.contextMeta;
    emailList = config.emailList;
}

/**
 * Show the trash view.
 */
export async function showTrashView() {
    const sidebar = document.getElementById('sidebar');
    const toolbar = document.querySelector('.content-toolbar');
    const headerActions = document.querySelector('.header-actions');
    const subfoldersBar = document.getElementById('subfoldersBar');
    
    sidebar.style.display = 'none';
    if (toolbar) toolbar.style.display = 'none';
    if (headerActions) headerActions.style.display = 'none';
    if (subfoldersBar) subfoldersBar.style.display = 'none';
    
    if (contextTitle) contextTitle.textContent = 'Trash';
    if (contextMeta) contextMeta.textContent = '';
    
    await loadFolders();
    await loadTrashedEmails();
    
    renderTrashView();
    updateTrashBadge();
}

/**
 * Load trashed emails from the server.
 */
async function loadTrashedEmails() {
    try {
        const response = await fetch('/api/trash/emails');
        if (response.ok) {
            const data = await response.json();
            trashedEmails = data.emails || [];
        }
    } catch (error) {
        console.error('Error loading trashed emails:', error);
        trashedEmails = [];
    }
}

/**
 * Render the trash view with current filters/sort.
 */
function renderTrashView() {
    const trashedFolders = getVisibleTrashedFolders();
    const folderCount = trashedFolders.length;
    const emailCount = trashedEmails.length;
    
    if (folderCount === 0 && emailCount === 0) {
        emailList.innerHTML = `
            <div class="empty-state">
                <i data-lucide="trash-2" class="empty-icon"></i>
                <h3>Trash is Empty</h3>
                <p>Items you delete will appear here.</p>
            </div>
        `;
        if (contextMeta) contextMeta.textContent = '';
    } else {
        if (currentTab === 'folders') {
            renderFoldersTab(trashedFolders);
        } else {
            renderEmailsTab();
        }
    }
    
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

/**
 * Sort folders based on current sort setting.
 */
function sortFolders(folders) {
    return [...folders].sort((a, b) => {
        switch (currentSort) {
            case 'date-desc':
                return b.deleted_at - a.deleted_at;
            case 'date-asc':
                return a.deleted_at - b.deleted_at;
            case 'name-asc':
                return a.name.localeCompare(b.name);
            case 'name-desc':
                return b.name.localeCompare(a.name);
            default:
                return b.deleted_at - a.deleted_at;
        }
    });
}

/**
 * Render tabs header.
 */
function renderTabsHeader() {
    const folderCount = getVisibleTrashedFolders().length;
    const emailCount = trashedEmails.length;
    
    return `
        <div class="trash-tabs">
            <button class="trash-tab ${currentTab === 'folders' ? 'active' : ''}" onclick="switchTrashTab('folders')">
                Folders${folderCount > 0 ? ` (${folderCount})` : ''}
            </button>
            <button class="trash-tab ${currentTab === 'emails' ? 'active' : ''}" onclick="switchTrashTab('emails')">
                Emails${emailCount > 0 ? ` (${emailCount})` : ''}
            </button>
        </div>
    `;
}

function renderFoldersTab(allTrashedFolders) {
    let trashedFolders = [...allTrashedFolders];
    
    // Apply search filter
    if (searchQuery) {
        const query = searchQuery.toLowerCase();
        trashedFolders = trashedFolders.filter(f => f.name.toLowerCase().includes(query));
    }
    
    // Apply sort
    trashedFolders = sortFolders(trashedFolders);
    
    const totalCount = allTrashedFolders.length;
    const showingFiltered = searchQuery && trashedFolders.length !== totalCount;
    
    // Update context meta with count
    const contextMeta = document.getElementById('contextMeta');
    if (contextMeta) {
        if (showingFiltered) {
            contextMeta.textContent = `${trashedFolders.length} of ${totalCount} deleted folders`;
        } else {
            contextMeta.textContent = `${totalCount} deleted folder${totalCount !== 1 ? 's' : ''}`;
        }
    }
    
    let html = `
        <div class="trash-management-list">
            ${renderTabsHeader()}
            <div class="trash-management-toolbar">
                <div class="trash-toolbar-left">
                    <div class="trash-search">
                        <i data-lucide="search" class="search-icon"></i>
                        <input type="text" 
                               id="trashSearch" 
                               placeholder="Search folders..." 
                               value="${escapeHtml(searchQuery)}"
                               oninput="handleTrashSearch(this.value)">
                        ${searchQuery ? '<button class="search-clear" onclick="clearTrashSearch()"><i data-lucide="x"></i></button>' : ''}
                    </div>
                    <select id="trashSort" class="trash-sort" onchange="handleTrashSort(this.value)">
                        <option value="date-desc" ${currentSort === 'date-desc' ? 'selected' : ''}>Newest first</option>
                        <option value="date-asc" ${currentSort === 'date-asc' ? 'selected' : ''}>Oldest first</option>
                        <option value="name-asc" ${currentSort === 'name-asc' ? 'selected' : ''}>Name A-Z</option>
                        <option value="name-desc" ${currentSort === 'name-desc' ? 'selected' : ''}>Name Z-A</option>
                    </select>
                </div>
                <button class="btn btn-danger" onclick="emptyTrash()">
                    <i data-lucide="trash-2"></i>
                    Delete Folders
                </button>
            </div>
    `;
    
    if (trashedFolders.length === 0) {
        html += `
            <div class="empty-state" style="padding: var(--space-xl);">
                <p>No folders match "${escapeHtml(searchQuery)}"</p>
            </div>
        `;
    } else {
        html += `
            <div class="trash-management-header">
                <span>Folder</span>
                <span>Deleted</span>
                <span>Actions</span>
            </div>
        `;
        trashedFolders.forEach(folder => {
            html += renderTrashItem(folder);
        });
    }
    
    html += `
        </div>
    `;
    
    emailList.innerHTML = html;
}

function renderTrashItem(folder) {
    const deletedDate = new Date(folder.deleted_at * 1000);
    
    // Count ALL descendants recursively
    function countDescendants(parentId) {
        const children = state.folders.filter(f => f.parent_id == parentId);
        let count = children.length;
        children.forEach(c => count += countDescendants(c.id));
        return count;
    }
    const descendantCount = countDescendants(folder.id);
    
    return `
        <div class="trash-management-item" data-id="${folder.id}">
            <div class="trash-management-name">
                <i data-lucide="folder" class="folder-icon"></i>
                <span class="folder-label">${escapeHtml(folder.name)}</span>
                ${descendantCount > 0 ? `<span class="subfolder-count">(+${descendantCount})</span>` : ''}
            </div>
            <div class="trash-management-date">
                ${formatDate(deletedDate)}
            </div>
            <div class="trash-management-actions">
                <button class="btn btn-sm btn-icon" onclick="restoreFolder(${folder.id})" title="Restore">
                    <i data-lucide="undo-2"></i>
                </button>
                <button class="btn btn-sm btn-icon btn-danger-subtle" onclick="permanentlyDeleteFolder(${folder.id})" title="Delete permanently">
                    <i data-lucide="x"></i>
                </button>
            </div>
        </div>
    `;
}

/**
 * Render the emails tab.
 */
function renderEmailsTab() {
    let emails = [...trashedEmails];
    
    // Apply search filter
    if (searchQuery) {
        const query = searchQuery.toLowerCase();
        emails = emails.filter(e => 
            (e.subject || '').toLowerCase().includes(query) ||
            (e.sender || '').toLowerCase().includes(query)
        );
    }
    
    // Apply sort
    emails = sortEmails(emails);
    
    const totalCount = trashedEmails.length;
    const showingFiltered = searchQuery && emails.length !== totalCount;
    
    // Update context meta
    const contextMeta = document.getElementById('contextMeta');
    if (contextMeta) {
        if (showingFiltered) {
            contextMeta.textContent = `${emails.length} of ${totalCount} deleted emails`;
        } else {
            contextMeta.textContent = `${totalCount} deleted email${totalCount !== 1 ? 's' : ''}`;
        }
    }
    
    let html = `
        <div class="trash-management-list">
            ${renderTabsHeader()}
            <div class="trash-management-toolbar">
                <div class="trash-toolbar-left">
                    <div class="trash-search">
                        <i data-lucide="search" class="search-icon"></i>
                        <input type="text" 
                               id="trashSearch" 
                               placeholder="Search emails..." 
                               value="${escapeHtml(searchQuery)}"
                               oninput="handleTrashSearch(this.value)">
                        ${searchQuery ? '<button class="search-clear" onclick="clearTrashSearch()"><i data-lucide="x"></i></button>' : ''}
                    </div>
                    <select id="trashSort" class="trash-sort" onchange="handleTrashSort(this.value)">
                        <option value="date-desc" ${currentSort === 'date-desc' ? 'selected' : ''}>Newest first</option>
                        <option value="date-asc" ${currentSort === 'date-asc' ? 'selected' : ''}>Oldest first</option>
                        <option value="name-asc" ${currentSort === 'name-asc' ? 'selected' : ''}>Subject A-Z</option>
                        <option value="name-desc" ${currentSort === 'name-desc' ? 'selected' : ''}>Subject Z-A</option>
                    </select>
                </div>
                <button class="btn btn-danger" onclick="emptyTrashEmails()">
                    <i data-lucide="trash-2"></i>
                    Delete Emails
                </button>
            </div>
    `;
    
    if (emails.length === 0) {
        if (searchQuery) {
            html += `
                <div class="empty-state" style="padding: var(--space-xl);">
                    <p>No emails match "${escapeHtml(searchQuery)}"</p>
                </div>
            `;
        } else {
            html += `
                <div class="empty-state" style="padding: var(--space-xl);">
                    <p>No deleted emails</p>
                </div>
            `;
        }
    } else {
        html += `
            <div class="trash-management-header">
                <span>Email</span>
                <span>Deleted</span>
                <span>Actions</span>
            </div>
        `;
        emails.forEach(email => {
            html += renderTrashEmailItem(email);
        });
    }
    
    html += `</div>`;
    emailList.innerHTML = html;
}

/**
 * Sort emails based on current sort setting.
 */
function sortEmails(emails) {
    return [...emails].sort((a, b) => {
        switch (currentSort) {
            case 'date-desc':
                return b.deleted_at - a.deleted_at;
            case 'date-asc':
                return a.deleted_at - b.deleted_at;
            case 'name-asc':
                return (a.subject || '').localeCompare(b.subject || '');
            case 'name-desc':
                return (b.subject || '').localeCompare(a.subject || '');
            default:
                return b.deleted_at - a.deleted_at;
        }
    });
}

/**
 * Render a single trashed email item.
 */
function renderTrashEmailItem(email) {
    const deletedDate = new Date(email.deleted_at * 1000);
    
    return `
        <div class="trash-management-item trash-email-item" data-id="${email.id}">
            <div class="trash-management-name">
                <i data-lucide="mail" class="folder-icon"></i>
                <div class="trash-email-info">
                    <span class="email-sender">${escapeHtml(extractName(email.sender || ''))}</span>
                    <span class="email-subject">${escapeHtml(email.subject || '(no subject)')}</span>
                </div>
            </div>
            <div class="trash-management-date">
                ${formatDate(deletedDate)}
            </div>
            <div class="trash-management-actions">
                <button class="btn btn-sm btn-icon" onclick="restoreEmail(${email.id})" title="Restore">
                    <i data-lucide="undo-2"></i>
                </button>
                <button class="btn btn-sm btn-icon btn-danger-subtle" onclick="permanentlyDeleteEmail(${email.id})" title="Delete permanently">
                    <i data-lucide="x"></i>
                </button>
            </div>
        </div>
    `;
}

export async function restoreFolder(folderId) {
    try {
        const response = await fetch(`/api/folders/${folderId}/restore`, {
            method: 'POST',
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            showAlert('Error', data.error || 'Failed to restore folder');
            return;
        }
        
        const folder = state.folders.find(f => f.id == folderId);
        if (folder) {
            folder.deleted_at = null;
            if (data.folder && data.folder.name) {
                folder.name = data.folder.name;
            }
            // Recursively restore all descendants in state
            function restoreDescendants(parentId) {
                state.folders.filter(f => f.parent_id == parentId).forEach(child => {
                    child.deleted_at = null;
                    restoreDescendants(child.id);
                });
            }
            restoreDescendants(folderId);
        }
        
        showTrashView();
        refreshSidebarFolders();
        
        if (data.folder && data.folder.renamed) {
            showAlert('Folder Restored', `Folder restored as "${data.folder.name}" to avoid a naming conflict.`);
        }
    } catch (error) {
        console.error('Error restoring folder:', error);
        showAlert('Error', 'Failed to restore folder');
    }
}
window.restoreFolder = restoreFolder;

export async function permanentlyDeleteFolder(folderId) {
    const folder = state.folders.find(f => f.id == folderId);
    if (!folder) return;
    
    // Count ALL descendants recursively
    function countDescendants(parentId) {
        const children = state.folders.filter(f => f.parent_id == parentId);
        let count = children.length;
        children.forEach(c => count += countDescendants(c.id));
        return count;
    }
    const descendantCount = countDescendants(folderId);
    
    let message = `Permanently delete "${folder.name}"? This cannot be undone.`;
    if (descendantCount > 0) {
        message = `Permanently delete "${folder.name}" and ${descendantCount} subfolder${descendantCount > 1 ? 's' : ''}? This cannot be undone.`;
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
        
        // Recursively collect all descendant IDs
        function collectDescendantIds(parentId) {
            let ids = [parentId];
            state.folders.filter(f => f.parent_id == parentId).forEach(child => {
                ids = ids.concat(collectDescendantIds(child.id));
            });
            return ids;
        }
        const idsToRemove = collectDescendantIds(folderId);
        
        state.folders = state.folders.filter(f => !idsToRemove.includes(f.id));
        showTrashView();
    } catch (error) {
        console.error('Error deleting folder:', error);
        showAlert('Error', 'Failed to delete folder');
    }
}
window.permanentlyDeleteFolder = permanentlyDeleteFolder;

export async function emptyTrash() {
    const trashedFolders = getVisibleTrashedFolders();
    if (trashedFolders.length === 0) return;
    
    const message = `Permanently delete ${trashedFolders.length} folder${trashedFolders.length > 1 ? 's' : ''} and all their contents? This cannot be undone.`;
    
    const confirmed = await showConfirm('Delete All Folders', message, { okText: 'Delete All', okClass: 'btn-danger' });
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
        
        state.folders = state.folders.filter(f => !f.deleted_at);
        showTrashView();
    } catch (error) {
        console.error('Error emptying trash:', error);
        showAlert('Error', 'Failed to empty trash');
    }
}
window.emptyTrash = emptyTrash;

export async function updateTrashBadge() {
    const badge = document.getElementById('trashBadge');
    if (!badge) return;
    
    const trashedFolderCount = getVisibleTrashedFolders().length;
    
    // Fetch current trashed email count from server
    let trashedEmailCount = trashedEmails.length;
    try {
        const response = await fetch('/api/trash/emails');
        if (response.ok) {
            const data = await response.json();
            trashedEmails = data.emails || [];
            trashedEmailCount = trashedEmails.length;
        }
    } catch (error) {
        // Use cached count on error
    }
    
    const trashedCount = trashedFolderCount + trashedEmailCount;
    badge.textContent = trashedCount;
    badge.classList.toggle('hidden', trashedCount === 0);
}

/**
 * Handle search input.
 */
function handleTrashSearch(query) {
    searchQuery = query;
    renderTrashView();
    // Refocus the search input and restore cursor position
    const input = document.getElementById('trashSearch');
    if (input) {
        input.focus();
        input.setSelectionRange(query.length, query.length);
    }
}
window.handleTrashSearch = handleTrashSearch;

/**
 * Clear search.
 */
function clearTrashSearch() {
    searchQuery = '';
    renderTrashView();
    const input = document.getElementById('trashSearch');
    if (input) input.focus();
}
window.clearTrashSearch = clearTrashSearch;

/**
 * Handle sort change.
 */
function handleTrashSort(sort) {
    currentSort = sort;
    renderTrashView();
}
window.handleTrashSort = handleTrashSort;

/**
 * Switch between folders and emails tabs.
 */
function switchTrashTab(tab) {
    currentTab = tab;
    searchQuery = '';  // Clear search when switching tabs
    renderTrashView();
}
window.switchTrashTab = switchTrashTab;

/**
 * Restore an email from trash.
 */
async function restoreEmail(emailId) {
    try {
        const response = await fetch(`/api/messages/${emailId}/restore`, {
            method: 'POST',
        });
        
        if (!response.ok) {
            const data = await response.json();
            showAlert('Error', data.error || 'Failed to restore email');
            return;
        }
        
        // Remove from trashed emails and re-render
        trashedEmails = trashedEmails.filter(e => e.id != emailId);
        renderTrashView();
        updateTrashBadge();
    } catch (error) {
        console.error('Error restoring email:', error);
        showAlert('Error', 'Failed to restore email');
    }
}
window.restoreEmail = restoreEmail;

/**
 * Permanently delete an email.
 */
async function permanentlyDeleteEmail(emailId) {
    const email = trashedEmails.find(e => e.id == emailId);
    if (!email) return;
    
    const confirmed = await showConfirm(
        'Delete Permanently',
        `Permanently delete "${email.subject || '(no subject)'}"? This cannot be undone.`,
        { okText: 'Delete', okClass: 'btn-danger' }
    );
    if (!confirmed) return;
    
    try {
        const response = await fetch(`/api/messages/${emailId}/permanent`, {
            method: 'DELETE',
        });
        
        if (!response.ok) {
            const data = await response.json();
            showAlert('Error', data.error || 'Failed to delete email');
            return;
        }
        
        trashedEmails = trashedEmails.filter(e => e.id != emailId);
        renderTrashView();
        updateTrashBadge();
    } catch (error) {
        console.error('Error deleting email:', error);
        showAlert('Error', 'Failed to delete email');
    }
}
window.permanentlyDeleteEmail = permanentlyDeleteEmail;

/**
 * Empty all trashed emails.
 */
async function emptyTrashEmails() {
    if (trashedEmails.length === 0) return;
    
    const confirmed = await showConfirm(
        'Delete All Emails',
        `Permanently delete ${trashedEmails.length} email${trashedEmails.length !== 1 ? 's' : ''}? This cannot be undone.`,
        { okText: 'Delete All', okClass: 'btn-danger' }
    );
    if (!confirmed) return;
    
    try {
        // Delete each email
        for (const email of trashedEmails) {
            await fetch(`/api/messages/${email.id}/permanent`, {
                method: 'DELETE',
            });
        }
        
        trashedEmails = [];
        renderTrashView();
        updateTrashBadge();
    } catch (error) {
        console.error('Error emptying trash:', error);
        showAlert('Error', 'Failed to empty trash');
    }
}
window.emptyTrashEmails = emptyTrashEmails;
