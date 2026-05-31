/**
 * MailRepo - Trash View
 *
 * Shows trashed folders (Folders tab) and trashed emails (Emails tab)
 * with restore + permanent-delete actions for each. The tab + filter +
 * sort state is module-local and survives renders.
 *
 * Click/input handling uses delegate.js -- no inline onclick/oninput,
 * no window exports. Render is split into shell (tabs + toolbar) and
 * list so typing in the filter doesn\'t replace the search input DOM
 * node and lose focus.
 */

import { escapeHtml, formatDate, extractName } from '../utils.js';
import { state, loadFolders } from '../state.js';
import { showConfirm, showAlert } from '../modals.js';
import { refreshSidebarFolders } from '../components/sidebar.js';
import { bindActions } from '../delegate.js';

// DOM references
let contextTitle = null;
let contextMeta = null;
let emailList = null;

// Sort/filter state
let currentSort = 'date-desc';  // 'date-desc', 'date-asc', 'name-asc', 'name-desc', and for emails 'sender-asc'/'sender-desc'
let searchQuery = '';
let currentTab = 'folders';     // 'folders' or 'emails'
let trashedEmails = [];

// ============================================================
// HELPERS
// ============================================================

/**
 * Get folders that should appear in Trash view.
 * Shows trashed folders that are either:
 *   - Top-level (no parent), OR
 *   - Their parent is NOT trashed (child was deleted independently)
 */
function getVisibleTrashedFolders() {
    return state.folders.filter(f => {
        if (!f.deleted_at) return false;
        if (!f.parent_id) return true;
        const parent = state.folders.find(p => p.id == f.parent_id);
        return !parent || !parent.deleted_at;
    });
}

function sortFolders(folders) {
    return [...folders].sort((a, b) => {
        switch (currentSort) {
            case 'date-desc': return b.deleted_at - a.deleted_at;
            case 'date-asc':  return a.deleted_at - b.deleted_at;
            case 'name-asc':  return a.name.localeCompare(b.name);
            case 'name-desc': return b.name.localeCompare(a.name);
            default:          return b.deleted_at - a.deleted_at;
        }
    });
}

function sortEmails(emails) {
    return [...emails].sort((a, b) => {
        switch (currentSort) {
            case 'date-desc':   return b.deleted_at - a.deleted_at;
            case 'date-asc':    return a.deleted_at - b.deleted_at;
            case 'sender-asc':  return (a.sender  || '').localeCompare(b.sender  || '');
            case 'sender-desc': return (b.sender  || '').localeCompare(a.sender  || '');
            case 'name-asc':    return (a.subject || '').localeCompare(b.subject || '');
            case 'name-desc':   return (b.subject || '').localeCompare(a.subject || '');
            default:            return b.deleted_at - a.deleted_at;
        }
    });
}

function filteredAndSortedFolders() {
    let folders = getVisibleTrashedFolders();
    if (searchQuery) {
        const q = searchQuery.toLowerCase();
        folders = folders.filter(f => f.name.toLowerCase().includes(q));
    }
    return sortFolders(folders);
}

function filteredAndSortedEmails() {
    let emails = [...trashedEmails];
    if (searchQuery) {
        const q = searchQuery.toLowerCase();
        emails = emails.filter(e =>
            (e.subject || '').toLowerCase().includes(q) ||
            (e.sender  || '').toLowerCase().includes(q)
        );
    }
    return sortEmails(emails);
}

// ============================================================
// LIFECYCLE / DATA LOADING
// ============================================================

/** Initialize trash view. Just stash DOM refs; actions are bound inside
 *  renderShell() on a view-specific root so they die with the view when
 *  another view's render replaces emailList's inner HTML. */
export function initTrashView(config) {
    contextTitle = config.contextTitle;
    contextMeta = config.contextMeta;
    emailList = config.emailList;
}

/** Show the trash view. */
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

    // Render immediately with cached state so the previous view's content
    // doesn't stay visible during the loadFolders + loadTrashedEmails
    // round-trips. Two renders total: this one shows cached/empty data
    // instantly, the post-fetch one updates with the loaded data.
    renderTrashView();

    await loadFolders();
    await loadTrashedEmails();

    renderTrashView();
    updateTrashBadge();
}

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

// ============================================================
// RENDER (split: shell + list)
// ============================================================

/**
 * Top-level render. Dispatches to:
 *   - empty state if nothing in trash
 *   - shell + list otherwise
 *
 * The shell (tabs + toolbar) is only re-rendered when the active tab
 * changes, since tab-switching changes the toolbar (search placeholder,
 * sort options, delete-all label). Filter/sort changes within a tab
 * only update the list -- the search input stays in the DOM so focus
 * and cursor position are naturally preserved.
 */
function renderTrashView() {
    const folderCount = getVisibleTrashedFolders().length;
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
        if (typeof lucide !== 'undefined') lucide.createIcons();
        return;
    }

    // Build the shell if not present, or if the current tab differs from
    // the one the existing shell was built for. Cheap to check.
    const listEl = document.getElementById('trashList');
    const shellTab = listEl ? listEl.dataset.tab : null;
    if (!listEl || shellTab !== currentTab) {
        renderShell();
    }

    renderList();
    updateTrashMeta();
}

/** Build tabs + toolbar + list container. Sensitive to currentTab. */
function renderShell() {
    const folderCount = getVisibleTrashedFolders().length;
    const emailCount = trashedEmails.length;
    const isEmails = currentTab === 'emails';

    const placeholder = isEmails ? 'Search emails...' : 'Search folders...';
    const deleteAction = isEmails ? 'emptyEmails' : 'emptyFolders';
    const deleteLabel = isEmails ? 'Delete Emails' : 'Delete Folders';
    const clearHidden = searchQuery ? '' : 'hidden';

    const sortOptions = isEmails
        ? [['date-desc', 'Newest first'], ['date-asc', 'Oldest first'],
           ['sender-asc', 'Sender A–Z'], ['sender-desc', 'Sender Z–A'],
           ['name-asc', 'Subject A–Z'], ['name-desc', 'Subject Z–A']]
        : [['date-desc', 'Newest first'], ['date-asc', 'Oldest first'],
           ['name-asc', 'Name A–Z'], ['name-desc', 'Name Z–A']];

    emailList.innerHTML = `
        <div class="trash-management-list trash-view-root">
            <div class="trash-tabs">
                <button class="trash-tab ${!isEmails ? 'active' : ''}"
                        data-action="switchTab" data-tab="folders">
                    Folders${folderCount > 0 ? ` (${folderCount})` : ''}
                </button>
                <button class="trash-tab ${isEmails ? 'active' : ''}"
                        data-action="switchTab" data-tab="emails">
                    Emails${emailCount > 0 ? ` (${emailCount})` : ''}
                </button>
            </div>
            <div class="trash-management-toolbar">
                <div class="trash-toolbar-left">
                    <div class="trash-search">
                        <i data-lucide="search" class="search-icon"></i>
                        <input type="text"
                               id="trashSearch"
                               placeholder="${placeholder}"
                               value="${escapeHtml(searchQuery)}"
                               data-input="searchInput">
                        <button class="search-clear ${clearHidden}"
                                id="trashClearBtn"
                                data-action="clearSearch">
                            <i data-lucide="x"></i>
                        </button>
                    </div>
                    ${renderTrashSortButton(sortOptions)}
                </div>
                <button class="btn btn-danger" data-action="${deleteAction}">
                    <i data-lucide="x"></i>
                    ${deleteLabel}
                </button>
            </div>
            <div id="trashList" data-tab="${currentTab}"></div>
        </div>
    `;
    if (typeof lucide !== 'undefined') lucide.createIcons();

    // Bind delegated handlers on the trash-specific root, NOT on the shared
    // emailList container. When the next view's render replaces emailList's
    // inner HTML, this root is destroyed and its listener goes with it --
    // no cross-talk with other views' listeners. See delegate.js docs.
    const root = emailList.querySelector('.trash-view-root');
    if (root) {
        bindActions(root, {
            switchTab: (el) => switchTrashTab(el.dataset.tab),
            searchInput: (el) => handleTrashSearch(el.value),
            clearSearch: () => clearTrashSearch(),
            toggleSort: (el, ev) => toggleTrashSortDropdown(ev),
            setSort: (el) => handleTrashSort(el.dataset.value),
            emptyFolders: () => emptyTrash(),
            emptyEmails: () => emptyTrashEmails(),
            restoreFolder: (el) => restoreFolder(Number(el.dataset.folderId)),
            deleteFolder: (el) => permanentlyDeleteFolder(Number(el.dataset.folderId)),
            restoreEmail: (el) => restoreEmail(Number(el.dataset.emailId)),
            deleteEmail: (el) => permanentlyDeleteEmail(Number(el.dataset.emailId)),
        }, ['click', 'input']);
    }
}

/** Build just the list portion. Doesn\'t touch the search input. */
function renderList() {
    const listEl = document.getElementById('trashList');
    if (!listEl) return;

    if (currentTab === 'folders') {
        const folders = filteredAndSortedFolders();
        if (folders.length === 0) {
            listEl.innerHTML = searchQuery
                ? `<div class="empty-state" style="padding: var(--space-xl);">
                       <p>No folders match "${escapeHtml(searchQuery)}"</p>
                   </div>`
                : `<div class="empty-state" style="padding: var(--space-xl);">
                       <p>No deleted folders</p>
                   </div>`;
        } else {
            listEl.innerHTML = `
                <div class="trash-management-header">
                    <span>Folder</span><span>Deleted</span><span>Actions</span>
                </div>
                ${folders.map(renderTrashItem).join('')}
            `;
        }
    } else {
        const emails = filteredAndSortedEmails();
        if (emails.length === 0) {
            listEl.innerHTML = searchQuery
                ? `<div class="empty-state" style="padding: var(--space-xl);">
                       <p>No emails match "${escapeHtml(searchQuery)}"</p>
                   </div>`
                : `<div class="empty-state" style="padding: var(--space-xl);">
                       <p>No deleted emails</p>
                   </div>`;
        } else {
            listEl.innerHTML = `
                <div class="trash-management-header">
                    <span>Email</span><span>Deleted</span><span>Actions</span>
                </div>
                ${emails.map(renderTrashEmailItem).join('')}
            `;
        }
    }

    // Sync the clear button visibility with the current filter state.
    const clearBtn = document.getElementById('trashClearBtn');
    if (clearBtn) clearBtn.classList.toggle('hidden', !searchQuery);

    if (typeof lucide !== 'undefined') lucide.createIcons();
}

/** Update the meta count line above the list. */
function updateTrashMeta() {
    if (!contextMeta) return;
    if (currentTab === 'folders') {
        const total = getVisibleTrashedFolders().length;
        const filtered = filteredAndSortedFolders().length;
        const showingFiltered = searchQuery && filtered !== total;
        contextMeta.textContent = showingFiltered
            ? `${filtered} of ${total} deleted folders`
            : `${total} deleted folder${total !== 1 ? 's' : ''}`;
    } else {
        const total = trashedEmails.length;
        const filtered = filteredAndSortedEmails().length;
        const showingFiltered = searchQuery && filtered !== total;
        contextMeta.textContent = showingFiltered
            ? `${filtered} of ${total} deleted emails`
            : `${total} deleted email${total !== 1 ? 's' : ''}`;
    }
}

// ============================================================
// ROW TEMPLATES
// ============================================================

function renderTrashItem(folder) {
    const deletedDate = new Date(folder.deleted_at * 1000);

    function countDescendants(parentId) {
        const children = state.folders.filter(f => f.parent_id == parentId && !f.retention_date);
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
            <div class="trash-management-date">${formatDate(deletedDate)}</div>
            <div class="trash-management-actions">
                <button class="btn btn-sm btn-icon"
                        data-action="restoreFolder" data-folder-id="${folder.id}"
                        title="Restore">
                    <i data-lucide="undo-2"></i>
                </button>
                <button class="btn btn-sm btn-icon btn-danger-subtle"
                        data-action="deleteFolder" data-folder-id="${folder.id}"
                        title="Delete permanently">
                    <i data-lucide="x"></i>
                </button>
            </div>
        </div>
    `;
}

function renderTrashEmailItem(email) {
    const deletedDate = new Date(email.deleted_at * 1000);

    // Show "Originally in: X" when the original folder still exists and
    // is alive. If the original is gone or in trash, the backend marks
    // original_folder_unavailable; surface that so the user knows a
    // destination prompt will appear on restore.
    const originLine = email.folder_name
        ? `<span class="trash-email-origin">Originally in: ${escapeHtml(email.folder_name)}</span>`
        : (email.original_folder_unavailable
            ? `<span class="trash-email-origin trash-email-origin-missing">Original folder is gone</span>`
            : '');

    return `
        <div class="trash-management-item trash-email-item" data-id="${email.id}">
            <div class="trash-management-name">
                <i data-lucide="mail" class="folder-icon"></i>
                <div class="trash-email-info">
                    <span class="email-sender">${escapeHtml(extractName(email.sender || ''))}</span>
                    <span class="email-subject">${escapeHtml(email.subject || '(no subject)')}</span>
                    ${originLine}
                </div>
            </div>
            <div class="trash-management-date">${formatDate(deletedDate)}</div>
            <div class="trash-management-actions">
                <button class="btn btn-sm btn-icon"
                        data-action="restoreEmail" data-email-id="${email.id}"
                        title="Restore">
                    <i data-lucide="undo-2"></i>
                </button>
                <button class="btn btn-sm btn-icon btn-danger-subtle"
                        data-action="deleteEmail" data-email-id="${email.id}"
                        title="Delete permanently">
                    <i data-lucide="x"></i>
                </button>
            </div>
        </div>
    `;
}

// ============================================================
// SORT DROPDOWN (custom open/close behavior)
// ============================================================

function renderTrashSortButton(options) {
    const labels = Object.fromEntries(options);
    const currentLabel = labels[currentSort] || 'Sort';
    const optionsHtml = options.map(([value, label]) =>
        `<div class="sort-option ${currentSort === value ? 'selected' : ''}"
              data-action="setSort" data-value="${value}">${label}</div>`
    ).join('');
    return `
        <div class="sort-dropdown-wrapper">
            <button class="btn btn-icon sort-btn"
                    data-action="toggleSort"
                    title="Sort: ${currentLabel}">
                <i data-lucide="arrow-up-down"></i>
            </button>
            <div class="sort-dropdown" id="trashSortDropdown">
                ${optionsHtml}
            </div>
        </div>
    `;
}

function toggleTrashSortDropdown(e) {
    e.stopPropagation();
    const dropdown = document.getElementById('trashSortDropdown');
    if (!dropdown) return;
    dropdown.classList.toggle('open');

    if (dropdown.classList.contains('open')) {
        // Close on outside click. Adding the listener async so this very
        // click event doesn\'t immediately re-fire it.
        const close = () => {
            dropdown.classList.remove('open');
            document.removeEventListener('click', close);
        };
        setTimeout(() => document.addEventListener('click', close), 0);
        // Note: clicks on .sort-option dispatch to setSort via the
        // delegated handler in initTrashView, then bubble up to document
        // where the close listener also fires -- so the dropdown closes
        // naturally after a selection. No need to wire option clicks
        // separately here.
    }
}

// ============================================================
// ACTIONS (handlers called from delegated dispatch)
// ============================================================

function switchTrashTab(tab) {
    currentTab = tab;
    searchQuery = '';
    currentSort = 'date-desc';  // reset to default when switching tabs
    renderTrashView();
}

function handleTrashSearch(query) {
    searchQuery = query;
    // Only re-render the list portion; the search input stays in the DOM
    // and keeps focus naturally.
    renderList();
    updateTrashMeta();
}

function clearTrashSearch() {
    searchQuery = '';
    // Shell isn\'t re-rendered on filter changes, so reset the input value
    // explicitly.
    const input = document.getElementById('trashSearch');
    if (input) {
        input.value = '';
        input.focus();
    }
    renderList();
    updateTrashMeta();
}

function handleTrashSort(sort) {
    currentSort = sort;
    renderList();
    // Sort label on the button is part of the shell -- update its title
    // attribute without re-rendering the whole shell.
    const sortBtn = emailList.querySelector('button.sort-btn[data-action="toggleSort"]');
    if (sortBtn) {
        // The label dict matches whatever was used to build this dropdown.
        // Cheap to recompute from the option list in the DOM.
        const selected = emailList.querySelector(`.sort-option[data-value="${sort}"]`);
        if (selected) {
            sortBtn.title = `Sort: ${selected.textContent.trim()}`;
        }
        // Update the .selected class on the options.
        emailList.querySelectorAll('.sort-option').forEach(o => {
            o.classList.toggle('selected', o.dataset.value === sort);
        });
    }
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

export async function permanentlyDeleteFolder(folderId) {
    const folder = state.folders.find(f => f.id == folderId);
    if (!folder) return;

    function countDescendants(parentId) {
        const children = state.folders.filter(f => f.parent_id == parentId && !f.retention_date);
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

async function restoreEmail(emailId, destinationFolderId) {
    /*
     * If destinationFolderId is omitted, the backend tries to restore
     * to the email\'s original folder. If that folder is gone or in
     * trash, the backend returns 409 with needs_destination=true; we
     * then open the folder-tree picker so the user can choose where
     * to restore, and call this function again with the picked
     * destination.
     */
    try {
        const body = destinationFolderId
            ? JSON.stringify({ folder_id: destinationFolderId })
            : JSON.stringify({});
        const response = await fetch(`/api/messages/${emailId}/restore`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body,
        });

        if (response.status === 409) {
            const data = await response.json();
            if (data.needs_destination) {
                const { openChangeDestinationModal } = await import('../components/staging.js');
                openChangeDestinationModal({
                    title: 'Restore email to folder',
                    confirmLabel: 'Restore',
                    currentDestId: null,
                    onConfirm: async (folderId) => {
                        await restoreEmail(emailId, folderId);
                    },
                });
                return;
            }
            showAlert('Error', data.error || 'Failed to restore email');
            return;
        }

        if (!response.ok) {
            const data = await response.json();
            showAlert('Error', data.error || 'Failed to restore email');
            return;
        }

        trashedEmails = trashedEmails.filter(e => e.id != emailId);
        renderTrashView();
        updateTrashBadge();
    } catch (error) {
        console.error('Error restoring email:', error);
        showAlert('Error', 'Failed to restore email');
    }
}

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

async function emptyTrashEmails() {
    if (trashedEmails.length === 0) return;

    const confirmed = await showConfirm(
        'Delete All Emails',
        `Permanently delete ${trashedEmails.length} email${trashedEmails.length !== 1 ? 's' : ''}? This cannot be undone.`,
        { okText: 'Delete All', okClass: 'btn-danger' }
    );
    if (!confirmed) return;

    try {
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

// ============================================================
// BADGE
// ============================================================

export async function updateTrashBadge() {
    const badge = document.getElementById('trashBadge');
    if (!badge) return;

    const trashedFolderCount = getVisibleTrashedFolders().length;

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
