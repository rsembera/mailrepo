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
let selectedVaultFolders = new Set();
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
    selectedVaultFolders.clear();
    
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
    
    // Check if any overdue folders are selected
    const selectedOverdue = [...selectedVaultFolders].filter(id => {
        const folder = vaultFolders.find(f => f.id === id);
        return folder && folder.is_overdue;
    });
    
    let html = `
        <div class="vault-list">
            <div class="vault-toolbar">
                <div class="vault-filter">
                    <i data-lucide="search" class="search-icon"></i>
                    <input type="text" 
                           id="vaultFilterInput" 
                           placeholder="Filter folders..." 
                           value="${escapeHtml(vaultFilter)}"
                           oninput="handleVaultFilter(this.value)">
                    ${vaultFilter ? '<button class="search-clear" onclick="clearVaultFilter()"><i data-lucide="x"></i></button>' : ''}
                </div>
                <div class="vault-sort">
                    <select id="vaultSortSelect" onchange="handleVaultSort(this.value)">
                        <option value="date-asc" ${vaultSort === 'date-asc' ? 'selected' : ''}>Date (Soonest)</option>
                        <option value="date-desc" ${vaultSort === 'date-desc' ? 'selected' : ''}>Date (Latest)</option>
                        <option value="name-asc" ${vaultSort === 'name-asc' ? 'selected' : ''}>Name (A-Z)</option>
                        <option value="name-desc" ${vaultSort === 'name-desc' ? 'selected' : ''}>Name (Z-A)</option>
                    </select>
                </div>
                ${selectedOverdue.length > 0 ? `
                    <button class="btn btn-danger" onclick="batchPermadelete()">
                        <i data-lucide="trash-2"></i>
                        Delete Selected (${selectedOverdue.length})
                    </button>
                ` : ''}
            </div>
    `;

    
    if (filtered.length === 0 && vaultFilter) {
        html += `
            <div class="empty-state" style="padding: var(--space-xl);">
                <p>No folders match "${escapeHtml(vaultFilter)}"</p>
            </div>
        `;
    } else {
        html += `<div class="vault-folder-list">`;
        
        for (const folder of filtered) {
            const days = daysUntil(folder.retention_date);
            const isOverdue = folder.is_overdue;
            const isSelected = selectedVaultFolders.has(folder.id);
            
            let daysText;
            if (isOverdue) {
                daysText = `<span class="vault-overdue-badge">OVERDUE</span> ${Math.abs(days)} days ago`;
            } else if (days === 0) {
                daysText = 'Today';
            } else if (days === 1) {
                daysText = 'Tomorrow';
            } else {
                daysText = `${days} days`;
            }
            
            const colorDot = folder.color ? 
                `<span class="color-dot" style="background: ${folder.color}"></span>` : '';
            
            html += `
                <div class="vault-folder-item ${isOverdue ? 'overdue' : ''} ${isSelected ? 'selected' : ''}" data-id="${folder.id}">
                    <div class="vault-folder-select">
                        ${isOverdue ? `
                            <input type="checkbox" 
                                   ${isSelected ? 'checked' : ''} 
                                   onchange="toggleVaultSelect(${folder.id}, this.checked)">
                        ` : '<span class="vault-select-placeholder"></span>'}
                    </div>
                    <div class="vault-folder-info">
                        <div class="vault-folder-name">
                            ${colorDot}
                            <i data-lucide="folder" class="folder-icon"></i>
                            <span>${escapeHtml(folder.name)}</span>
                            <span class="vault-email-count">(${folder.email_count} emails)</span>
                        </div>
                        <div class="vault-folder-date">
                            Delete by: ${formatDate(folder.retention_date)} &middot; ${daysText}
                        </div>
                    </div>
                    <div class="vault-folder-actions">
                        <button class="btn btn-sm btn-secondary" onclick="openRestoreFolder(${folder.id})" title="Restore to Archive">
                            <i data-lucide="archive-restore"></i>
                            Restore
                        </button>
                        ${isOverdue ? `
                            <button class="btn btn-sm btn-danger" onclick="permadeleteFolder(${folder.id})" title="Permanently Delete">
                                <i data-lucide="trash-2"></i>
                                Delete
                            </button>
                        ` : ''}
                    </div>
                </div>
            `;
        }
        
        html += `</div>`;
    }
    
    html += `</div>`;
    
    emailList.innerHTML = html;
    if (typeof lucide !== 'undefined') lucide.createIcons();
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
 * Toggle vault folder selection.
 */
function toggleVaultSelect(folderId, checked) {
    if (checked) {
        selectedVaultFolders.add(folderId);
    } else {
        selectedVaultFolders.delete(folderId);
    }
    renderVaultList();
}
window.toggleVaultSelect = toggleVaultSelect;


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
 * Batch permanently delete selected folders.
 */
async function batchPermadelete() {
    const selectedOverdue = [...selectedVaultFolders].filter(id => {
        const folder = vaultFolders.find(f => f.id === id);
        return folder && folder.is_overdue;
    });
    
    if (selectedOverdue.length === 0) return;
    
    const totalEmails = selectedOverdue.reduce((sum, id) => {
        const folder = vaultFolders.find(f => f.id === id);
        return sum + (folder?.email_count || 0);
    }, 0);
    
    const confirmed = await showConfirm(
        'Permanently Delete?',
        `Delete ${selectedOverdue.length} folders containing ${totalEmails} emails? This cannot be undone.`,
        { okText: 'Delete Forever', danger: true }
    );
    
    if (!confirmed) return;
    
    try {
        const response = await fetch('/api/folders/batch-permadelete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ folder_ids: selectedOverdue }),
        });
        
        if (!response.ok) {
            const data = await response.json();
            showAlert('Error', data.error || 'Failed to delete folders');
            return;
        }
        
        selectedVaultFolders.clear();
        
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
window.batchPermadelete = batchPermadelete;


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
