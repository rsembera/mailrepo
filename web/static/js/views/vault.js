/**
 * MailRepo - Retention Vault View
 * 
 * Handles:
 * - Displaying folders in the retention vault
 * - Sorting and filtering vault folders
 * - Viewing emails within vault folders (read-only)
 * - Restoring folders from vault
 * - Permanently deleting overdue folders
 */

import { escapeHtml } from '../utils.js';
import { state, loadFolders } from '../state.js';
import { closeModal, showConfirm, showAlert } from '../modals.js';
import { refreshSidebarFolders } from '../components/sidebar.js';
import { formatDate, daysUntil } from '../components/date-picker.js';
import { renderEmailList } from '../components/email-list.js';
import { openEmailViewer } from './mail.js';
import { bindActions } from '../delegate.js';

// Module state
let vaultFolders = [];
let vaultFilter = '';
let vaultSort = 'date-asc'; // 'date-asc', 'date-desc', 'name-asc', 'name-desc'
let restoreFolderId = null;
let restoreDestinationId = null;

// State for viewing folder contents
let viewingFolder = null;  // null = folder list, object = viewing folder's emails
let vaultEmails = [];
let vaultBreadcrumbs = [];  // Stack of {id, name} for navigation
let vaultSubfolders = [];   // Subfolders of current viewing folder

// DOM references
let contextTitle = null;
let contextMeta = null;
let emailList = null;

/**
 * Initialize vault view with DOM references.
 */
export function initVault(config) {
    contextTitle = config.contextTitle;
    contextMeta = config.contextMeta;
    emailList = config.emailList;
}

/**
 * Load vault folders from API.
 */
async function loadVaultFolders() {
    try {
        const response = await fetch('/api/folders/vault');
        if (!response.ok) throw new Error('Failed to load vault');
        const data = await response.json();
        vaultFolders = data.folders || [];
        return data;
    } catch (error) {
        console.error('Error loading vault folders:', error);
        vaultFolders = [];
        return { folders: [], overdue_count: 0 };
    }
}

/**
 * Show the retention vault view.
 */
export async function showVaultView() {
    vaultFilter = '';
    viewingFolder = null;  // Reset to folder list view
    vaultEmails = [];
    
    const sidebar = document.getElementById('sidebar');
    const toolbar = document.querySelector('.content-toolbar');
    const headerActions = document.querySelector('.header-actions');
    const subfoldersBar = document.getElementById('subfoldersBar');
    
    sidebar.style.display = 'none';
    if (toolbar) toolbar.style.display = 'none';
    if (headerActions) headerActions.style.display = 'none';
    if (subfoldersBar) subfoldersBar.style.display = 'none';
    
    if (contextTitle) contextTitle.textContent = 'Retention Vault';
    if (contextMeta) contextMeta.textContent = 'Loading...';
    
    await loadVaultFolders();
    renderVaultList();
}

/**
 * Filter and sort vault folders.
 */
function getFilteredVaultFolders() {
    let filtered = [...vaultFolders];
    
    // Apply filter
    if (vaultFilter) {
        const query = vaultFilter.toLowerCase();
        filtered = filtered.filter(f => f.name.toLowerCase().includes(query));
    }
    
    // Apply sort
    filtered.sort((a, b) => {
        switch (vaultSort) {
            case 'date-asc':
                return a.retention_date - b.retention_date;
            case 'date-desc':
                return b.retention_date - a.retention_date;
            case 'name-asc':
                return a.name.localeCompare(b.name);
            case 'name-desc':
                return b.name.localeCompare(a.name);
            default:
                return a.retention_date - b.retention_date;
        }
    });
    
    return filtered;
}

/**
 * Render the vault folder list.
 */
function renderVaultList() {
    const filtered = getFilteredVaultFolders();
    const overdueCount = vaultFolders.filter(f => f.is_overdue).length;
    
    // Update context meta
    if (contextMeta) {
        if (vaultFolders.length === 0) {
            contextMeta.textContent = 'No folders';
        } else if (vaultFilter && filtered.length !== vaultFolders.length) {
            contextMeta.textContent = `${filtered.length} of ${vaultFolders.length} folders`;
        } else {
            const overdueText = overdueCount > 0 ? ` (${overdueCount} overdue)` : '';
            contextMeta.textContent = `${vaultFolders.length} folder${vaultFolders.length !== 1 ? 's' : ''}${overdueText}`;
        }
    }
    
    if (vaultFolders.length === 0) {
        emailList.innerHTML = `
            <div class="empty-state">
                <i data-lucide="archive" class="empty-icon"></i>
                <h3>Retention Vault Empty</h3>
                <p>Folders moved here will be held until their retention date, then flagged for permanent deletion.</p>
            </div>
        `;
        if (typeof lucide !== 'undefined') lucide.createIcons();
        return;
    }
    
    let html = `
        <div class="vault-management-list vault-view-root">
            <div class="vault-management-toolbar">
                <div class="vault-toolbar-left">
                    <div class="vault-search">
                        <i data-lucide="search" class="search-icon"></i>
                        <input type="text" 
                               id="vaultFilterInput" 
                               placeholder="Search folders..." 
                               value="${escapeHtml(vaultFilter)}"
                               data-input="vaultFilter">
                        ${vaultFilter ? '<button class="search-clear" data-action="clearFilter"><i data-lucide="x"></i></button>' : ''}
                    </div>
                    ${renderVaultSortButton()}
                </div>
                ${overdueCount > 0 ? `
                    <button class="btn btn-danger" data-action="deleteAllOverdue">
                        <i data-lucide="x"></i>
                        Delete Overdue (${overdueCount})
                    </button>
                ` : '<div></div>'}
            </div>
    `;
    
    if (filtered.length === 0 && vaultFilter) {
        html += `
            <div class="empty-state" style="padding: var(--space-xl);">
                <p>No folders match "${escapeHtml(vaultFilter)}"</p>
            </div>
        `;
    } else {
        html += `
            <div class="vault-management-header">
                <span>Folder</span>
                <span>Delete By</span>
                <span>Actions</span>
            </div>
        `;
        
        for (const folder of filtered) {
            html += renderVaultItem(folder);
        }
    }
    
    html += `</div>`;
    
    emailList.innerHTML = html;
    if (typeof lucide !== 'undefined') lucide.createIcons();
    bindVaultActions();
}

/**
 * Render a single vault folder item.
 */
function renderVaultItem(folder) {
    const days = daysUntil(folder.retention_date);
    const isOverdue = folder.is_overdue;
    
    let dateText;
    if (isOverdue) {
        dateText = `<span class="vault-overdue-badge">OVERDUE</span>`;
    } else {
        dateText = formatDate(folder.retention_date);
    }
    
    const colorDot = folder.color ? 
        `<span class="color-dot" style="background: ${folder.color}"></span>` : '';
    
    return `
        <div class="vault-management-item ${isOverdue ? 'overdue' : ''}">
            <div class="vault-management-name clickable" data-action="openFolder" data-folder-id="${folder.id}">
                ${colorDot}
                <i data-lucide="folder" class="folder-icon"></i>
                <span class="folder-label">${escapeHtml(folder.name)}</span>
                <span class="email-count">(${folder.email_count})</span>
            </div>
            <div class="vault-management-date ${isOverdue ? 'overdue' : ''}">
                ${dateText}
            </div>
            <div class="vault-management-actions">
                <button class="btn btn-sm btn-icon" data-action="openRestore" data-folder-id="${folder.id}" title="Restore to Archive">
                    <i data-lucide="archive-restore"></i>
                </button>
                ${isOverdue ? `
                    <button class="btn btn-sm btn-icon btn-danger-subtle" data-action="permadelete" data-folder-id="${folder.id}" title="Permanently Delete">
                        <i data-lucide="x"></i>
                    </button>
                ` : ''}
            </div>
        </div>
    `;
}

/**
 * Open a vault folder to view its emails.
 * @param {number} folderId - Folder ID to open
 * @param {boolean} isSubfolder - If true, this is navigating into a subfolder (add to breadcrumbs)
 */
async function openVaultFolder(folderId, isSubfolder = false) {
    // Find folder in state.folders (includes all folders, not just top-level vault)
    const folder = state.folders.find(f => f.id === folderId);
    if (!folder) return;
    
    // If navigating into a subfolder, add current folder to breadcrumbs first
    if (isSubfolder && viewingFolder) {
        vaultBreadcrumbs.push({ id: viewingFolder.id, name: viewingFolder.name });
    } else if (!isSubfolder) {
        // Starting fresh from vault list - clear breadcrumbs
        vaultBreadcrumbs = [];
    }
    
    viewingFolder = folder;
    
    if (contextTitle) contextTitle.textContent = folder.name;
    if (contextMeta) contextMeta.textContent = 'Loading...';
    
    try {
        const response = await fetch(`/api/folders/${folderId}/emails`);
        if (!response.ok) throw new Error('Failed to load emails');
        
        const data = await response.json();
        vaultEmails = data.emails || [];
        
        // Find subfolders (children in vault that aren't deleted)
        vaultSubfolders = state.folders.filter(f => 
            f.parent_id === folderId && 
            f.retention_date && 
            !f.deleted_at
        ).sort((a, b) => a.name.localeCompare(b.name));
        
        renderVaultFolderContents();
    } catch (error) {
        console.error('Error loading vault folder emails:', error);
        if (contextMeta) contextMeta.textContent = 'Error loading emails';
    }
}

/**
 * Go back to vault folder list from folder contents view.
 */
function backToVaultList() {
    viewingFolder = null;
    vaultEmails = [];
    vaultBreadcrumbs = [];
    vaultSubfolders = [];
    
    if (contextTitle) contextTitle.textContent = 'Retention Vault';
    renderVaultList();
}

/**
 * Navigate to a breadcrumb folder.
 */
async function navigateVaultBreadcrumb(folderId) {
    // Find index in breadcrumbs
    const index = vaultBreadcrumbs.findIndex(b => b.id === folderId);
    if (index === -1) return;
    
    // Trim breadcrumbs to this point (don't include the clicked one)
    vaultBreadcrumbs = vaultBreadcrumbs.slice(0, index);
    
    // Open the folder (not as subfolder since we've already trimmed breadcrumbs)
    const folder = state.folders.find(f => f.id === folderId);
    if (!folder) return;
    
    viewingFolder = folder;
    
    if (contextTitle) contextTitle.textContent = folder.name;
    if (contextMeta) contextMeta.textContent = 'Loading...';
    
    try {
        const response = await fetch(`/api/folders/${folderId}/emails`);
        if (!response.ok) throw new Error('Failed to load emails');
        
        const data = await response.json();
        vaultEmails = data.emails || [];
        
        vaultSubfolders = state.folders.filter(f => 
            f.parent_id === folderId && 
            f.retention_date && 
            !f.deleted_at
        ).sort((a, b) => a.name.localeCompare(b.name));
        
        renderVaultFolderContents();
    } catch (error) {
        console.error('Error loading vault folder emails:', error);
        if (contextMeta) contextMeta.textContent = 'Error loading emails';
    }
}

/**
 * Render the contents of a vault folder (email list).
 */
function renderVaultFolderContents() {
    if (!viewingFolder) return;
    
    // Get retention info from top-level vault folder
    const topLevelFolder = vaultFolders.find(f => f.id === viewingFolder.id) || 
        vaultFolders.find(f => {
            // Walk up to find the top-level vault folder
            let current = viewingFolder;
            while (current) {
                if (f.id === current.id) return true;
                current = state.folders.find(p => p.id === current.parent_id && p.retention_date);
            }
            return false;
        });
    
    const dateText = topLevelFolder?.is_overdue 
        ? 'OVERDUE' 
        : (topLevelFolder ? `Delete by: ${formatDate(topLevelFolder.retention_date)}` : '');
    
    if (contextMeta) contextMeta.textContent = dateText ? `${vaultEmails.length} emails · ${dateText}` : `${vaultEmails.length} emails`;
    
    // Build navigation bar (breadcrumbs + subfolders) like main view
    let navBarHtml = '';
    const hasBreadcrumbs = vaultBreadcrumbs.length > 0;
    const hasSubfolders = vaultSubfolders.length > 0;
    
    if (hasBreadcrumbs || hasSubfolders) {
        navBarHtml = `<div class="vault-nav-bar">`;
        
        // Breadcrumb trail
        if (hasBreadcrumbs) {
            navBarHtml += `<div class="vault-breadcrumbs">`;
            vaultBreadcrumbs.forEach((b, i) => {
                if (i > 0) navBarHtml += ` <i data-lucide="chevron-right" class="breadcrumb-sep"></i> `;
                navBarHtml += `<a href="#" data-action="navBreadcrumb" data-folder-id="${b.id}" class="breadcrumb-link">${escapeHtml(b.name)}</a>`;
            });
            navBarHtml += ` <i data-lucide="chevron-right" class="breadcrumb-sep"></i> `;
            navBarHtml += `<span class="breadcrumb-current">${escapeHtml(viewingFolder.name)}</span>`;
            navBarHtml += `</div>`;
        }
        
        // Subfolder links
        if (hasSubfolders) {
            navBarHtml += `<div class="vault-subfolder-links">`;
            navBarHtml += `<span class="subfolder-label">Subfolders:</span> `;
            navBarHtml += vaultSubfolders.map((sf, i) => {
                const separator = i < vaultSubfolders.length - 1 ? ', ' : '';
                return `<a href="#" data-action="openFolder" data-folder-id="${sf.id}" data-is-subfolder="1" class="subfolder-link">${escapeHtml(sf.name)}</a>${separator}`;
            }).join('');
            navBarHtml += `</div>`;
        }
        
        navBarHtml += `</div>`;
    }
    
    let html = `
        <div class="vault-folder-view vault-view-root">
            <div class="vault-folder-toolbar">
                <button class="btn btn-secondary" data-action="backToList">
                    <i data-lucide="arrow-left"></i>
                    Back to Vault
                </button>
                <button class="btn btn-secondary" data-action="openRestore" data-folder-id="${vaultBreadcrumbs.length > 0 ? vaultBreadcrumbs[0].id : viewingFolder.id}">
                    <i data-lucide="archive-restore"></i>
                    Restore Folder
                </button>
            </div>
            ${navBarHtml}
            <div class="vault-email-list">
    `;
    
    if (vaultEmails.length === 0) {
        html += `
            <div class="empty-state">
                <p>No emails in this folder</p>
            </div>
        `;
    } else {
        for (const email of vaultEmails) {
            html += renderVaultEmailRow(email);
        }
    }
    
    html += `
            </div>
        </div>
    `;
    
    emailList.innerHTML = html;
    if (typeof lucide !== 'undefined') lucide.createIcons();
    bindVaultActions();
}

/**
 * Render a single email row in vault folder view.
 */
function renderVaultEmailRow(email) {
    const date = new Date(email.date * 1000);
    const dateStr = date.toLocaleDateString('en-US', { 
        month: 'short', 
        day: 'numeric',
        year: date.getFullYear() !== new Date().getFullYear() ? 'numeric' : undefined
    });
    
    return `
        <div class="email-row" data-action="openEmail" data-folder-id="${viewingFolder.id}" data-email-id="${email.id}">
            <div class="email-row-main">
                <span class="email-sender">${escapeHtml(email.sender || '(No sender)')}</span>
                <span class="email-subject">${escapeHtml(email.subject || '(No subject)')}</span>
            </div>
            <div class="email-row-meta">
                <span class="email-date">${dateStr}</span>
            </div>
        </div>
    `;
}

/**
 * Open an email from the vault in the viewer (read-only).
 */
async function openVaultEmail(folderId, emailId) {
    // Use the existing email viewer from mail.js
    // Pass vault mode flag and folder ID for fetching
    openEmailViewer(emailId, { vaultMode: true, folderId: folderId });
}

/**
 * Render sort icon button with dropdown.
 */
function renderVaultSortButton() {
    const sortLabels = {
        'date-asc': 'Soonest first',
        'date-desc': 'Latest first',
        'name-asc': 'Name A–Z',
        'name-desc': 'Name Z–A'
    };
    const options = [
        ['date-asc', 'Soonest first'],
        ['date-desc', 'Latest first'],
        ['name-asc', 'Name A–Z'],
        ['name-desc', 'Name Z–A']
    ];
    const currentLabel = sortLabels[vaultSort] || 'Sort';
    const optionsHtml = options.map(([value, label]) =>
        `<div class="sort-option ${vaultSort === value ? 'selected' : ''}" data-value="${value}">${label}</div>`
    ).join('');
    return `
        <div class="sort-dropdown-wrapper">
            <button class="btn btn-icon sort-btn" data-action="toggleSort" title="Sort: ${currentLabel}">
                <i data-lucide="arrow-up-down"></i>
            </button>
            <div class="sort-dropdown" id="vaultSortDropdown">
                ${optionsHtml}
            </div>
        </div>
    `;
}

function toggleVaultSortDropdown(e) {
    e.stopPropagation();
    const dropdown = document.getElementById('vaultSortDropdown');
    if (!dropdown) return;
    dropdown.classList.toggle('open');
    
    if (dropdown.classList.contains('open')) {
        const close = (ev) => {
            dropdown.classList.remove('open');
            document.removeEventListener('click', close);
        };
        setTimeout(() => document.addEventListener('click', close), 0);
        
        dropdown.querySelectorAll('.sort-option').forEach(opt => {
            opt.onclick = (ev) => {
                ev.stopPropagation();
                handleVaultSort(opt.dataset.value);
                dropdown.classList.remove('open');
            };
        });
    }
}

/**
 * Handle vault filter input.
 */
function handleVaultFilter(query) {
    vaultFilter = query;
    renderVaultList();
    
    const input = document.getElementById('vaultFilterInput');
    if (input) {
        input.focus();
        input.setSelectionRange(query.length, query.length);
    }
}

/**
 * Clear vault filter.
 */
function clearVaultFilter() {
    vaultFilter = '';
    renderVaultList();
    const input = document.getElementById('vaultFilterInput');
    if (input) input.focus();
}

/**
 * Handle vault sort change.
 */
function handleVaultSort(value) {
    vaultSort = value;
    renderVaultList();
}

/**
 * Open restore folder modal.
 */
async function openRestoreFolder(folderId) {
    restoreFolderId = folderId;
    restoreDestinationId = null;
    
    // Load folders for destination selection
    await loadFolders();
    
    const folder = vaultFolders.find(f => f.id === folderId);
    document.getElementById('restoreModalTitle').textContent = `Restore "${folder?.name || 'Folder'}"`;
    
    renderRestoreDestinations();
    document.getElementById('restoreFolderModal').classList.add('active');
}

/**
 * Render restore destination folder list.
 */

/**
 * Bind delegated handlers on the vault-specific root. Listener dies with
 * the view when another view's render replaces emailList. Called by both
 * the folder-list and folder-detail render paths (same handler set works
 * for both since they share toolbar / row actions / breadcrumb links).
 *
 * The two anchor-tag handlers (navBreadcrumb + openFolder-as-subfolder)
 * call e.preventDefault() so the page doesn't jump to top when clicked
 * (replaces the legacy 'return false' on the inline onclick).
 *
 * See delegate.js docs.
 */
function bindVaultActions() {
    const root = emailList.querySelector('.vault-view-root');
    if (!root) return;
    bindActions(root, {
        clearFilter:      () => clearVaultFilter(),
        vaultFilter:      (el) => handleVaultFilter(el.value),
        deleteAllOverdue: () => deleteAllOverdue(),
        openFolder:       (el, ev) => {
            // This handler is wired to both <button> and <a href="#"> elements
            // (the <a> for subfolder navigation in the breadcrumb area).
            // preventDefault keeps the <a> from scrolling the page.
            ev.preventDefault();
            const id = Number(el.dataset.folderId);
            const isSubfolder = el.dataset.isSubfolder === '1';
            openVaultFolder(id, isSubfolder);
        },
        openRestore:      (el) => openRestoreFolder(Number(el.dataset.folderId)),
        permadelete:      (el) => permadeleteFolder(Number(el.dataset.folderId)),
        navBreadcrumb:    (el, ev) => {
            // <a href="#"> -- prevent default scroll-to-top
            ev.preventDefault();
            navigateVaultBreadcrumb(Number(el.dataset.folderId));
        },
        backToList:       () => backToVaultList(),
        openEmail:        (el) => openVaultEmail(
            Number(el.dataset.folderId),
            Number(el.dataset.emailId),
        ),
        toggleSort:       (el, ev) => toggleVaultSortDropdown(ev),
    }, ['click', 'input']);
}

/**
 * Bind the destination-picker handler. The restore-folder modal lives
 * in the index.html template (outside emailList), so it needs its own
 * bindActions call on the picker container -- can't ride along with
 * bindVaultActions which targets emailList descendants only.
 */
function bindRestorePickerActions() {
    const container = document.getElementById('restoreDestinationList');
    if (!container) return;
    bindActions(container, {
        selectDest: (el) => {
            const destId = el.dataset.destId;
            selectRestoreDestination(destId === '' ? null : Number(destId));
        },
    });
}

function renderRestoreDestinations() {
    const container = document.getElementById('restoreDestinationList');
    
    // Filter out deleted folders and vault folders
    const availableFolders = state.folders.filter(f => !f.deleted_at && !f.retention_date);
    const topLevel = availableFolders.filter(f => !f.parent_id);
    topLevel.sort((a, b) => a.name.localeCompare(b.name));
    
    let html = `
        <div class="folder-select-item ${restoreDestinationId === null ? 'selected' : ''}" 
             data-action="selectDest" data-dest-id="">
            <i data-lucide="home" style="width: 16px; height: 16px;"></i>
            <span>Archive Root</span>
        </div>
    `;

    
    function renderFolder(folder, depth = 0) {
        const indent = depth * 20;
        const children = availableFolders.filter(f => f.parent_id === folder.id);
        children.sort((a, b) => a.name.localeCompare(b.name));
        
        const colorDot = folder.color ? 
            `<span class="color-dot" style="background: ${folder.color}"></span>` : '';
        
        html += `
            <div class="folder-select-item ${restoreDestinationId === folder.id ? 'selected' : ''}" 
                 style="padding-left: ${16 + indent}px;"
                 data-action="selectDest" data-dest-id="${folder.id}">
                ${colorDot}
                <i data-lucide="folder" style="width: 16px; height: 16px;"></i>
                <span>${escapeHtml(folder.name)}</span>
            </div>
        `;
        
        for (const child of children) {
            renderFolder(child, depth + 1);
        }
    }
    
    for (const folder of topLevel) {
        renderFolder(folder, 0);
    }
    
    container.innerHTML = html;
    if (typeof lucide !== 'undefined') lucide.createIcons();
    bindRestorePickerActions();
}

/**
 * Select restore destination.
 */
function selectRestoreDestination(folderId) {
    restoreDestinationId = folderId;
    renderRestoreDestinations();
}

/**
 * Confirm restore folder from vault.
 */
export async function confirmRestoreFolder() {
    if (!restoreFolderId) return;
    
    try {
        const response = await fetch(`/api/folders/${restoreFolderId}/vault/restore`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ destination_id: restoreDestinationId }),
        });
        
        if (!response.ok) {
            const data = await response.json();
            showAlert('Error', data.error || 'Failed to restore folder');
            return;
        }
        
        closeModal('restoreFolderModal');
        
        // Refresh views
        await loadVaultFolders();
        await loadFolders();
        renderVaultList();
        refreshSidebarFolders();
        
    } catch (error) {
        console.error('Error restoring folder:', error);
        showAlert('Error', 'Failed to restore folder');
    }
}

/**
 * Permanently delete a single folder from vault.
 */
async function permadeleteFolder(folderId) {
    const folder = vaultFolders.find(f => f.id === folderId);
    if (!folder) return;
    
    const confirmed = await showConfirm(
        'Permanently Delete?',
        `Delete "${folder.name}" and all ${folder.email_count} emails? This cannot be undone.`,
        { okText: 'Delete Forever', danger: true }
    );
    
    if (!confirmed) return;
    
    try {
        const response = await fetch(`/api/folders/${folderId}/permadelete`, {
            method: 'DELETE',
        });
        
        if (!response.ok) {
            const data = await response.json();
            showAlert('Error', data.error || 'Failed to delete folder');
            return;
        }
        
        // Refresh
        await loadVaultFolders();
        await loadFolders();
        renderVaultList();
        refreshSidebarFolders();
        updateVaultBadge();
        
    } catch (error) {
        console.error('Error deleting folder:', error);
        showAlert('Error', 'Failed to delete folder');
    }
}

/**
 * Delete all overdue folders.
 */
async function deleteAllOverdue() {
    const overdueFolders = vaultFolders.filter(f => f.is_overdue);
    
    if (overdueFolders.length === 0) return;
    
    const totalEmails = overdueFolders.reduce((sum, f) => sum + (f.email_count || 0), 0);
    
    const confirmed = await showConfirm(
        'Permanently Delete?',
        `Delete ${overdueFolders.length} overdue folder${overdueFolders.length !== 1 ? 's' : ''} containing ${totalEmails} emails? This cannot be undone.`,
        { okText: 'Delete Forever', danger: true }
    );
    
    if (!confirmed) return;
    
    try {
        const response = await fetch('/api/folders/batch-permadelete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ folder_ids: overdueFolders.map(f => f.id) }),
        });
        
        if (!response.ok) {
            const data = await response.json();
            showAlert('Error', data.error || 'Failed to delete folders');
            return;
        }
        
        // Refresh
        await loadVaultFolders();
        await loadFolders();
        renderVaultList();
        refreshSidebarFolders();
        updateVaultBadge();
        
    } catch (error) {
        console.error('Error deleting folders:', error);
        showAlert('Error', 'Failed to delete folders');
    }
}

/**
 * Update the vault badge in the left rail.
 */
export async function updateVaultBadge() {
    try {
        const response = await fetch('/api/folders/vault/overdue-count');
        if (!response.ok) return;
        const data = await response.json();
        
        const badge = document.getElementById('vaultBadge');
        if (badge) {
            if (data.count > 0) {
                badge.textContent = data.count;
                badge.style.display = 'flex';
            } else {
                badge.style.display = 'none';
            }
        }
        
        return data.count;
    } catch (error) {
        console.error('Error updating vault badge:', error);
        return 0;
    }
}

// Session-based dismiss tracking
let overdueAlertDismissed = false;

/**
 * Check for overdue folders and show alert if needed.
 * Only shows alert on main mail view.
 * Respects session-based dismiss state.
 */
export async function checkOverdueFolders(showAlert = true) {
    const count = await updateVaultBadge();
    
    if (showAlert && count > 0 && !overdueAlertDismissed) {
        const alertBar = document.getElementById('overdueAlert');
        if (alertBar) {
            document.getElementById('overdueCount').textContent = count;
            alertBar.style.display = 'flex';
        }
    }
    
    return count;
}

/**
 * Hide the overdue alert bar.
 */
export function hideOverdueAlert() {
    const alertBar = document.getElementById('overdueAlert');
    if (alertBar) {
        alertBar.style.display = 'none';
    }
}

/**
 * Dismiss the overdue alert for this session.
 */
export function dismissOverdueAlert() {
    overdueAlertDismissed = true;
    hideOverdueAlert();
}

/**
 * Reset the dismiss state (e.g., when new folders become overdue).
 */
export function resetOverdueAlertDismiss() {
    overdueAlertDismissed = false;
}
