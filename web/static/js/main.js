/**
 * MailRepo - Main Application JavaScript
 * 
 * Handles:
 * - Three-pane navigation
 * - Account/folder tree interactions
 * - Email list rendering
 * - Staging workflow
 */

// ============================================
// STATE
// ============================================

const state = {
    currentView: null,      // { type: 'account'|'folder', id: number, label?: string }
    emails: [],
    staged: new Map(),      // Map<emailId, {email, destinationFolderId, sourceAccountId, sourceFolder}>
    selectedEmails: new Set(),
    folders: [],
    expandedAccounts: new Set(),
};

// ============================================
// DOM ELEMENTS
// ============================================

const elements = {
    // Sidebar
    accountsSection: document.getElementById('accountsSection'),
    archiveSection: document.getElementById('archiveSection'),
    sidebarFilter: document.getElementById('sidebarFilter'),
    
    // Main content
    contextTitle: document.getElementById('contextTitle'),
    contextMeta: document.getElementById('contextMeta'),
    emailList: document.getElementById('emailList'),
    selectAll: document.getElementById('selectAll'),
    searchInput: document.getElementById('searchInput'),
    
    // Buttons
    stageBtn: document.getElementById('stageBtn'),
    reviewBtn: document.getElementById('reviewBtn'),
    stagedBadge: document.getElementById('stagedBadge'),
    newFolderBtn: document.getElementById('newFolderBtn'),
    addFolderBtn: document.getElementById('addFolderBtn'),
    
    // Modals
    stageModal: document.getElementById('stageModal'),
    newFolderModal: document.getElementById('newFolderModal'),
};

// ============================================
// INITIALIZATION
// ============================================

document.addEventListener('DOMContentLoaded', () => {
    initEventListeners();
    loadFolders();
    updateStagedBadge();
    
    // Load labels for each account
    document.querySelectorAll('.account-item').forEach(item => {
        const accountId = item.dataset.accountId;
        loadAccountLabels(accountId);
    });
});

function initEventListeners() {
    // Section headers (collapse/expand)
    document.querySelectorAll('.section-header').forEach(header => {
        header.addEventListener('click', () => toggleSection(header));
    });
    
    // Tree item clicks
    document.querySelectorAll('.tree-item-row[data-type]').forEach(row => {
        row.addEventListener('click', (e) => handleTreeItemClick(e, row));
    });
    
    // Stage/Review buttons
    elements.stageBtn?.addEventListener('click', openStageModal);
    elements.reviewBtn?.addEventListener('click', goToReview);
    
    // Select all
    elements.selectAll?.addEventListener('change', handleSelectAll);
    
    // Search
    elements.searchInput?.addEventListener('input', debounce(handleSearch, 300));
    
    // New folder buttons
    elements.newFolderBtn?.addEventListener('click', () => openNewFolderModal(false));
    elements.addFolderBtn?.addEventListener('click', () => openNewFolderModal(false));
    
    // Folder select in stage modal
    document.getElementById('folderSelectList')?.addEventListener('click', handleFolderSelect);
    document.getElementById('confirmStageBtn')?.addEventListener('click', confirmStage);
    
    // New folder modal
    document.getElementById('createFolderBtn')?.addEventListener('click', () => createFolder(false));
    
    // Navigation warning
    window.addEventListener('beforeunload', handleBeforeUnload);
}

// ============================================
// SECTION COLLAPSE/EXPAND
// ============================================

function toggleSection(header) {
    const section = header.dataset.section;
    const content = document.getElementById(section + 'Section') || 
                    document.getElementById(section === 'accounts' ? 'accountsSection' : 'archiveSection');
    
    header.classList.toggle('collapsed');
    content?.classList.toggle('expanded');
}

// ============================================
// TREE NAVIGATION
// ============================================

function handleTreeItemClick(e, row) {
    const type = row.dataset.type;
    const id = row.dataset.id;
    
    // Handle account expansion
    if (type === 'account') {
        row.classList.toggle('expanded');
        const children = row.nextElementSibling;
        if (children?.classList.contains('tree-children')) {
            children.style.display = row.classList.contains('expanded') ? 'block' : 'none';
        }
        return;
    }
    
    // Handle label click (under account) - now handles IMAP folders
    if (type === 'label' || type === 'imap-folder') {
        const accountId = row.dataset.accountId;
        const folder = row.dataset.label || row.dataset.folder;
        selectView({ type: 'account', id: accountId, folder: folder });
    }
    
    // Handle folder click (archive)
    if (type === 'folder') {
        selectView({ type: 'folder', id: id });
    }
    
    // Update active state
    document.querySelectorAll('.tree-item-row').forEach(r => r.classList.remove('active'));
    row.classList.add('active');
}

function selectView(view) {
    state.currentView = view;
    state.selectedEmails.clear();
    
    if (view.type === 'account') {
        loadAccountEmails(view.id, view.folder);
    } else if (view.type === 'folder') {
        loadFolderEmails(view.id);
    }
    
    updateButtonStates();
}

// ============================================
// LOAD ACCOUNT FOLDERS (IMAP)
// ============================================

async function loadAccountLabels(accountId) {
    const container = document.getElementById(`labels-${accountId}`);
    if (!container) return;
    
    try {
        const response = await fetch(`/api/accounts/${accountId}/folders`);
        
        if (!response.ok) {
            const data = await response.json();
            container.innerHTML = `<div class="tree-loading">${data.error || 'Failed to load'}</div>`;
            return;
        }
        
        const data = await response.json();
        const folders = data.folders || [];
        
        // Common folder names to prioritize
        const priorityFolders = ['INBOX', 'Sent', 'Sent Messages', 'Drafts', 'Trash', 'Junk', 'Spam', 'Archive'];
        
        // Sort: priority folders first, then alphabetically
        folders.sort((a, b) => {
            const aIdx = priorityFolders.findIndex(p => a.name.toUpperCase().includes(p.toUpperCase()));
            const bIdx = priorityFolders.findIndex(p => b.name.toUpperCase().includes(p.toUpperCase()));
            
            if (aIdx !== -1 && bIdx === -1) return -1;
            if (aIdx === -1 && bIdx !== -1) return 1;
            if (aIdx !== -1 && bIdx !== -1) return aIdx - bIdx;
            return a.name.localeCompare(b.name);
        });
        
        let html = '';
        
        // Show folders (limit to 15 to avoid overwhelming the sidebar)
        folders.slice(0, 15).forEach(folder => {
            html += `
                <div class="tree-item-row" data-type="imap-folder" data-account-id="${accountId}" data-folder="${escapeHtml(folder.name)}">
                    <i data-lucide="${getFolderIcon(folder.name)}" class="tree-icon"></i>
                    <span class="tree-label">${escapeHtml(folder.name)}</span>
                </div>
            `;
        });
        
        container.innerHTML = html || '<div class="tree-loading">No folders</div>';
        
        // Render Lucide icons
        if (typeof lucide !== 'undefined') {
            lucide.createIcons();
        }
        
        // Add click handlers
        container.querySelectorAll('.tree-item-row').forEach(row => {
            row.addEventListener('click', (e) => {
                e.stopPropagation();
                handleTreeItemClick(e, row);
            });
        });
        
    } catch (error) {
        console.error('Error loading folders:', error);
        container.innerHTML = '<div class="tree-loading">Error loading folders</div>';
    }
}

function getFolderIcon(folderName) {
    const name = folderName.toUpperCase();
    if (name === 'INBOX') return 'inbox';
    if (name.includes('SENT')) return 'send';
    if (name.includes('DRAFT')) return 'file-edit';
    if (name.includes('SPAM') || name.includes('JUNK')) return 'alert-triangle';
    if (name.includes('TRASH') || name.includes('DELETED')) return 'trash-2';
    if (name.includes('ARCHIVE')) return 'archive';
    if (name.includes('STAR') || name.includes('FLAG')) return 'star';
    return 'folder';
}

// ============================================
// LOAD EMAILS
// ============================================

async function loadAccountEmails(accountId, folder = 'INBOX') {
    elements.contextTitle.textContent = `Loading...`;
    elements.contextMeta.textContent = '';
    showLoading();
    
    try {
        const response = await fetch(`/api/accounts/${accountId}/emails?folder=${encodeURIComponent(folder)}`);
        
        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.error || 'Failed to load emails');
        }
        
        const data = await response.json();
        state.emails = data.emails || [];
        
        // Update header
        elements.contextTitle.textContent = folder;
        elements.contextMeta.textContent = `${state.emails.length} emails`;
        
        renderEmailList();
        
    } catch (error) {
        console.error('Error loading emails:', error);
        elements.contextTitle.textContent = 'Error';
        showError(error.message);
    }
}

async function loadFolderEmails(folderId) {
    elements.contextTitle.textContent = `Loading...`;
    elements.contextMeta.textContent = '';
    showLoading();
    
    try {
        const response = await fetch(`/api/folders/${folderId}/emails`);
        
        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.error || 'Failed to load emails');
        }
        
        const data = await response.json();
        state.emails = data.emails || [];
        
        // Get folder name
        const folder = state.folders.find(f => f.id == folderId);
        elements.contextTitle.textContent = folder?.name || 'Archive';
        elements.contextMeta.textContent = `${state.emails.length} archived emails`;
        
        renderEmailList();
        
    } catch (error) {
        console.error('Error loading emails:', error);
        elements.contextTitle.textContent = 'Error';
        showError(error.message);
    }
}

async function loadFolders() {
    try {
        const response = await fetch('/api/folders');
        if (response.ok) {
            const data = await response.json();
            state.folders = data.folders || [];
        }
    } catch (e) {
        console.error('Failed to load folders:', e);
    }
}

// ============================================
// RENDER EMAIL LIST
// ============================================

function renderEmailList() {
    if (!elements.emailList) return;
    
    if (state.emails.length === 0) {
        elements.emailList.innerHTML = `
            <div class="empty-state">
                <i data-lucide="mail-x" class="empty-icon"></i>
                <h3>No Emails</h3>
                <p>This folder is empty.</p>
            </div>
        `;
        if (typeof lucide !== 'undefined') lucide.createIcons();
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
                        <span class="email-sender">${escapeHtml(extractName(email.sender))}</span>
                        <span class="email-date">${formatDate(email.date)}</span>
                    </div>
                    <div class="email-subject">${escapeHtml(email.subject || '(no subject)')}</div>
                    ${email.snippet ? `<div class="email-preview">${escapeHtml(email.snippet)}</div>` : ''}
                </div>
            </div>
        `;
    }).join('');
    
    updateSelectAllState();
}

function toggleEmailSelection(emailId) {
    if (state.staged.has(emailId)) return;
    
    if (state.selectedEmails.has(emailId)) {
        state.selectedEmails.delete(emailId);
    } else {
        state.selectedEmails.add(emailId);
    }
    
    // Update UI
    const item = document.querySelector(`.email-item[data-id="${emailId}"]`);
    if (item) {
        item.classList.toggle('selected', state.selectedEmails.has(emailId));
        item.querySelector('input[type="checkbox"]').checked = state.selectedEmails.has(emailId);
    }
    
    updateButtonStates();
    updateSelectAllState();
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
    
    const available = state.emails.filter(e => !state.staged.has(e.id));
    const selectedCount = [...state.selectedEmails].filter(id => 
        available.some(e => e.id === id)
    ).length;
    
    elements.selectAll.checked = available.length > 0 && selectedCount === available.length;
    elements.selectAll.indeterminate = selectedCount > 0 && selectedCount < available.length;
}

// ============================================
// STAGING
// ============================================

let selectedDestinationFolder = null;

function openStageModal() {
    if (state.selectedEmails.size === 0) return;
    
    document.getElementById('stageCount').textContent = state.selectedEmails.size;
    selectedDestinationFolder = null;
    
    // Reset folder selection
    document.querySelectorAll('.folder-select-item').forEach(item => {
        item.classList.remove('selected');
    });
    document.getElementById('confirmStageBtn').disabled = true;
    
    elements.stageModal.classList.add('active');
}

function handleFolderSelect(e) {
    const item = e.target.closest('.folder-select-item');
    if (!item) return;
    
    if (item.dataset.action === 'new') {
        openNewFolderModal(true);
        return;
    }
    
    document.querySelectorAll('.folder-select-item').forEach(i => i.classList.remove('selected'));
    item.classList.add('selected');
    
    selectedDestinationFolder = item.dataset.id;
    document.getElementById('confirmStageBtn').disabled = false;
}

function confirmStage() {
    if (!selectedDestinationFolder || !state.currentView) return;
    
    state.selectedEmails.forEach(emailId => {
        const email = state.emails.find(e => e.id === emailId);
        if (email) {
            state.staged.set(emailId, {
                email,
                destinationFolderId: selectedDestinationFolder,
                sourceAccountId: state.currentView.type === 'account' ? state.currentView.id : null,
                sourceFolder: state.currentView.folder || 'INBOX',
            });
        }
    });
    
    state.selectedEmails.clear();
    closeModal('stageModal');
    
    updateStagedBadge();
    updateButtonStates();
    renderEmailList();
}

function updateStagedBadge() {
    if (!elements.stagedBadge) return;
    
    const count = state.staged.size;
    elements.stagedBadge.textContent = count;
    elements.stagedBadge.classList.toggle('hidden', count === 0);
}

function updateButtonStates() {
    if (elements.stageBtn) {
        // Only enable stage for account views (not archive)
        const canStage = state.currentView?.type === 'account' && state.selectedEmails.size > 0;
        elements.stageBtn.disabled = !canStage;
    }
    if (elements.reviewBtn) {
        elements.reviewBtn.disabled = state.staged.size === 0;
    }
}

function goToReview() {
    if (state.staged.size === 0) return;
    
    sessionStorage.setItem('stagedEmails', JSON.stringify([...state.staged.entries()]));
    window.location.href = '/review';
}

// ============================================
// NEW FOLDER
// ============================================

function openNewFolderModal(fromStageModal = false) {
    elements.newFolderModal.dataset.fromStage = fromStageModal;
    document.getElementById('newFolderName').value = '';
    elements.newFolderModal.classList.add('active');
    document.getElementById('newFolderName').focus();
}

async function createFolder(returnToStage) {
    const name = document.getElementById('newFolderName').value.trim();
    const encrypted = document.querySelector('input[name="encryption"]:checked').value === '1';
    const fromStage = elements.newFolderModal.dataset.fromStage === 'true';
    
    if (!name) {
        document.getElementById('newFolderName').focus();
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
        state.folders.push(data.folder);
        
        closeModal('newFolderModal');
        
        if (fromStage) {
            // Add to stage modal folder list
            const list = document.getElementById('folderSelectList');
            const newItem = document.createElement('div');
            newItem.className = 'folder-select-item selected';
            newItem.dataset.id = data.folder.id;
            newItem.innerHTML = `
                <i data-lucide="${encrypted ? 'lock' : 'folder'}" class="folder-icon"></i>
                <span class="folder-name">${escapeHtml(name)}</span>
            `;
            list.appendChild(newItem);
            
            document.querySelectorAll('.folder-select-item').forEach(i => {
                if (i !== newItem) i.classList.remove('selected');
            });
            
            selectedDestinationFolder = data.folder.id;
            document.getElementById('confirmStageBtn').disabled = false;
        } else {
            location.reload();
        }
        
    } catch (error) {
        console.error('Error creating folder:', error);
        alert('Failed to create folder');
    }
}

// ============================================
// UTILITIES
// ============================================

function closeModal(modalId) {
    document.getElementById(modalId)?.classList.remove('active');
}

function showLoading() {
    if (!elements.emailList) return;
    elements.emailList.innerHTML = `
        <div class="empty-state">
            <i data-lucide="loader" class="empty-icon spin"></i>
            <h3>Loading...</h3>
        </div>
    `;
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function showError(message) {
    if (!elements.emailList) return;
    elements.emailList.innerHTML = `
        <div class="empty-state">
            <i data-lucide="alert-triangle" class="empty-icon"></i>
            <h3>Error</h3>
            <p>${escapeHtml(message)}</p>
        </div>
    `;
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function extractName(sender) {
    if (!sender) return '';
    // Extract name from "Name <email>" format
    const match = sender.match(/^([^<]+)</);
    return match ? match[1].trim() : sender;
}

function formatDate(dateStr) {
    if (!dateStr) return '';
    
    try {
        const date = new Date(dateStr);
        const now = new Date();
        
        if (isNaN(date.getTime())) return dateStr;
        
        // Same day
        if (date.toDateString() === now.toDateString()) {
            return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        }
        
        // This year
        if (date.getFullYear() === now.getFullYear()) {
            return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
        }
        
        // Other
        return date.toLocaleDateString([], { year: 'numeric', month: 'short', day: 'numeric' });
    } catch {
        return dateStr;
    }
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
        email.snippet?.toLowerCase().includes(query)
    );
    
    const original = state.emails;
    state.emails = filtered;
    renderEmailList();
    state.emails = original;
}

function handleBeforeUnload(e) {
    if (state.staged.size > 0) {
        e.preventDefault();
        e.returnValue = '';
        return '';
    }
}

// Global functions for inline handlers
window.toggleEmailSelection = toggleEmailSelection;
window.closeModal = closeModal;
