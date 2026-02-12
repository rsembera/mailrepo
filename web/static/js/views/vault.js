/**
 * MailRepo - Retention Vault View
 * 
 * Handles:
 * - Displaying folders in the retention vault
 * - Sorting and filtering vault folders
 * - Restoring folders from vault
 * - Permanently deleting overdue folders
 */

import { escapeHtml } from '../utils.js';
import { state, loadFolders } from '../state.js';
import { closeModal, showConfirm, showAlert } from '../modals.js';
import { refreshSidebarFolders } from '../components/sidebar.js';
import { formatDate, daysUntil } from '../components/date-picker.js';

// Module state
let vaultFolders = [];
let vaultFilter = '';
let vaultSort = 'date-asc'; // 'date-asc', 'date-desc', 'name-asc', 'name-desc'
let restoreFolderId = null;
let restoreDestinationId = null;

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
    
    // Count overdue folders
    const overdueCount = vaultFolders.filter(f => f.is_overdue).length;
    
    let html = `
        <div class="vault-management-list">
            <div class="vault-management-toolbar">
                <div class="vault-toolbar-left">
                    <div class="vault-search">
                        <i data-lucide="search" class="search-icon"></i>
                        <input type="text" 
                               id="vaultFilterInput" 
                               placeholder="Search folders..." 
                               value="${escapeHtml(vaultFilter)}"
                               oninput="handleVaultFilter(this.value)">
                        ${vaultFilter ? '<button class="search-clear" onclick="clearVaultFilter()"><i data-lucide="x"></i></button>' : ''}
                    </div>
                    ${renderVaultSortButton()}
                </div>
                ${overdueCount > 0 ? `
                    <button class="btn btn-danger" onclick="deleteAllOverdue()">
                        <i data-lucide="trash-2"></i>
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
            <div class="vault-management-name">
                ${colorDot}
                <i data-lucide="folder" class="folder-icon"></i>
                <span class="folder-label">${escapeHtml(folder.name)}</span>
                <span class="email-count">(${folder.email_count})</span>
            </div>
            <div class="vault-management-date ${isOverdue ? 'overdue' : ''}">
                ${dateText}
            </div>
            <div class="vault-management-actions">
                <button class="btn btn-sm btn-icon" onclick="openRestoreFolder(${folder.id})" title="Restore to Archive">
                    <i data-lucide="archive-restore"></i>
                </button>
                ${isOverdue ? `
                    <button class="btn btn-sm btn-icon btn-danger-icon" onclick="permadeleteFolder(${folder.id})" title="Permanently Delete">
                        <i data-lucide="trash-2"></i>
                    </button>
                ` : ''}
            </div>
        </div>
    `;
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
            <button class="btn btn-icon sort-btn" onclick="toggleVaultSortDropdown(event)" title="Sort: ${currentLabel}">
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
window.toggleVaultSortDropdown = toggleVaultSortDropdown;


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
window.handleVaultFilter = handleVaultFilter;

/**
 * Clear vault filter.
 */
function clearVaultFilter() {
    vaultFilter = '';
    renderVaultList();
    const input = document.getElementById('vaultFilterInput');
    if (input) input.focus();
}
window.clearVaultFilter = clearVaultFilter;

/**
 * Handle vault sort change.
 */
function handleVaultSort(value) {
    vaultSort = value;
    renderVaultList();
}
window.handleVaultSort = handleVaultSort;


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
window.openRestoreFolder = openRestoreFolder;

/**
 * Render restore destination folder list.
 */
function renderRestoreDestinations() {
    const container = document.getElementById('restoreDestinationList');
    
    // Filter out deleted folders and vault folders
    const availableFolders = state.folders.filter(f => !f.deleted_at && !f.retention_date);
    const topLevel = availableFolders.filter(f => !f.parent_id);
    topLevel.sort((a, b) => a.name.localeCompare(b.name));
    
    let html = `
        <div class="folder-select-item ${restoreDestinationId === null ? 'selected' : ''}" 
             onclick="selectRestoreDestination(null)">
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
                 onclick="selectRestoreDestination(${folder.id})">
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
}

/**
 * Select restore destination.
 */
function selectRestoreDestination(folderId) {
    restoreDestinationId = folderId;
    renderRestoreDestinations();
}
window.selectRestoreDestination = selectRestoreDestination;


/**
 * Confirm restore folder from vault.
 */
async function confirmRestoreFolder() {
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
window.confirmRestoreFolder = confirmRestoreFolder;


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
window.permadeleteFolder = permadeleteFolder;


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
window.deleteAllOverdue = deleteAllOverdue;


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

/**
 * Check for overdue folders and show alert if needed.
 * Only shows alert on main mail view.
 */
export async function checkOverdueFolders(showAlert = true) {
    const count = await updateVaultBadge();
    
    if (showAlert && count > 0) {
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
 * Dismiss the overdue alert.
 */
function dismissOverdueAlert() {
    hideOverdueAlert();
}
window.dismissOverdueAlert = dismissOverdueAlert;
