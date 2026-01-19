/**
 * MailRepo - Main Application JavaScript
 * 
 * Handles:
 * - Account/folder selection
 * - Email list rendering
 * - Staging workflow
 * - Navigation warnings
 */

// ============================================
// STATE
// ============================================

const state = {
    currentAccount: null,
    currentFolder: null,
    viewMode: 'inbox',  // 'inbox' or 'archive'
    emails: [],
    staged: new Map(),  // Map<emailId, {email, destinationFolderId}>
    selectedEmails: new Set(),
};

// ============================================
// DOM ELEMENTS
// ============================================

const elements = {
    accountDropdown: document.getElementById('accountDropdown'),
    stageBtn: document.getElementById('stageBtn'),
    reviewBtn: document.getElementById('reviewBtn'),
    stageBadge: document.getElementById('stageBadge'),
    folderTree: document.getElementById('folderTree'),
    emailList: document.getElementById('emailList'),
    selectAll: document.getElementById('selectAll'),
    searchInput: document.getElementById('searchInput'),
    newFolderBtn: document.getElementById('newFolderBtn'),
};

// ============================================
// INITIALIZATION
// ============================================

document.addEventListener('DOMContentLoaded', () => {
    initEventListeners();
    updateStageBadge();
});

function initEventListeners() {
    // Account dropdown
    elements.accountDropdown?.addEventListener('change', handleAccountChange);
    
    // Folder selection
    elements.folderTree?.addEventListener('click', handleFolderClick);
    
    // Stage/Review buttons
    elements.stageBtn?.addEventListener('click', openStageModal);
    elements.reviewBtn?.addEventListener('click', goToReview);
    
    // Select all checkbox
    elements.selectAll?.addEventListener('change', handleSelectAll);
    
    // Search
    elements.searchInput?.addEventListener('input', debounce(handleSearch, 300));
    
    // New folder button
    elements.newFolderBtn?.addEventListener('click', openNewFolderModal);
    
    // Navigation warning
    window.addEventListener('beforeunload', handleBeforeUnload);
}

// ============================================
// ACCOUNT & FOLDER HANDLING
// ============================================

function handleAccountChange(e) {
    const value = e.target.value;
    
    if (value === 'archive') {
        state.viewMode = 'archive';
        state.currentAccount = null;
        loadArchiveFolders();
    } else if (value === 'settings') {
        window.location.href = '/settings';
    } else if (value === 'import') {
        openImportModal();
    } else if (value) {
        state.viewMode = 'inbox';
        state.currentAccount = value;
        loadInbox(value);
    }
}

function handleFolderClick(e) {
    const folderItem = e.target.closest('.folder-item');
    if (!folderItem) return;
    
    const folderId = folderItem.dataset.id;
    
    // Update active state
    document.querySelectorAll('.folder-item').forEach(f => f.classList.remove('active'));
    folderItem.classList.add('active');
    
    state.currentFolder = folderId;
    
    if (state.viewMode === 'archive') {
        loadArchivedEmails(folderId);
    }
}

// ============================================
// EMAIL LIST
// ============================================

async function loadInbox(accountId) {
    showLoading();
    
    try {
        const response = await fetch(`/api/accounts/${accountId}/emails`);
        if (!response.ok) throw new Error('Failed to load emails');
        
        const data = await response.json();
        state.emails = data.emails || [];
        renderEmailList();
    } catch (error) {
        console.error('Error loading inbox:', error);
        showError('Failed to load emails. Please try again.');
    }
}

async function loadArchivedEmails(folderId) {
    showLoading();
    
    try {
        const response = await fetch(`/api/folders/${folderId}/emails`);
        if (!response.ok) throw new Error('Failed to load archived emails');
        
        const data = await response.json();
        state.emails = data.emails || [];
        renderEmailList();
    } catch (error) {
        console.error('Error loading archived emails:', error);
        showError('Failed to load archived emails. Please try again.');
    }
}

function renderEmailList() {
    if (!elements.emailList) return;
    
    if (state.emails.length === 0) {
        elements.emailList.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">📭</div>
                <h3>No Emails</h3>
                <p>No emails found in this ${state.viewMode === 'inbox' ? 'inbox' : 'folder'}.</p>
            </div>
        `;
        return;
    }
    
    elements.emailList.innerHTML = state.emails.map(email => {
        const isStaged = state.staged.has(email.id);
        const isSelected = state.selectedEmails.has(email.id);
        
        return `
            <div class="email-item ${isStaged ? 'staged' : ''} ${isSelected ? 'selected' : ''}" 
                 data-id="${email.id}">
                <div class="email-checkbox">
                    <input type="checkbox" 
                           ${isSelected ? 'checked' : ''} 
                           ${isStaged ? 'disabled' : ''}
                           onchange="toggleEmailSelection('${email.id}')">
                </div>
                <div class="email-content">
                    <div class="email-header">
                        <span class="email-sender">${escapeHtml(email.sender)}</span>
                        <span class="email-date">${formatDate(email.date)}</span>
                    </div>
                    <div class="email-subject">${escapeHtml(email.subject)}</div>
                    ${email.preview ? `<div class="email-preview">${escapeHtml(email.preview)}</div>` : ''}
                </div>
            </div>
        `;
    }).join('');
    
    updateSelectAllState();
}

function toggleEmailSelection(emailId) {
    if (state.selectedEmails.has(emailId)) {
        state.selectedEmails.delete(emailId);
    } else {
        state.selectedEmails.add(emailId);
    }
    
    updateButtonStates();
    updateSelectAllState();
    
    // Update visual state
    const emailItem = document.querySelector(`.email-item[data-id="${emailId}"]`);
    if (emailItem) {
        emailItem.classList.toggle('selected', state.selectedEmails.has(emailId));
    }
}

function handleSelectAll(e) {
    const checked = e.target.checked;
    
    state.emails.forEach(email => {
        if (!state.staged.has(email.id)) {
            if (checked) {
                state.selectedEmails.add(email.id);
            } else {
                state.selectedEmails.delete(email.id);
            }
        }
    });
    
    renderEmailList();
    updateButtonStates();
}

function updateSelectAllState() {
    if (!elements.selectAll) return;
    
    const availableEmails = state.emails.filter(e => !state.staged.has(e.id));
    const selectedCount = [...state.selectedEmails].filter(id => 
        availableEmails.some(e => e.id === id)
    ).length;
    
    elements.selectAll.checked = availableEmails.length > 0 && 
                                  selectedCount === availableEmails.length;
    elements.selectAll.indeterminate = selectedCount > 0 && 
                                        selectedCount < availableEmails.length;
}

// ============================================
// STAGING WORKFLOW
// ============================================

function openStageModal() {
    if (state.selectedEmails.size === 0) return;
    
    // Create and show modal
    const modal = document.createElement('div');
    modal.className = 'modal-overlay active';
    modal.id = 'stageModal';
    modal.innerHTML = `
        <div class="modal-content">
            <div class="modal-header">
                <h2>Stage ${state.selectedEmails.size} Email${state.selectedEmails.size > 1 ? 's' : ''}</h2>
            </div>
            
            <p>Select destination folder:</p>
            
            <div class="folder-select-list" id="folderSelectList">
                <div class="folder-select-item new-folder" data-action="new">
                    <span>+ New Folder</span>
                </div>
                <!-- Folders will be loaded here -->
            </div>
            
            <div class="modal-actions">
                <button class="btn btn-secondary" onclick="closeModal('stageModal')">Cancel</button>
                <button class="btn btn-primary" id="confirmStageBtn" disabled>Stage</button>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
    loadFoldersForModal();
    
    // Event listeners
    modal.querySelector('.folder-select-list').addEventListener('click', handleFolderSelect);
    modal.querySelector('#confirmStageBtn').addEventListener('click', confirmStage);
    modal.addEventListener('click', (e) => {
        if (e.target === modal) closeModal('stageModal');
    });
}

async function loadFoldersForModal() {
    try {
        const response = await fetch('/api/folders');
        if (!response.ok) throw new Error('Failed to load folders');
        
        const data = await response.json();
        const list = document.getElementById('folderSelectList');
        
        data.folders.forEach(folder => {
            const item = document.createElement('div');
            item.className = 'folder-select-item';
            item.dataset.id = folder.id;
            item.innerHTML = `
                <span class="folder-icon">${folder.encrypted ? '🔒' : '📁'}</span>
                <span class="folder-name">${escapeHtml(folder.name)}</span>
            `;
            list.appendChild(item);
        });
    } catch (error) {
        console.error('Error loading folders:', error);
    }
}

let selectedDestinationFolder = null;

function handleFolderSelect(e) {
    const item = e.target.closest('.folder-select-item');
    if (!item) return;
    
    if (item.dataset.action === 'new') {
        openNewFolderModal(true);  // Modal-in-modal
        return;
    }
    
    // Update selection
    document.querySelectorAll('.folder-select-item').forEach(i => i.classList.remove('selected'));
    item.classList.add('selected');
    
    selectedDestinationFolder = item.dataset.id;
    document.getElementById('confirmStageBtn').disabled = false;
}

function confirmStage() {
    if (!selectedDestinationFolder) return;
    
    // Add selected emails to staged map
    state.selectedEmails.forEach(emailId => {
        const email = state.emails.find(e => e.id === emailId);
        if (email) {
            state.staged.set(emailId, {
                email,
                destinationFolderId: selectedDestinationFolder,
                sourceAccountId: state.currentAccount,
            });
        }
    });
    
    // Clear selection
    state.selectedEmails.clear();
    
    closeModal('stageModal');
    selectedDestinationFolder = null;
    
    updateStageBadge();
    updateButtonStates();
    renderEmailList();
}

function updateStageBadge() {
    if (!elements.stageBadge) return;
    
    const count = state.staged.size;
    elements.stageBadge.textContent = count;
    elements.stageBadge.classList.toggle('hidden', count === 0);
}

function updateButtonStates() {
    if (elements.stageBtn) {
        elements.stageBtn.disabled = state.selectedEmails.size === 0;
    }
    if (elements.reviewBtn) {
        elements.reviewBtn.disabled = state.staged.size === 0;
    }
}

function goToReview() {
    if (state.staged.size === 0) return;
    
    // Save staged data to sessionStorage and navigate
    sessionStorage.setItem('stagedEmails', JSON.stringify([...state.staged.entries()]));
    window.location.href = '/review';
}

// ============================================
// NEW FOLDER MODAL
// ============================================

function openNewFolderModal(isNested = false) {
    const modal = document.createElement('div');
    modal.className = 'modal-overlay active';
    modal.id = 'newFolderModal';
    modal.style.zIndex = isNested ? '1001' : '1000';
    modal.innerHTML = `
        <div class="modal-content">
            <div class="modal-header">
                <h2>New Folder</h2>
            </div>
            
            <div class="form-group">
                <label for="newFolderName">Folder Name</label>
                <input type="text" id="newFolderName" placeholder="e.g., Client: John Smith" autofocus>
            </div>
            
            <div class="form-group">
                <label>Encryption</label>
                <div class="radio-group">
                    <label class="radio-label">
                        <input type="radio" name="encryption" value="1" checked>
                        <div class="radio-text">
                            <strong>🔒 Encrypted</strong>
                            <span class="radio-hint">For client correspondence, sensitive materials</span>
                        </div>
                    </label>
                    <label class="radio-label">
                        <input type="radio" name="encryption" value="0">
                        <div class="radio-text">
                            <strong>📁 Unencrypted</strong>
                            <span class="radio-hint">For personal emails, newsletters</span>
                        </div>
                    </label>
                </div>
            </div>
            
            <div class="modal-actions">
                <button class="btn btn-secondary" onclick="closeModal('newFolderModal')">Cancel</button>
                <button class="btn btn-primary" id="createFolderBtn">Create</button>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
    
    // Event listeners
    modal.querySelector('#createFolderBtn').addEventListener('click', () => createFolder(isNested));
    modal.querySelector('#newFolderName').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') createFolder(isNested);
    });
    modal.addEventListener('click', (e) => {
        if (e.target === modal) closeModal('newFolderModal');
    });
}

async function createFolder(returnToStageModal = false) {
    const nameInput = document.getElementById('newFolderName');
    const name = nameInput.value.trim();
    const encrypted = document.querySelector('input[name="encryption"]:checked').value === '1';
    
    if (!name) {
        nameInput.focus();
        return;
    }
    
    try {
        const response = await fetch('/api/folders', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, encrypted }),
        });
        
        if (!response.ok) {
            const data = await response.json();
            alert(data.error || 'Failed to create folder');
            return;
        }
        
        const data = await response.json();
        
        closeModal('newFolderModal');
        
        if (returnToStageModal) {
            // Add new folder to stage modal list and select it
            const list = document.getElementById('folderSelectList');
            if (list) {
                const item = document.createElement('div');
                item.className = 'folder-select-item selected';
                item.dataset.id = data.folder.id;
                item.innerHTML = `
                    <span class="folder-icon">${encrypted ? '🔒' : '📁'}</span>
                    <span class="folder-name">${escapeHtml(name)}</span>
                `;
                list.appendChild(item);
                
                // Clear other selections
                document.querySelectorAll('.folder-select-item').forEach(i => {
                    if (i !== item) i.classList.remove('selected');
                });
                
                selectedDestinationFolder = data.folder.id;
                document.getElementById('confirmStageBtn').disabled = false;
            }
        } else {
            // Refresh folder tree
            location.reload();
        }
    } catch (error) {
        console.error('Error creating folder:', error);
        alert('Failed to create folder. Please try again.');
    }
}

// ============================================
// NAVIGATION WARNING
// ============================================

function handleBeforeUnload(e) {
    if (state.staged.size > 0) {
        e.preventDefault();
        e.returnValue = '';  // Chrome requires this
        return '';
    }
}

// ============================================
// UTILITIES
// ============================================

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.remove('active');
        setTimeout(() => modal.remove(), 200);
    }
}

function showLoading() {
    if (!elements.emailList) return;
    elements.emailList.innerHTML = `
        <div class="empty-state">
            <div class="empty-icon">⏳</div>
            <h3>Loading...</h3>
        </div>
    `;
}

function showError(message) {
    if (!elements.emailList) return;
    elements.emailList.innerHTML = `
        <div class="empty-state">
            <div class="empty-icon">⚠️</div>
            <h3>Error</h3>
            <p>${escapeHtml(message)}</p>
        </div>
    `;
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function formatDate(timestamp) {
    if (!timestamp) return '';
    const date = new Date(timestamp * 1000);
    const now = new Date();
    
    // Same day: show time
    if (date.toDateString() === now.toDateString()) {
        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }
    
    // This year: show month and day
    if (date.getFullYear() === now.getFullYear()) {
        return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
    }
    
    // Different year: show full date
    return date.toLocaleDateString([], { year: 'numeric', month: 'short', day: 'numeric' });
}

function debounce(fn, delay) {
    let timeout;
    return function(...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => fn.apply(this, args), delay);
    };
}

function handleSearch(e) {
    const query = e.target.value.toLowerCase().trim();
    
    if (!query) {
        renderEmailList();
        return;
    }
    
    const filtered = state.emails.filter(email => 
        email.subject?.toLowerCase().includes(query) ||
        email.sender?.toLowerCase().includes(query) ||
        email.preview?.toLowerCase().includes(query)
    );
    
    const originalEmails = state.emails;
    state.emails = filtered;
    renderEmailList();
    state.emails = originalEmails;  // Restore for future operations
}

// Make functions globally available for inline handlers
window.toggleEmailSelection = toggleEmailSelection;
window.closeModal = closeModal;
