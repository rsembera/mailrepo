/**
 * Review View
 * 
 * Renders the staged items review as a view within the main app layout.
 */

import { getStagedEmails, getStagedFolders, clearStagedEmail, clearStagedFolder, clearAllStaged, updateStagedBadge } from '../components/staging.js';
import { showConfirm, showAlert } from '../modals.js';
import { loadFolders } from '../state.js';
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
    
    // Hide sidebar and toolbar
    if (sidebar) sidebar.style.display = 'none';
    if (toolbar) toolbar.style.display = 'none';
    
    if (contextTitle) contextTitle.textContent = 'Review Staged Items';
    if (contextMeta) contextMeta.textContent = '';
    
    // Set up header actions
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
    
    // Load accounts from API
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
                    <p>Select emails from an account or archive folder, then click Stage to queue them for archiving.</p>
                </div>
            </div>
        `;
        if (typeof lucide !== 'undefined') lucide.createIcons();
        updateButtons();
        return;
    }
    
    let html = '<div class="review-view"><div class="review-list">';
    
    // Group emails by source
    const emailsBySource = new Map();
    stagedEmails.forEach((data, emailId) => {
        const key = data.sourceType === 'import' 
            ? `import:${data.sourceImportId}` 
            : `account:${data.sourceAccountId}:${data.sourceFolder || 'INBOX'}`;
        if (!emailsBySource.has(key)) {
            emailsBySource.set(key, []);
        }
        // Flatten email data for easier access in template
        emailsBySource.get(key).push({ 
            emailId, 
            ...data,
            // Pull email properties to top level for template access
            subject: data.email?.subject,
            from: data.email?.from,
            date: data.email?.date,
        });
    });
    
    // Render email groups
    emailsBySource.forEach((emails, sourceKey) => {
        const firstEmail = emails[0];
        const sourceName = getSourceName(sourceKey, firstEmail);
        const isImapSource = sourceKey.startsWith('account:');
        
        html += `
            <div class="review-group">
                <div class="review-group-header">
                    <div class="review-group-header-left">
                        <span class="review-group-title">${escapeHtml(sourceName)}</span>
                        <span class="review-group-count">${emails.length} email${emails.length !== 1 ? 's' : ''}</span>
                    </div>
                    ${isImapSource ? `
                    <div class="review-group-header-right">
                        <label class="source-action-label">
                            <span>After commit:</span>
                            ${renderSourceActionDropdown(sourceKey)}
                        </label>
                    </div>
                    ` : ''}
                </div>
                <div class="review-group-items">
        `;
        
        emails.forEach(email => {
            const destFolder = folders.find(f => f.id == email.destinationFolderId);
            const destName = destFolder ? destFolder.name : 'Select folder...';
            
            html += `
                <div class="review-item" data-email-id="${email.emailId}">
                    <div class="review-item-info">
                        <div class="review-item-subject">${escapeHtml(email.subject || '(no subject)')}</div>
                        <div class="review-item-meta">
                            <span class="review-item-from">${escapeHtml(extractName(email.from))}</span>
                            <span class="review-item-date">${formatDate(email.date)}</span>
                        </div>
                    </div>
                    <div class="review-item-dest">
                        <div class="icon-select" data-email-id="${email.emailId}" data-value="${email.destinationFolderId || ''}">
                            <button class="icon-select-trigger">
                                <i data-lucide="folder"></i>
                                <span>${escapeHtml(destName)}</span>
                                <i data-lucide="chevron-down" class="icon-select-arrow"></i>
                            </button>
                            <div class="icon-select-dropdown">
                                ${renderFolderOptions(email.destinationFolderId)}
                            </div>
                        </div>
                    </div>
                    <button class="btn btn-sm btn-icon btn-danger-subtle" onclick="unstageEmailFromReview('${email.emailId}')" title="Unstage">
                        <i data-lucide="x"></i>
                    </button>
                </div>
            `;
        });
        
        html += '</div></div>';
    });

    // Render staged folders - group by source
    if (stagedFolders.length > 0) {
        // Group folders by source
        const foldersBySource = new Map();
        stagedFolders.forEach((sf, index) => {
            const key = sf.sourceType === 'import'
                ? `import:${sf.importId}`
                : `account:${sf.accountId}`;
            if (!foldersBySource.has(key)) {
                foldersBySource.set(key, []);
            }
            foldersBySource.get(key).push({ ...sf, originalIndex: index });
        });
        
        foldersBySource.forEach((foldersInSource, sourceKey) => {
            const firstFolder = foldersInSource[0];
            const isImapSource = sourceKey.startsWith('account:');
            const sourceName = firstFolder.sourceType === 'import'
                ? getImportName(firstFolder.importId)
                : getAccountName(firstFolder.accountId);
            
            html += `
                <div class="review-group">
                    <div class="review-group-header">
                        <div class="review-group-header-left">
                            <span class="review-group-title">${escapeHtml(sourceName)} (Folders)</span>
                            <span class="review-group-count">${foldersInSource.length} folder${foldersInSource.length !== 1 ? 's' : ''}</span>
                        </div>
                        ${isImapSource ? `
                        <div class="review-group-header-right">
                            <label class="source-action-label">
                                <span>After commit:</span>
                                ${renderSourceActionDropdown(`folder:${sourceKey}`)}
                            </label>
                        </div>
                        ` : ''}
                    </div>
                    <div class="review-group-items">
            `;
            
            foldersInSource.forEach((sf) => {
                const index = sf.originalIndex;
                const destFolder = folders.find(f => f.id == sf.destinationFolderId);
                const destName = destFolder ? destFolder.name : 'Select folder...';
                
                html += `
                    <div class="review-item review-item-folder" data-folder-index="${index}">
                        <div class="review-item-info">
                            <div class="review-item-subject">
                                <i data-lucide="folder" style="width: 16px; height: 16px; margin-right: 4px;"></i>
                                ${escapeHtml(sf.archivePath || sf.folder.split('/').pop() || '(root)')}
                            </div>
                            <div class="review-item-meta">
                                <span class="review-item-from">${escapeHtml(sf.folder)}</span>
                            </div>
                        </div>
                        <div class="review-item-dest">
                            <div class="icon-select" data-folder-index="${index}" data-value="${sf.destinationFolderId || ''}">
                                <button class="icon-select-trigger">
                                    <i data-lucide="folder"></i>
                                    <span>${escapeHtml(destName)}</span>
                                    <i data-lucide="chevron-down" class="icon-select-arrow"></i>
                                </button>
                                <div class="icon-select-dropdown">
                                    ${renderFolderOptions(sf.destinationFolderId)}
                                </div>
                            </div>
                        </div>
                        <button class="btn btn-sm btn-icon btn-danger-subtle" onclick="unstageFolderFromReview(${index})" title="Unstage">
                            <i data-lucide="x"></i>
                        </button>
                    </div>
                `;
            });
            
            html += '</div></div>';
        });
    }
    
    html += '</div></div>';
    
    emailList.innerHTML = html;
    if (typeof lucide !== 'undefined') lucide.createIcons();
    
    initIconSelects();
    updateButtons();
}

function getSourceName(sourceKey, firstEmail) {
    if (sourceKey.startsWith('import:')) {
        const importId = sourceKey.split(':')[1];
        return getImportName(importId);
    } else {
        const parts = sourceKey.split(':');
        const accountId = parts[1];
        const folder = parts[2] || 'INBOX';
        const accountName = getAccountName(accountId);
        return `${accountName} / ${folder}`;
    }
}

function getAccountName(accountId) {
    const account = accounts.find(a => a.id == accountId);
    return account ? account.name : `Account ${accountId}`;
}

function getImportName(importId) {
    const imports = window.getMountedImports ? window.getMountedImports() : [];
    const imp = imports.find(i => i.id === importId);
    return imp ? imp.name : `Import`;
}

function getFolderSourceName(sf) {
    if (sf.sourceType === 'import') {
        return getImportName(sf.importId);
    } else {
        return getAccountName(sf.accountId);
    }
}

function renderSourceActionDropdown(sourceKey, selectedValue = 'leave') {
    const options = [
        { value: 'leave', label: 'Leave in place' },
        { value: 'archive', label: 'Move to Archive' },
        { value: 'trash', label: 'Move to Trash' },
        { value: 'delete', label: 'Delete permanently' },
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

function renderFolderOptions(selectedId) {
    const topLevel = folders.filter(f => !f.parent_id && !f.deleted_at);
    
    function renderFolder(folder, depth) {
        const indent = depth * 12;
        const isSelected = folder.id == selectedId;
        
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
    
    let html = '';
    topLevel.forEach(folder => {
        html += renderFolder(folder, 0);
    });
    
    return html || '<div class="icon-select-empty">No folders available</div>';
}

function initIconSelects() {
    document.querySelectorAll('.icon-select').forEach(select => {
        const trigger = select.querySelector('.icon-select-trigger');
        const dropdown = select.querySelector('.icon-select-dropdown');
        const isSourceAction = select.classList.contains('source-action-dropdown');
        
        trigger?.addEventListener('click', (e) => {
            e.stopPropagation();
            document.querySelectorAll('.icon-select-dropdown.open').forEach(d => {
                if (d !== dropdown) {
                    d.classList.remove('open');
                    d.style.removeProperty('bottom');
                    d.style.removeProperty('top');
                }
            });
            
            // Check if dropdown would go off screen
            if (dropdown) {
                const triggerRect = trigger.getBoundingClientRect();
                const dropdownHeight = 200; // max-height from CSS
                const spaceBelow = window.innerHeight - triggerRect.bottom;
                
                if (spaceBelow < dropdownHeight && triggerRect.top > dropdownHeight) {
                    // Show above
                    dropdown.style.bottom = '100%';
                    dropdown.style.top = 'auto';
                    dropdown.style.marginBottom = '4px';
                    dropdown.style.marginTop = '0';
                } else {
                    // Show below (default)
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
                const emailId = select.dataset.emailId;
                const folderIndex = select.dataset.folderIndex;
                const sourceKey = select.dataset.sourceKey;
                
                if (sourceKey) {
                    // Source action dropdown - just update the display and store the value
                    select.dataset.value = value;
                    const triggerSpan = trigger.querySelector('span');
                    if (triggerSpan) {
                        triggerSpan.textContent = option.querySelector('span')?.textContent || value;
                    }
                    // Update selected state
                    dropdown.querySelectorAll('.icon-select-option').forEach(o => o.classList.remove('selected'));
                    option.classList.add('selected');
                    // Store in module state
                    sourceActions[sourceKey] = value;
                } else if (emailId) {
                    changeEmailDestination(emailId, value);
                } else if (folderIndex !== undefined) {
                    changeFolderDestination(parseInt(folderIndex), value);
                }
                
                dropdown.classList.remove('open');
            });
        });
    });
    
    // Close dropdowns when clicking outside (only add once)
    if (!dropdownClickListenerAdded) {
        document.addEventListener('click', () => {
            document.querySelectorAll('.icon-select-dropdown.open').forEach(d => {
                d.classList.remove('open');
            });
        });
        dropdownClickListenerAdded = true;
    }
}

function changeEmailDestination(emailId, folderId) {
    const stagedEmails = getStagedEmails();
    const data = stagedEmails.get(emailId);
    if (data) {
        data.destinationFolderId = folderId;
        sessionStorage.setItem('stagedEmails', JSON.stringify([...stagedEmails.entries()]));
        renderReviewView();
    }
}

function changeFolderDestination(index, folderId) {
    const stagedFolders = getStagedFolders();
    if (stagedFolders[index]) {
        stagedFolders[index].destinationFolderId = folderId;
        sessionStorage.setItem('stagedFolders', JSON.stringify(stagedFolders));
        renderReviewView();
    }
}

function unstageAll() {
    clearAllStaged();
    updateStagedBadge();
    renderReviewView();
}

window.unstageEmailFromReview = function(emailId) {
    clearStagedEmail(emailId);
    updateStagedBadge();
    renderReviewView();
};

window.unstageFolderFromReview = function(index) {
    clearStagedFolder(index);
    updateStagedBadge();
    renderReviewView();
};

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

async function commitAll() {
    const stagedEmails = getStagedEmails();
    const stagedFolders = getStagedFolders();
    
    if (stagedEmails.size === 0 && stagedFolders.length === 0) return;
    
    const commitBtn = document.getElementById('commitBtn');
    if (commitBtn) {
        commitBtn.disabled = true;
    }
    
    // Show progress modal
    const modal = document.getElementById('commitProgressModal');
    const progressContainer = document.getElementById('commitProgressContent');
    modal.classList.add('active');
    
    // Import and create progress component
    const { createProgress } = await import('../components/progress.js');
    const progress = createProgress(progressContainer);
    
    try {
        // Prepare commit data
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
        
        // Collect source actions from icon-select dropdowns
        const postCommitActions = { ...sourceActions };
        document.querySelectorAll('.source-action-dropdown').forEach(dropdown => {
            const sourceKey = dropdown.dataset.sourceKey;
            const value = dropdown.dataset.value || 'leave';
            postCommitActions[sourceKey] = value;
        });
        
        // Use progress component for streaming
        await progress.startPostStream('/api/commit/stream', {
            staged: emails,
            folders: foldersToCommit,
            sourceActions: postCommitActions,
        }, {
            onComplete: async (data) => {
                // Close modal
                modal.classList.remove('active');
                
                // Clear all staged items after commit
                clearAllStaged();
                updateStagedBadge();
                
                // Refresh sidebar to show new folders
                await refreshSidebar();
                
                // Re-render the review view (now empty)
                renderReviewView();
                
                // Show results
                const results = data.results || {};
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
        if (commitBtn) {
            commitBtn.disabled = false;
        }
        updateButtons();
    }
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function extractName(sender) {
    if (!sender) return 'Unknown';
    const match = sender.match(/^([^<]+)/);
    return match ? match[1].trim().replace(/"/g, '') : sender;
}

function formatDate(dateStr) {
    if (!dateStr) return '';
    try {
        const date = new Date(dateStr);
        return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    } catch (e) {
        return dateStr;
    }
}
