/**
 * MailRepo - Email List Component
 * 
 * Handles rendering and interaction with the email list.
 */

import { escapeHtml, extractName, formatDate } from '../utils.js';
import { state } from '../state.js';

// Reference to DOM elements (set via init)
let emailListEl = null;

/**
 * Parse a date value to milliseconds since epoch.
 * Handles RFC 2822 strings, ISO 8601 strings, and Unix timestamps (seconds).
 */
function parseDateToMs(val) {
    if (!val) return 0;
    const num = Number(val);
    // Unix timestamp in seconds (year 2000-3000 range)
    if (!isNaN(num) && num > 946684800 && num < 32503680000) {
        return num * 1000;
    }
    return new Date(val).getTime() || 0;
}
let onSelectionChange = null;
let onFilterChange = null;

// Filter state
let emailFilter = '';

// Sort state
let currentSort = 'date-desc';  // date-desc, date-asc, sender-asc, sender-desc, subject-asc, subject-desc

// Archive selection state (separate from staging selection)
let selectedArchivedEmails = new Set();

/**
 * Initialize the email list component.
 * @param {Object} config
 * @param {HTMLElement} config.emailList - Email list container
 * @param {Function} config.onSelectionChange - Callback when selection changes
 * @param {Function} config.onFilterChange - Callback when filter changes (receives filteredCount, totalCount)
 */
export function initEmailList(config) {
    emailListEl = config.emailList;
    onSelectionChange = config.onSelectionChange;
    onFilterChange = config.onFilterChange;
}

/**
 * Clear the email filter (called when switching views).
 */
export function clearEmailFilter() {
    emailFilter = '';
}

/**
 * Get filtered emails based on current filter.
 */
function getFilteredEmails() {
    let emails = state.emails;
    
    if (emailFilter) {
        const query = emailFilter.toLowerCase();
        emails = emails.filter(email => {
            const sender = (email.from || email.sender || '').toLowerCase();
            const subject = (email.subject || '').toLowerCase();
            return sender.includes(query) || subject.includes(query);
        });
    }
    
    return sortEmails(emails);
}

/**
 * Sort emails based on current sort setting.
 */
function sortEmails(emails) {
    const sorted = [...emails];
    const [field, direction] = currentSort.split('-');
    const mul = direction === 'asc' ? 1 : -1;
    
    sorted.sort((a, b) => {
        let valA, valB;
        if (field === 'date') {
            // Parse date strings to timestamps for proper chronological sorting
            // Handles RFC 2822, ISO 8601, and Unix timestamps (seconds)
            valA = parseDateToMs(a.date || a.internal_date || '');
            valB = parseDateToMs(b.date || b.internal_date || '');
        } else if (field === 'sender') {
            valA = (a.from || a.sender || '').toLowerCase();
            valB = (b.from || b.sender || '').toLowerCase();
        } else if (field === 'subject') {
            valA = (a.subject || '').toLowerCase();
            valB = (b.subject || '').toLowerCase();
        }
        if (valA < valB) return -1 * mul;
        if (valA > valB) return 1 * mul;
        return 0;
    });
    
    return sorted;
}

/**
 * Render the sort select dropdown.
 */
function renderSortSelect() {
    const labels = {
        'date-desc': 'Newest first',
        'date-asc': 'Oldest first',
        'sender-asc': 'Sender A–Z',
        'sender-desc': 'Sender Z–A',
        'subject-asc': 'Subject A–Z',
        'subject-desc': 'Subject Z–A',
    };
    const options = Object.entries(labels);
    const currentLabel = labels[currentSort] || 'Sort';
    
    const optionsHtml = options.map(([value, label]) => 
        `<div class="sort-option ${currentSort === value ? 'selected' : ''}" data-value="${value}">${label}</div>`
    ).join('');
    
    return `
        <div class="sort-dropdown-wrapper">
            <button class="btn btn-icon sort-btn" onclick="toggleSortDropdown(event)" title="Sort: ${currentLabel}">
                <i data-lucide="arrow-up-down"></i>
            </button>
            <div class="sort-dropdown" id="sortDropdown">
                ${optionsHtml}
            </div>
        </div>
    `;
}

/**
 * Change sort order and re-render.
 */
function changeEmailSort(value) {
    currentSort = value;
    renderEmailList();
}
window.changeEmailSort = changeEmailSort;

function toggleSortDropdown(e) {
    e.stopPropagation();
    const dropdown = document.getElementById('sortDropdown');
    if (!dropdown) return;
    dropdown.classList.toggle('open');
    
    // Close on outside click
    if (dropdown.classList.contains('open')) {
        const close = (ev) => {
            dropdown.classList.remove('open');
            document.removeEventListener('click', close);
        };
        setTimeout(() => document.addEventListener('click', close), 0);
        
        // Attach option click handlers
        dropdown.querySelectorAll('.sort-option').forEach(opt => {
            opt.onclick = (ev) => {
                ev.stopPropagation();
                changeEmailSort(opt.dataset.value);
                dropdown.classList.remove('open');
                document.removeEventListener('click', close);
            };
        });
    }
}
window.toggleSortDropdown = toggleSortDropdown;

/**
 * Render the email list.
 */
export function renderEmailList() {
    if (!emailListEl) return;
    
    const isArchiveView = state.currentView?.type === 'folder';
    
    // Detect if we're viewing a "Sent" folder on IMAP (show recipient instead of sender)
    // Only applies to IMAP views, not archive folders
    const folderName = state.currentView?.type === 'account' ? (state.currentView?.folder || '') : '';
    const isSentFolder = /^sent|sent\s*mail|sent\s*items$/i.test(folderName) || 
                         folderName.toLowerCase().includes('[gmail]/sent');
    
    if (state.emails.length === 0) {
        emailListEl.innerHTML = `
            <div class="empty-state">
                <i data-lucide="mail-x" class="empty-icon"></i>
                <h3>No Emails</h3>
                <p>This folder is empty.</p>
            </div>
        `;
        if (typeof lucide !== 'undefined') lucide.createIcons();
        if (onFilterChange) onFilterChange(0, 0);
        return;
    }
    
    const filteredEmails = getFilteredEmails();
    const selectedCount = state.selectedEmails.size;
    const archiveSelectedCount = selectedArchivedEmails.size;
    
    // Notify about filter/selection state
    if (onFilterChange) {
        onFilterChange(filteredEmails.length, state.emails.length, isArchiveView ? archiveSelectedCount : 0);
    }
    
    // Build table-style layout
    let html = `<div class="folder-management-list">`;
    
    if (isArchiveView) {
        // Archive view - filter + selection buttons
        const archiveSelectedCount = selectedArchivedEmails.size;
        html += `
            <div class="email-list-toolbar">
                <div class="toolbar-left">
                    <div class="email-filter">
                        <i data-lucide="search" class="search-icon"></i>
                        <input type="text" 
                               id="emailFilterInput" 
                               placeholder="Filter by sender or subject..." 
                               value="${escapeHtml(emailFilter)}"
                               oninput="handleEmailFilter(this.value)">
                        ${emailFilter ? '<button class="search-clear" onclick="clearEmailFilterInput()"><i data-lucide="x"></i></button>' : ''}
                    </div>
                    ${renderSortSelect()}
                </div>
                <div class="toolbar-actions">
                    <button class="btn btn-secondary btn-icon-only" onclick="selectAllArchivedEmails()" title="Select all">
                        <i data-lucide="check-square"></i>
                    </button>
                    <button class="btn btn-secondary btn-icon-only" onclick="clearSelectedArchivedEmails()" ${archiveSelectedCount === 0 ? 'disabled' : ''} title="Clear selection">
                        <i data-lucide="x"></i>
                    </button>
                    <button class="btn btn-secondary btn-icon-only" onclick="moveSelectedArchivedEmails()" ${archiveSelectedCount === 0 ? 'disabled' : ''} title="Move selected emails">
                        <i data-lucide="folder-input"></i>
                    </button>
                    <button class="btn btn-secondary btn-icon-only" onclick="exportSelectedArchivedEmails()" ${archiveSelectedCount === 0 ? 'disabled' : ''} title="Export selected emails as PDF">
                        <i data-lucide="download"></i>
                    </button>
                    <button class="btn btn-danger btn-icon-only" onclick="deleteSelectedArchivedEmails()" ${archiveSelectedCount === 0 ? 'disabled' : ''} title="Move to Trash">
                        <i data-lucide="trash-2"></i>
                    </button>
                </div>
            </div>
            <div class="folder-management-header email-list-header">
                <span>Email</span>
                <span>Actions</span>
            </div>
        `;
    } else {
        // IMAP/Import view - staging toolbar
        html += `
            <div class="email-list-toolbar">
                <div class="toolbar-left">
                    <div class="email-filter">
                        <i data-lucide="search" class="search-icon"></i>
                        <input type="text" 
                               id="emailFilterInput" 
                               placeholder="Filter by sender or subject..." 
                               value="${escapeHtml(emailFilter)}"
                               oninput="handleEmailFilter(this.value)">
                        ${emailFilter ? '<button class="search-clear" onclick="clearEmailFilterInput()"><i data-lucide="x"></i></button>' : ''}
                    </div>
                    ${renderSortSelect()}
                </div>
                <div class="toolbar-actions">
                    ${state.currentView?.type === 'account' ? `
                    <button class="btn btn-secondary btn-icon-only" onclick="refreshImapFolder()" title="Refresh folder">
                        <i data-lucide="refresh-cw"></i>
                    </button>
                    ` : ''}
                    <button class="btn btn-secondary" onclick="selectAllEmails()">
                        <i data-lucide="check-square"></i>
                        All
                    </button>
                    <button class="btn btn-secondary" onclick="clearSelectedEmails()" ${selectedCount === 0 ? 'disabled' : ''}>
                        <i data-lucide="x"></i>
                        Clear
                    </button>
                    <button class="btn btn-primary" id="stageSelectedEmailsBtn" onclick="openStageModalForSelected()" ${selectedCount === 0 ? 'disabled' : ''}>
                        <i data-lucide="archive"></i>
                        Stage${selectedCount > 0 ? ` (${selectedCount})` : ''}
                    </button>
                </div>
            </div>
            <div class="folder-management-header email-list-header">
                <span>Email</span>
                <span>Actions</span>
            </div>
        `;
    }
    
    if (filteredEmails.length === 0) {
        html += `
            <div class="empty-state" style="padding: var(--space-xl);">
                <p>No emails match "${escapeHtml(emailFilter)}"</p>
            </div>
        `;
    } else {
        html += filteredEmails.map(email => {
        const emailId = email.uid || email.id;
        const isStaged = state.staged.has(emailId);
        const isSelected = state.selectedEmails.has(emailId);
        const isArchivedSelected = selectedArchivedEmails.has(emailId);
        
        let rowClass = 'folder-management-item email-list-item';
        if (isArchiveView) {
            if (isArchivedSelected) rowClass += ' selected';
        } else {
            if (isStaged) rowClass += ' staged';
            if (isSelected) rowClass += ' selected';
        }
        
        // Determine which action buttons to show
        let actionsHtml = '';
        if (isArchiveView) {
            // Archive view - select/deselect buttons (same pattern as staging)
            if (isArchivedSelected) {
                actionsHtml = `
                    <button class="btn btn-sm btn-icon btn-selected" disabled title="Selected">
                        <i data-lucide="check"></i>
                    </button>
                    <button class="btn btn-sm btn-icon" onclick="event.stopPropagation(); toggleArchivedEmailSelection(${emailId})" title="Deselect">
                        <i data-lucide="x"></i>
                    </button>
                `;
            } else {
                actionsHtml = `
                    <button class="btn btn-sm btn-icon" onclick="event.stopPropagation(); toggleArchivedEmailSelection(${emailId})" title="Select">
                        <i data-lucide="circle"></i>
                    </button>
                    <button class="btn btn-sm btn-icon" disabled title="Not selected">
                        <i data-lucide="x"></i>
                    </button>
                `;
            }
        } else if (isStaged) {
            actionsHtml = `
                <button class="btn btn-sm btn-icon" disabled title="Already staged">
                    <i data-lucide="circle"></i>
                </button>
                <button class="btn btn-sm btn-icon" onclick="event.stopPropagation(); clearEmail('${emailId}')" title="Unstage">
                    <i data-lucide="x"></i>
                </button>
            `;
        } else if (isSelected) {
            actionsHtml = `
                <button class="btn btn-sm btn-icon btn-selected" disabled title="Selected">
                    <i data-lucide="check"></i>
                </button>
                <button class="btn btn-sm btn-icon" onclick="event.stopPropagation(); clearEmail('${emailId}')" title="Deselect">
                    <i data-lucide="x"></i>
                </button>
            `;
        } else {
            actionsHtml = `
                <button class="btn btn-sm btn-icon" onclick="event.stopPropagation(); selectEmail('${emailId}')" title="Select">
                    <i data-lucide="circle"></i>
                </button>
                <button class="btn btn-sm btn-icon" disabled title="Not selected">
                    <i data-lucide="x"></i>
                </button>
            `;
        }
        
        return `
            <div class="${rowClass}" data-id="${emailId}" onclick="openEmailViewer('${emailId}')">
                <div class="email-list-content">
                    <div class="email-list-main">
                        <div class="email-list-header-row">
                            <span class="email-sender">${isSentFolder ? 'To: ' : ''}${escapeHtml(extractName(isSentFolder ? (email.to || email.recipients) : (email.from || email.sender)))}</span>
                            <span class="email-date">${formatDate(email.date)}</span>
                        </div>
                        <span class="email-subject">${escapeHtml(email.subject || '(no subject)')}</span>
                    </div>
                </div>
                <div class="folder-management-actions" onclick="event.stopPropagation()">${actionsHtml}</div>
            </div>
        `;
        }).join('');
    }
    
    html += `</div>`;
    
    emailListEl.innerHTML = html;
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

/**
 * Select an email.
 */
export function selectEmail(emailId) {
    if (state.staged.has(emailId)) return;
    state.selectedEmails.add(emailId);
    renderEmailList();
    if (onSelectionChange) onSelectionChange();
}
window.selectEmail = selectEmail;

/**
 * Clear an email - deselects if selected, unstages if staged.
 */
export function clearEmail(emailId) {
    if (state.selectedEmails.has(emailId)) {
        state.selectedEmails.delete(emailId);
        renderEmailList();
        if (onSelectionChange) onSelectionChange();
        return;
    }
    
    if (state.staged.has(emailId)) {
        state.staged.delete(emailId);
        sessionStorage.setItem('staged', JSON.stringify([...state.staged.entries()]));
        renderEmailList();
        if (onSelectionChange) onSelectionChange();
        // Update staged badge
        import('./staging.js').then(m => m.updateStagedBadge());
    }
}
window.clearEmail = clearEmail;

/**
 * Select all unstaged emails.
 */
export function selectAllEmails() {
    state.emails.forEach(email => {
        const emailId = email.uid || email.id;
        if (!state.staged.has(emailId)) {
            state.selectedEmails.add(emailId);
        }
    });
    renderEmailList();
    if (onSelectionChange) onSelectionChange();
}
window.selectAllEmails = selectAllEmails;

/**
 * Clear all selected emails.
 */
export function clearSelectedEmails() {
    state.selectedEmails.clear();
    renderEmailList();
    if (onSelectionChange) onSelectionChange();
}
window.clearSelectedEmails = clearSelectedEmails;

/**
 * Open stage modal for selected emails.
 */
export function openStageModalForSelected() {
    if (state.selectedEmails.size === 0) return;
    import('./staging.js').then(m => m.openStageModal());
}
window.openStageModalForSelected = openStageModalForSelected;

/**
 * Update toolbar button states.
 */
export function updateToolbarButtons() {
    const selectAllBtn = document.getElementById('selectAllEmailsBtn');
    const clearSelectedBtn = document.getElementById('clearSelectedEmailsBtn');
    
    const hasSelected = state.selectedEmails.size > 0;
    
    if (clearSelectedBtn) {
        clearSelectedBtn.disabled = !hasSelected;
    }
}

// Legacy function for backward compatibility
export function toggleEmailSelection(emailId) {
    if (state.staged.has(emailId)) return;
    
    if (state.selectedEmails.has(emailId)) {
        state.selectedEmails.delete(emailId);
    } else {
        state.selectedEmails.add(emailId);
    }
    
    renderEmailList();
    if (onSelectionChange) onSelectionChange();
}
window.toggleEmailSelection = toggleEmailSelection;

// Legacy - keep for compatibility but no longer used
export function handleSelectAll(e) {
    if (e.target.checked) {
        selectAllEmails();
    } else {
        clearSelectedEmails();
    }
}

export function updateSelectAllState() {
    updateToolbarButtons();
}

/**
 * Handle email filter input.
 */
function handleEmailFilter(query) {
    emailFilter = query;
    renderEmailList();
    // Refocus the input and restore cursor position
    const input = document.getElementById('emailFilterInput');
    if (input) {
        input.focus();
        input.setSelectionRange(query.length, query.length);
    }
}
window.handleEmailFilter = handleEmailFilter;

/**
 * Clear email filter.
 */
function clearEmailFilterInput() {
    emailFilter = '';
    renderEmailList();
    const input = document.getElementById('emailFilterInput');
    if (input) input.focus();
}
window.clearEmailFilterInput = clearEmailFilterInput;

/**
 * Delete an archived email (move to trash).
 */
async function deleteArchivedEmail(emailId) {
    const email = state.emails.find(e => e.id == emailId);
    if (!email) return;
    
    const { showConfirm, showAlert } = await import('../modals.js');
    const confirmed = await showConfirm('Delete Email', `Move "${email.subject || '(no subject)'}" to trash?`, { okText: 'Move to Trash' });
    if (!confirmed) return;
    
    try {
        const response = await fetch(`/api/messages/${emailId}`, { method: 'DELETE' });
        if (!response.ok) {
            const data = await response.json();
            showAlert('Error', data.error || 'Failed to delete email');
            return;
        }
        
        // Remove from state and re-render
        state.emails = state.emails.filter(e => e.id != emailId);
        renderEmailList();
        
        // Update trash badge
        const { updateTrashBadge } = await import('../views/trash.js');
        updateTrashBadge();
    } catch (error) {
        console.error('Error deleting email:', error);
        showAlert('Error', 'Failed to delete email');
    }
}
window.deleteArchivedEmail = deleteArchivedEmail;

/**
 * Move an archived email to a different folder.
 */
async function moveArchivedEmail(emailId) {
    const email = state.emails.find(e => e.id == emailId);
    if (!email) return;
    
    // Store the email ID for the move modal
    window.pendingMoveEmailIds = [emailId];
    
    // Open the move email modal
    const modal = document.getElementById('moveEmailModal');
    if (modal) {
        // Render folder tree in modal
        const { renderMoveEmailFolderTree } = await import('./move-email-modal.js');
        renderMoveEmailFolderTree();
        modal.classList.add('active');
    }
}
window.moveArchivedEmail = moveArchivedEmail;

/**
 * Toggle selection of an archived email.
 */
function toggleArchivedEmailSelection(emailId) {
    if (selectedArchivedEmails.has(emailId)) {
        selectedArchivedEmails.delete(emailId);
    } else {
        selectedArchivedEmails.add(emailId);
    }
    renderEmailList();
}
window.toggleArchivedEmailSelection = toggleArchivedEmailSelection;

/**
 * Select all archived emails.
 */
function selectAllArchivedEmails() {
    const filteredEmails = getFilteredEmails();
    filteredEmails.forEach(email => {
        selectedArchivedEmails.add(email.id);
    });
    renderEmailList();
}
window.selectAllArchivedEmails = selectAllArchivedEmails;

/**
 * Clear all archived email selections.
 */
function clearSelectedArchivedEmails() {
    selectedArchivedEmails.clear();
    renderEmailList();
}
window.clearSelectedArchivedEmails = clearSelectedArchivedEmails;

/**
 * Clear archived selection when switching views.
 */
export function clearArchivedEmailSelection() {
    selectedArchivedEmails.clear();
}

/**
 * Move selected archived emails.
 */
async function moveSelectedArchivedEmails() {
    if (selectedArchivedEmails.size === 0) return;
    
    // Store the email IDs for the move modal
    window.pendingMoveEmailIds = Array.from(selectedArchivedEmails);
    
    // Open the move email modal
    const modal = document.getElementById('moveEmailModal');
    if (modal) {
        const { renderMoveEmailFolderTree } = await import('./move-email-modal.js');
        renderMoveEmailFolderTree();
        modal.classList.add('active');
    }
}
window.moveSelectedArchivedEmails = moveSelectedArchivedEmails;

/**
 * Delete selected archived emails.
 */
async function deleteSelectedArchivedEmails() {
    if (selectedArchivedEmails.size === 0) return;
    
    const count = selectedArchivedEmails.size;
    const { showConfirm, showAlert } = await import('../modals.js');
    const confirmed = await showConfirm(
        'Delete Emails',
        `Move ${count} email${count > 1 ? 's' : ''} to trash?`,
        { okText: 'Move to Trash' }
    );
    if (!confirmed) return;
    
    try {
        const ids = Array.from(selectedArchivedEmails);
        for (const emailId of ids) {
            const response = await fetch(`/api/messages/${emailId}`, { method: 'DELETE' });
            if (!response.ok) {
                console.error(`Failed to delete email ${emailId}`);
            }
        }
        
        // Remove from state and clear selection
        state.emails = state.emails.filter(e => !selectedArchivedEmails.has(e.id));
        selectedArchivedEmails.clear();
        renderEmailList();
        
        // Update trash badge
        const { updateTrashBadge } = await import('../views/trash.js');
        updateTrashBadge();
    } catch (error) {
        console.error('Error deleting emails:', error);
        showAlert('Error', 'Failed to delete some emails');
    }
}
window.deleteSelectedArchivedEmails = deleteSelectedArchivedEmails;

/**
 * Export selected archived emails via the bulk-export modal (Phase 2).
 *
 * Builds a human-readable scope label that names the current folder when
 * we\'re in a folder view, so the cover page tells the recipient where
 * these emails came from.
 */
function exportSelectedArchivedEmails() {
    if (selectedArchivedEmails.size === 0) return;
    const ids = Array.from(selectedArchivedEmails);

    // Try to name the source folder (we\'re always in an archive folder
    // view when this button is clickable, but be defensive).
    let label = `${ids.length} selected email${ids.length === 1 ? '' : 's'}`;
    if (state.currentView?.type === 'folder') {
        const folder = (state.folders || []).find(f => String(f.id) === String(state.currentView.id));
        if (folder?.name) {
            label = `${ids.length} email${ids.length === 1 ? '' : 's'} from ${folder.name}`;
        }
    }

    const opts = {
        source: 'messages',
        message_ids: ids,
        label,
    };
    if (typeof window.openExportModal === 'function') {
        window.openExportModal(opts);
    } else {
        // Lazy-load on first use \u2014 same pattern as context-menu.js.
        // The module registers window.openExportModal on import.
        import('./export-modal.js').then((m) => {
            (m.openExportModal || window.openExportModal)?.(opts);
        }).catch((err) => {
            console.error('Failed to load export modal:', err);
        });
    }
}
window.exportSelectedArchivedEmails = exportSelectedArchivedEmails;
