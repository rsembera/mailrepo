/* ============================================
   REVIEW PAGE SCRIPTS
   ============================================ */

let stagedEmails = new Map();
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
    
    // Update badge
    document.getElementById('stagedBadge').textContent = stagedEmails.size;
    
    if (stagedEmails.size === 0) {
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

function getAccountName(accountId) {
    if (accountId === 'import') return 'Imported';
    const account = accounts.find(a => a.id == accountId);
    return account ? (account.name || account.email) : `Account ${accountId}`;
}

function renderSidebar() {
    const section = document.getElementById('stagedAccountsSection');
    
    // Group by account
    const byAccount = new Map();
    stagedEmails.forEach((data, emailId) => {
        const key = data.sourceAccountId || 'import';
        if (!byAccount.has(key)) {
            byAccount.set(key, []);
        }
        byAccount.get(key).push({ emailId, ...data });
    });
    
    let html = '';
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
    document.getElementById('reviewMeta').textContent = `${stagedEmails.size} emails staged`;
    
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function renderReviewList() {
    const content = document.getElementById('reviewContent');
    
    // Group by source account
    const byAccount = new Map();
    stagedEmails.forEach((data, emailId) => {
        const key = data.sourceAccountId || 'import';
        if (!byAccount.has(key)) {
            byAccount.set(key, []);
        }
        byAccount.get(key).push({ emailId, ...data });
    });
    
    let html = '';
    
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
                                ${folders.map(f => `
                                    <div class="icon-select-option ${f.id == item.destinationFolderId ? 'selected' : ''}" 
                                         data-value="${f.id}" data-icon="${f.encrypted ? 'lock' : 'folder'}">
                                        <i data-lucide="${f.encrypted ? 'lock' : 'folder'}"></i>
                                        <span>${escapeHtml(f.name)}</span>
                                    </div>
                                `).join('')}
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
    // Folder selects
    document.querySelectorAll('.icon-select.folder-select').forEach(select => {
        initDropdown(select, (value, icon, label) => {
            const emailId = select.dataset.emailId;
            changeDestination(emailId, value);
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
    document.getElementById('commitCount').textContent = checkedCount;
    document.getElementById('commitBtn').disabled = checkedCount === 0;
}

function goBack() {
    window.location.href = '/';
}

// Commit handler
document.getElementById('commitBtn').addEventListener('click', commitEmails);

async function commitEmails() {
    const toCommit = [];
    document.querySelectorAll('.review-item').forEach(item => {
        const checkbox = item.querySelector('input[type="checkbox"]');
        if (checkbox.checked) {
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
    
    if (toCommit.length === 0) return;
    
    const progressModal = document.getElementById('progressModal');
    const progressFill = document.getElementById('progressFill');
    const progressText = document.getElementById('progressText');
    
    progressModal.classList.add('active');
    progressFill.style.width = '0%';
    progressText.textContent = `Filing 0 of ${toCommit.length}...`;
    
    try {
        const response = await fetch('/api/commit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ staged: toCommit }),
        });
        
        const data = await response.json();
        progressModal.classList.remove('active');
        
        const resultsModal = document.getElementById('resultsModal');
        const successCount = data.results.success.length;
        const failedCount = data.results.failed.length;
        const skippedCount = data.results.skipped?.length || 0;
        
        document.getElementById('resultsTitle').textContent = failedCount === 0 ? 'Success!' : 'Complete';
        document.getElementById('resultsMessage').textContent = data.message;
        
        const failedList = document.getElementById('failedList');
        const failedItems = document.getElementById('failedItems');
        
        if (failedCount > 0 || skippedCount > 0) {
            failedList.classList.remove('hidden');
            let listHtml = '';
            
            if (skippedCount > 0) {
                listHtml += '<li class="list-header">Skipped (already archived):</li>';
                listHtml += data.results.skipped.map(s => 
                    `<li class="skipped-item">${escapeHtml(s.subject || s.uid)}</li>`
                ).join('');
            }
            
            if (failedCount > 0) {
                listHtml += '<li class="list-header">Failed:</li>';
                listHtml += data.results.failed.map(f => 
                    `<li class="failed-item">${escapeHtml(f.uid)}: ${escapeHtml(f.error)}</li>`
                ).join('');
            }
            
            failedItems.innerHTML = listHtml;
            document.getElementById('retryBtn').classList.toggle('hidden', failedCount === 0);
        } else {
            failedList.classList.add('hidden');
            document.getElementById('retryBtn').classList.add('hidden');
        }
        
        resultsModal.classList.add('active');
        
        // Remove committed emails
        data.results.success.forEach(id => stagedEmails.delete(id));
        if (data.results.skipped) {
            data.results.skipped.forEach(s => stagedEmails.delete(s.uid));
        }
        sessionStorage.setItem('stagedEmails', JSON.stringify([...stagedEmails.entries()]));
        
    } catch (error) {
        console.error('Commit failed:', error);
        progressModal.classList.remove('active');
        alert('Failed to commit emails. Please try again.');
    }
}

document.getElementById('doneBtn').addEventListener('click', () => {
    if (stagedEmails.size === 0) {
        sessionStorage.removeItem('stagedEmails');
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
