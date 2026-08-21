/**
 * MailRepo - Email List Component
 * 
 * Handles rendering and interaction with the email list.
 */

import { escapeHtml, extractName, formatDate } from '../utils.js';
import { state } from '../state.js';
import { bindActions } from '../delegate.js';

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

/**
 * Extract the four-digit year from an email's date.
 * Returns null if the date is missing or unparseable, so callers can
 * skip dividers for rows we can't place on a timeline.
 */
function getEmailYear(email) {
    const ms = parseDateToMs(email.date || email.internal_date || '');
    if (!ms) return null;
    const year = new Date(ms).getFullYear();
    return isNaN(year) ? null : year;
}
let onSelectionChange = null;
let onFilterChange = null;
let onOpenEmail = null;
let onRefresh = null;

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
    // Cross-module callbacks: opening an email and refreshing an IMAP
    // folder live in mail.js. App.js wires them up here so this component
    // can dispatch through the config rather than reaching for window.X.
    onOpenEmail = config.onOpenEmail;
    onRefresh = config.onRefresh;
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
            <button class="btn btn-icon sort-btn" data-action="toggleSort" title="Sort: ${currentLabel}">
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
        // An archive folder whose mail is all filed in subfolders is not
        // empty, and the subfolder links above say where it went.
        const nested = isArchiveView ? (state.nestedEmailCount || 0) : 0;
        emailListEl.innerHTML = `
            <div class="empty-state">
                <i data-lucide="mail-x" class="empty-icon"></i>
                <h3>No Emails</h3>
                <p>${nested > 0
                    ? 'No emails here — they are in the subfolders above.'
                    : 'This folder is empty.'}</p>
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
    let html = `<div class="folder-management-list email-list-root">`;
    
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
                               data-input="emailFilter">
                        ${emailFilter ? '<button class="search-clear" data-action="clearFilter"><i data-lucide="x"></i></button>' : ''}
                    </div>
                    ${renderSortSelect()}
                </div>
                <div class="toolbar-actions">
                    <button class="btn btn-secondary btn-icon-only" data-action="selectAllArchived" title="Select all">
                        <i data-lucide="check-square"></i>
                    </button>
                    <button class="btn btn-secondary btn-icon-only" data-action="clearArchived" ${archiveSelectedCount === 0 ? 'disabled' : ''} title="Clear selection">
                        <i data-lucide="x"></i>
                    </button>
                    <button class="btn btn-secondary btn-icon-only" data-action="moveArchived" ${archiveSelectedCount === 0 ? 'disabled' : ''} title="Move selected emails">
                        <i data-lucide="folder-input"></i>
                    </button>
                    <button class="btn btn-secondary btn-icon-only" data-action="exportArchived" ${archiveSelectedCount === 0 ? 'disabled' : ''} title="Export selected emails as PDF">
                        <i data-lucide="download"></i>
                    </button>
                    <button class="btn btn-danger btn-icon-only" data-action="deleteArchived" ${archiveSelectedCount === 0 ? 'disabled' : ''} title="Move to Trash">
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
                               data-input="emailFilter">
                        ${emailFilter ? '<button class="search-clear" data-action="clearFilter"><i data-lucide="x"></i></button>' : ''}
                    </div>
                    ${renderSortSelect()}
                </div>
                <div class="toolbar-actions">
                    ${state.currentView?.type === 'account' ? `
                    <button class="btn btn-secondary btn-icon-only" data-action="refresh" title="Refresh folder">
                        <i data-lucide="refresh-cw"></i>
                    </button>
                    ` : ''}
                    <button class="btn btn-secondary" data-action="selectAll">
                        <i data-lucide="check-square"></i>
                        All
                    </button>
                    <button class="btn btn-secondary" data-action="clearSelected" ${selectedCount === 0 ? 'disabled' : ''}>
                        <i data-lucide="x"></i>
                        Clear
                    </button>
                    <button class="btn btn-primary" id="stageSelectedEmailsBtn" data-action="openStage" ${selectedCount === 0 ? 'disabled' : ''}>
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
        // Year dividers: a labelled rule between rows when the year
        // changes. Only shown in the archive folder view, only when
        // sorted by date (the grouping is meaningless under sender/
        // subject sorts), and only when the folder actually spans more
        // than one year (a divider for a single year is just noise).
        const sortedByDate = currentSort.startsWith('date');
        const distinctYears = new Set(
            filteredEmails.map(getEmailYear).filter(y => y !== null)
        );
        const showYearDividers = isArchiveView && sortedByDate && distinctYears.size > 1;

        let lastYear = null;

        html += filteredEmails.map(email => {
        const emailId = email.uid || email.id;
        const isStaged = state.staged.has(emailId);
        const isSelected = state.selectedEmails.has(emailId);
        const isArchivedSelected = selectedArchivedEmails.has(emailId);

        // Emit a year divider before this row if the year just changed.
        let dividerHtml = '';
        if (showYearDividers) {
            const year = getEmailYear(email);
            if (year !== null && year !== lastYear) {
                dividerHtml = `<div class="email-year-divider"><span>${year}</span></div>`;
                lastYear = year;
            }
        }
        
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
                    <button class="btn btn-sm btn-icon" data-action="toggleArchSel" data-email-id="${emailId}" title="Deselect">
                        <i data-lucide="x"></i>
                    </button>
                `;
            } else {
                actionsHtml = `
                    <button class="btn btn-sm btn-icon" data-action="toggleArchSel" data-email-id="${emailId}" title="Select">
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
                <button class="btn btn-sm btn-icon" data-action="clearOne" data-email-id="${emailId}" title="Unstage">
                    <i data-lucide="x"></i>
                </button>
            `;
        } else if (isSelected) {
            actionsHtml = `
                <button class="btn btn-sm btn-icon btn-selected" disabled title="Selected">
                    <i data-lucide="check"></i>
                </button>
                <button class="btn btn-sm btn-icon" data-action="clearOne" data-email-id="${emailId}" title="Deselect">
                    <i data-lucide="x"></i>
                </button>
            `;
        } else {
            actionsHtml = `
                <button class="btn btn-sm btn-icon" data-action="selectOne" data-email-id="${emailId}" title="Select">
                    <i data-lucide="circle"></i>
                </button>
                <button class="btn btn-sm btn-icon" disabled title="Not selected">
                    <i data-lucide="x"></i>
                </button>
            `;
        }
        
        return `
            ${dividerHtml}
            <div class="${rowClass}" data-id="${emailId}" data-action="openEmail" data-email-id="${emailId}">
                <div class="email-list-content">
                    <div class="email-list-main">
                        <div class="email-list-header-row">
                            <span class="email-sender">${isSentFolder ? 'To: ' : ''}${escapeHtml(extractName(isSentFolder ? (email.to || email.recipients) : (email.from || email.sender)))}</span>
                            <span class="email-list-meta">
                                ${email.flagged_at ? '<i data-lucide="star" class="email-list-star"></i>' : ''}
                                <span class="email-date">${formatDate(email.date)}</span>
                            </span>
                        </div>
                        <span class="email-subject">${escapeHtml(email.subject || '(no subject)')}</span>
                    </div>
                </div>
                <div class="folder-management-actions">${actionsHtml}</div>
            </div>
        `;
        }).join('');
    }
    
    html += `</div>`;
    
    emailListEl.innerHTML = html;
    if (typeof lucide !== 'undefined') lucide.createIcons();

    // Bind delegated handlers on the email-list-specific root. Listener
    // dies with the view when another view's render replaces emailListEl.
    // See delegate.js docs.
    const root = emailListEl.querySelector('.email-list-root');
    if (root) {
        bindActions(root, {
            // Toolbar (shared archive + account paths)
            toggleSort:        (el, ev) => toggleSortDropdown(ev),
            clearFilter:       () => clearEmailFilterInput(),
            emailFilter:       (el) => handleEmailFilter(el.value),
            // Archive-view toolbar
            selectAllArchived: () => selectAllArchivedEmails(),
            clearArchived:     () => clearSelectedArchivedEmails(),
            moveArchived:      () => moveSelectedArchivedEmails(),
            exportArchived:    () => exportSelectedArchivedEmails(),
            deleteArchived:    () => deleteSelectedArchivedEmails(),
            // Account-view toolbar
            refresh:           () => onRefresh && onRefresh(),
            selectAll:         () => selectAllEmails(),
            clearSelected:     () => clearSelectedEmails(),
            openStage:         () => openStageModalForSelected(),
            // Row-level action buttons
            toggleArchSel:     (el) => toggleArchivedEmailSelection(Number(el.dataset.emailId)),
            clearOne:          (el) => clearEmail(el.dataset.emailId),
            selectOne:         (el) => selectEmail(el.dataset.emailId),
            // Row click -> open email viewer
            openEmail:         (el, ev) => {
                // Skip if click was inside the actions wrapper (replaces the
                // legacy onclick='event.stopPropagation()' on the actions div).
                if (ev.target.closest('.folder-management-actions')) return;
                if (onOpenEmail) onOpenEmail(el.dataset.emailId);
            },
        }, ['click', 'input']);
    }
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

/**
 * Clear all selected emails.
 */
export function clearSelectedEmails() {
    state.selectedEmails.clear();
    renderEmailList();
    if (onSelectionChange) onSelectionChange();
}

/**
 * Open stage modal for selected emails.
 */
export function openStageModalForSelected() {
    if (state.selectedEmails.size === 0) return;
    import('./staging.js').then(m => m.openStageModal());
}

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

/**
 * Clear email filter.
 */
function clearEmailFilterInput() {
    emailFilter = '';
    renderEmailList();
    const input = document.getElementById('emailFilterInput');
    if (input) input.focus();
}

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

/**
 * Move an archived email to a different folder.
 */
async function moveArchivedEmail(emailId) {
    const email = state.emails.find(e => e.id == emailId);
    if (!email) return;
    
    // Store the email ID for the move modal
    const { setPendingMoveEmailIds } = await import('./move-email-modal.js');
    setPendingMoveEmailIds([emailId]);
    
    // Open the move email modal
    const modal = document.getElementById('moveEmailModal');
    if (modal) {
        // Render folder tree in modal
        const { renderMoveEmailFolderTree } = await import('./move-email-modal.js');
        renderMoveEmailFolderTree();
        modal.classList.add('active');
    }
}

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

/**
 * Clear all archived email selections.
 */
function clearSelectedArchivedEmails() {
    selectedArchivedEmails.clear();
    renderEmailList();
}

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
    const { setPendingMoveEmailIds } = await import('./move-email-modal.js');
    setPendingMoveEmailIds(Array.from(selectedArchivedEmails));
    
    // Open the move email modal
    const modal = document.getElementById('moveEmailModal');
    if (modal) {
        const { renderMoveEmailFolderTree } = await import('./move-email-modal.js');
        renderMoveEmailFolderTree();
        modal.classList.add('active');
    }
}

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
    // Export modal is lazily loaded -- the module is ~865 lines and
    // most users go a long time between exports, so it doesn't earn
    // its bytes at app startup.
    import('./export-modal.js').then((m) => {
        m.openExportModal(opts);
    }).catch((err) => {
        console.error('Failed to load export modal:', err);
    });
}
