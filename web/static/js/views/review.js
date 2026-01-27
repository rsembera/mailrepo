/**
 * Review View
 * 
 * Renders the staged items review as a view within the main app layout.
 * Uses collapsible sections for better readability with large numbers of items.
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
let expandedSections = new Set(); // Track which sections are expanded
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
    
    // Build hierarchical structure: Account -> Folder -> Emails
    // For IMAP: group by account, then by source folder
    // For imports: group by import source
    
    const emailsByAccount = new Map(); // accountId -> Map(folder -> emails[])
    const emailsByImport = new Map();  // importId -> emails[]
    
    stagedEmails.forEach((data, emailId) => {
        const emailData = { 
            emailId, 
            ...data,
            subject: data.email?.subject,
            from: data.email?.from,
            date: data.email?.date,
        };
        
        if (data.sourceType === 'import') {
            const importId = data.sourceImportId;
            if (!emailsByImport.has(importId)) {
                emailsByImport.set(importId, []);
            }
            emailsByImport.get(importId).push(emailData);
        } else {
            const accountId = data.sourceAccountId;
            const folder = data.sourceFolder || 'INBOX';
            
            if (!emailsByAccount.has(accountId)) {
                emailsByAccount.set(accountId, new Map());
            }
            const accountFolders = emailsByAccount.get(accountId);
            if (!accountFolders.has(folder)) {
                accountFolders.set(folder, []);
            }
            accountFolders.get(folder).push(emailData);
        }
    });
    
    // Render IMAP account groups (emails)
    emailsByAccount.forEach((folderMap, accountId) => {
        const accountName = getAccountName(accountId);
        let totalEmails = 0;
        folderMap.forEach(emails => totalEmails += emails.length);
        
        const accountKey = `account:${accountId}`;
        const isAccountExpanded = expandedSections.has(accountKey);
        
        html += `
            <div class="review-group review-group-account">
                <div class="review-group-header review-group-header-account" onclick="toggleReviewSection('${accountKey}')">
                    <div class="review-group-header-left">
                        <i data-lucide="${isAccountExpanded ? 'chevron-down' : 'chevron-right'}" class="review-chevron"></i>
                        <i data-lucide="mail" class="review-source-icon"></i>
                        <span class="review-group-title">${escapeHtml(accountName)}</span>
                        <span class="review-group-count">${totalEmails} email${totalEmails !== 1 ? 's' : ''}</span>
                    </div>
                </div>
                <div class="review-group-content ${isAccountExpanded ? 'expanded' : 'collapsed'}">
        `;
        
        // Render each folder within this account
        folderMap.forEach((emails, folder) => {
            const folderKey = `account:${accountId}:${folder}`;
            const isFolderExpanded = expandedSections.has(folderKey);
            
            html += `
                <div class="review-subgroup">
                    <div class="review-subgroup-header" onclick="toggleReviewSection('${escapeForOnclick(folderKey)}'); event.stopPropagation();">
                        <div class="review-subgroup-header-left">
                            <i data-lucide="${isFolderExpanded ? 'chevron-down' : 'chevron-right'}" class="review-chevron"></i>
                            <i data-lucide="folder" class="review-folder-icon"></i>
                            <span class="review-subgroup-title">${escapeHtml(folder)}</span>
                            <span class="review-group-count">${emails.length} email${emails.length !== 1 ? 's' : ''}</span>
                        </div>
                        <div class="review-subgroup-header-right" onclick="event.stopPropagation();">
                            <label class="source-action-label">
                                <span>After commit:</span>
                                ${renderSourceActionDropdown(folderKey)}
                            </label>
                        </div>
                    </div>
                    <div class="review-subgroup-items ${isFolderExpanded ? 'expanded' : 'collapsed'}">
            `;
            
            emails.forEach(email => {
                html += renderEmailItem(email);
            });
            
            html += `
                    </div>
                </div>
            `;
        });
        
        html += `
                </div>
            </div>
        `;
    });
    
    // Render import groups (emails)
    emailsByImport.forEach((emails, importId) => {
        const importName = getImportName(importId);
        const importKey = `import:${importId}`;
        const isExpanded = expandedSections.has(importKey);
        
        html += `
            <div class="review-group review-group-import">
                <div class="review-group-header" onclick="toggleReviewSection('${importKey}')">
                    <div class="review-group-header-left">
                        <i data-lucide="${isExpanded ? 'chevron-down' : 'chevron-right'}" class="review-chevron"></i>
                        <i data-lucide="archive" class="review-source-icon"></i>
                        <span class="review-group-title">${escapeHtml(importName)}</span>
                        <span class="review-group-count">${emails.length} email${emails.length !== 1 ? 's' : ''}</span>
                    </div>
                </div>
                <div class="review-group-content ${isExpanded ? 'expanded' : 'collapsed'}">
                    <div class="review-group-items">
        `;
        
        emails.forEach(email => {
            html += renderEmailItem(email);
        });
        
        html += `
                    </div>
                </div>
            </div>
        `;
    });


    // Render staged folders - group by source
    if (stagedFolders.length > 0) {
        const foldersByAccount = new Map();
        const foldersByImport = new Map();
        
        stagedFolders.forEach((sf, index) => {
            const folderData = { ...sf, originalIndex: index };
            
            if (sf.sourceType === 'import') {
                if (!foldersByImport.has(sf.importId)) {
                    foldersByImport.set(sf.importId, []);
                }
                foldersByImport.get(sf.importId).push(folderData);
            } else {
                if (!foldersByAccount.has(sf.accountId)) {
                    foldersByAccount.set(sf.accountId, []);
                }
                foldersByAccount.get(sf.accountId).push(folderData);
            }
        });
        
        // Render IMAP folder groups
        foldersByAccount.forEach((foldersInSource, accountId) => {
            const accountName = getAccountName(accountId);
            const groupKey = `folders:account:${accountId}`;
            const isExpanded = expandedSections.has(groupKey);
            
            html += `
                <div class="review-group review-group-folders">
                    <div class="review-group-header" onclick="toggleReviewSection('${groupKey}')">
                        <div class="review-group-header-left">
                            <i data-lucide="${isExpanded ? 'chevron-down' : 'chevron-right'}" class="review-chevron"></i>
                            <i data-lucide="folders" class="review-source-icon"></i>
                            <span class="review-group-title">${escapeHtml(accountName)} (Folders)</span>
                            <span class="review-group-count">${foldersInSource.length} folder${foldersInSource.length !== 1 ? 's' : ''}</span>
                        </div>
                        <div class="review-group-header-right" onclick="event.stopPropagation();">
                            <label class="source-action-label">
                                <span>After commit:</span>
                                ${renderSourceActionDropdown(`folder:account:${accountId}`)}
                            </label>
                        </div>
                    </div>
                    <div class="review-group-content ${isExpanded ? 'expanded' : 'collapsed'}">
                        <div class="review-group-items">
            `;
            
            foldersInSource.forEach(sf => {
                html += renderFolderItem(sf);
            });
            
            html += `
                        </div>
                    </div>
                </div>
            `;
        });
        
        // Render import folder groups
        foldersByImport.forEach((foldersInSource, importId) => {
            const importName = getImportName(importId);
            const groupKey = `folders:import:${importId}`;
            const isExpanded = expandedSections.has(groupKey);
            
            html += `
                <div class="review-group review-group-folders">
                    <div class="review-group-header" onclick="toggleReviewSection('${groupKey}')">
                        <div class="review-group-header-left">
                            <i data-lucide="${isExpanded ? 'chevron-down' : 'chevron-right'}" class="review-chevron"></i>
                            <i data-lucide="folders" class="review-source-icon"></i>
                            <span class="review-group-title">${escapeHtml(importName)} (Folders)</span>
                            <span class="review-group-count">${foldersInSource.length} folder${foldersInSource.length !== 1 ? 's' : ''}</span>
                        </div>
                    </div>
                    <div class="review-group-content ${isExpanded ? 'expanded' : 'collapsed'}">
                        <div class="review-group-items">
            `;
            
            foldersInSource.forEach(sf => {
                html += renderFolderItem(sf);
            });
            
            html += `
                        </div>
                    </div>
                </div>
            `;
        });
    }
    
    html += '</div></div>';
    
    emailList.innerHTML = html;
    if (typeof lucide !== 'undefined') lucide.createIcons();
    
    initIconSelects();
    updateButtons();
}

function renderEmailItem(email) {
    const destFolder = folders.find(f => f.id == email.destinationFolderId);
    const destName = destFolder ? destFolder.name : 'Select folder...';
    
    return `
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
}

function renderFolderItem(sf) {
    const index = sf.originalIndex;
    const destFolder = folders.find(f => f.id == sf.destinationFolderId);
    const destName = destFolder ? destFolder.name : 'Select folder...';
    
    return `
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
}

// Toggle section expansion
window.toggleReviewSection = function(sectionKey) {
    if (expandedSections.has(sectionKey)) {
        expandedSections.delete(sectionKey);
    } else {
        expandedSections.add(sectionKey);
    }
    renderReviewView();
};


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
        
        trigger?.addEventListener('click', (e) => {
            e.stopPropagation();
            document.querySelectorAll('.icon-select-dropdown.open').forEach(d => {
                if (d !== dropdown) {
                    d.classList.remove('open');
                    d.style.removeProperty('bottom');
                    d.style.removeProperty('top');
                }
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
                const emailId = select.dataset.emailId;
                const folderIndex = select.dataset.folderIndex;
                const sourceKey = select.dataset.sourceKey;
                
                if (sourceKey) {
                    select.dataset.value = value;
                    const triggerSpan = trigger.querySelector('span');
                    if (triggerSpan) {
                        triggerSpan.textContent = option.querySelector('span')?.textContent || value;
                    }
                    dropdown.querySelectorAll('.icon-select-option').forEach(o => o.classList.remove('selected'));
                    option.classList.add('selected');
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

function escapeForOnclick(str) {
    if (!str) return '';
    return str.replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '&quot;');
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
