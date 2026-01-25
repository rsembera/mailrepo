/**
 * Review View
 * 
 * Renders the staged items review as a view within the main app layout.
 */

import { getStagedEmails, getStagedFolders, clearStagedEmail, clearStagedFolder, clearAllStaged, updateStagedBadge } from '../components/staging.js';
import { showConfirm, showAlert } from '../modals.js';

let contextTitle = null;
let contextMeta = null;
let emailList = null;

let folders = [];
let accounts = [];
let sourceActions = {};

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
    
    // Load accounts from page data
    accounts = window.accountsData || [];
    
    await loadFolders();
    renderReviewView();
}

async function loadFolders() {
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
            : `account:${data.accountId}:${data.folder || 'INBOX'}`;
        if (!emailsBySource.has(key)) {
            emailsBySource.set(key, []);
        }
        emailsBySource.get(key).push({ emailId, ...data });
    });
    
    // Render email groups
    emailsBySource.forEach((emails, sourceKey) => {
        const firstEmail = emails[0];
        const sourceName = getSourceName(sourceKey, firstEmail);
        
        html += `
            <div class="review-group">
                <div class="review-group-header">
                    <span class="review-group-title">${escapeHtml(sourceName)}</span>
                    <span class="review-group-count">${emails.length} email${emails.length !== 1 ? 's' : ''}</span>
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

    // Render staged folders
    if (stagedFolders.length > 0) {
        html += `
            <div class="review-group">
                <div class="review-group-header">
                    <span class="review-group-title">Staged Folders</span>
                    <span class="review-group-count">${stagedFolders.length} folder${stagedFolders.length !== 1 ? 's' : ''}</span>
                </div>
                <div class="review-group-items">
        `;
        
        stagedFolders.forEach((sf, index) => {
            const destFolder = folders.find(f => f.id == sf.destinationFolderId);
            const destName = destFolder ? destFolder.name : 'Select folder...';
            
            html += `
                <div class="review-item review-item-folder" data-folder-index="${index}">
                    <div class="review-item-info">
                        <div class="review-item-subject">
                            <i data-lucide="folder" style="width: 16px; height: 16px; margin-right: 4px;"></i>
                            ${escapeHtml(sf.folder || '(root)')}
                        </div>
                        <div class="review-item-meta">
                            <span class="review-item-from">${escapeHtml(getFolderSourceName(sf))}</span>
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
    }
    
    html += '</div></div>';
    
    emailList.innerHTML = html;
    if (typeof lucide !== 'undefined') lucide.createIcons();
    
    initIconSelects();
    updateButtons();
}

function getSourceName(sourceKey, firstEmail) {
    if (sourceKey.startsWith('import:')) {
        return firstEmail.importName || 'Import';
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
                if (d !== dropdown) d.classList.remove('open');
            });
            dropdown?.classList.toggle('open');
        });
        
        dropdown?.querySelectorAll('.icon-select-option').forEach(option => {
            option.addEventListener('click', () => {
                const value = option.dataset.value;
                const emailId = select.dataset.emailId;
                const folderIndex = select.dataset.folderIndex;
                
                if (emailId) {
                    changeEmailDestination(emailId, value);
                } else if (folderIndex !== undefined) {
                    changeFolderDestination(parseInt(folderIndex), value);
                }
                
                dropdown.classList.remove('open');
            });
        });
    });
    
    // Close dropdowns when clicking outside
    document.addEventListener('click', () => {
        document.querySelectorAll('.icon-select-dropdown.open').forEach(d => {
            d.classList.remove('open');
        });
    });
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
        commitBtn.innerHTML = '<i data-lucide="loader-2" class="spin"></i> Committing...';
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }
    
    try {
        // Prepare commit data
        const emails = [];
        stagedEmails.forEach((data, emailId) => {
            emails.push({
                email: data.email,  // Include full email object
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
        
        // Stream commit
        const response = await fetch('/api/commit/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ staged: emails, folders: foldersToCommit }),
        });
        
        if (!response.ok) {
            throw new Error('Commit failed');
        }
        
        // Read streaming response
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let emailSuccess = 0;
        let emailError = 0;
        let folderSuccess = 0;
        let folderError = 0;
        
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            
            const text = decoder.decode(value);
            const lines = text.split('\n').filter(l => l.trim());
            
            for (const line of lines) {
                try {
                    // Parse SSE format: "event: xxx\ndata: {...}"
                    if (line.startsWith('data: ')) {
                        const data = JSON.parse(line.slice(6));
                        
                        if (data.status === 'success') {
                            emailSuccess++;
                        } else if (data.status === 'failed') {
                            emailError++;
                        } else if (data.status === 'folder_success') {
                            folderSuccess++;
                        } else if (data.status === 'folder_failed') {
                            folderError++;
                        }
                    }
                } catch (e) {
                    // Ignore parse errors
                }
            }
        }
        
        // Clear all staged items after commit
        clearAllStaged();
        updateStagedBadge();
        renderReviewView();
        
        // Show results
        const results = [];
        if (emailSuccess > 0) results.push(`${emailSuccess} emails`);
        if (folderSuccess > 0) results.push(`${folderSuccess} folders`);
        if (emailError > 0 || folderError > 0) {
            const errors = emailError + folderError;
            showAlert('Commit Complete', `Committed ${results.join(', ')}. ${errors} failed.`);
        } else if (results.length > 0) {
            showAlert('Commit Complete', `Successfully committed ${results.join(' and ')}.`);
        }
        
    } catch (e) {
        console.error('Commit error:', e);
        alert('Failed to commit emails: ' + e.message);
    } finally {
        if (commitBtn) {
            commitBtn.disabled = false;
            commitBtn.innerHTML = '<i data-lucide="archive"></i> Commit';
            if (typeof lucide !== 'undefined') lucide.createIcons();
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
