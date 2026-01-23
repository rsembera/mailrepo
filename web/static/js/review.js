/* ============================================
   REVIEW PAGE SCRIPTS
   ============================================ */

let stagedEmails = new Map();
let stagedFolders = null;  // { accountId, folders: [], destinationFolderId }
let folders = [];
let accounts = [];
let sourceActions = {};  // { accountId: action }

document.addEventListener('DOMContentLoaded', async () => {
    // Load accounts from page data
    accounts = window.accountsData || [];
    
    // Load staged emails from sessionStorage
    const savedStaged = sessionStorage.getItem('stagedEmails');
    if (savedStaged) {
        try {
            const entries = JSON.parse(savedStaged);
            stagedEmails = new Map(entries);
        } catch (e) {
            console.error('Failed to parse staged emails:', e);
        }
    }
    
    // Load staged folders from sessionStorage
    const savedFolders = sessionStorage.getItem('stagedFolders');
    if (savedFolders) {
        try {
            stagedFolders = JSON.parse(savedFolders);
        } catch (e) {
            console.error('Failed to parse staged folders:', e);
        }
    }
    
    // Update badge
    const totalCount = stagedEmails.size + (stagedFolders?.folders?.length || 0);
    document.getElementById('stagedBadge').textContent = totalCount;
    
    if (stagedEmails.size === 0 && !stagedFolders) {
        return;  // Show empty state
    }
    
    // Load folders
    await loadFolders();
    
    // Render sidebar and review list
    renderSidebar();
    renderReviewList();
    updateCommitButton();
});

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

/**
 * Render hierarchical folder options for dropdown.
 */
function renderFolderOptions(selectedId) {
    const topLevel = folders.filter(f => !f.parent_id && !f.deleted_at);
    
    function renderFolder(folder, depth) {
        const indent = depth * 12;
        const isSelected = folder.id == selectedId;
        const icon = folder.encrypted ? 'lock' : 'folder';
        
        let html = `
            <div class="icon-select-option ${isSelected ? 'selected' : ''}" 
                 data-value="${folder.id}" data-icon="${icon}" style="padding-left: ${8 + indent}px">
                <i data-lucide="${icon}"></i>
                <span>${escapeHtml(folder.name)}</span>
            </div>
        `;
        
        // Render children
        const children = folders.filter(f => f.parent_id == folder.id && !f.deleted_at);
        children.forEach(child => {
            html += renderFolder(child, depth + 1);
        });
        
        return html;
    }
    
    return topLevel.map(f => renderFolder(f, 0)).join('');
}

function getAccountName(accountId) {
    if (accountId === 'import') return 'Imported';
    const account = accounts.find(a => a.id == accountId);
    return account ? (account.name || account.email) : `Account ${accountId}`;
}

function renderSidebar() {
    const section = document.getElementById('stagedAccountsSection');
    
    // Group emails by account
    const byAccount = new Map();
    stagedEmails.forEach((data, emailId) => {
        const key = data.sourceAccountId || 'import';
        if (!byAccount.has(key)) {
            byAccount.set(key, []);
        }
        byAccount.get(key).push({ emailId, ...data });
    });
    
    let html = '';
    
    // Show staged folders first
    if (stagedFolders && stagedFolders.folders.length > 0) {
        const accountName = getAccountName(stagedFolders.accountId);
        html += `
            <div class="tree-item-row active" data-type="folders" data-account-id="${stagedFolders.accountId}">
                <i data-lucide="folders" class="tree-icon"></i>
                <span class="tree-label">${escapeHtml(accountName)} (Folders)</span>
                <span class="tree-count">${stagedFolders.folders.length}</span>
            </div>
        `;
    }
    
    // Show staged emails by account
    byAccount.forEach((emails, accountId) => {
        const accountName = getAccountName(accountId);
        html += `
            <div class="tree-item-row active" data-account-id="${accountId}">
                <i data-lucide="mail" class="tree-icon"></i>
                <span class="tree-label">${escapeHtml(accountName)}</span>
                <span class="tree-count">${emails.length}</span>
            </div>
        `;
    });
    
    section.innerHTML = html;
    
    // Update meta
    const emailCount = stagedEmails.size;
    const folderCount = stagedFolders?.folders?.length || 0;
    let metaText = [];
    if (emailCount > 0) metaText.push(`${emailCount} email${emailCount > 1 ? 's' : ''}`);
    if (folderCount > 0) metaText.push(`${folderCount} folder${folderCount > 1 ? 's' : ''}`);
    document.getElementById('reviewMeta').textContent = metaText.join(', ') + ' staged';
    
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function renderReviewList() {
    const content = document.getElementById('reviewContent');
    
    let html = '';
    
    // Render staged folders first
    if (stagedFolders && stagedFolders.folders.length > 0) {
        const accountName = getAccountName(stagedFolders.accountId);
        const destFolder = folders.find(f => f.id == stagedFolders.destinationFolderId);
        const destName = destFolder ? destFolder.name : 'Unknown';
        const destIcon = destFolder?.encrypted ? 'lock' : 'folder';
        
        html += `
            <div class="review-group folders-group">
                <div class="review-group-header">
                    <h2><i data-lucide="folders"></i> ${escapeHtml(accountName)} - Folder Archive</h2>
                    <div class="source-action">
                        <label>After commit:</label>
                        <div class="icon-select action-select" data-account-id="${stagedFolders.accountId}-folders">
                            <button class="icon-select-trigger" type="button">
                                <i data-lucide="inbox" class="action-icon"></i>
                                <span class="icon-select-label">Leave in place</span>
                                <i data-lucide="chevron-down" class="icon-select-arrow"></i>
                            </button>
                            <div class="icon-select-dropdown">
                                <div class="icon-select-option selected" data-value="leave" data-icon="inbox">
                                    <i data-lucide="inbox"></i>
                                    <span>Leave in place</span>
                                </div>
                                <div class="icon-select-option" data-value="archive" data-icon="archive">
                                    <i data-lucide="archive"></i>
                                    <span>Archive</span>
                                </div>
                                <div class="icon-select-option" data-value="trash" data-icon="trash-2">
                                    <i data-lucide="trash-2"></i>
                                    <span>Move to trash</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="folder-commit-info">
                    <div class="folder-destination-row">
                        <span>Destination:</span>
                        <div class="icon-select folder-dest-select">
                            <button class="icon-select-trigger" type="button">
                                <i data-lucide="${destIcon}" class="folder-icon"></i>
                                <span class="icon-select-label">${escapeHtml(destName)}</span>
                                <i data-lucide="chevron-down" class="icon-select-arrow"></i>
                            </button>
                            <div class="icon-select-dropdown">
                                ${renderFolderOptions(stagedFolders.destinationFolderId)}
                            </div>
                        </div>
                    </div>
                    <p class="info-note">Folder structure will be preserved. All emails in these folders will be archived.</p>
                    <ul class="folders-to-commit">
                        ${stagedFolders.folders.map(f => `<li><i data-lucide="folder"></i> ${escapeHtml(f)}</li>`).join('')}
                    </ul>
                </div>
            </div>
        `;
    }
    
    // Group emails by source account
    const byAccount = new Map();
    stagedEmails.forEach((data, emailId) => {
        const key = data.sourceAccountId || 'import';
        if (!byAccount.has(key)) {
            byAccount.set(key, []);
        }
        byAccount.get(key).push({ emailId, ...data });
    });
    
    byAccount.forEach((emails, accountId) => {
        const accountName = getAccountName(accountId);
        
        html += `
            <div class="review-group">
                <div class="review-group-header">
                    <h2>${escapeHtml(accountName)}</h2>
                    <div class="source-action">
                        <label>After commit:</label>
                        <div class="icon-select action-select" data-account-id="${accountId}">
                            <button class="icon-select-trigger" type="button">
                                <i data-lucide="inbox" class="action-icon"></i>
                                <span class="icon-select-label">Leave in place</span>
                                <i data-lucide="chevron-down" class="icon-select-arrow"></i>
                            </button>
                            <div class="icon-select-dropdown">
                                <div class="icon-select-option selected" data-value="leave" data-icon="inbox">
                                    <i data-lucide="inbox"></i>
                                    <span>Leave in place</span>
                                </div>
                                <div class="icon-select-option" data-value="archive" data-icon="archive">
                                    <i data-lucide="archive"></i>
                                    <span>Archive</span>
                                </div>
                                <div class="icon-select-option" data-value="trash" data-icon="trash-2">
                                    <i data-lucide="trash-2"></i>
                                    <span>Move to trash</span>
                                </div>
                                <div class="icon-select-option" data-value="delete" data-icon="x-circle">
                                    <i data-lucide="x-circle"></i>
                                    <span>Delete permanently</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="review-list">
        `;
        
        emails.forEach(item => {
            const folder = folders.find(f => f.id == item.destinationFolderId);
            const folderName = folder ? folder.name : 'Unknown';
            const folderIcon = folder?.encrypted ? 'lock' : 'folder';
            
            html += `
                <div class="review-item" data-id="${item.emailId}">
                    <label class="review-checkbox">
                        <input type="checkbox" checked onchange="toggleReviewItem('${item.emailId}')">
                    </label>
                    <div class="review-email">
                        <div class="review-subject">${escapeHtml(item.email.subject || '(no subject)')}</div>
                        <div class="review-meta">
                            <span class="review-sender">${escapeHtml(extractName(item.email.from || item.email.sender))}</span>
                            <span class="review-date">${formatDate(item.email.date)}</span>
                        </div>
                    </div>
                    <div class="review-destination">
                        <div class="icon-select folder-select" data-email-id="${item.emailId}">
                            <button class="icon-select-trigger" type="button">
                                <i data-lucide="${folderIcon}" class="folder-icon"></i>
                                <span class="icon-select-label">${escapeHtml(folderName)}</span>
                                <i data-lucide="chevron-down" class="icon-select-arrow"></i>
                            </button>
                            <div class="icon-select-dropdown">
                                ${renderFolderOptions(item.destinationFolderId)}
                            </div>
                        </div>
                    </div>
                </div>
            `;
        });
        
        html += `
                </div>
            </div>
        `;
    });
    
    content.innerHTML = html;
    
    if (typeof lucide !== 'undefined') lucide.createIcons();
    
    initIconSelects();
}

function initIconSelects() {
    // Folder selects (for emails)
    document.querySelectorAll('.icon-select.folder-select').forEach(select => {
        initDropdown(select, (value, icon, label) => {
            const emailId = select.dataset.emailId;
            changeDestination(emailId, value);
        });
    });
    
    // Folder destination select (for bulk folder staging)
    document.querySelectorAll('.icon-select.folder-dest-select').forEach(select => {
        initDropdown(select, (value, icon, label) => {
            if (stagedFolders) {
                stagedFolders.destinationFolderId = parseInt(value);
                sessionStorage.setItem('stagedFolders', JSON.stringify(stagedFolders));
            }
        });
    });
    
    // Action selects
    document.querySelectorAll('.icon-select.action-select').forEach(select => {
        initDropdown(select, (value, icon, label) => {
            const accountId = select.dataset.accountId;
            setSourceAction(accountId, value);
        });
    });
}

function initDropdown(select, onChange) {
    const trigger = select.querySelector('.icon-select-trigger');
    const dropdown = select.querySelector('.icon-select-dropdown');
    
    trigger.addEventListener('click', (e) => {
        e.stopPropagation();
        document.querySelectorAll('.icon-select.open').forEach(s => {
            if (s !== select) s.classList.remove('open');
        });
        select.classList.toggle('open');
    });
    
    dropdown.querySelectorAll('.icon-select-option').forEach(option => {
        option.addEventListener('click', (e) => {
            e.stopPropagation();
            const value = option.dataset.value;
            const icon = option.dataset.icon;
            const label = option.querySelector('span').textContent;
            
            // Update trigger
            const iconEl = trigger.querySelector('.folder-icon, .action-icon');
            if (iconEl) iconEl.setAttribute('data-lucide', icon);
            trigger.querySelector('.icon-select-label').textContent = label;
            
            // Update selected
            dropdown.querySelectorAll('.icon-select-option').forEach(o => o.classList.remove('selected'));
            option.classList.add('selected');
            
            if (typeof lucide !== 'undefined') lucide.createIcons();
            select.classList.remove('open');
            
            onChange(value, icon, label);
        });
    });
}

// Close dropdowns on outside click
document.addEventListener('click', () => {
    document.querySelectorAll('.icon-select.open').forEach(s => s.classList.remove('open'));
});

function toggleReviewItem(emailId) {
    const item = document.querySelector(`.review-item[data-id="${emailId}"]`);
    const checkbox = item?.querySelector('input[type="checkbox"]');
    
    if (checkbox?.checked) {
        item.classList.remove('unchecked');
    } else {
        item?.classList.add('unchecked');
    }
    
    updateCommitButton();
}

function changeDestination(emailId, folderId) {
    const data = stagedEmails.get(emailId);
    if (data) {
        data.destinationFolderId = parseInt(folderId);
        stagedEmails.set(emailId, data);
    }
}

function setSourceAction(accountId, action) {
    sourceActions[accountId] = action;
}

function updateCommitButton() {
    const checkedCount = document.querySelectorAll('.review-item input[type="checkbox"]:checked').length;
    const hasFolders = stagedFolders && stagedFolders.folders.length > 0;
    
    // Enable/disable based on having items to commit
    const totalCount = checkedCount + (hasFolders ? stagedFolders.folders.length : 0);
    document.getElementById('commitBtn').disabled = totalCount === 0;
}

function goBack() {
    window.location.href = '/';
}

// Commit handler
document.getElementById('commitBtn').addEventListener('click', commitAll);

async function commitAll() {
    const progressModal = document.getElementById('progressModal');
    const progressFill = document.getElementById('progressFill');
    const progressText = document.getElementById('progressText');
    
    progressModal.classList.add('active');
    progressFill.style.width = '0%';
    
    let totalResults = {
        success: 0,
        failed: 0,
        skipped: 0,
        folders_created: 0,
        messages: [],
    };
    
    // Commit folders first
    if (stagedFolders && stagedFolders.folders.length > 0) {
        progressText.textContent = `Archiving ${stagedFolders.folders.length} folders...`;
        
        try {
            const response = await fetch('/api/commit-folders', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    accountId: stagedFolders.accountId,
                    folders: stagedFolders.folders,
                    destinationFolderId: stagedFolders.destinationFolderId,
                }),
            });
            
            const data = await response.json();
            
            if (response.ok) {
                totalResults.success += data.results.success;
                totalResults.failed += data.results.failed;
                totalResults.skipped += data.results.skipped;
                totalResults.folders_created += data.results.folders_created;
                totalResults.messages.push(data.message);
                
                // Clear staged folders
                stagedFolders = null;
                sessionStorage.removeItem('stagedFolders');
            } else {
                totalResults.messages.push(`Folder archive failed: ${data.error}`);
                totalResults.failed += stagedFolders.folders.length;
            }
        } catch (error) {
            console.error('Folder commit failed:', error);
            totalResults.messages.push('Folder archive failed: Network error');
            totalResults.failed += stagedFolders.folders.length;
        }
    }
    
    // Commit emails
    const toCommit = [];
    document.querySelectorAll('.review-item').forEach(item => {
        const checkbox = item.querySelector('input[type="checkbox"]');
        if (checkbox?.checked) {
            const emailId = item.dataset.id;
            const data = stagedEmails.get(emailId);
            if (data) {
                toCommit.push({
                    email: data.email,
                    destinationFolderId: data.destinationFolderId,
                    sourceAccountId: data.sourceAccountId,
                    sourceFolder: data.sourceFolder,
                    sourceAction: sourceActions[data.sourceAccountId] || 'leave',
                });
            }
        }
    });
    
    if (toCommit.length > 0) {
        progressText.textContent = `Filing ${toCommit.length} emails...`;
        
        try {
            const response = await fetch('/api/commit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ staged: toCommit }),
            });
            
            const data = await response.json();
            
            if (response.ok) {
                totalResults.success += data.results.success.length;
                totalResults.failed += data.results.failed.length;
                totalResults.skipped += data.results.skipped?.length || 0;
                totalResults.messages.push(data.message);
                
                // Remove committed emails
                data.results.success.forEach(id => stagedEmails.delete(id));
                if (data.results.skipped) {
                    data.results.skipped.forEach(s => stagedEmails.delete(s.uid));
                }
                sessionStorage.setItem('stagedEmails', JSON.stringify([...stagedEmails.entries()]));
            } else {
                totalResults.messages.push(`Email archive failed: ${data.error}`);
            }
        } catch (error) {
            console.error('Email commit failed:', error);
            totalResults.messages.push('Email archive failed: Network error');
        }
    }
    
    progressModal.classList.remove('active');
    
    // Show results
    const resultsModal = document.getElementById('resultsModal');
    document.getElementById('resultsTitle').textContent = totalResults.failed === 0 ? 'Success!' : 'Complete';
    document.getElementById('resultsMessage').textContent = totalResults.messages.join(' ');
    
    const failedList = document.getElementById('failedList');
    if (totalResults.failed > 0 || totalResults.skipped > 0) {
        failedList.classList.remove('hidden');
        let summaryHtml = '';
        if (totalResults.skipped > 0) summaryHtml += `<li>${totalResults.skipped} skipped (duplicates)</li>`;
        if (totalResults.failed > 0) summaryHtml += `<li>${totalResults.failed} failed</li>`;
        document.getElementById('failedItems').innerHTML = summaryHtml;
    } else {
        failedList.classList.add('hidden');
    }
    
    document.getElementById('retryBtn').classList.add('hidden');
    resultsModal.classList.add('active');
}

document.getElementById('doneBtn').addEventListener('click', () => {
    if (stagedEmails.size === 0 && !stagedFolders) {
        sessionStorage.removeItem('stagedEmails');
        sessionStorage.removeItem('stagedFolders');
        window.location.href = '/';
    } else {
        document.getElementById('resultsModal').classList.remove('active');
        renderSidebar();
        renderReviewList();
        updateCommitButton();
    }
});

document.getElementById('retryBtn').addEventListener('click', () => {
    document.getElementById('resultsModal').classList.remove('active');
    commitEmails();
});

// Utilities
function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function extractName(sender) {
    if (!sender) return '';
    const match = sender.match(/^([^<]+)</);
    return match ? match[1].trim() : sender;
}

function formatDate(dateStr) {
    if (!dateStr) return '';
    
    try {
        // Handle both string dates and timestamps
        let date;
        if (typeof dateStr === 'number') {
            date = new Date(dateStr * 1000);
        } else {
            date = new Date(dateStr);
        }
        
        if (isNaN(date.getTime())) return '';
        
        return date.toLocaleDateString([], { year: 'numeric', month: 'short', day: 'numeric' });
    } catch {
        return '';
    }
}

// Global
window.toggleReviewItem = toggleReviewItem;
