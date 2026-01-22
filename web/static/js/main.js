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
    loadFolders().then(() => {
        updateTrashBadge();
        refreshSidebarFolders(); // Render folder tree with hierarchy
    });
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
// SIDEBAR FOLDER UPDATES
// ============================================

function updateSidebarFolders(newFolder) {
    const archiveSection = document.getElementById('archiveSection');
    if (!archiveSection) return;
    
    // Find the "New Folder" button to insert before it
    const addBtn = archiveSection.querySelector('.add-folder-btn');
    
    // Create the new folder element
    const folderItem = document.createElement('div');
    folderItem.className = 'tree-item folder-item';
    
    const colorDot = newFolder.color ? 
        `<span class="color-dot" style="background: ${newFolder.color}"></span>` : '';
    
    folderItem.innerHTML = `
        <div class="tree-item-row" data-type="folder" data-id="${newFolder.id}" data-color="${newFolder.color || ''}">
            ${colorDot}
            <i data-lucide="folder" class="tree-icon"></i>
            <span class="tree-label">${escapeHtml(newFolder.name)}</span>
        </div>
    `;
    
    // Insert before the add button
    if (addBtn) {
        archiveSection.insertBefore(folderItem, addBtn);
    } else {
        archiveSection.appendChild(folderItem);
    }
    
    // Add click handler
    const row = folderItem.querySelector('.tree-item-row');
    row.addEventListener('click', (e) => handleTreeItemClick(e, row));
    
    // Update folder count
    const countEl = document.getElementById('folderCount');
    if (countEl) {
        countEl.textContent = state.folders.length;
    }
    
    // Remove empty state if present
    const emptyState = archiveSection.querySelector('.sidebar-empty');
    if (emptyState) {
        emptyState.remove();
    }
    
    // Re-render icons
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

/**
 * Refresh the entire sidebar folder list from state.
 * Renders hierarchical folder tree with expand/collapse for parents.
 */
function refreshSidebarFolders() {
    const archiveSection = document.getElementById('archiveSection');
    if (!archiveSection) return;
    
    // Remove all folder items (but keep the add button)
    archiveSection.querySelectorAll('.folder-item').forEach(el => el.remove());
    archiveSection.querySelector('.sidebar-empty')?.remove();
    
    // Get visible folders (not deleted)
    const visibleFolders = state.folders.filter(f => !f.deleted_at);
    const topLevel = visibleFolders.filter(f => !f.parent_id);
    
    // Find the add button
    const addBtn = archiveSection.querySelector('.add-folder-btn');
    
    if (topLevel.length === 0) {
        // Show empty state
        const empty = document.createElement('div');
        empty.className = 'sidebar-empty';
        empty.innerHTML = '<p>No archive folders</p>';
        if (addBtn) {
            archiveSection.insertBefore(empty, addBtn);
        } else {
            archiveSection.appendChild(empty);
        }
    } else {
        // Render folder tree
        topLevel.forEach(folder => {
            const children = visibleFolders.filter(f => f.parent_id == folder.id);
            const folderEl = createFolderTreeItem(folder, children, 0);
            
            if (addBtn) {
                archiveSection.insertBefore(folderEl, addBtn);
            } else {
                archiveSection.appendChild(folderEl);
            }
        });
    }
    
    // Update folder count (only top-level for now)
    const countEl = document.getElementById('folderCount');
    if (countEl) {
        countEl.textContent = topLevel.length;
    }
    
    // Re-render icons
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

/**
 * Create a folder tree item with optional children.
 */
function createFolderTreeItem(folder, children, depth) {
    const folderItem = document.createElement('div');
    folderItem.className = 'tree-item folder-item';
    folderItem.dataset.folderId = folder.id;
    
    const hasChildren = children && children.length > 0;
    const colorDot = folder.color ? 
        `<span class="color-dot" style="background: ${folder.color}"></span>` : '';
    const chevron = hasChildren ? 
        `<i data-lucide="chevron-right" class="chevron"></i>` : '';
    const indent = depth > 0 ? `style="padding-left: ${12 + depth * 20}px"` : '';
    
    folderItem.innerHTML = `
        <div class="tree-item-row ${hasChildren ? 'has-children' : ''}" data-type="folder" data-id="${folder.id}" data-color="${folder.color || ''}" ${indent}>
            ${chevron}
            ${colorDot}
            <i data-lucide="folder" class="tree-icon"></i>
            <span class="tree-label">${escapeHtml(folder.name)}</span>
        </div>
    `;
    
    // Add children container if has children
    if (hasChildren) {
        const childrenContainer = document.createElement('div');
        childrenContainer.className = 'tree-children';
        childrenContainer.style.display = 'none'; // Start collapsed
        
        children.forEach(child => {
            // Get grandchildren
            const grandchildren = state.folders.filter(f => f.parent_id == child.id && !f.deleted_at);
            const childEl = createFolderTreeItem(child, grandchildren, depth + 1);
            childrenContainer.appendChild(childEl);
        });
        
        folderItem.appendChild(childrenContainer);
    }
    
    // Add click handler
    const row = folderItem.querySelector('.tree-item-row');
    row.addEventListener('click', (e) => {
        // Handle expansion for folders with children
        if (hasChildren && (e.target.closest('.chevron') || e.target.classList.contains('chevron'))) {
            e.stopPropagation();
            row.classList.toggle('expanded');
            const childContainer = folderItem.querySelector('.tree-children');
            if (childContainer) {
                childContainer.style.display = row.classList.contains('expanded') ? 'block' : 'none';
            }
            return;
        }
        handleTreeItemClick(e, row);
    });
    
    return folderItem;
}

// ============================================
// TREE NAVIGATION
// ============================================

function handleTreeItemClick(e, row) {
    const type = row.dataset.type;
    const id = row.dataset.id;
    
    // Handle account expansion - also auto-select INBOX
    if (type === 'account') {
        const wasExpanded = row.classList.contains('expanded');
        row.classList.toggle('expanded');
        const children = row.nextElementSibling;
        if (children?.classList.contains('tree-children')) {
            children.style.display = row.classList.contains('expanded') ? 'block' : 'none';
        }
        
        // If expanding (not collapsing), auto-select INBOX
        if (!wasExpanded) {
            // Update active state
            document.querySelectorAll('.tree-item-row').forEach(r => r.classList.remove('active'));
            row.classList.add('active');
            
            // Select INBOX view for this account
            selectView({ type: 'account', id: id, folder: 'INBOX' });
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
        folders.forEach(folder => {
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
        const emailId = email.uid || email.id;
        const isStaged = state.staged.has(emailId);
        const isSelected = state.selectedEmails.has(emailId);
        
        return `
            <div class="email-item ${isStaged ? 'staged' : ''} ${isSelected ? 'selected' : ''}" 
                 data-id="${emailId}">
                <div class="email-checkbox" onclick="event.stopPropagation()">
                    <input type="checkbox" 
                           ${isSelected ? 'checked' : ''} 
                           ${isStaged ? 'disabled' : ''}
                           onchange="toggleEmailSelection('${emailId}')">
                </div>
                <div class="email-content" onclick="openEmailViewer('${emailId}')">
                    <div class="email-header">
                        <span class="email-sender">${escapeHtml(extractName(email.from || email.sender))}</span>
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
        const emailId = email.uid || email.id;
        if (!state.staged.has(emailId)) {
            if (checked) {
                state.selectedEmails.add(emailId);
            } else {
                state.selectedEmails.delete(emailId);
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
        const email = state.emails.find(e => (e.uid || e.id) === emailId);
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
    window.removeEventListener('beforeunload', handleBeforeUnload);
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
    const fromStage = elements.newFolderModal.dataset.fromStage === 'true';
    
    if (!name) {
        document.getElementById('newFolderName').focus();
        return;
    }
    
    try {
        const response = await fetch('/api/folders', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name }),
        });
        
        if (!response.ok) {
            const data = await response.json();
            showAlert('Error', data.error || 'Failed to create folder');
            return;
        }
        
        const data = await response.json();
        state.folders.push(data.folder);
        
        closeModal('newFolderModal');
        
        // Update sidebar archive section
        updateSidebarFolders(data.folder);
        
        if (fromStage) {
            // Add to stage modal folder list
            const list = document.getElementById('folderSelectList');
            const newItem = document.createElement('div');
            newItem.className = 'folder-select-item selected';
            newItem.dataset.id = data.folder.id;
            newItem.innerHTML = `
                <i data-lucide="folder" class="folder-icon"></i>
                <span class="folder-name">${escapeHtml(name)}</span>
            `;
            list.appendChild(newItem);
            
            document.querySelectorAll('.folder-select-item').forEach(i => {
                if (i !== newItem) i.classList.remove('selected');
            });
            
            selectedDestinationFolder = data.folder.id;
            document.getElementById('confirmStageBtn').disabled = false;
            
            // Re-render icons
            if (typeof lucide !== 'undefined') lucide.createIcons();
        } else {
            // Check if we're in folder management view
            const activeView = document.querySelector('.rail-btn.active')?.dataset.view;
            if (activeView === 'folders') {
                showFolderManagementView();
            } else {
                location.reload();
            }
        }
        
    } catch (error) {
        console.error('Error creating folder:', error);
        showAlert('Error', 'Failed to create folder');
    }
}

// ============================================
// UTILITIES
// ============================================

function closeModal(modalId) {
    document.getElementById(modalId)?.classList.remove('active');
}

// ============================================
// MODAL HELPERS (replace native prompt/confirm/alert)
// ============================================

let promptResolver = null;
let confirmResolver = null;

/**
 * Show a styled prompt modal (replaces native prompt)
 * @param {string} title - Modal title
 * @param {string} defaultValue - Default input value
 * @returns {Promise<string|null>} - User input or null if cancelled
 */
function showPrompt(title, defaultValue = '') {
    return new Promise(resolve => {
        promptResolver = resolve;
        document.getElementById('promptTitle').textContent = title;
        document.getElementById('promptInput').value = defaultValue;
        document.getElementById('promptModal').classList.add('active');
        document.getElementById('promptInput').focus();
        document.getElementById('promptInput').select();
    });
}

function resolvePrompt(value) {
    closeModal('promptModal');
    if (promptResolver) {
        promptResolver(value);
        promptResolver = null;
    }
}
window.resolvePrompt = resolvePrompt;

// Handle Enter key in prompt
document.getElementById('promptInput')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
        resolvePrompt(e.target.value);
    } else if (e.key === 'Escape') {
        resolvePrompt(null);
    }
});

/**
 * Show a styled confirm modal (replaces native confirm)
 * @param {string} title - Modal title
 * @param {string} message - Confirmation message
 * @param {object} options - Optional settings
 * @param {string} options.okText - Text for OK button (default: "OK")
 * @param {boolean} options.danger - Use danger styling for OK button
 * @returns {Promise<boolean>} - true if confirmed, false if cancelled
 */
function showConfirm(title, message, options = {}) {
    return new Promise(resolve => {
        confirmResolver = resolve;
        document.getElementById('confirmTitle').textContent = title;
        document.getElementById('confirmMessage').textContent = message;
        
        const okBtn = document.getElementById('confirmOkBtn');
        okBtn.textContent = options.okText || 'OK';
        okBtn.className = options.danger ? 'btn btn-danger' : 'btn btn-primary';
        
        document.getElementById('confirmModal').classList.add('active');
    });
}

function resolveConfirm(value) {
    closeModal('confirmModal');
    if (confirmResolver) {
        confirmResolver(value);
        confirmResolver = null;
    }
}
window.resolveConfirm = resolveConfirm;

/**
 * Show a styled alert modal (replaces native alert)
 * @param {string} title - Modal title
 * @param {string} message - Alert message
 */
function showAlert(title, message) {
    document.getElementById('alertTitle').textContent = title;
    document.getElementById('alertMessage').textContent = message;
    document.getElementById('alertModal').classList.add('active');
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

// ============================================
// EMAIL VIEWER
// ============================================

async function openEmailViewer(emailId) {
    const email = state.emails.find(e => e.uid == emailId || e.id == emailId);
    if (!email) return;
    
    // Show overlay with loading state
    const overlay = document.getElementById('emailViewerOverlay');
    overlay.classList.add('active');
    
    document.getElementById('viewerSubject').textContent = email.subject || '(no subject)';
    document.getElementById('viewerFrom').textContent = email.from || email.sender || '';
    document.getElementById('viewerTo').textContent = email.to || '';
    document.getElementById('viewerDate').textContent = email.date || '';
    document.getElementById('viewerBody').innerHTML = '<div class="loading-spinner">Loading...</div>';
    document.getElementById('viewerAttachments').style.display = 'none';
    document.getElementById('viewerCcRow').style.display = 'none';
    
    // Render icons
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
    
    // Fetch full email based on view type
    try {
        let response;
        
        if (state.currentView?.type === 'account') {
            // IMAP email
            const accountId = state.currentView.id;
            const folder = state.currentView.folder || 'INBOX';
            const uid = email.uid || email.id;
            
            response = await fetch(
                `/api/accounts/${accountId}/emails/${uid}?folder=${encodeURIComponent(folder)}`
            );
        } else if (state.currentView?.type === 'folder') {
            // Archived email
            const folderId = state.currentView.id;
            const messageId = email.id;
            
            response = await fetch(`/api/folders/${folderId}/emails/${messageId}`);
        } else {
            throw new Error('Unknown view type');
        }
        
        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.error || 'Failed to load email');
        }
        
        const data = await response.json();
        renderEmailContent(data.email);
        
    } catch (error) {
        console.error('Error loading email:', error);
        document.getElementById('viewerBody').innerHTML = 
            `<div class="error-message">Failed to load email: ${escapeHtml(error.message)}</div>`;
    }
}

function renderEmailContent(email) {
    // Update meta
    document.getElementById('viewerSubject').textContent = email.subject || '(no subject)';
    document.getElementById('viewerFrom').textContent = email.from || '';
    document.getElementById('viewerTo').textContent = email.to || '';
    document.getElementById('viewerDate').textContent = email.date || '';
    
    if (email.cc) {
        document.getElementById('viewerCc').textContent = email.cc;
        document.getElementById('viewerCcRow').style.display = 'flex';
    }
    
    // Attachments
    if (email.attachments && email.attachments.length > 0) {
        const attachDiv = document.getElementById('viewerAttachments');
        let html = '<div class="attachment-list">';
        email.attachments.forEach(att => {
            html += `
                <div class="attachment-item">
                    <i data-lucide="paperclip"></i>
                    <span>${escapeHtml(att.filename)}</span>
                </div>
            `;
        });
        html += '</div>';
        attachDiv.innerHTML = html;
        attachDiv.style.display = 'block';
        
        if (typeof lucide !== 'undefined') {
            lucide.createIcons();
        }
    }
    
    // Body - prefer HTML, fall back to text
    const bodyDiv = document.getElementById('viewerBody');
    
    if (email.html_body) {
        // Use an iframe for HTML content to isolate styles
        const iframe = document.createElement('iframe');
        iframe.sandbox = 'allow-same-origin';
        iframe.style.width = '100%';
        iframe.style.border = 'none';
        bodyDiv.innerHTML = '';
        bodyDiv.appendChild(iframe);
        
        // Write content to iframe
        const doc = iframe.contentDocument || iframe.contentWindow.document;
        doc.open();
        doc.write(`
            <!DOCTYPE html>
            <html>
            <head>
                <style>
                    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
                           font-size: 14px; line-height: 1.5; color: #333; margin: 0; padding: 0; }
                    img { max-width: 100%; height: auto; }
                    a { color: #1a73e8; }
                </style>
            </head>
            <body>${email.html_body}</body>
            </html>
        `);
        doc.close();
        
        // Adjust iframe height to content
        setTimeout(() => {
            iframe.style.height = doc.body.scrollHeight + 'px';
        }, 100);
        
    } else if (email.text_body) {
        bodyDiv.innerHTML = `<div class="email-text-body">${escapeHtml(email.text_body)}</div>`;
    } else {
        bodyDiv.innerHTML = '<div class="email-text-body">(No content)</div>';
    }
}

function closeEmailViewer() {
    document.getElementById('emailViewerOverlay').classList.remove('active');
}

// Close viewer on Escape or backdrop click
document.getElementById('emailViewerOverlay')?.addEventListener('click', (e) => {
    if (e.target.id === 'emailViewerOverlay') {
        closeEmailViewer();
    }
});

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && document.getElementById('emailViewerOverlay')?.classList.contains('active')) {
        closeEmailViewer();
    }
});

// Global functions for inline handlers
window.toggleEmailSelection = toggleEmailSelection;
window.closeModal = closeModal;
window.openEmailViewer = openEmailViewer;
window.closeEmailViewer = closeEmailViewer;

// ============================================
// SIDEBAR RESIZE
// ============================================

(function() {
    const sidebar = document.getElementById('sidebar');
    const handle = document.getElementById('sidebarResizeHandle');
    if (!sidebar || !handle) return;
    
    const MIN_WIDTH = 280;
    const MAX_WIDTH = 420;
    let isResizing = false;
    let startX, startWidth;
    
    // Load saved width
    const savedWidth = localStorage.getItem('mailrepo-sidebar-width');
    if (savedWidth) {
        const width = parseInt(savedWidth, 10);
        if (width >= MIN_WIDTH && width <= MAX_WIDTH) {
            sidebar.style.width = width + 'px';
        }
    }
    
    handle.addEventListener('mousedown', (e) => {
        isResizing = true;
        startX = e.clientX;
        startWidth = sidebar.offsetWidth;
        handle.classList.add('dragging');
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
        e.preventDefault();
    });
    
    document.addEventListener('mousemove', (e) => {
        if (!isResizing) return;
        
        const delta = e.clientX - startX;
        let newWidth = startWidth + delta;
        
        // Clamp to min/max
        newWidth = Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, newWidth));
        sidebar.style.width = newWidth + 'px';
    });
    
    document.addEventListener('mouseup', () => {
        if (!isResizing) return;
        
        isResizing = false;
        handle.classList.remove('dragging');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        
        // Save width
        localStorage.setItem('mailrepo-sidebar-width', sidebar.offsetWidth);
    });
})();

// ============================================
// LEFT RAIL VIEW SWITCHING
// ============================================

const FOLDER_COLORS = [
    { name: 'Gray', value: null },
    { name: 'Red', value: '#e53935' },
    { name: 'Orange', value: '#fb8c00' },
    { name: 'Yellow', value: '#fdd835' },
    { name: 'Green', value: '#43a047' },
    { name: 'Teal', value: '#00897b' },
    { name: 'Blue', value: '#1e88e5' },
    { name: 'Purple', value: '#8e24aa' },
    { name: 'Pink', value: '#d81b60' },
];

(function() {
    const railBtns = document.querySelectorAll('.rail-btn[data-view]');
    
    railBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const view = btn.dataset.view;
            
            // Update active state
            railBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            // Switch view
            switch(view) {
                case 'mail':
                    showMailView();
                    break;
                case 'staged':
                    showStagedView();
                    break;
                case 'folders':
                    showFolderManagementView();
                    break;
                case 'trash':
                    showTrashView();
                    break;
            }
        });
    });
})();

function showMailView() {
    // Restore normal mail view
    const sidebar = document.getElementById('sidebar');
    const toolbar = document.querySelector('.content-toolbar');
    const headerActions = document.querySelector('.header-actions');
    
    sidebar.style.display = '';
    if (toolbar) toolbar.style.display = '';
    if (headerActions) headerActions.style.display = '';
    
    // Clear selection and show default
    state.currentView = null;
    elements.contextTitle.textContent = 'Select a folder';
    elements.contextMeta.textContent = '';
    elements.emailList.innerHTML = `
        <div class="empty-state">
            <i data-lucide="arrow-left" class="empty-icon"></i>
            <h3>No Folder Selected</h3>
            <p>Select an account or archive folder from the sidebar to view emails.</p>
        </div>
    `;
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function showStagedView() {
    const sidebar = document.getElementById('sidebar');
    const toolbar = document.querySelector('.content-toolbar');
    const headerActions = document.querySelector('.header-actions');
    
    sidebar.style.display = 'none';
    if (toolbar) toolbar.style.display = 'none';
    if (headerActions) headerActions.style.display = '';
    
    elements.contextTitle.textContent = 'Staged Emails';
    elements.contextMeta.textContent = `${state.staged.size} email${state.staged.size !== 1 ? 's' : ''} staged`;
    
    if (state.staged.size === 0) {
        elements.emailList.innerHTML = `
            <div class="empty-state">
                <i data-lucide="package" class="empty-icon"></i>
                <h3>No Staged Emails</h3>
                <p>Select emails from your inbox and click "Stage" to prepare them for archiving.</p>
            </div>
        `;
    } else {
        renderStagedList();
    }
    
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function renderStagedList() {
    const stagedArray = [...state.staged.entries()];
    
    elements.emailList.innerHTML = stagedArray.map(([emailId, data]) => {
        const email = data.email;
        const folder = state.folders.find(f => f.id == data.destinationFolderId);
        
        return `
            <div class="email-item staged-item" data-id="${emailId}">
                <div class="email-content">
                    <div class="email-header">
                        <span class="email-sender">${escapeHtml(extractName(email.from || email.sender))}</span>
                        <span class="email-date">${formatDate(email.date)}</span>
                    </div>
                    <div class="email-subject">${escapeHtml(email.subject || '(no subject)')}</div>
                    <div class="email-preview staged-destination">
                        <i data-lucide="folder"></i>
                        <span>→ ${escapeHtml(folder?.name || 'Unknown folder')}</span>
                    </div>
                </div>
                <button class="btn btn-sm btn-secondary unstage-btn" onclick="unstageEmail('${emailId}')">
                    <i data-lucide="x"></i>
                </button>
            </div>
        `;
    }).join('');
    
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function unstageEmail(emailId) {
    state.staged.delete(emailId);
    updateStagedBadge();
    
    // Re-render if still in staged view
    const activeBtn = document.querySelector('.rail-btn.active');
    if (activeBtn?.dataset.view === 'staged') {
        showStagedView();
    }
}
window.unstageEmail = unstageEmail;

// ============================================
// FOLDER MANAGEMENT VIEW
// ============================================

async function showFolderManagementView() {
    const sidebar = document.getElementById('sidebar');
    const toolbar = document.querySelector('.content-toolbar');
    const headerActions = document.querySelector('.header-actions');
    
    sidebar.style.display = 'none';
    if (toolbar) toolbar.style.display = 'none';
    if (headerActions) headerActions.style.display = 'none';
    
    elements.contextTitle.textContent = 'Manage Folders';
    elements.contextMeta.textContent = '';
    
    // Reload folders first
    await loadFolders();
    
    if (state.folders.length === 0) {
        elements.emailList.innerHTML = `
            <div class="empty-state">
                <i data-lucide="folder" class="empty-icon"></i>
                <h3>No Folders</h3>
                <p>Create your first folder to start archiving emails.</p>
                <button class="btn btn-primary" onclick="openNewFolderModal(false)">
                    <i data-lucide="plus"></i> New Folder
                </button>
            </div>
        `;
    } else {
        renderFolderManagementList();
    }
    
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function renderFolderManagementList() {
    // Build folder tree
    const topLevelFolders = state.folders.filter(f => !f.parent_id && !f.deleted_at);
    
    let html = `
        <div class="folder-management-list">
            <div class="folder-management-header">
                <span>Folder</span>
                <span>Color</span>
                <span>Actions</span>
            </div>
    `;
    
    // Recursive function to render folder and all descendants
    function renderFolderWithChildren(folder, depth) {
        html += renderFolderManagementItem(folder, depth);
        
        // Render children recursively
        const children = state.folders.filter(f => f.parent_id == folder.id && !f.deleted_at);
        children.forEach(child => {
            renderFolderWithChildren(child, depth + 1);
        });
    }
    
    topLevelFolders.forEach(folder => {
        renderFolderWithChildren(folder, 0);
    });
    
    html += `
            <button class="folder-management-add" onclick="openNewFolderModal(false)">
                <i data-lucide="plus"></i>
                <span>New Folder</span>
            </button>
        </div>
    `;
    
    elements.emailList.innerHTML = html;
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function renderFolderManagementItem(folder, depth = 0) {
    const colorDot = folder.color ? 
        `<span class="color-dot" style="background: ${folder.color}"></span>` : 
        `<span class="color-dot color-dot-none"></span>`;
    
    return `
        <div class="folder-management-item" data-id="${folder.id}" style="padding-left: ${20 + depth * 24}px">
            <div class="folder-management-name">
                ${colorDot}
                <i data-lucide="folder" class="folder-icon"></i>
                <span class="folder-label" data-id="${folder.id}">${escapeHtml(folder.name)}</span>
            </div>
            <div class="folder-management-color">
                <button class="color-picker-btn" onclick="openColorPicker(${folder.id}, event)" title="Change color">
                    ${folder.color ? `<span class="color-swatch" style="background: ${folder.color}"></span>` : '<i data-lucide="palette"></i>'}
                </button>
            </div>
            <div class="folder-management-actions">
                <button class="btn btn-sm btn-icon" onclick="renameFolder(${folder.id})" title="Rename">
                    <i data-lucide="pencil"></i>
                </button>
                <button class="btn btn-sm btn-icon" onclick="openMoveFolder(${folder.id})" title="Move">
                    <i data-lucide="folder-input"></i>
                </button>
                <button class="btn btn-sm btn-icon" onclick="createSubfolder(${folder.id})" title="Add subfolder">
                    <i data-lucide="folder-plus"></i>
                </button>
                <button class="btn btn-sm btn-icon btn-danger-subtle" onclick="deleteFolder(${folder.id})" title="Delete">
                    <i data-lucide="trash-2"></i>
                </button>
            </div>
        </div>
    `;
}

async function renameFolder(folderId) {
    const folder = state.folders.find(f => f.id == folderId);
    if (!folder) return;
    
    const newName = await showPrompt('Rename folder:', folder.name);
    if (!newName || newName.trim() === '' || newName === folder.name) return;
    
    try {
        const response = await fetch(`/api/folders/${folderId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: newName.trim() }),
        });
        
        if (!response.ok) {
            const data = await response.json();
            showAlert('Error', data.error || 'Failed to rename folder');
            return;
        }
        
        folder.name = newName.trim();
        showFolderManagementView();
        refreshSidebarFolders();
        
    } catch (error) {
        console.error('Error renaming folder:', error);
        showAlert('Error', 'Failed to rename folder');
    }
}
window.renameFolder = renameFolder;

async function createSubfolder(parentId) {
    const name = await showPrompt('New subfolder name:', '');
    if (!name || name.trim() === '') return;
    
    try {
        const response = await fetch('/api/folders', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name.trim(), parent_id: parentId }),
        });
        
        if (!response.ok) {
            const data = await response.json();
            showAlert('Error', data.error || 'Failed to create folder');
            return;
        }
        
        const data = await response.json();
        state.folders.push(data.folder);
        showFolderManagementView();
        refreshSidebarFolders();
        
    } catch (error) {
        console.error('Error creating subfolder:', error);
        showAlert('Error', 'Failed to create subfolder');
    }
}
window.createSubfolder = createSubfolder;

// ============================================
// MOVE FOLDER
// ============================================

let movingFolderId = null;
let moveDestinationId = null;

function openMoveFolder(folderId) {
    const folder = state.folders.find(f => f.id == folderId);
    if (!folder) return;
    
    movingFolderId = folderId;
    moveDestinationId = null;
    
    document.getElementById('moveFolderName').textContent = folder.name;
    document.getElementById('confirmMoveBtn').disabled = true;
    
    // Get all descendants of this folder (can't move into itself or children)
    const descendants = getDescendantIds(folderId);
    
    // Build folder list
    const list = document.getElementById('moveFolderList');
    let html = `
        <div class="folder-select-item" data-id="root">
            <i data-lucide="home"></i>
            <span>Root level (no parent)</span>
        </div>
    `;
    
    // Add all valid folders (not the folder itself, not its descendants, not deleted)
    const validFolders = state.folders.filter(f => 
        !f.deleted_at && 
        f.id != folderId && 
        !descendants.includes(f.id)
    );
    
    // Render as flat list with indentation showing hierarchy
    function renderFolderOption(f, depth) {
        const indent = depth * 16;
        const isCurrentParent = (folder.parent_id === f.id) || (folder.parent_id === null && f.id === 'root');
        html += `
            <div class="folder-select-item ${isCurrentParent ? 'current-location' : ''}" data-id="${f.id}" style="padding-left: ${12 + indent}px">
                <i data-lucide="folder"></i>
                <span>${escapeHtml(f.name)}</span>
                ${isCurrentParent ? '<span class="current-badge">current</span>' : ''}
            </div>
        `;
        // Render children
        const children = validFolders.filter(c => c.parent_id == f.id);
        children.forEach(child => renderFolderOption(child, depth + 1));
    }
    
    // Render top-level folders
    validFolders.filter(f => !f.parent_id).forEach(f => renderFolderOption(f, 0));
    
    list.innerHTML = html;
    
    // Mark root as current if folder is at root level
    if (folder.parent_id === null) {
        list.querySelector('[data-id="root"]')?.classList.add('current-location');
        const rootItem = list.querySelector('[data-id="root"]');
        if (rootItem && !rootItem.querySelector('.current-badge')) {
            rootItem.innerHTML += '<span class="current-badge">current</span>';
        }
    }
    
    // Add click handlers
    list.querySelectorAll('.folder-select-item').forEach(item => {
        item.addEventListener('click', () => {
            list.querySelectorAll('.folder-select-item').forEach(i => i.classList.remove('selected'));
            item.classList.add('selected');
            moveDestinationId = item.dataset.id;
            document.getElementById('confirmMoveBtn').disabled = false;
        });
    });
    
    document.getElementById('moveFolderModal').classList.add('active');
    if (typeof lucide !== 'undefined') lucide.createIcons();
}
window.openMoveFolder = openMoveFolder;

function getDescendantIds(folderId) {
    const descendants = [];
    function collect(parentId) {
        state.folders.filter(f => f.parent_id == parentId && !f.deleted_at).forEach(child => {
            descendants.push(child.id);
            collect(child.id);
        });
    }
    collect(folderId);
    return descendants;
}

async function confirmMoveFolder() {
    if (!movingFolderId || moveDestinationId === null) return;
    
    const newParentId = moveDestinationId === 'root' ? null : parseInt(moveDestinationId);
    const folder = state.folders.find(f => f.id == movingFolderId);
    
    // Check if actually moving
    if (folder.parent_id === newParentId) {
        closeModal('moveFolderModal');
        return;
    }
    
    try {
        const response = await fetch(`/api/folders/${movingFolderId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ parent_id: newParentId }),
        });
        
        if (!response.ok) {
            const data = await response.json();
            showAlert('Error', data.error || 'Failed to move folder');
            return;
        }
        
        // Update local state
        folder.parent_id = newParentId;
        
        closeModal('moveFolderModal');
        showFolderManagementView();
        refreshSidebarFolders();
        
    } catch (error) {
        console.error('Error moving folder:', error);
        showAlert('Error', 'Failed to move folder');
    }
}
window.confirmMoveFolder = confirmMoveFolder;

async function deleteFolder(folderId) {
    const folder = state.folders.find(f => f.id == folderId);
    if (!folder) return;
    
    // Count children and emails
    const children = state.folders.filter(f => f.parent_id == folderId && !f.deleted_at);
    
    let message = `Move "${folder.name}" to trash?`;
    if (children.length > 0) {
        message = `Move "${folder.name}" and ${children.length} subfolder${children.length > 1 ? 's' : ''} to trash?`;
    }
    
    const confirmed = await showConfirm('Delete Folder', message, { okText: 'Move to Trash' });
    if (!confirmed) return;
    
    try {
        const response = await fetch(`/api/folders/${folderId}`, {
            method: 'DELETE',
        });
        
        if (!response.ok) {
            const data = await response.json();
            showAlert('Error', data.error || 'Failed to delete folder');
            return;
        }
        
        // Update local state
        folder.deleted_at = Date.now() / 1000;
        children.forEach(c => c.deleted_at = Date.now() / 1000);
        
        showFolderManagementView();
        updateTrashBadge();
        updateSidebarFoldersAfterDelete(folderId);
        
    } catch (error) {
        console.error('Error deleting folder:', error);
        showAlert('Error', 'Failed to delete folder');
    }
}
window.deleteFolder = deleteFolder;

function updateSidebarFoldersAfterDelete(folderId) {
    const archiveSection = document.getElementById('archiveSection');
    if (!archiveSection) return;
    
    const folderEl = archiveSection.querySelector(`.tree-item-row[data-id="${folderId}"]`);
    if (folderEl) {
        folderEl.closest('.tree-item')?.remove();
    }
    
    // Update count
    const countEl = document.getElementById('folderCount');
    if (countEl) {
        const visibleFolders = state.folders.filter(f => !f.deleted_at);
        countEl.textContent = visibleFolders.length;
    }
}

// Color picker
function openColorPicker(folderId, event) {
    event.stopPropagation();
    
    // Remove any existing picker
    document.querySelector('.color-picker-popup')?.remove();
    
    const folder = state.folders.find(f => f.id == folderId);
    const btn = event.currentTarget;
    const rect = btn.getBoundingClientRect();
    
    const popup = document.createElement('div');
    popup.className = 'color-picker-popup';
    popup.style.top = `${rect.bottom + 4}px`;
    popup.style.left = `${rect.left}px`;
    
    popup.innerHTML = FOLDER_COLORS.map(c => `
        <button class="color-option ${folder?.color === c.value ? 'selected' : ''}" 
                data-color="${c.value || ''}" 
                title="${c.name}">
            ${c.value ? `<span style="background: ${c.value}"></span>` : '<i data-lucide="x"></i>'}
        </button>
    `).join('');
    
    document.body.appendChild(popup);
    if (typeof lucide !== 'undefined') lucide.createIcons();
    
    // Handle selection
    popup.addEventListener('click', async (e) => {
        const option = e.target.closest('.color-option');
        if (!option) return;
        
        const color = option.dataset.color || null;
        await setFolderColor(folderId, color);
        popup.remove();
    });
    
    // Close on outside click
    setTimeout(() => {
        document.addEventListener('click', function closePopup(e) {
            if (!popup.contains(e.target)) {
                popup.remove();
                document.removeEventListener('click', closePopup);
            }
        });
    }, 10);
}
window.openColorPicker = openColorPicker;

async function setFolderColor(folderId, color) {
    try {
        const response = await fetch(`/api/folders/${folderId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ color: color }),
        });
        
        if (!response.ok) {
            const data = await response.json();
            showAlert('Error', data.error || 'Failed to update color');
            return;
        }
        
        const folder = state.folders.find(f => f.id == folderId);
        if (folder) folder.color = color;
        
        showFolderManagementView();
        refreshSidebarFolders();
        
    } catch (error) {
        console.error('Error updating folder color:', error);
    }
}

// ============================================
// TRASH VIEW
// ============================================

async function showTrashView() {
    const sidebar = document.getElementById('sidebar');
    const toolbar = document.querySelector('.content-toolbar');
    const headerActions = document.querySelector('.header-actions');
    
    sidebar.style.display = 'none';
    if (toolbar) toolbar.style.display = 'none';
    if (headerActions) headerActions.style.display = 'none';
    
    elements.contextTitle.textContent = 'Trash';
    elements.contextMeta.textContent = '';
    
    // Reload folders to get fresh deleted_at data
    await loadFolders();
    
    // Get trashed folders (only top-level ones that were directly deleted)
    const trashedFolders = state.folders
        .filter(f => f.deleted_at && !f.parent_id)
        .sort((a, b) => b.deleted_at - a.deleted_at);  // Most recent first
    // Also include folders whose parent is deleted
    const allTrashed = state.folders.filter(f => {
        if (f.deleted_at) return true;
        // Check if parent is deleted
        if (f.parent_id) {
            const parent = state.folders.find(p => p.id == f.parent_id);
            return parent?.deleted_at;
        }
        return false;
    });
    
    if (trashedFolders.length === 0) {
        elements.emailList.innerHTML = `
            <div class="empty-state">
                <i data-lucide="trash-2" class="empty-icon"></i>
                <h3>Trash is Empty</h3>
                <p>Items you delete will appear here.</p>
            </div>
        `;
    } else {
        renderTrashList(trashedFolders);
    }
    
    updateTrashBadge();
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function renderTrashList(trashedFolders) {
    let html = `
        <div class="trash-list">
            <div class="trash-header">
                <span>Folder</span>
                <span>Deleted</span>
                <span>Actions</span>
            </div>
    `;
    
    trashedFolders.forEach(folder => {
        const deletedDate = new Date(folder.deleted_at * 1000);
        const children = state.folders.filter(f => f.parent_id == folder.id);
        
        html += `
            <div class="trash-item" data-id="${folder.id}">
                <div class="trash-item-name">
                    <i data-lucide="folder" class="folder-icon"></i>
                    <span class="folder-name">${escapeHtml(folder.name)}</span>
                    ${children.length > 0 ? `<span class="subfolder-count">(+${children.length})</span>` : ''}
                </div>
                <div class="trash-item-date">
                    ${formatDate(deletedDate)}
                </div>
                <div class="trash-item-actions">
                    <button class="btn btn-sm btn-icon" onclick="restoreFolder(${folder.id})" title="Restore">
                        <i data-lucide="undo-2"></i>
                    </button>
                    <button class="btn btn-sm btn-icon btn-danger-subtle" onclick="permanentlyDeleteFolder(${folder.id})" title="Delete permanently">
                        <i data-lucide="x"></i>
                    </button>
                </div>
            </div>
        `;
    });
    
    // Empty Trash button at bottom
    html += `
            <div class="trash-footer">
                <button class="btn btn-sm btn-danger" onclick="emptyTrash()">
                    <i data-lucide="trash-2"></i> Empty Trash
                </button>
            </div>
        </div>
    `;
    elements.emailList.innerHTML = html;
}

async function restoreFolder(folderId) {
    try {
        const response = await fetch(`/api/folders/${folderId}/restore`, {
            method: 'POST',
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            showAlert('Error', data.error || 'Failed to restore folder');
            return;
        }
        
        // Update local state
        const folder = state.folders.find(f => f.id == folderId);
        if (folder) {
            folder.deleted_at = null;
            // Update name if it was renamed due to conflict
            if (data.folder && data.folder.name) {
                folder.name = data.folder.name;
            }
            // Also restore children
            state.folders.filter(f => f.parent_id == folderId).forEach(c => c.deleted_at = null);
        }
        
        showTrashView();
        updateSidebarAfterRestore(folder);
        
        // Notify user if folder was renamed
        if (data.folder && data.folder.renamed) {
            showAlert('Folder Restored', `Folder restored as "${data.folder.name}" to avoid a naming conflict.`);
        }
        
    } catch (error) {
        console.error('Error restoring folder:', error);
        showAlert('Error', 'Failed to restore folder');
    }
}
window.restoreFolder = restoreFolder;

function updateSidebarAfterRestore(folder) {
    if (!folder) return;
    updateSidebarFolders(folder);
}

async function permanentlyDeleteFolder(folderId) {
    const folder = state.folders.find(f => f.id == folderId);
    if (!folder) return;
    
    const children = state.folders.filter(f => f.parent_id == folderId);
    
    let message = `Permanently delete "${folder.name}"? This cannot be undone.`;
    if (children.length > 0) {
        message = `Permanently delete "${folder.name}" and ${children.length} subfolder${children.length > 1 ? 's' : ''}? This cannot be undone.`;
    }
    
    const confirmed = await showConfirm('Permanent Delete', message, { okText: 'Delete Forever', danger: true });
    if (!confirmed) return;
    
    try {
        const response = await fetch(`/api/folders/${folderId}/permanent`, {
            method: 'DELETE',
        });
        
        if (!response.ok) {
            const data = await response.json();
            showAlert('Error', data.error || 'Failed to delete folder');
            return;
        }
        
        // Remove from local state
        state.folders = state.folders.filter(f => f.id != folderId && f.parent_id != folderId);
        
        showTrashView();
        
    } catch (error) {
        console.error('Error deleting folder:', error);
        showAlert('Error', 'Failed to delete folder');
    }
}
window.permanentlyDeleteFolder = permanentlyDeleteFolder;

async function emptyTrash() {
    const trashedFolders = state.folders.filter(f => f.deleted_at && !f.parent_id);
    if (trashedFolders.length === 0) return;
    
    const message = `Permanently delete ${trashedFolders.length} folder${trashedFolders.length > 1 ? 's' : ''} and all their contents? This cannot be undone.`;
    
    const confirmed = await showConfirm('Empty Trash', message, { okText: 'Empty Trash', danger: true });
    if (!confirmed) return;
    
    try {
        const response = await fetch('/api/trash/empty', {
            method: 'POST',
        });
        
        if (!response.ok) {
            const data = await response.json();
            showAlert('Error', data.error || 'Failed to empty trash');
            return;
        }
        
        // Remove all trashed folders from state
        state.folders = state.folders.filter(f => !f.deleted_at);
        
        showTrashView();
        
    } catch (error) {
        console.error('Error emptying trash:', error);
        showAlert('Error', 'Failed to empty trash');
    }
}
window.emptyTrash = emptyTrash;

function updateTrashBadge() {
    const badge = document.getElementById('trashBadge');
    if (!badge) return;
    
    const trashedCount = state.folders.filter(f => f.deleted_at && !f.parent_id).length;
    badge.textContent = trashedCount;
    badge.classList.toggle('hidden', trashedCount === 0);
}
