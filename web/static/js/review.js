/* ============================================
   REVIEW PAGE SCRIPTS
   ============================================ */

let stagedEmails = new Map();
let folders = [];
let sourceActions = {};  // { accountId-labelId: action }

document.addEventListener('DOMContentLoaded', async () => {
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
    
    if (stagedEmails.size === 0) {
        return;  // Show empty state
    }
    
    // Load folders
    await loadFolders();
    
    // Render review list
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
        const accountName = accountId === 'import' ? 'Imported' : `Account ${accountId}`;
        
        html += `
            <div class="review-group">
                <div class="review-group-header">
                    <h2>${escapeHtml(accountName)}</h2>
                    <div class="source-action">
                        <label>After commit:</label>
                        <select onchange="setSourceAction('${accountId}', this.value)">
                            <option value="leave">Leave in place</option>
                            <option value="archive">Archive</option>
                            <option value="trash">Move to trash</option>
                            <option value="delete">Delete permanently</option>
                        </select>
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
                    <div class="review-checkbox">
                        <input type="checkbox" checked onchange="toggleReviewItem('${item.emailId}')">
                    </div>
                    <div class="review-email">
                        <div class="review-email-header">
                            <span class="review-sender">${escapeHtml(item.email.sender)}</span>
                            <span class="review-date">${formatDate(item.email.date)}</span>
                        </div>
                        <div class="review-subject">${escapeHtml(item.email.subject)}</div>
                    </div>
                    <div class="review-destination">
                        <div class="icon-select" data-email-id="${item.emailId}">
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
    
    // Render Lucide icons
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
    
    // Initialize custom dropdowns
    initIconSelects();
}

// Custom icon-select dropdown handling
function initIconSelects() {
    document.querySelectorAll('.icon-select').forEach(select => {
        const trigger = select.querySelector('.icon-select-trigger');
        const dropdown = select.querySelector('.icon-select-dropdown');
        
        trigger.addEventListener('click', (e) => {
            e.stopPropagation();
            // Close other open dropdowns
            document.querySelectorAll('.icon-select.open').forEach(s => {
                if (s !== select) s.classList.remove('open');
            });
            select.classList.toggle('open');
        });
        
        dropdown.querySelectorAll('.icon-select-option').forEach(option => {
            option.addEventListener('click', (e) => {
                e.stopPropagation();
                const emailId = select.dataset.emailId;
                const folderId = option.dataset.value;
                const icon = option.dataset.icon;
                const label = option.querySelector('span').textContent;
                
                // Update trigger display
                trigger.querySelector('.folder-icon').setAttribute('data-lucide', icon);
                trigger.querySelector('.icon-select-label').textContent = label;
                
                // Update selected state
                dropdown.querySelectorAll('.icon-select-option').forEach(o => o.classList.remove('selected'));
                option.classList.add('selected');
                
                // Re-render icons and close
                if (typeof lucide !== 'undefined') lucide.createIcons();
                select.classList.remove('open');
                
                // Update data
                changeDestination(emailId, folderId);
            });
        });
    });
    
    // Close dropdowns when clicking outside
    document.addEventListener('click', () => {
        document.querySelectorAll('.icon-select.open').forEach(s => s.classList.remove('open'));
    });
}

function toggleReviewItem(emailId) {
    const checkbox = document.querySelector(`.review-item[data-id="${emailId}"] input[type="checkbox"]`);
    const item = document.querySelector(`.review-item[data-id="${emailId}"]`);
    
    if (checkbox.checked) {
        item.classList.remove('unchecked');
    } else {
        item.classList.add('unchecked');
    }
    
    updateCommitButton();
}

function changeDestination(emailId, folderId) {
    const data = stagedEmails.get(emailId);
    if (data) {
        data.destinationFolderId = folderId;
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

// Commit button handler
document.getElementById('commitBtn').addEventListener('click', commitEmails);

async function commitEmails() {
    // Gather checked emails
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
                    sourceAction: sourceActions[data.sourceAccountId] || 'leave',
                });
            }
        }
    });
    
    if (toCommit.length === 0) return;
    
    // Show progress modal
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
        
        // Hide progress, show results
        progressModal.classList.remove('active');
        
        const resultsModal = document.getElementById('resultsModal');
        const resultsTitle = document.getElementById('resultsTitle');
        const resultsMessage = document.getElementById('resultsMessage');
        const failedList = document.getElementById('failedList');
        const failedItems = document.getElementById('failedItems');
        const retryBtn = document.getElementById('retryBtn');
        
        const successCount = data.results.success.length;
        const failedCount = data.results.failed.length;
        
        resultsTitle.textContent = failedCount === 0 ? 'Success!' : 'Complete';
        resultsMessage.textContent = data.message;
        
        if (failedCount > 0) {
            failedList.classList.remove('hidden');
            failedItems.innerHTML = data.results.failed.map(f => 
                `<li>${escapeHtml(f.id)}: ${escapeHtml(f.error)}</li>`
            ).join('');
            retryBtn.classList.remove('hidden');
        } else {
            failedList.classList.add('hidden');
            retryBtn.classList.add('hidden');
        }
        
        resultsModal.classList.add('active');
        
        // Remove successful emails from staged
        data.results.success.forEach(id => stagedEmails.delete(id));
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

function formatDate(timestamp) {
    if (!timestamp) return '';
    const date = new Date(timestamp * 1000);
    return date.toLocaleDateString([], { year: 'numeric', month: 'short', day: 'numeric' });
}
