/**
 * Review View
 * 
 * Renders the staged items review grouped by destination folder.
 * Bulk operations only - individual item management happens during staging.
 */

import { getStagedEmails, getStagedFolders, clearAllStaged, updateStagedBadge } from '../components/staging.js';
import { showConfirm, showAlert } from '../modals.js';
import { state, loadFolders } from '../state.js';
import { refreshSidebarFolders } from '../components/sidebar.js';

let contextTitle = null;
let contextMeta = null;
let emailList = null;

let folders = [];
let accounts = [];
let sourceActions = {};
let dropdownClickListenerAdded = false;

/**
 * Refresh sidebar by reloading folders from server and re-rendering.
 */
async function refreshSidebar() {
    await loadFolders();
    refreshSidebarFolders();
}

/**
 * Initialize the review view.
 */
export function initReviewView(config) {
    contextTitle = config.contextTitle;
    contextMeta = config.contextMeta;
    emailList = config.emailList;
}

/**
 * Show the review view in the main content area.
 */
export async function showReviewView() {
    const sidebar = document.getElementById('sidebar');
    const toolbar = document.querySelector('.content-toolbar');
    const headerActions = document.querySelector('.header-actions');
    
    if (sidebar) sidebar.style.display = 'none';
    if (toolbar) toolbar.style.display = 'none';
    
    if (contextTitle) contextTitle.textContent = 'Review Staged Items';
    if (contextMeta) contextMeta.textContent = '';
    
    if (headerActions) {
        headerActions.innerHTML = `
            <button class="btn btn-secondary" id="unstageAllBtn" title="Unstage all items">
                <i data-lucide="x-circle"></i>
                Unstage All
            </button>
            <button class="btn btn-primary" id="commitBtn" disabled>
                <i data-lucide="archive"></i>
                Commit
            </button>
        `;
        if (typeof lucide !== 'undefined') lucide.createIcons();
        
        document.getElementById('unstageAllBtn')?.addEventListener('click', async () => {
            const confirmed = await showConfirm(
                'Unstage All Items',
                'Are you sure you want to unstage all items? This cannot be undone.',
                { confirmText: 'Unstage All', confirmClass: 'btn-danger' }
            );
            if (confirmed) {
                unstageAll();
            }
        });
        
        document.getElementById('commitBtn')?.addEventListener('click', commitAll);
    }
    
    await loadAccounts();
    await loadFoldersForReview();
    renderReviewView();
}

async function loadAccounts() {
    try {
        const response = await fetch('/api/accounts');
        if (response.ok) {
            const data = await response.json();
            accounts = data.accounts || [];
        }
    } catch (e) {
        console.error('Failed to load accounts:', e);
    }
}

async function loadFoldersForReview() {
    try {
        const response = await fetch('/api/folders');
        if (response.ok) {
            const data = await response.json();
            folders = data.folders;
        }
    } catch (e) {
        console.error('Failed to load folders:', e);
    }
}


/**
 * Build data structure grouped by destination, then source.
 * Returns: Map<destinationId, { emails: Map<sourceKey, items[]>, folders: Map<sourceKey, items[]> }>
 */
function buildGroupedData() {
    const stagedEmails = getStagedEmails();
    const stagedFolders = getStagedFolders();
    
    // Group by destination folder ID
    const byDestination = new Map();
    
    // Process emails
    stagedEmails.forEach((data, emailId) => {
        const destId = data.destinationFolderId || 'unassigned';
        if (!byDestination.has(destId)) {
            byDestination.set(destId, { emails: new Map(), folders: new Map() });
        }
        
        const sourceKey = data.sourceType === 'import'
            ? `import:${data.sourceImportId}`
            : `account:${data.sourceAccountId}`;
        
        const sourceFolder = data.sourceFolder || 'INBOX';
        const fullSourceKey = data.sourceType === 'import' 
            ? sourceKey 
            : `${sourceKey}:${sourceFolder}`;
        
        const dest = byDestination.get(destId);
        if (!dest.emails.has(sourceKey)) {
            dest.emails.set(sourceKey, { byFolder: new Map(), sourceType: data.sourceType, accountId: data.sourceAccountId, importId: data.sourceImportId });
        }
        
        const source = dest.emails.get(sourceKey);
        if (!source.byFolder.has(sourceFolder)) {
            source.byFolder.set(sourceFolder, []);
        }
        source.byFolder.get(sourceFolder).push({ emailId, ...data });
    });
    
    // Process folders
    stagedFolders.forEach((sf, index) => {
        const destId = sf.destinationFolderId || 'unassigned';
        if (!byDestination.has(destId)) {
            byDestination.set(destId, { emails: new Map(), folders: new Map() });
        }
        
        const sourceKey = sf.sourceType === 'import'
            ? `import:${sf.importId}`
            : `account:${sf.accountId}`;
        
        const dest = byDestination.get(destId);
        if (!dest.folders.has(sourceKey)) {
            dest.folders.set(sourceKey, { items: [], sourceType: sf.sourceType, accountId: sf.accountId, importId: sf.importId });
        }
        dest.folders.get(sourceKey).items.push({ ...sf, originalIndex: index });
    });
    
    return byDestination;
}

function renderReviewView() {
    const stagedEmails = getStagedEmails();
    const stagedFolders = getStagedFolders();
    const totalCount = stagedEmails.size + stagedFolders.length;
    
    if (totalCount === 0) {
        emailList.innerHTML = `
            <div class="review-view">
                <div class="empty-state">
                    <i data-lucide="package" class="empty-icon"></i>
                    <h3>No Staged Items</h3>
                    <p>Select emails or folders from an account or import, then click Stage to queue them for archiving.</p>
                </div>
            </div>
        `;
        if (typeof lucide !== 'undefined') lucide.createIcons();
        updateButtons();
        return;
    }
    
    const byDestination = buildGroupedData();
    
    let html = '<div class="review-view"><div class="review-list">';
    
    byDestination.forEach((destData, destId) => {
        const destFolder = folders.find(f => f.id == destId);
        const destName = destFolder ? destFolder.name : (destId === 'unassigned' ? 'No destination selected' : 'Unknown folder');
        
        // Count totals for this destination
        let emailCount = 0;
        let folderCount = 0;
        destData.emails.forEach(source => {
            source.byFolder.forEach(items => emailCount += items.length);
        });
        destData.folders.forEach(source => {
            folderCount += source.items.length;
        });
        
        const countParts = [];
        if (emailCount > 0) countParts.push(`${emailCount} email${emailCount !== 1 ? 's' : ''}`);
        if (folderCount > 0) countParts.push(`${folderCount} folder${folderCount !== 1 ? 's' : ''}`);
        
        html += `
            <div class="review-destination-group" data-dest-id="${destId}">
                <div class="review-destination-header">
                    <div class="review-destination-header-left">
                        <i data-lucide="folder" class="review-dest-icon"></i>
                        <span class="review-destination-title">→ ${escapeHtml(destName)}</span>
                        <span class="review-destination-count">(${countParts.join(', ')})</span>
                    </div>
                    <div class="review-destination-header-right">
                        ${renderDestinationDropdown(destId)}
                        <button class="btn btn-sm btn-icon" onclick="unstageDestination('${destId}')" title="Unstage all items going to this folder">
                            <i data-lucide="x"></i>
                        </button>
                    </div>
                </div>
                <div class="review-destination-content">
        `;
        
        // Render email sources
        destData.emails.forEach((source, sourceKey) => {
            html += renderSourceGroup(source, sourceKey, destId, 'emails');
        });
        
        // Render folder sources
        destData.folders.forEach((source, sourceKey) => {
            html += renderSourceGroup(source, sourceKey, destId, 'folders');
        });
        
        html += `
                </div>
            </div>
        `;
    });
    
    html += '</div></div>';
    
    emailList.innerHTML = html;
    if (typeof lucide !== 'undefined') lucide.createIcons();
    
    initIconSelects();
    updateButtons();
}


function renderSourceGroup(source, sourceKey, destId, type) {
    const isImap = sourceKey.startsWith('account:');
    const sourceName = isImap ? getAccountName(source.accountId) : getImportName(source.importId);
    
    let html = '';
    
    if (type === 'emails') {
        // For emails: one line per source folder within the account
        source.byFolder.forEach((items, folderName) => {
            const lineKey = `${sourceKey}:${folderName}`;
            const escapedLineKey = escapeForOnclick(lineKey);
            const escapedDestId = escapeForOnclick(String(destId));
            
            html += `
                <div class="review-source-line" data-source-key="${escapeHtml(lineKey)}" data-dest-id="${destId}">
                    <div class="review-source-line-left">
                        <i data-lucide="${isImap ? 'mail' : 'archive'}" class="review-source-icon"></i>
                        <span class="review-source-name">${escapeHtml(sourceName)}</span>
                        <span class="review-source-folder">${escapeHtml(folderName)}</span>
                        <span class="review-source-count">(${items.length})</span>
                    </div>
                    <div class="review-source-line-right">
                        ${isImap ? `
                            <label class="source-action-label">
                                <span>After:</span>
                                ${renderSourceActionDropdown(`${sourceKey}:${folderName}:${destId}`)}
                            </label>
                        ` : `
                            <span class="review-import-label">No server action</span>
                        `}
                        <button class="btn btn-sm btn-icon" onclick="unstageSourceFolder('${escapedLineKey}', '${escapedDestId}')" title="Unstage">
                            <i data-lucide="x"></i>
                        </button>
                    </div>
                </div>
            `;
        });
    } else {
        // For folders: one line per staged folder
        source.items.forEach((sf) => {
            const folderDisplayName = sf.archivePath || sf.folder.split('/').pop() || '(folder)';
            const index = sf.originalIndex;
            const escapedDestId = escapeForOnclick(String(destId));
            
            html += `
                <div class="review-source-line" data-folder-index="${index}" data-dest-id="${destId}">
                    <div class="review-source-line-left">
                        <i data-lucide="folder" class="review-source-icon"></i>
                        <span class="review-source-name">${escapeHtml(sourceName)}</span>
                        <span class="review-source-folder">${escapeHtml(folderDisplayName)}</span>
                    </div>
                    <div class="review-source-line-right">
                        ${isImap ? `
                            <label class="source-action-label">
                                <span>After:</span>
                                ${renderSourceActionDropdown(`folder:${sourceKey}:${index}:${destId}`)}
                            </label>
                        ` : `
                            <span class="review-import-label">No server action</span>
                        `}
                        <button class="btn btn-sm btn-icon" onclick="unstageFolderByIndex(${index})" title="Unstage">
                            <i data-lucide="x"></i>
                        </button>
                    </div>
                </div>
            `;
        });
    }
    
    return html;
}

function renderDestinationDropdown(currentDestId) {
    const topLevel = folders.filter(f => !f.parent_id && !f.deleted_at);
    
    function renderFolder(folder, depth) {
        const indent = depth * 12;
        const isSelected = folder.id == currentDestId;
        
        let html = `
            <div class="icon-select-option ${isSelected ? 'selected' : ''}" 
                 data-value="${folder.id}" style="padding-left: ${8 + indent}px">
                <i data-lucide="folder"></i>
                <span>${escapeHtml(folder.name)}</span>
            </div>
        `;
        
        const children = folders.filter(f => f.parent_id == folder.id && !f.deleted_at);
        children.forEach(child => {
            html += renderFolder(child, depth + 1);
        });
        
        return html;
    }
    
    let optionsHtml = '';
    topLevel.forEach(folder => {
        optionsHtml += renderFolder(folder, 0);
    });
    
    const currentFolder = folders.find(f => f.id == currentDestId);
    const currentName = currentFolder ? currentFolder.name : 'Select...';
    
    return `
        <div class="icon-select dest-change-dropdown" data-dest-id="${currentDestId}">
            <button class="icon-select-trigger" title="Change destination folder">
                <i data-lucide="folder-output" class="icon-select-icon"></i>
                <span>Destination</span>
                <i data-lucide="chevron-down" class="icon-select-arrow"></i>
            </button>
            <div class="icon-select-dropdown">
                ${optionsHtml || '<div class="icon-select-empty">No folders available</div>'}
            </div>
        </div>
    `;
}

function renderSourceActionDropdown(sourceKey, selectedValue = 'leave') {
    const options = [
        { value: 'leave', label: 'Leave' },
        { value: 'archive', label: 'Archive' },
        { value: 'trash', label: 'Trash' },
        { value: 'delete', label: 'Delete' },
    ];
    
    const selected = options.find(o => o.value === selectedValue) || options[0];
    
    return `
        <div class="icon-select source-action-dropdown" data-source-key="${escapeHtml(sourceKey)}" data-value="${selected.value}">
            <button class="icon-select-trigger">
                <span>${escapeHtml(selected.label)}</span>
                <i data-lucide="chevron-down" class="icon-select-arrow"></i>
            </button>
            <div class="icon-select-dropdown">
                ${options.map(opt => `
                    <div class="icon-select-option ${opt.value === selected.value ? 'selected' : ''}" data-value="${opt.value}">
                        <span>${escapeHtml(opt.label)}</span>
                    </div>
                `).join('')}
            </div>
        </div>
    `;
}


// === Unstage functions ===

window.unstageDestination = async function(destId) {
    const stagedEmails = getStagedEmails();
    const stagedFolders = getStagedFolders();
    
    // Count items to unstage
    let count = 0;
    stagedEmails.forEach(data => {
        if (String(data.destinationFolderId) === String(destId) || (destId === 'unassigned' && !data.destinationFolderId)) {
            count++;
        }
    });
    stagedFolders.forEach(sf => {
        if (String(sf.destinationFolderId) === String(destId) || (destId === 'unassigned' && !sf.destinationFolderId)) {
            count++;
        }
    });
    
    const destFolder = folders.find(f => f.id == destId);
    const destName = destFolder ? destFolder.name : 'this destination';
    
    const confirmed = await showConfirm(
        'Unstage Items',
        `Unstage all ${count} item${count !== 1 ? 's' : ''} going to "${destName}"?`,
        { confirmText: 'Unstage', confirmClass: 'btn-danger' }
    );
    
    if (!confirmed) return;
    
    // Remove matching emails
    const newEmails = new Map();
    stagedEmails.forEach((data, emailId) => {
        const matches = String(data.destinationFolderId) === String(destId) || (destId === 'unassigned' && !data.destinationFolderId);
        if (!matches) {
            newEmails.set(emailId, data);
        }
    });
    sessionStorage.setItem('stagedEmails', JSON.stringify([...newEmails.entries()]));
    
    // Remove matching folders
    const newFolders = stagedFolders.filter(sf => {
        const matches = String(sf.destinationFolderId) === String(destId) || (destId === 'unassigned' && !sf.destinationFolderId);
        return !matches;
    });
    sessionStorage.setItem('stagedFolders', JSON.stringify(newFolders));
    
    updateStagedBadge();
    renderReviewView();
};

window.unstageSource = async function(sourceKey, destId, type) {
    const stagedEmails = getStagedEmails();
    const stagedFolders = getStagedFolders();
    
    // Count items to unstage
    let count = 0;
    
    if (type === 'emails') {
        stagedEmails.forEach(data => {
            const itemSourceKey = data.sourceType === 'import'
                ? `import:${data.sourceImportId}`
                : `account:${data.sourceAccountId}`;
            const itemDestId = String(data.destinationFolderId || 'unassigned');
            if (itemSourceKey === sourceKey && itemDestId === String(destId)) {
                count++;
            }
        });
    } else {
        stagedFolders.forEach(sf => {
            const itemSourceKey = sf.sourceType === 'import'
                ? `import:${sf.importId}`
                : `account:${sf.accountId}`;
            const itemDestId = String(sf.destinationFolderId || 'unassigned');
            if (itemSourceKey === sourceKey && itemDestId === String(destId)) {
                count++;
            }
        });
    }
    
    const confirmed = await showConfirm(
        'Unstage Items',
        `Unstage ${count} ${type === 'emails' ? 'email' : 'folder'}${count !== 1 ? 's' : ''} from this source?`,
        { confirmText: 'Unstage', confirmClass: 'btn-danger' }
    );
    
    if (!confirmed) return;
    
    if (type === 'emails') {
        const newEmails = new Map();
        stagedEmails.forEach((data, emailId) => {
            const itemSourceKey = data.sourceType === 'import'
                ? `import:${data.sourceImportId}`
                : `account:${data.sourceAccountId}`;
            const itemDestId = String(data.destinationFolderId || 'unassigned');
            const matches = itemSourceKey === sourceKey && itemDestId === String(destId);
            if (!matches) {
                newEmails.set(emailId, data);
            }
        });
        sessionStorage.setItem('stagedEmails', JSON.stringify([...newEmails.entries()]));
    } else {
        const newFolders = stagedFolders.filter(sf => {
            const itemSourceKey = sf.sourceType === 'import'
                ? `import:${sf.importId}`
                : `account:${sf.accountId}`;
            const itemDestId = String(sf.destinationFolderId || 'unassigned');
            const matches = itemSourceKey === sourceKey && itemDestId === String(destId);
            return !matches;
        });
        sessionStorage.setItem('stagedFolders', JSON.stringify(newFolders));
    }
    
    updateStagedBadge();
    renderReviewView();
};

// Unstage emails from a specific source folder (account:id:folderName)
window.unstageSourceFolder = async function(lineKey, destId) {
    const stagedEmails = getStagedEmails();
    
    // Parse lineKey: "account:123:INBOX" or "import:abc:FolderName"
    const parts = lineKey.split(':');
    const sourceType = parts[0];
    const sourceId = parts[1];
    const folderName = parts.slice(2).join(':'); // Handle folder names with colons
    
    // Count matching emails
    let count = 0;
    stagedEmails.forEach(data => {
        const itemSourceKey = data.sourceType === 'import'
            ? `import:${data.sourceImportId}`
            : `account:${data.sourceAccountId}`;
        const itemFolder = data.sourceFolder || 'INBOX';
        const itemDestId = String(data.destinationFolderId || 'unassigned');
        
        if (`${sourceType}:${sourceId}` === itemSourceKey && 
            itemFolder === folderName && 
            itemDestId === String(destId)) {
            count++;
        }
    });
    
    const confirmed = await showConfirm(
        'Unstage Emails',
        `Unstage ${count} email${count !== 1 ? 's' : ''} from ${folderName}?`,
        { confirmText: 'Unstage', confirmClass: 'btn-danger' }
    );
    
    if (!confirmed) return;
    
    const newEmails = new Map();
    stagedEmails.forEach((data, emailId) => {
        const itemSourceKey = data.sourceType === 'import'
            ? `import:${data.sourceImportId}`
            : `account:${data.sourceAccountId}`;
        const itemFolder = data.sourceFolder || 'INBOX';
        const itemDestId = String(data.destinationFolderId || 'unassigned');
        
        const matches = `${sourceType}:${sourceId}` === itemSourceKey && 
                       itemFolder === folderName && 
                       itemDestId === String(destId);
        if (!matches) {
            newEmails.set(emailId, data);
        }
    });
    sessionStorage.setItem('stagedEmails', JSON.stringify([...newEmails.entries()]));
    
    updateStagedBadge();
    renderReviewView();
};

// Unstage a single folder by its index
window.unstageFolderByIndex = async function(index) {
    const stagedFolders = getStagedFolders();
    const sf = stagedFolders[index];
    if (!sf) return;
    
    const folderName = sf.archivePath || sf.folder.split('/').pop() || 'this folder';
    
    const confirmed = await showConfirm(
        'Unstage Folder',
        `Unstage "${folderName}"?`,
        { confirmText: 'Unstage', confirmClass: 'btn-danger' }
    );
    
    if (!confirmed) return;
    
    stagedFolders.splice(index, 1);
    sessionStorage.setItem('stagedFolders', JSON.stringify(stagedFolders));
    
    updateStagedBadge();
    renderReviewView();
};

// === Change destination ===

function changeDestination(oldDestId, newDestId) {
    const stagedEmails = getStagedEmails();
    const stagedFolders = getStagedFolders();
    
    // Update emails
    stagedEmails.forEach(data => {
        const itemDestId = String(data.destinationFolderId || 'unassigned');
        if (itemDestId === String(oldDestId)) {
            data.destinationFolderId = newDestId;
        }
    });
    sessionStorage.setItem('stagedEmails', JSON.stringify([...stagedEmails.entries()]));
    
    // Update folders
    stagedFolders.forEach(sf => {
        const itemDestId = String(sf.destinationFolderId || 'unassigned');
        if (itemDestId === String(oldDestId)) {
            sf.destinationFolderId = newDestId;
        }
    });
    sessionStorage.setItem('stagedFolders', JSON.stringify(stagedFolders));
    
    renderReviewView();
}


// === Icon select initialization ===

function initIconSelects() {
    document.querySelectorAll('.icon-select').forEach(select => {
        const trigger = select.querySelector('.icon-select-trigger');
        const dropdown = select.querySelector('.icon-select-dropdown');
        
        trigger?.addEventListener('click', (e) => {
            e.stopPropagation();
            document.querySelectorAll('.icon-select-dropdown.open').forEach(d => {
                if (d !== dropdown) d.classList.remove('open');
            });
            
            if (dropdown) {
                const triggerRect = trigger.getBoundingClientRect();
                const dropdownHeight = 200;
                const spaceBelow = window.innerHeight - triggerRect.bottom;
                
                if (spaceBelow < dropdownHeight && triggerRect.top > dropdownHeight) {
                    dropdown.style.bottom = '100%';
                    dropdown.style.top = 'auto';
                    dropdown.style.marginBottom = '4px';
                    dropdown.style.marginTop = '0';
                } else {
                    dropdown.style.top = '100%';
                    dropdown.style.bottom = 'auto';
                    dropdown.style.marginTop = '4px';
                    dropdown.style.marginBottom = '0';
                }
                
                dropdown.classList.toggle('open');
            }
        });
        
        dropdown?.querySelectorAll('.icon-select-option').forEach(option => {
            option.addEventListener('click', () => {
                const value = option.dataset.value;
                
                if (select.classList.contains('dest-change-dropdown')) {
                    // Change destination dropdown
                    const oldDestId = select.dataset.destId;
                    changeDestination(oldDestId, value);
                } else if (select.classList.contains('source-action-dropdown')) {
                    // Source action dropdown
                    const sourceKey = select.dataset.sourceKey;
                    select.dataset.value = value;
                    const triggerSpan = trigger.querySelector('span');
                    if (triggerSpan) {
                        triggerSpan.textContent = option.querySelector('span')?.textContent || value;
                    }
                    dropdown.querySelectorAll('.icon-select-option').forEach(o => o.classList.remove('selected'));
                    option.classList.add('selected');
                    sourceActions[sourceKey] = value;
                }
                
                dropdown.classList.remove('open');
            });
        });
    });
    
    if (!dropdownClickListenerAdded) {
        document.addEventListener('click', () => {
            document.querySelectorAll('.icon-select-dropdown.open').forEach(d => d.classList.remove('open'));
        });
        dropdownClickListenerAdded = true;
    }
}

// === Helper functions ===

function getAccountName(accountId) {
    const account = accounts.find(a => a.id == accountId);
    return account ? account.name : `Account ${accountId}`;
}

function getImportName(importId) {
    const imports = window.getMountedImports ? window.getMountedImports() : [];
    const imp = imports.find(i => i.id === importId);
    return imp ? imp.name : `Import`;
}

function unstageAll() {
    clearAllStaged();
    updateStagedBadge();
    renderReviewView();
}

function updateButtons() {
    const stagedEmails = getStagedEmails();
    const stagedFolders = getStagedFolders();
    const totalCount = stagedEmails.size + stagedFolders.length;
    
    const commitBtn = document.getElementById('commitBtn');
    const unstageAllBtn = document.getElementById('unstageAllBtn');
    
    // Check if all items have destinations
    let allHaveDestinations = true;
    stagedEmails.forEach(data => {
        if (!data.destinationFolderId) allHaveDestinations = false;
    });
    stagedFolders.forEach(sf => {
        if (!sf.destinationFolderId) allHaveDestinations = false;
    });
    
    if (commitBtn) {
        commitBtn.disabled = totalCount === 0 || !allHaveDestinations;
    }
    if (unstageAllBtn) {
        unstageAllBtn.disabled = totalCount === 0;
    }
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function escapeForOnclick(str) {
    if (!str) return '';
    return str.replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '&quot;');
}


// === Commit function ===

async function commitAll() {
    const stagedEmails = getStagedEmails();
    const stagedFolders = getStagedFolders();
    
    if (stagedEmails.size === 0 && stagedFolders.length === 0) return;
    
    const commitBtn = document.getElementById('commitBtn');
    if (commitBtn) commitBtn.disabled = true;
    
    const modal = document.getElementById('commitProgressModal');
    const progressContainer = document.getElementById('commitProgressContent');
    modal.classList.add('active');
    
    const { createProgress } = await import('../components/progress.js');
    const progress = createProgress(progressContainer);
    
    try {
        const emails = [];
        stagedEmails.forEach((data, emailId) => {
            emails.push({
                email: data.email,
                destinationFolderId: data.destinationFolderId,
                sourceType: data.sourceType,
                sourceAccountId: data.sourceAccountId,
                sourceImportId: data.sourceImportId,
                sourceFolder: data.sourceFolder,
            });
        });
        
        const foldersToCommit = stagedFolders.map(sf => ({
            sourceType: sf.sourceType,
            accountId: sf.accountId,
            importId: sf.importId,
            importPath: sf.importPath,
            importType: sf.importType,
            folder: sf.folder,
            archivePath: sf.archivePath,
            destinationFolderId: sf.destinationFolderId,
        }));
        
        // Collect source actions
        const postCommitActions = { ...sourceActions };
        document.querySelectorAll('.source-action-dropdown').forEach(dropdown => {
            const sourceKey = dropdown.dataset.sourceKey;
            const value = dropdown.dataset.value || 'leave';
            postCommitActions[sourceKey] = value;
        });
        
        await progress.startPostStream('/api/commit/stream', {
            staged: emails,
            folders: foldersToCommit,
            sourceActions: postCommitActions,
        }, {
            onComplete: async (data) => {
                modal.classList.remove('active');
                clearAllStaged();
                updateStagedBadge();
                await refreshSidebar();
                renderReviewView();
                const msg = data.message || 'Commit complete.';
                showAlert('Commit Complete', msg);
            },
            onError: (err) => {
                modal.classList.remove('active');
                showAlert('Commit Failed', err.error || 'An error occurred during commit.');
            },
        });
        
    } catch (e) {
        console.error('Commit error:', e);
        modal.classList.remove('active');
        showAlert('Commit Error', 'Failed to commit: ' + e.message);
    } finally {
        if (commitBtn) commitBtn.disabled = false;
        updateButtons();
    }
}
