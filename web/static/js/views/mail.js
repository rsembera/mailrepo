/**
 * MailRepo - Mail View Component
 * 
 * Handles:
 * - Loading emails from IMAP accounts
 * - Loading emails from archive folders
 * - Email viewer (reading full emails)
 * - View state management
 */

import { escapeHtml, escapeForOnclick } from '../utils.js';
import { state } from '../state.js';
import { renderEmailList, clearEmailFilter, clearArchivedEmailSelection } from '../components/email-list.js';

// DOM element references
let contextTitle = null;
let contextMeta = null;
let emailList = null;

// Current email viewer context (for download/print functions)
let currentViewerContext = null;

/**
 * Show or hide the "Stage thread to..." button based on the viewer context.
 * The button only makes sense for live IMAP mail (context.type === 'account').
 * Archived folder views and import previews don't have an IMAP UID to
 * thread from, so the button is hidden.
 */
function _updateStageThreadButton(context) {
    const btn = document.getElementById('stageThreadBtn');
    if (!btn) return;
    const showIt = context && context.type === 'account'
        && context.accountId && context.folder && context.uid;
    btn.style.display = showIt ? '' : 'none';
}

/**
 * Show, hide, and enable/disable the prev/next buttons based on context.
 * Visible only when viewing an archived email (context.type === 'folder').
 * Hidden for search-result, live IMAP, and import contexts — those are
 * either result sets users don\'t browse sequentially, or live mail
 * which the user said doesn\'t need this.
 *
 * When visible, the buttons are disabled at list boundaries (no wrap-around).
 */
function _updatePrevNextButtons(context) {
    const prevBtn = document.getElementById('viewerPrevBtn');
    const nextBtn = document.getElementById('viewerNextBtn');
    if (!prevBtn || !nextBtn) return;

    const isArchiveFolder = context && context.type === 'folder' && context.messageId;
    if (!isArchiveFolder) {
        prevBtn.style.display = 'none';
        nextBtn.style.display = 'none';
        return;
    }

    prevBtn.style.display = '';
    nextBtn.style.display = '';

    // Find current email's position in state.emails (the list backing
    // the current view). state.emails is sorted by date DESC, so the
    // entry above is newer (prev) and the one below is older (next).
    const emails = state.emails || [];
    const idx = emails.findIndex(e => (e.id == context.messageId));
    prevBtn.disabled = idx <= 0;
    nextBtn.disabled = idx < 0 || idx >= emails.length - 1;
}

/**
 * Show, hide, and reflect the current flagged state of the star button.
 *
 * The star is archive-only (context.type === 'folder'). For live IMAP
 * and import previews the button stays hidden. The icon swaps between
 * empty and filled based on whether the email currently has a
 * flagged_at value.
 *
 * Lucide swaps icons by re-creating from data-lucide, so we re-run
 * lucide.createIcons() after changing it.
 */
function _updateStarButton(context) {
    const btn = document.getElementById('starBtn');
    if (!btn) return;

    const isArchive = context && context.type === 'folder' && context.messageId;
    if (!isArchive) {
        btn.style.display = 'none';
        return;
    }
    btn.style.display = '';

    // Find the email in the current list to read flagged_at. The viewer
    // context doesn't carry flagged_at directly — the source of truth is
    // state.emails (folder list) or the email-data attached during render.
    const emails = state.emails || [];
    const email = emails.find(e => (e.id == context.messageId));
    const isFlagged = !!(email && email.flagged_at);

    // Update icon and tooltip
    const iconHost = btn.querySelector('[data-lucide]');
    if (iconHost) {
        iconHost.setAttribute('data-lucide', 'star');
        if (isFlagged) {
            btn.classList.add('starred');
            btn.title = 'Unstar this email — press s';
        } else {
            btn.classList.remove('starred');
            btn.title = 'Star this email — press s';
        }
    }
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

// Callbacks
let onButtonStatesUpdate = null;

/**
 * Restore default header actions for email list view (Stage Selected only).
 */
export function restoreDefaultHeaderActions() {
    const headerActions = document.querySelector('.header-actions');
    const toolbar = document.querySelector('.content-toolbar');
    const sidebar = document.getElementById('sidebar');
    
    // Show sidebar, hide old toolbar (email list has its own now)
    if (sidebar) sidebar.style.display = '';
    if (toolbar) toolbar.style.display = 'none';
    
    // Clear header actions - email list has its own toolbar now
    if (headerActions) {
        headerActions.innerHTML = '';
    }
}

/**
 * Clear header actions for archive view.
 */
function clearHeaderActions() {
    const headerActions = document.querySelector('.header-actions');
    const toolbar = document.querySelector('.content-toolbar');
    const sidebar = document.getElementById('sidebar');
    
    // Show sidebar, hide old toolbar (email list has its own now)
    if (sidebar) sidebar.style.display = '';
    if (toolbar) toolbar.style.display = 'none';
    
    // Clear buttons (archive view - no staging)
    if (headerActions) {
        headerActions.innerHTML = '';
    }
}

/**
 * Initialize the mail view component.
 * @param {Object} config
 * @param {HTMLElement} config.contextTitle - Title element
 * @param {HTMLElement} config.contextMeta - Meta/subtitle element
 * @param {HTMLElement} config.emailList - Email list container
 * @param {Function} config.onButtonStatesUpdate - Callback to update button states
 */
export function initMailView(config) {
    contextTitle = config.contextTitle;
    contextMeta = config.contextMeta;
    emailList = config.emailList;
    onButtonStatesUpdate = config.onButtonStatesUpdate;
    
    initEmailViewerListeners();
}

/**
 * Select a view and load its emails.
 * @param {Object} view - View descriptor
 * @param {string} view.type - 'account' or 'folder'
 * @param {string|number} view.id - Account or folder ID
 * @param {string} [view.folder] - IMAP folder name (for account type)
 */
export function selectView(view) {
    state.currentView = view;
    state.selectedEmails.clear();
    clearEmailFilter();
    clearArchivedEmailSelection();
    
    if (view.type === 'account') {
        loadAccountEmails(view.id, view.folder);
    } else if (view.type === 'folder') {
        loadFolderEmails(view.id);
    }
    
    if (onButtonStatesUpdate) onButtonStatesUpdate();
}

/**
 * Load emails from an IMAP account folder.
 * Uses streaming for progress updates.
 */
export async function loadAccountEmails(accountId, folder = 'INBOX', { forceRefresh = false } = {}) {
    // Restore default header actions and toolbar
    restoreDefaultHeaderActions();
    
    // Render IMAP breadcrumbs and subfolders
    renderImapNavigation(accountId, folder);
    
    // Show just the folder name in title, not full path
    const folderName = folder.includes('/') ? folder.split('/').pop() : folder;
    if (contextTitle) contextTitle.textContent = folderName;
    if (contextMeta) contextMeta.textContent = 'Loading...';
    
    // Show progress UI
    emailList.innerHTML = `
        <div class="empty-state">
            <div id="loadProgress"></div>
        </div>
    `;
    
    // Dynamically import progress component
    const { createProgress } = await import('../components/progress.js');
    const progressContainer = document.getElementById('loadProgress');
    const progress = createProgress(progressContainer);
    
    // Start streaming - fetch all emails (or use a large limit)
    // The backend can handle large numbers efficiently with streaming
    const streamUrl = `/api/accounts/${accountId}/emails/stream?folder=${encodeURIComponent(folder)}${forceRefresh ? '&refresh=true' : ''}`;
    
    progress.startStream(streamUrl, {
        onComplete: (data) => {
            state.emails = data.emails || [];
            if (contextMeta) contextMeta.textContent = `${state.emails.length} emails`;
            renderEmailList();
        },
        onError: (err) => {
            if (contextTitle) contextTitle.textContent = 'Error';
            if (contextMeta) contextMeta.textContent = '';
            showError(err.error || 'Failed to load emails');
        },
    });
}

/**
 * Load emails from an archive folder.
 */
export async function loadFolderEmails(folderId) {
    // Clear header actions for archive view (no staging needed)
    clearHeaderActions();
    
    if (contextTitle) contextTitle.textContent = 'Loading...';
    if (contextMeta) contextMeta.textContent = '';
    showLoading();
    
    try {
        const response = await fetch(`/api/folders/${folderId}/emails`);
        
        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.error || 'Failed to load emails');
        }
        
        const data = await response.json();
        state.emails = data.emails || [];
        
        const folder = state.folders.find(f => f.id == folderId);
        if (contextTitle) contextTitle.textContent = folder?.name || 'Archive';
        if (contextMeta) contextMeta.textContent = `${state.emails.length} archived emails`;
        
        // Check for subfolders (exclude deleted and retention vault folders)
        const subfolders = state.folders.filter(f => f.parent_id == folderId && !f.deleted_at && !f.retention_date);
        
        // Render subfolders + emails
        renderFolderContents(folderId, subfolders);
        
    } catch (error) {
        console.error('Error loading emails:', error);
        if (contextTitle) contextTitle.textContent = 'Error';
        showError(error.message);
    }
}

/**
 * Show archive search view.
 */
export function showArchiveSearch() {
    // Update view state
    state.currentView = { type: 'search' };
    state.selectedEmails.clear();
    clearArchivedEmailSelection();
    clearEmailFilter();
    
    // Clear header actions
    clearHeaderActions();
    
    // Hide subfolders bar
    const subfoldersBar = document.getElementById('subfoldersBar');
    if (subfoldersBar) {
        subfoldersBar.style.display = 'none';
        subfoldersBar.innerHTML = '';
    }
    
    // Update sidebar selection
    document.querySelectorAll('.tree-item-row').forEach(r => r.classList.remove('active'));
    const searchRow = document.querySelector('.tree-item-row[data-type="search"]');
    if (searchRow) searchRow.classList.add('active');
    
    // Set header
    if (contextTitle) contextTitle.textContent = 'Search Archive';
    if (contextMeta) contextMeta.textContent = 'Search all archived emails';
    
    // Render search interface
    renderSearchView();
}
window.showArchiveSearch = showArchiveSearch;

/**
 * Render the search view interface.
 */
function renderSearchView(results = null, query = '') {
    if (!emailList) return;
    
    const hasQuery = query.length > 0;
    
    // Current scope label (for the scope button)
    const scopeLabel = getSearchScopeLabel();
    
    let html = `
        <div class="folder-management-list search-view">
            <div class="email-list-toolbar">
                <div class="email-filter" style="flex: 1;">
                    <i data-lucide="search" class="search-icon"></i>
                    <input type="text" 
                           id="archiveSearchInput" 
                           placeholder="Search subject, sender, or content…" 
                           value="${escapeHtml(query)}"
                           autocomplete="off">
                </div>
                <div class="toolbar-actions">
                    <button class="btn btn-secondary search-scope-btn" id="searchScopeBtn" onclick="openSearchScopePicker()" title="Choose folder to search in">
                        <i data-lucide="folder"></i>
                        <span class="search-scope-label">${escapeHtml(scopeLabel)}</span>
                        <i data-lucide="chevron-down" class="search-scope-chevron"></i>
                    </button>
                    <button class="btn btn-primary" onclick="executeArchiveSearch()">
                        <i data-lucide="search"></i>
                        Search
                    </button>
                    <button class="btn btn-secondary" onclick="clearArchiveSearch()" ${!hasQuery ? 'disabled' : ''}>
                        <i data-lucide="x"></i>
                        Clear
                    </button>
                    ${(results && results.length > 0) ? `
                        <button class="btn btn-secondary" onclick="exportSearchResults()" title="Export these search results as PDF">
                            <i data-lucide="download"></i>
                            Export…
                        </button>
                    ` : ''}
                </div>
            </div>
    `;
    
    if (results === null) {
        // Build a scope-aware sentence so the helper text matches the active scope.
        const folderId = window._searchFolderId;
        const includeSubs = window._searchIncludeSubfolders !== false;
        let scopeSentence;
        if (!folderId) {
            scopeSentence = 'Type a search term and press Enter (or click Search) to find emails across your entire archive.';
        } else {
            // Use the folder's name (not the full path) for the helper sentence — readable inline.
            const folder = (state.folders || []).find(f => String(f.id) === String(folderId));
            const folderName = folder ? folder.name : 'this folder';
            const where = includeSubs
                ? `${escapeHtml(folderName)} and its subfolders`
                : `${escapeHtml(folderName)} only`;
            scopeSentence = `Type a search term and press Enter (or click Search) to find emails in <strong>${where}</strong>. Use the folder button above to change the scope.`;
        }
        
        // Initial state - show helpful text
        html += `
            <div class="search-help">
                <p>${scopeSentence}</p>
                <p class="search-hint">Searches subject lines, sender/recipient addresses, and email content.</p>
                <details class="search-tips">
                    <summary>Search tips</summary>
                    <table class="search-tips-table">
                        <tr><td><code>ther*</code></td><td>Prefix search — matches "therapy", "therapist", etc.</td></tr>
                        <tr><td><code>"meeting notes"</code></td><td>Exact phrase</td></tr>
                        <tr><td><code>smith AND invoice</code></td><td>Both terms must appear</td></tr>
                        <tr><td><code>smith OR jones</code></td><td>Either term</td></tr>
                        <tr><td><code>invoice NOT receipt</code></td><td>Exclude a term</td></tr>
                        <tr><td><code>subject: invoice</code></td><td>Search subject line only</td></tr>
                        <tr><td><code>sender: smith</code></td><td>Search by sender name</td></tr>
                        <tr><td><code>sender: "smith@gmail.com"</code></td><td>Search by exact email address</td></tr>
                        <tr><td><code>recipients: jones</code></td><td>Search To, CC, and BCC fields</td></tr>
                    </table>
                    <p class="search-hint" style="margin-top: var(--space-sm);">Searches are always case-insensitive.</p>
                </details>
            </div>
        `;
    } else if (results.length === 0) {
        html += `
            <div class="empty-state">
                <i data-lucide="search-x" class="empty-icon"></i>
                <h3>No Results</h3>
                <p>No emails found matching "${escapeHtml(query)}"</p>
            </div>
        `;
    } else {
        results.forEach(email => {
            html += `
                <div class="folder-management-item email-list-item search-result" 
                     onclick="openSearchResult(${email.id}, ${email.folder_id})">
                    <div class="email-list-content">
                        <div class="email-list-main">
                            <div class="email-list-header-row">
                                <span class="email-sender">${escapeHtml(extractName(email.sender))}</span>
                                <span class="email-date">${formatDate(email.date)}</span>
                            </div>
                            <span class="email-subject">${escapeHtml(email.subject || '(no subject)')}</span>
                            <span class="email-folder-path">${escapeHtml(email.folder_path)}</span>
                        </div>
                    </div>
                </div>
            `;
        });
    }
    
    html += `</div>`;
    
    // Capture pre-render focus state so re-renders don't yank focus from the
    // search input (which would otherwise stop Enter from working until the
    // user clicked back into the field).
    const oldInput = document.getElementById('archiveSearchInput');
    const hadFocus = oldInput && document.activeElement === oldInput;
    const caretPos = hadFocus ? oldInput.selectionStart : null;
    
    emailList.innerHTML = html;
    if (typeof lucide !== 'undefined') lucide.createIcons();
    
    const input = document.getElementById('archiveSearchInput');
    if (input) {
        // Attach a real listener so Enter triggers a search reliably,
        // even after the input has been re-emitted into the DOM.
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                executeArchiveSearch();
            }
        });
        
        if (hadFocus) {
            input.focus();
            // Put the caret back where it was, or at the end if we don't know.
            const pos = caretPos != null ? caretPos : input.value.length;
            try { input.setSelectionRange(pos, pos); } catch (_) { /* ignore */ }
        } else if (!query) {
            input.focus();
        }
    }
}

/**
 * Get the human-readable label for the current search scope.
 * Returns "All folders" if no folder is selected, or the folder path
 * (e.g., "Clients/Smith") for a specific folder.
 */
function getSearchScopeLabel() {
    const folderId = window._searchFolderId;
    if (!folderId) return 'All folders';
    
    const folders = state.folders || [];
    const folder = folders.find(f => String(f.id) === String(folderId));
    if (!folder) return 'All folders';
    
    // Build full path by walking up parents
    const parts = [];
    let current = folder;
    const seen = new Set();
    while (current && !seen.has(current.id)) {
        seen.add(current.id);
        parts.unshift(current.name);
        current = folders.find(f => f.id === current.parent_id);
    }
    const path = parts.join('/');
    
    // Note when subfolders are excluded — only meaningful for a specific folder.
    // Default (undefined or true) means "include", so we only annotate when false.
    const includeSubs = window._searchIncludeSubfolders;
    if (includeSubs === false) {
        return `${path} (only)`;
    }
    return path;
}

// Track the picker's tree controller and its filter state across re-renders
let _searchScopePickerController = null;
let _searchScopePickerFilter = '';

/**
 * Open the search scope picker modal.
 * Lets the user navigate the folder tree to pick a folder to search within
 * (or "All folders" to search the whole archive).
 */
async function openSearchScopePicker() {
    // Lazily build the modal markup on first use
    let modal = document.getElementById('searchScopePickerModal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'searchScopePickerModal';
        modal.className = 'modal-overlay';
        modal.innerHTML = `
            <div class="modal-content search-scope-modal">
                <div class="modal-header">
                    <h2>Search in folder</h2>
                </div>
                <div class="search-scope-filter">
                    <i data-lucide="search" class="search-icon"></i>
                    <input type="text" id="searchScopeFilterInput"
                           placeholder="Filter folders…"
                           autocomplete="off">
                </div>
                <div class="search-scope-all-row" id="searchScopeAllRow">
                    <i data-lucide="inbox"></i>
                    <span>All folders</span>
                    <span class="search-scope-all-hint">Search the whole archive</span>
                </div>
                <label class="search-scope-subfolders">
                    <input type="checkbox" id="searchScopeSubfoldersToggle">
                    <span>Include subfolders</span>
                    <span class="search-scope-subfolders-hint">Also search inside nested folders</span>
                </label>
                <div class="search-scope-tree" id="searchScopeTree"></div>
                <div class="modal-actions">
                    <button class="btn btn-secondary" id="searchScopeCancelBtn">Cancel</button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);
        
        // Wire up cancel + backdrop close
        modal.querySelector('#searchScopeCancelBtn').addEventListener('click', closeSearchScopePicker);
        modal.addEventListener('click', (e) => {
            if (e.target === modal) closeSearchScopePicker();
        });
        
        // Filter input
        modal.querySelector('#searchScopeFilterInput').addEventListener('input', (e) => {
            _searchScopePickerFilter = e.target.value.trim().toLowerCase();
            renderSearchScopeTreeContent();
        });
        
        // "All folders" row → clear scope and close
        modal.querySelector('#searchScopeAllRow').addEventListener('click', () => {
            window._searchFolderId = '';
            closeSearchScopePicker();
            updateSearchScopeButton();
        });
        
        // Subfolder toggle → just persist state; user closes via tree-pick or backdrop
        modal.querySelector('#searchScopeSubfoldersToggle').addEventListener('change', (e) => {
            window._searchIncludeSubfolders = e.target.checked;
            updateSearchScopeButton();
        });
    }
    
    // Reset filter and render fresh
    _searchScopePickerFilter = '';
    const filterInput = modal.querySelector('#searchScopeFilterInput');
    if (filterInput) filterInput.value = '';
    
    // Sync the checkbox to the current state (defaults to true on first open)
    if (window._searchIncludeSubfolders === undefined) {
        window._searchIncludeSubfolders = true;
    }
    const subfolderToggle = modal.querySelector('#searchScopeSubfoldersToggle');
    if (subfolderToggle) subfolderToggle.checked = !!window._searchIncludeSubfolders;
    
    // Highlight the current selection on "All folders" row if applicable
    const allRow = modal.querySelector('#searchScopeAllRow');
    if (allRow) {
        allRow.classList.toggle('selected', !window._searchFolderId);
    }
    
    renderSearchScopeTreeContent();
    
    modal.classList.add('active');
    if (typeof lucide !== 'undefined') lucide.createIcons();
    
    // Focus the filter input for fast typing
    setTimeout(() => filterInput?.focus(), 50);
}
window.openSearchScopePicker = openSearchScopePicker;

/**
 * Close the search scope picker modal.
 */
function closeSearchScopePicker() {
    const modal = document.getElementById('searchScopePickerModal');
    if (modal) modal.classList.remove('active');
}

/**
 * Render the folder tree inside the scope picker, applying the current filter.
 * Uses the unified folder-tree component for consistency with the rest of the app.
 */
async function renderSearchScopeTreeContent() {
    const container = document.getElementById('searchScopeTree');
    if (!container) return;
    
    const { renderFolderTree } = await import('../components/folder-tree.js');
    
    const filter = _searchScopePickerFilter;
    const allFolders = state.folders || [];
    
    // If filtering, compute the set of folders to show (matches + their ancestors,
    // so the tree stays valid). Also auto-expand ancestors of matches.
    let folderFilterFn;
    let autoExpandIds = null;
    
    if (filter) {
        const matchIds = new Set();
        const ancestorIds = new Set();
        
        for (const f of allFolders) {
            if (f.deleted_at || f.retention_date) continue;
            if ((f.name || '').toLowerCase().includes(filter)) {
                matchIds.add(f.id);
                // Walk up parents to keep the path visible
                let cur = f;
                const seen = new Set();
                while (cur && cur.parent_id && !seen.has(cur.id)) {
                    seen.add(cur.id);
                    const parent = allFolders.find(p => p.id === cur.parent_id);
                    if (!parent) break;
                    ancestorIds.add(parent.id);
                    cur = parent;
                }
            }
        }
        
        const visibleIds = new Set([...matchIds, ...ancestorIds]);
        folderFilterFn = (f) => !f.deleted_at && !f.retention_date && visibleIds.has(f.id);
        autoExpandIds = ancestorIds;
        
        if (visibleIds.size === 0) {
            container.innerHTML = '<div class="folder-tree-empty">No folders match.</div>';
            return;
        }
    }
    
    const treeOptions = {
        selectable: true,
        selectedId: window._searchFolderId ? Number(window._searchFolderId) : null,
        showChevrons: true,
        showColorDots: true,
        showAddButtons: false,
        onSelect: (folderId) => {
            window._searchFolderId = String(folderId);
            closeSearchScopePicker();
            updateSearchScopeButton();
        }
    };
    // Only override the component's default filter when we actually have one
    if (folderFilterFn) {
        treeOptions.filter = folderFilterFn;
    }
    
    const controller = renderFolderTree(container, treeOptions);
    
    _searchScopePickerController = controller;
    
    // Auto-expand ancestors of filter matches so the matches are visible
    if (autoExpandIds && controller && controller.expand) {
        for (const id of autoExpandIds) {
            try { controller.expand(id); } catch (_) { /* ignore */ }
        }
    }
    
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

/**
 * Update the scope button label without re-rendering the whole search view.
 * Called after the user picks a folder (or clears the scope).
 */
function updateSearchScopeButton() {
    // Re-render the search view so both the button label AND the helper text
    // reflect the new scope. Preserve the current query so the user doesn't
    // lose what they've typed.
    const input = document.getElementById('archiveSearchInput');
    const currentQuery = input?.value || '';
    
    // If results are currently displayed, leave them — the user will run a new
    // search when they're ready. Just update the button in place.
    const hasResults = !!document.querySelector('.search-result, .empty-state');
    if (hasResults) {
        const btn = document.getElementById('searchScopeBtn');
        if (btn) {
            const labelEl = btn.querySelector('.search-scope-label');
            if (labelEl) labelEl.textContent = getSearchScopeLabel();
            btn.classList.toggle('has-scope', !!window._searchFolderId);
        }
        return;
    }
    
    // Otherwise we're on the initial helper screen — re-render so the helper
    // sentence matches the new scope.
    renderSearchView(null, currentQuery);
}

/**
 * Execute archive search.
 */
async function executeArchiveSearch() {
    const input = document.getElementById('archiveSearchInput');
    const query = input?.value?.trim();
    
    if (!query) {
        renderSearchView(null, '');
        return;
    }
    
    // Show loading state
    if (contextMeta) contextMeta.textContent = 'Searching...';
    
    try {
        const folderId = window._searchFolderId || '';
        let folderParam = '';
        if (folderId) {
            folderParam = `&folder_id=${encodeURIComponent(folderId)}`;
            // Only meaningful when a folder is chosen. Default is true.
            if (window._searchIncludeSubfolders === false) {
                folderParam += '&include_subfolders=false';
            }
        }
        const response = await fetch(`/api/search?q=${encodeURIComponent(query)}&limit=100${folderParam}`);
        
        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.error || 'Search failed');
        }
        
        const data = await response.json();
        
        if (contextMeta) {
            contextMeta.textContent = `${data.count} result${data.count !== 1 ? 's' : ''}`;
        }
        
        renderSearchView(data.emails, query);
        
    } catch (error) {
        console.error('Search error:', error);
        if (contextMeta) contextMeta.textContent = 'Search failed';
        const { showAlert } = await import('../modals.js');
        showAlert('Search Error', error.message);
    }
}
window.executeArchiveSearch = executeArchiveSearch;

/**
 * Clear archive search and reset to initial state.
 */
function clearArchiveSearch() {
    window._searchFolderId = '';
    window._searchIncludeSubfolders = true;
    if (contextMeta) contextMeta.textContent = 'Search all archived emails';
    renderSearchView(null, '');
    updateSearchScopeButton();
}
window.clearArchiveSearch = clearArchiveSearch;

/**
 * Open a search result - load the email in viewer.
 */
async function openSearchResult(messageId, folderId) {
    // Open the email viewer with the search result
    try {
        const response = await fetch(`/api/folders/${folderId}/emails/${messageId}`);
        
        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.error || 'Failed to load email');
        }
        
        const data = await response.json();
        
        // Set viewer context for archive email
        currentViewerContext = {
            type: 'folder',
            folderId: folderId,
            messageId: messageId
        };
        
        // Render email in viewer
        renderEmailContent(data.email, currentViewerContext);
        
        // Show viewer overlay
        document.getElementById('emailViewerOverlay').classList.add('active');
        
    } catch (error) {
        console.error('Error loading email:', error);
        const { showAlert } = await import('../modals.js');
        showAlert('Error', error.message);
    }
}
window.openSearchResult = openSearchResult;

/**
 * Export the current search results via the bulk-export modal (Phase 2).
 *
 * Uses the search source (not messages) so the backend re-runs the FTS
 * query at export time. This is consistent with what the user just saw,
 * and avoids the ceiling that would apply if we packed thousands of IDs
 * into the message_ids payload.
 */
function exportSearchResults() {
    const input = document.getElementById('archiveSearchInput');
    const query = (input?.value || '').trim();
    if (!query) return;

    const folderId = window._searchFolderId || null;
    // Default is true for include_subfolders (matches the picker default)
    const includeSubs = window._searchIncludeSubfolders !== false;

    // Build a folder_name hint for the modal\'s "Exporting" line so the
    // user sees the same scope they searched in.
    let folderName = null;
    if (folderId) {
        const folder = (state.folders || []).find(f => String(f.id) === String(folderId));
        if (folder?.name) folderName = folder.name;
    }

    const opts = {
        source: 'search',
        query,
        folder_id: folderId,
        include_subfolders: includeSubs,
        folder_name: folderName,
    };

    if (typeof window.openExportModal === 'function') {
        window.openExportModal(opts);
    } else {
        // Lazy-load on first use \u2014 same pattern as context-menu.js
        import('../components/export-modal.js').then((m) => {
            (m.openExportModal || window.openExportModal)?.(opts);
        }).catch((err) => {
            console.error('Failed to load export modal:', err);
        });
    }
}
window.exportSearchResults = exportSearchResults;

// Helper functions for search results display
function extractName(sender) {
    if (!sender) return '';
    const match = sender.match(/^([^<]+)</);
    return match ? match[1].trim() : sender;
}

function formatDate(dateVal) {
    if (!dateVal) return '';
    const date = typeof dateVal === 'number' ? new Date(dateVal * 1000) : new Date(dateVal);
    if (isNaN(date.getTime())) return '';
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

/**
 * Render IMAP folder navigation: breadcrumbs and subfolder links.
 */
function renderImapNavigation(accountId, folderPath) {
    const subfoldersBar = document.getElementById('subfoldersBar');
    if (!subfoldersBar) return;
    
    // Get cached IMAP folder data (accountId might be string or number, try both)
    let imapData = state.imapFolders.get(accountId);
    if (!imapData) {
        imapData = state.imapFolders.get(String(accountId));
    }
    if (!imapData) {
        imapData = state.imapFolders.get(Number(accountId));
    }
    if (!imapData) {
        subfoldersBar.style.display = 'none';
        subfoldersBar.innerHTML = '';
        return;
    }
    
    // Determine delimiter from folder data
    let delimiter = '/';
    if (imapData.folders.length > 0 && imapData.folders[0].delimiter) {
        delimiter = imapData.folders[0].delimiter;
    }
    
    // Build breadcrumb parts from folder path
    const parts = folderPath.split(delimiter);
    
    // Find direct subfolders of current folder
    const subfolders = imapData.folders.filter(f => {
        if (f.name === folderPath) return false;
        if (f.name.startsWith(folderPath + delimiter)) {
            // Check it's a direct child, not a grandchild
            const remainder = f.name.slice(folderPath.length + delimiter.length);
            return !remainder.includes(delimiter);
        }
        return false;
    });
    
    // Show bar if nested (more than one part) or has subfolders
    const isNested = parts.length > 1;
    if (isNested || subfolders.length > 0) {
        let html = '';
        
        // Breadcrumb trail (only if nested)
        if (isNested) {
            html += `<div class="subfolder-breadcrumbs">`;
            parts.forEach((part, i) => {
                if (i > 0) html += ` <i data-lucide="chevron-right" class="breadcrumb-sep"></i> `;
                if (i === parts.length - 1) {
                    html += `<span class="breadcrumb-current">${escapeHtml(part)}</span>`;
                } else {
                    const pathToHere = parts.slice(0, i + 1).join(delimiter);
                    html += `<a href="#" onclick="window.navigateToImapFolder(${accountId}, '${escapeForOnclick(pathToHere)}'); return false;" class="breadcrumb-link">${escapeHtml(part)}</a>`;
                }
            });
            html += `</div>`;
        }
        
        // Subfolder links
        if (subfolders.length > 0) {
            // Sort alphabetically by name (last part of path)
            subfolders.sort((a, b) => {
                const aName = a.name.split(delimiter).pop();
                const bName = b.name.split(delimiter).pop();
                return aName.localeCompare(bName);
            });
            
            html += `<div class="subfolder-links">`;
            html += `<span class="subfolder-label">Subfolders:</span> `;
            html += subfolders.map((sf, i) => {
                const name = sf.name.split(delimiter).pop();
                const separator = i < subfolders.length - 1 ? ', ' : '';
                return `<a href="#" onclick="window.navigateToImapFolder(${accountId}, '${escapeForOnclick(sf.name)}'); return false;" class="subfolder-link">${escapeHtml(name)}</a>${separator}`;
            }).join('');
            html += `</div>`;
        }
        
        subfoldersBar.innerHTML = html;
        subfoldersBar.style.display = 'block';
        if (typeof lucide !== 'undefined') lucide.createIcons();
    } else {
        subfoldersBar.style.display = 'none';
        subfoldersBar.innerHTML = '';
    }
}

/**
 * Render folder contents: subfolders (if any) followed by emails.
 */
function renderFolderContents(folderId, subfolders) {
    if (!emailList) return;
    
    const subfoldersBar = document.getElementById('subfoldersBar');
    const currentFolder = state.folders.find(f => f.id == folderId);
    
    // Build breadcrumb trail from root to current folder
    const breadcrumbs = [];
    let folder = currentFolder;
    while (folder) {
        breadcrumbs.unshift(folder);
        folder = folder.parent_id ? state.folders.find(f => f.id == folder.parent_id) : null;
    }
    
    // Show bar if we're in a nested folder (breadcrumbs > 1) OR have subfolders
    const isNested = breadcrumbs.length > 1;
    if ((isNested || subfolders.length > 0) && subfoldersBar) {
        let html = '';
        
        // Breadcrumb trail (only if we're in a nested folder, not at root level)
        if (isNested) {
            html += `<div class="subfolder-breadcrumbs">`;
            breadcrumbs.forEach((crumb, i) => {
                if (i > 0) html += ` <i data-lucide="chevron-right" class="breadcrumb-sep"></i> `;
                if (i === breadcrumbs.length - 1) {
                    html += `<span class="breadcrumb-current">${escapeHtml(crumb.name)}</span>`;
                } else {
                    html += `<a href="#" onclick="window.navigateToSubfolder(${crumb.id}); return false;" class="breadcrumb-link">${escapeHtml(crumb.name)}</a>`;
                }
            });
            html += `</div>`;
        }
        
        // Subfolder links (inline text style)
        if (subfolders.length > 0) {
            html += `<div class="subfolder-links">`;
            html += `<span class="subfolder-label">Subfolders:</span> `;
            html += subfolders.map((sf, i) => {
                const separator = i < subfolders.length - 1 ? ', ' : '';
                return `<a href="#" onclick="window.navigateToSubfolder(${sf.id}); return false;" class="subfolder-link">${escapeHtml(sf.name)}</a>${separator}`;
            }).join('');
            html += `</div>`;
        }
        
        subfoldersBar.innerHTML = html;
        subfoldersBar.style.display = 'block';
        if (typeof lucide !== 'undefined') lucide.createIcons();
    } else if (subfoldersBar) {
        subfoldersBar.style.display = 'none';
        subfoldersBar.innerHTML = '';
    }
    
    // Render emails using standard list
    renderEmailList();
}

/**
 * Navigate to a subfolder.
 */
window.navigateToSubfolder = function(folderId) {
    // Update view state
    state.currentView = { type: 'folder', id: folderId };
    state.selectedEmails.clear();
    
    // Load the subfolder
    loadFolderEmails(folderId);
    
    // Update sidebar selection
    import('../components/sidebar.js').then(m => {
        if (m.selectFolderInSidebar) {
            m.selectFolderInSidebar(folderId);
        }
    });
};

/**
 * Navigate to an IMAP folder.
 */
window.navigateToImapFolder = function(accountId, folderPath) {
    // Update view state
    state.currentView = { type: 'account', id: accountId, folder: folderPath };
    state.selectedEmails.clear();
    
    // Load the folder
    loadAccountEmails(accountId, folderPath);
};

/**
 * Refresh the current IMAP folder, bypassing cache.
 */
window.refreshImapFolder = function() {
    if (state.currentView?.type !== 'account') return;
    const accountId = state.currentView.id;
    const folder = state.currentView.folder || 'INBOX';
    loadAccountEmails(accountId, folder, { forceRefresh: true });
};

/**
 * Show loading state in email list.
 */
export function showLoading() {
    if (!emailList) return;
    emailList.innerHTML = `
        <div class="empty-state">
            <i data-lucide="loader" class="empty-icon spin"></i>
            <h3>Loading...</h3>
        </div>
    `;
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

/**
 * Show error state in email list.
 */
export function showError(message) {
    if (!emailList) return;
    emailList.innerHTML = `
        <div class="empty-state">
            <i data-lucide="alert-triangle" class="empty-icon"></i>
            <h3>Error</h3>
            <p>${escapeHtml(message)}</p>
        </div>
    `;
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

/**
 * Open the email viewer overlay.
 * @param {number|string} emailId - Email ID or UID
 * @param {Object} options - Optional settings
 * @param {boolean} options.vaultMode - If true, viewing from vault (read-only, folderId required)
 * @param {number} options.folderId - Folder ID (required for vault mode)
 */
export async function openEmailViewer(emailId, options = {}) {
    const { vaultMode = false, folderId = null } = options;
    
    // For vault mode, we don't have the email in state.emails, so fetch minimal info
    let email;
    if (vaultMode && folderId) {
        // We'll get full details from API, just set up minimal placeholder
        email = { id: emailId };
    } else {
        email = state.emails.find(e => e.uid == emailId || e.id == emailId);
        if (!email) return;
    }
    
    const overlay = document.getElementById('emailViewerOverlay');
    overlay.classList.add('active');
    
    // In vault mode, hide any action buttons that modify emails
    if (vaultMode) {
        overlay.classList.add('vault-mode');
    } else {
        overlay.classList.remove('vault-mode');
    }
    
    document.getElementById('viewerSubject').textContent = email.subject || 'Loading...';
    document.getElementById('viewerFrom').textContent = email.from || email.sender || '';
    document.getElementById('viewerTo').textContent = email.to || '';
    document.getElementById('viewerDate').textContent = email.date || '';
    document.getElementById('viewerBody').innerHTML = '<div class="loading-spinner">Loading...</div>';
    document.getElementById('viewerAttachments').style.display = 'none';
    document.getElementById('viewerCcRow').style.display = 'none';
    
    if (typeof lucide !== 'undefined') lucide.createIcons();
    
    // Helper to fetch with retry (for intermittent IMAP connection issues)
    async function fetchWithRetry(url, options = {}, maxRetries = 2) {
        let lastError;
        for (let attempt = 0; attempt <= maxRetries; attempt++) {
            try {
                const response = await fetch(url, options);
                if (!response.ok) {
                    const data = await response.json();
                    throw new Error(data.error || 'Request failed');
                }
                const data = await response.json();
                // Check for empty body (might indicate incomplete fetch)
                if (data.email && !data.email.html_body && !data.email.text_body && attempt < maxRetries) {
                    console.warn(`Email body empty on attempt ${attempt + 1}, retrying...`);
                    await new Promise(r => setTimeout(r, 500));
                    continue;
                }
                return data;
            } catch (err) {
                lastError = err;
                if (attempt < maxRetries) {
                    console.warn(`Fetch attempt ${attempt + 1} failed, retrying...`, err);
                    await new Promise(r => setTimeout(r, 500));
                }
            }
        }
        throw lastError;
    }
    
    try {
        let data;
        let context = { type: state.currentView?.type };
        
        if (vaultMode && folderId) {
            // Vault mode: fetch from archived folder (use 'folder' type for API compatibility)
            const messageId = email.id;
            context = { type: 'folder', folderId, messageId };
            data = await fetchWithRetry(`/api/folders/${folderId}/emails/${messageId}`);
        } else if (state.currentView?.type === 'account') {
            const accountId = state.currentView.id;
            const folder = state.currentView.folder || 'INBOX';
            const uid = email.uid || email.id;
            context = { type: 'account', accountId, folder, uid };
            data = await fetchWithRetry(`/api/accounts/${accountId}/emails/${uid}?folder=${encodeURIComponent(folder)}`);
        } else if (state.currentView?.type === 'folder') {
            const folderId = state.currentView.id;
            const messageId = email.id;
            context = { type: 'folder', folderId, messageId };
            data = await fetchWithRetry(`/api/folders/${folderId}/emails/${messageId}`);
        } else if (state.currentView?.type === 'import') {
            // Get import details from mounted imports
            const imports = window.getMountedImports ? window.getMountedImports() : [];
            const imp = imports.find(i => i.id === state.currentView.id);
            if (!imp) {
                throw new Error('Import not found');
            }
            context = { 
                type: 'import',
                sourcePath: imp.path,
                uid: email.uid || email.id,
                importType: imp.type,
                folderPath: state.currentView.folder || '',
                emailSourcePath: email.sourcePath || '',
            };
            data = await fetchWithRetry('/api/import/email', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    sourcePath: imp.path,
                    uid: email.uid || email.id,
                    importType: imp.type,
                    folderPath: state.currentView.folder || '',
                    emailSourcePath: email.sourcePath || '',
                }),
            });
        } else {
            throw new Error('Unknown view type');
        }
        
        // Store context for download/print functions
        currentViewerContext = context;
        _updateStageThreadButton(context);
        _updatePrevNextButtons(context);
        _updateStarButton(context);
        renderEmailContent(data.email, context);
        
    } catch (error) {
        console.error('Error loading email:', error);
        document.getElementById('viewerBody').innerHTML = 
            `<div class="error-message">Failed to load email: ${escapeHtml(error.message)}</div>`;
    }
}

/**
 * Convert plain text with > quote markers into nested HTML blockquotes.
 * Handles multiple levels of quoting (>, >>, >>> etc.)
 * Also converts URLs to clickable links.
 * @param {string} text - Plain text email body
 * @returns {string} HTML string with blockquotes and links
 */
function plainTextToHtml(text) {
    const blockquoteStyle = 'border-left: 2px solid #ccc; margin: 0 0 0 0.5em; padding: 0 0 0 0.5em; color: #888;';
    
    // Normalize line endings and collapse excessive blank lines
    text = text.replace(/\r\n/g, '\n');           // Windows -> Unix
    text = text.replace(/\r/g, '\n');             // Old Mac -> Unix
    text = text.replace(/^[ \t]+$/gm, '');        // Lines with only spaces/tabs -> empty
    text = text.replace(/\n{3,}/g, '\n\n');       // 3+ blank lines -> 2
    
    const lines = text.split('\n');
    let html = '';
    let currentDepth = 0;

    for (const line of lines) {
        // Count leading > characters
        const match = line.match(/^(>+)\s?/);
        const depth = match ? match[1].length : 0;
        const content = match ? line.slice(match[0].length) : line;

        // Close or open blockquotes as needed
        while (currentDepth > depth) {
            html += '</blockquote>';
            currentDepth--;
        }
        while (currentDepth < depth) {
            html += `<blockquote style="${blockquoteStyle}">`;
            currentDepth++;
        }

        // Escape HTML first, then linkify URLs
        html += linkifyUrls(escapeHtml(content)) + '<br>';
    }

    // Close any remaining open blockquotes
    while (currentDepth > 0) {
        html += '</blockquote>';
        currentDepth--;
    }

    return html;
}

/**
 * Convert HTML to plain text, preserving structure with line breaks.
 * @param {string} html - HTML content
 * @returns {string} Plain text with appropriate line breaks
 */
function htmlToPlainText(html) {
    // Create a temporary element to parse HTML
    const temp = document.createElement('div');
    temp.innerHTML = html;
    
    // Recursive function to extract text with proper spacing
    function extractText(node) {
        let result = '';
        
        for (const child of node.childNodes) {
            if (child.nodeType === Node.TEXT_NODE) {
                // Text node - normalize whitespace (newlines become spaces)
                result += child.textContent.replace(/\s+/g, ' ');
            } else if (child.nodeType === Node.ELEMENT_NODE) {
                const tag = child.tagName.toLowerCase();
                
                // Block-level elements get line breaks
                const blockTags = ['p', 'div', 'br', 'tr', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote'];
                const isBlock = blockTags.includes(tag);
                
                if (tag === 'br') {
                    result += '\n';
                } else if (isBlock) {
                    // Trim trailing space before block break
                    result = result.replace(/ $/, '');
                    if (result && !result.endsWith('\n')) {
                        result += '\n';
                    }
                    result += extractText(child);
                    if (!result.endsWith('\n')) {
                        result += '\n';
                    }
                } else {
                    // Inline element - just get content
                    result += extractText(child);
                }
            }
        }
        
        return result;
    }
    
    let text = extractText(temp);
    
    // Clean up whitespace
    text = text.replace(/[^\S\n]+/g, ' ');   // Collapse horizontal whitespace (but not newlines)
    text = text.replace(/ ?\n ?/g, '\n');    // Clean up spaces around line breaks
    text = text.replace(/\n{3,}/g, '\n\n');  // Max 2 consecutive line breaks
    text = text.trim();
    
    return text;
}

/**
 * Convert URLs in text to clickable links.
 * @param {string} text - Text that has already been HTML-escaped
 * @returns {string} HTML with URLs as clickable links
 */
function linkifyUrls(text) {
    // Match URLs (http, https, ftp) - text is already escaped so no HTML to worry about
    return text.replace(
        /\b(https?:\/\/|ftp:\/\/)[^\s<>\[\]()'"]+/gi,
        '<a href="$&" target="_blank" rel="noopener noreferrer">$&</a>'
    );
}

/**
 * Convert email addresses in a header string to clickable mailto: links.
 * Handles formats like "Name <email@example.com>" and bare "email@example.com".
 * @param {string} headerText - Raw header text (From, To, Cc)
 * @returns {string} HTML with email addresses as mailto: links
 */
function linkifyEmailAddresses(headerText) {
    if (!headerText) return '';
    // Match email addresses (bare or inside angle brackets)
    return escapeHtml(headerText).replace(
        /([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})/g,
        '<a href="mailto:$1" title="Send email to $1">$1</a>'
    );
}

/**
 * Render email content in the viewer.
 * @param {Object} email - Email data
 * @param {Object} context - Viewer context for building download URLs
 */
function renderEmailContent(email, context = null) {
    document.getElementById('viewerSubject').textContent = email.subject || '(no subject)';
    document.getElementById('viewerFrom').innerHTML = linkifyEmailAddresses(email.from || '');
    document.getElementById('viewerTo').innerHTML = linkifyEmailAddresses(email.to || '');
    document.getElementById('viewerDate').textContent = email.date || '';
    
    if (email.cc) {
        document.getElementById('viewerCc').innerHTML = linkifyEmailAddresses(email.cc);
        document.getElementById('viewerCcRow').style.display = 'flex';
    }
    
    // Attachments with download/view links
    const attachDiv = document.getElementById('viewerAttachments');
    if (email.attachments && email.attachments.length > 0) {
        // Check for S/MIME signature and filter it out from display
        const hasSignature = email.attachments.some(att => 
            att.filename && att.filename.toLowerCase() === 'smime.p7s'
        );
        const visibleAttachments = email.attachments.filter(att => 
            !att.filename || att.filename.toLowerCase() !== 'smime.p7s'
        );
        
        let html = '<div class="attachment-list">';
        
        // Show signed badge if S/MIME signature present
        if (hasSignature) {
            html += `
                <div class="attachment-badge signed">
                    <i data-lucide="shield-check"></i>
                    <span>Signed</span>
                </div>
            `;
        }
        
        visibleAttachments.forEach((att, index) => {
            // Find original index for download URL
            const originalIndex = email.attachments.indexOf(att);
            const downloadUrl = getAttachmentDownloadUrl(context, originalIndex);
            const isViewable = isViewableInBrowser(att.content_type, att.filename);
            
            if (downloadUrl && downloadUrl.startsWith('import-attachment:')) {
                // Import attachments need special handling with POST request
                html += `
                    <div class="attachment-item">
                        <i data-lucide="paperclip"></i>
                        <span class="attachment-name">${escapeHtml(att.filename)}</span>
                        <span class="attachment-actions">
                            <button class="attachment-action" onclick="downloadImportAttachment(${originalIndex}, false)" title="Download"><i data-lucide="download"></i></button>
                            ${isViewable ? `<button class="attachment-action" onclick="downloadImportAttachment(${originalIndex}, true)" title="Open in new tab"><i data-lucide="external-link"></i></button>` : ''}
                        </span>
                    </div>
                `;
            } else if (downloadUrl) {
                const viewUrl = downloadUrl + (downloadUrl.includes('?') ? '&' : '?') + 'view=1';
                html += `
                    <div class="attachment-item">
                        <i data-lucide="paperclip"></i>
                        <span class="attachment-name">${escapeHtml(att.filename)}</span>
                        <span class="attachment-actions">
                            <a href="${downloadUrl}" download class="attachment-action" title="Download"><i data-lucide="download"></i></a>
                            ${isViewable ? `<a href="${viewUrl}" target="_blank" class="attachment-action" title="Open in new tab"><i data-lucide="external-link"></i></a>` : ''}
                        </span>
                    </div>
                `;
            } else {
                html += `
                    <div class="attachment-item">
                        <i data-lucide="paperclip"></i>
                        <span>${escapeHtml(att.filename)}</span>
                    </div>
                `;
            }
        });
        html += '</div>';
        attachDiv.innerHTML = html;
        attachDiv.style.display = (visibleAttachments.length > 0 || hasSignature) ? 'block' : 'none';
    } else {
        attachDiv.style.display = 'none';
    }
    
    // Show/hide load remote content button based on HTML content
    const loadRemoteBtn = document.getElementById('loadRemoteBtn');
    const hasExternalContent = email.html_body && (
        email.html_body.includes('src="http') || 
        email.html_body.includes("src='http") ||
        email.html_body.includes('src="//') ||
        email.html_body.includes("src='//") ||
        email.html_body.includes('url(http') ||
        email.html_body.includes('url(//') ||
        /src=["']\/[^"']+["']/.test(email.html_body)  // relative paths like /static/...
    );
    if (loadRemoteBtn) {
        loadRemoteBtn.style.display = hasExternalContent ? '' : 'none';
        loadRemoteBtn.disabled = false;
    }
    
    // Body
    const bodyDiv = document.getElementById('viewerBody');
    
    // Detect visually-empty bodies. A Gmail mobile picture-message arrives
    // with html_body = "<div dir=\"auto\"></div>" and text_body = "\r\n" \u2014
    // technically truthy, but they render as nothing. Strip tags and
    // whitespace and check whether there\'s any visible content.
    const stripHtml = (s) => (s || '').replace(/<[^>]*>/g, '').replace(/\s+/g, '').trim();
    const stripText = (s) => (s || '').replace(/\s+/g, '').trim();
    const htmlHasContent = email.html_body && stripHtml(email.html_body).length > 0;
    const textHasContent = email.text_body && stripText(email.text_body).length > 0;
    const hasAttachments = Array.isArray(email.attachments) && email.attachments.length > 0;

    if (htmlHasContent) {
        renderHtmlBody(bodyDiv, email.html_body, false);
    } else if (textHasContent) {
        bodyDiv.innerHTML = `<div class="email-text-body">${plainTextToHtml(email.text_body)}</div>`;
    } else if (hasAttachments) {
        bodyDiv.innerHTML = '<div class="email-text-body">(This message has no text \u2014 see attachments above.)</div>';
    } else {
        bodyDiv.innerHTML = '<div class="email-text-body">(No content)</div>';
    }
    
    // Store email data for remote content loading
    currentViewerContext.emailData = email;
    
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

/**
 * Render HTML body in an iframe.
 * @param {HTMLElement} container - Container element
 * @param {string} html - HTML content
 * @param {boolean} allowRemote - Whether to allow remote content
 */
function renderHtmlBody(container, html, allowRemote = false) {
    const iframe = document.createElement('iframe');
    // Sandbox: allow-same-origin for script access, allow-modals for print dialog,
    // allow-popups for opening links in new tabs, allow-popups-to-escape-sandbox so
    // opened tabs aren't sandboxed
    iframe.sandbox = 'allow-same-origin allow-modals allow-popups allow-popups-to-escape-sandbox';
    iframe.style.width = '100%';
    iframe.style.border = 'none';
    iframe.style.display = 'block';  // Remove inline-element baseline gap
    container.innerHTML = '';
    container.appendChild(iframe);
    
    const doc = iframe.contentDocument || iframe.contentWindow.document;
    doc.open();
    
    // If not allowing remote, block external resources via CSP
    // If allowing remote, explicitly permit all sources (Safari needs this)
    const cspMeta = allowRemote 
        ? `<meta http-equiv="Content-Security-Policy" content="img-src * data: blob:; style-src * 'unsafe-inline'; font-src * data:; default-src * 'unsafe-inline';">`
        : `<meta http-equiv="Content-Security-Policy" content="img-src 'self' data: cid:; default-src 'self' 'unsafe-inline';">`;
    
    doc.write(`
        <!DOCTYPE html>
        <html>
        <head>
            ${cspMeta}
            <base target="_blank">
            <style>
                /* The iframe document handles its own overflow:
                   - overflow-y: hidden so the iframe never shows a vertical
                     scrollbar (outer .email-viewer-body is the only V scroll)
                   - overflow-x: hidden so the iframe never shows a horizontal
                     scrollbar either. Wide content gets constrained or clipped
                     by the rules below. Same approach as Gmail/Apple Mail. */
                html, body { 
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
                    font-size: 14px; line-height: 1.5; color: #333; 
                    margin: 0; padding: 0; 
                    overflow: hidden;
                    word-wrap: break-word;
                    overflow-wrap: break-word;
                }
                /* Constrain common wide elements so they fit the iframe width.
                   Email HTML often contains 600-700px fixed-width tables, long
                   unbroken URLs, or wide images. Without these rules, that
                   content overflows horizontally and triggers a scrollbar. */
                img { max-width: 100%; height: auto; }
                table { max-width: 100% !important; }
                pre, code { 
                    white-space: pre-wrap; 
                    word-wrap: break-word; 
                    overflow-wrap: anywhere;
                    max-width: 100%;
                }
                /* Long unbroken strings (URLs, IDs, etc.) get broken at any
                   character rather than pushing the viewport wider. */
                a { color: #1a73e8; word-break: break-word; overflow-wrap: anywhere; }
                @media print {
                    html, body { overflow: visible; height: auto; }
                    * { page-break-inside: auto; }
                }
            </style>
        </head>
        <body>${html}</body>
        </html>
    `);
    doc.close();
    
    // Resize the iframe to match its content height. The iframe contains
    // an HTML document whose size can change at any time (images loading,
    // web fonts loading, JS-driven layout shifts). The previous code used
    // three timed snapshots (100ms/500ms/1s); if the content changed after
    // the last snapshot, the iframe stayed at the wrong size and its own
    // scrollbar appeared on top of the parent\'s.
    //
    // ResizeObserver is the right primitive here: we resize on every
    // genuine layout change rather than guessing when content is "done".
    const adjustHeight = () => {
        try {
            const body = doc.body;
            const root = doc.documentElement;
            const height = Math.max(
                body.scrollHeight || 0,
                body.offsetHeight || 0,
                root.scrollHeight || 0,
                root.offsetHeight || 0,
                300  // minimum height for very short emails
            );
            iframe.style.height = height + 'px';
        } catch (e) {
            // Cross-origin or torn-down iframe \u2014 fall back to a sane default
            iframe.style.height = '500px';
        }
    };

    // Initial measurement once the document is parsed
    adjustHeight();

    // ResizeObserver tracks ongoing layout changes. Some browsers don\'t
    // fire it for image loads inside the iframe document, so we keep an
    // image-load listener as a belt-and-braces measure.
    try {
        if (typeof iframe.contentWindow?.ResizeObserver === 'function') {
            const ro = new iframe.contentWindow.ResizeObserver(() => adjustHeight());
            ro.observe(doc.body);
            ro.observe(doc.documentElement);
        }
        // Image-load fallback: re-measure as each image lands
        const imgs = doc.querySelectorAll('img');
        imgs.forEach(img => {
            if (!img.complete) {
                img.addEventListener('load', adjustHeight, { once: true });
                img.addEventListener('error', adjustHeight, { once: true });
            }
        });
        // One more measurement after the load event in case anything else
        // shifted layout (web fonts, late-running CSS)
        if (iframe.contentWindow) {
            iframe.contentWindow.addEventListener('load', adjustHeight, { once: true });
        }
    } catch (e) {
        // If observer setup throws, fall back to the original timed snapshots
        setTimeout(adjustHeight, 100);
        setTimeout(adjustHeight, 500);
        setTimeout(adjustHeight, 1000);
    }
}

/**
 * Check if a file type can be viewed inline in the browser.
 * @param {string} contentType - MIME type
 * @param {string} filename - Filename (for extension fallback)
 * @returns {boolean}
 */
function isViewableInBrowser(contentType, filename) {
    // Types browsers can display inline
    const viewableTypes = [
        'application/pdf',
        'text/plain',
        'text/html',
        'text/css',
        'text/javascript',
        'application/json',
        'image/jpeg',
        'image/png',
        'image/gif',
        'image/webp',
        'image/svg+xml',
    ];
    
    if (contentType && viewableTypes.includes(contentType.toLowerCase())) {
        return true;
    }
    
    // Fallback: check extension
    if (filename) {
        const ext = filename.split('.').pop()?.toLowerCase();
        const viewableExts = ['pdf', 'txt', 'html', 'htm', 'css', 'js', 'json', 'jpg', 'jpeg', 'png', 'gif', 'webp', 'svg'];
        return viewableExts.includes(ext);
    }
    
    return false;
}

/**
 * Get attachment download URL based on viewer context.
 */
function getAttachmentDownloadUrl(context, index) {
    if (!context) return null;
    
    if (context.type === 'account') {
        return `/api/accounts/${context.accountId}/emails/${context.uid}/attachments/${index}?folder=${encodeURIComponent(context.folder)}`;
    } else if (context.type === 'folder') {
        return `/api/folders/${context.folderId}/emails/${context.messageId}/attachments/${index}`;
    } else if (context.type === 'import') {
        // Import attachments need POST request - return a marker that renderEmailContent will handle
        return `import-attachment:${index}`;
    }
    return null;
}

/**
 * Close the email viewer overlay.
 */
export function closeEmailViewer() {
    document.getElementById('emailViewerOverlay').classList.remove('active');
    currentViewerContext = null;
    _updateStageThreadButton(null);
    _updatePrevNextButtons(null);
    _updateStarButton(null);
}

/**
 * Download attachment from an import source.
 * Uses POST request since imports require body parameters.
 */
window.downloadImportAttachment = async function(index, viewInline = false) {
    if (!currentViewerContext || currentViewerContext.type !== 'import') {
        console.error('No import context available');
        return;
    }
    
    try {
        const response = await fetch('/api/import/attachment', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                sourcePath: currentViewerContext.sourcePath,
                uid: currentViewerContext.uid,
                importType: currentViewerContext.importType,
                folderPath: currentViewerContext.folderPath,
                emailSourcePath: currentViewerContext.emailSourcePath,
                index: index,
                inline: viewInline,
            }),
        });
        
        if (!response.ok) {
            // Try to get error message, but handle non-JSON responses
            let errorMsg = 'Failed to download attachment';
            const contentType = response.headers.get('Content-Type') || '';
            if (contentType.includes('application/json')) {
                const data = await response.json();
                errorMsg = data.error || errorMsg;
            } else {
                errorMsg = `Server error (${response.status})`;
            }
            throw new Error(errorMsg);
        }
        
        // Get filename from Content-Disposition header
        const contentDisposition = response.headers.get('Content-Disposition') || '';
        const filenameMatch = contentDisposition.match(/filename="([^"]+)"/);
        const filename = filenameMatch ? filenameMatch[1] : 'attachment';
        
        const blob = await response.blob();
        
        if (viewInline) {
            // Open in new tab
            const url = URL.createObjectURL(blob);
            window.open(url, '_blank');
        } else {
            // Trigger download
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        }
    } catch (error) {
        console.error('Error downloading attachment:', error);
        alert('Failed to download attachment: ' + error.message);
    }
};

/**
 * Print the current email (browser print dialog).
 */
function printEmail() {
    if (!currentViewerContext?.emailData) return;
    
    const email = currentViewerContext.emailData;
    const attachments = email.attachments || [];
    
    // Build a standalone print document
    const printWindow = window.open('', '_blank');
    if (!printWindow) return;
    
    let attachmentHtml = '';
    if (attachments.length > 0) {
        const items = attachments.map(att => {
            let sizeStr = '';
            if (att.size) {
                const kb = att.size / 1024;
                sizeStr = kb >= 1024 ? ` (${(kb / 1024).toFixed(1)} MB)` : ` (${Math.round(kb)} KB)`;
            }
            return `${escapeHtml(att.filename || 'unnamed')}${sizeStr}`;
        }).join(', ');
        attachmentHtml = `<hr style="border: none; border-top: 1px solid #ccc; margin: 1.5em 0 0.5em 0;"><p style="font-size: 13px; color: #555; margin: 0;"><strong style="color: #333;">Attachments (${attachments.length}):</strong> ${items}</p>`;
    }
    
    const body = email.html_body 
        ? email.html_body
            .replace(/<html[^>]*>/gi, '').replace(/<\/html>/gi, '')
            .replace(/<head[^>]*>[\s\S]*?<\/head>/gi, '')
            .replace(/<body[^>]*>/gi, '').replace(/<\/body>/gi, '')
            .replace(/<meta[^>]*>/gi, '')
            .replace(/<!DOCTYPE[^>]*>/gi, '')
            // Strip MS Word @page rules and page: properties that force page breaks
            .replace(/@page\s+\w+\s*\{[^}]*\}/gi, '')
            .replace(/page:\s*\w+\s*;?/gi, '')
        : `<pre style="white-space: pre-wrap; font-family: inherit;">${escapeHtml(email.text_body || '')}</pre>`;
    
    printWindow.document.write(`<!DOCTYPE html>
<html>
<head>
    <title>Print: ${escapeHtml(email.subject || '(No subject)')}</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
               font-size: 14px; line-height: 1.5; color: #333; margin: 1em; padding: 0; }
        img { max-width: 100%; height: auto; }
        a { color: #1a73e8; }
        .print-header { margin-bottom: 1.5em; padding-bottom: 1em; border-bottom: 2px solid #333; }
        .print-header h2 { margin: 0 0 0.5em 0; font-size: 16px; }
        .print-header p { margin: 0.2em 0; font-size: 13px; color: #555; }
        .print-header strong { color: #333; }
        @media print {
            body { margin: 0; }
            .print-header { page-break-after: avoid; }
        }
    </style>
</head>
<body>
    <div class="print-header">
        <h2>${escapeHtml(email.subject || '(No subject)')}</h2>
        <p><strong>From:</strong> ${escapeHtml(email.from || '')}</p>
        <p><strong>To:</strong> ${escapeHtml(email.to || '')}</p>
        ${email.cc ? `<p><strong>Cc:</strong> ${escapeHtml(email.cc)}</p>` : ''}
        <p><strong>Date:</strong> ${escapeHtml(email.date || '')}</p>
    </div>
    ${body}
    ${attachmentHtml}
</body>
</html>`);
    printWindow.document.close();
    
    // Wait for content to render, then print and close
    printWindow.onload = () => {
        printWindow.print();
        printWindow.close();
    };
    // Fallback if onload doesn't fire (some browsers)
    setTimeout(() => {
        if (!printWindow.closed) {
            printWindow.print();
            printWindow.close();
        }
    }, 500);
}
window.printEmail = printEmail;

/**
 * Copy the current email formatted as a reply to the clipboard.
 * Copies both HTML (with blockquote) and plain text (with > prefixes)
 * so it pastes correctly in both HTML and plain text compose modes.
 */
async function copyAsReply() {
    if (!currentViewerContext?.emailData) return;
    
    const email = currentViewerContext.emailData;
    const fromStr = email.from || '';
    const date = email.date || '';
    
    // For plain text: prefer extracting from HTML (more reliable), fall back to text_body
    const textBody = email.html_body 
        ? htmlToPlainText(email.html_body)
        : (email.text_body || '');
    
    // For HTML: use original HTML body if available, otherwise convert plain text
    const htmlBody = email.html_body || (email.text_body ? plainTextToHtml(email.text_body) : '');
    
    if (!textBody && !htmlBody) {
        const { showAlert } = await import('../modals.js');
        showAlert('Copy as Reply', 'No text content available to quote.');
        return;
    }
    
    // Plain text version with > quoting
    const quotedLines = textBody.split('\n').map(line => `> ${line}`).join('\n');
    const plainText = `On ${date}, ${fromStr} wrote:\n${quotedLines}`;
    
    // HTML version with blockquote - use original HTML body directly for best fidelity
    const htmlText = `<p>On ${escapeHtml(date)}, ${escapeHtml(fromStr)} wrote:</p>` +
        `<blockquote style="border-left: 2px solid #ccc; margin: 0 0 0 0.5em; padding: 0 0 0 0.5em; color: #555;">${htmlBody}</blockquote>`;
    
    try {
        // Write both formats — mail client picks the one it prefers
        const clipboardItem = new ClipboardItem({
            'text/html': new Blob([htmlText], { type: 'text/html' }),
            'text/plain': new Blob([plainText], { type: 'text/plain' })
        });
        await navigator.clipboard.write([clipboardItem]);
        
        // Brief visual feedback on the button
        const btn = document.querySelector('[onclick="copyAsReply()"]');
        if (btn) {
            const originalTitle = btn.title;
            btn.title = 'Copied!';
            btn.classList.add('btn-success-flash');
            setTimeout(() => {
                btn.title = originalTitle;
                btn.classList.remove('btn-success-flash');
            }, 1500);
        }
    } catch (error) {
        const { showAlert } = await import('../modals.js');
        showAlert('Copy Failed', 'Could not copy to clipboard: ' + error.message);
    }
}
window.copyAsReply = copyAsReply;

/**
 * Download the current email as .eml file.
 */
function downloadEmail() {
    if (!currentViewerContext) return;
    
    let downloadUrl = null;
    
    if (currentViewerContext.type === 'account') {
        downloadUrl = `/api/accounts/${currentViewerContext.accountId}/emails/${currentViewerContext.uid}/download?folder=${encodeURIComponent(currentViewerContext.folder)}`;
    } else if (currentViewerContext.type === 'folder') {
        downloadUrl = `/api/folders/${currentViewerContext.folderId}/emails/${currentViewerContext.messageId}/download`;
    }
    
    if (downloadUrl) {
        // Create a temporary link and click it
        const a = document.createElement('a');
        a.href = downloadUrl;
        a.download = '';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    }
}
window.downloadEmail = downloadEmail;

/**
 * Load remote content (images, etc.) in the current email.
 */
function loadRemoteContent() {
    if (!currentViewerContext?.emailData?.html_body) return;
    
    const bodyDiv = document.getElementById('viewerBody');
    renderHtmlBody(bodyDiv, currentViewerContext.emailData.html_body, true);
    
    // Disable the button after loading (keep visible as indicator)
    const loadRemoteBtn = document.getElementById('loadRemoteBtn');
    if (loadRemoteBtn) loadRemoteBtn.disabled = true;
}
window.loadRemoteContent = loadRemoteContent;

/**
 * View raw source of the current email.
 */
async function viewEmailSource() {
    if (!currentViewerContext) return;
    
    let sourceUrl = null;
    
    if (currentViewerContext.type === 'account') {
        sourceUrl = `/api/accounts/${currentViewerContext.accountId}/emails/${currentViewerContext.uid}/source?folder=${encodeURIComponent(currentViewerContext.folder)}`;
    } else if (currentViewerContext.type === 'folder') {
        sourceUrl = `/api/folders/${currentViewerContext.folderId}/emails/${currentViewerContext.messageId}/source`;
    }
    
    if (!sourceUrl) return;
    
    // Open window immediately (before async fetch) to avoid popup blocker
    const win = window.open('', '_blank');
    if (!win) {
        const { showAlert } = await import('../modals.js');
        showAlert('Error', 'Unable to open new window. Please allow popups for this site.');
        return;
    }
    
    // Show loading state
    win.document.write(`<!DOCTYPE html>
<html>
<head>
    <title>Email Source</title>
    <style>
        body { font-family: 'SF Mono', 'Menlo', 'Monaco', 'Consolas', monospace; 
               white-space: pre-wrap; word-wrap: break-word; 
               padding: 20px; background: #fff; color: #333; margin: 0;
               font-size: 13px; line-height: 1.5; }
    </style>
</head>
<body>Loading...</body>
</html>`);
    
    try {
        const response = await fetch(sourceUrl);
        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.error || 'Failed to fetch source');
        }
        
        const data = await response.json();
        
        // Update window with source
        win.document.body.textContent = data.source;
    } catch (error) {
        console.error('Error fetching email source:', error);
        win.document.body.textContent = `Error: ${error.message}`;
    }
}
window.viewEmailSource = viewEmailSource;

/**
 * Initialize email viewer event listeners.
 */
function initEmailViewerListeners() {
    // Close on backdrop click
    document.getElementById('emailViewerOverlay')?.addEventListener('click', (e) => {
        if (e.target.id === 'emailViewerOverlay') {
            closeEmailViewer();
        }
    });
    
    // Close on Escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && document.getElementById('emailViewerOverlay')?.classList.contains('active')) {
            closeEmailViewer();
        }
    });
}

// Expose to window for inline onclick handlers
window.openEmailViewer = openEmailViewer;
window.closeEmailViewer = closeEmailViewer;


/**
 * Click handler for the "Stage thread to..." button in the email viewer.
 * Reads the current viewer context (which only contains the IMAP account
 * and UID details when type === 'account') and lazy-loads the thread-stage
 * module. The module owns the folder-picker / find / confirm / stage flow.
 */
window.stageThreadFromViewer = async function() {
    const ctx = currentViewerContext;
    if (!ctx || ctx.type !== 'account') {
        console.warn('stageThreadFromViewer called outside a live IMAP context');
        return;
    }
    try {
        const mod = await import('../components/thread-stage.js');
        await mod.openStageThreadModal({
            accountId: ctx.accountId,
            folder: ctx.folder,
            uid: String(ctx.uid),
            subject: currentViewerContext?.emailData?.subject || '',
        });
    } catch (e) {
        console.error('Failed to load thread-stage module:', e);
    }
};


/**
 * Click handler for the viewer prev/next buttons. Also called by
 * keyboard shortcut handler.
 *
 * @param {number} direction - -1 for previous (newer), +1 for next (older)
 */
window.viewerNavigate = function(direction) {
    const ctx = currentViewerContext;
    if (!ctx || ctx.type !== 'folder' || !ctx.messageId) return;

    const emails = state.emails || [];
    const idx = emails.findIndex(e => (e.id == ctx.messageId));
    if (idx < 0) return;

    const newIdx = idx + direction;
    if (newIdx < 0 || newIdx >= emails.length) return;

    const nextEmail = emails[newIdx];
    const nextId = nextEmail.id || nextEmail.uid;
    if (nextId == null) return;

    // Reopen the viewer with the new email. openEmailViewer handles all
    // the loading, context-update, and button-state work.
    openEmailViewer(nextId);
};

/**
 * Keyboard shortcuts for the email viewer:
 *   j  - next email (older, down the list)
 *   k  - previous email (newer, up the list)
 *   Esc - close viewer
 *
 * Only active when the viewer is open. Skipped when an input/textarea
 * has focus so the user can still type freely.
 *
 * j/k chosen over arrow keys because arrows would conflict with scrolling
 * the email body. j/k is Gmail and vim convention. Escape is the universal
 * modal-close shortcut.
 */
document.addEventListener('keydown', (e) => {
    const overlay = document.getElementById('emailViewerOverlay');
    if (!overlay || !overlay.classList.contains('active')) return;

    // Don\'t steal keys when the user is typing
    const tag = (e.target?.tagName || '').toUpperCase();
    if (tag === 'INPUT' || tag === 'TEXTAREA' || e.target?.isContentEditable) return;

    // Ignore when modifier keys are held — those are browser shortcuts
    if (e.metaKey || e.ctrlKey || e.altKey) return;

    if (e.key === 'Escape') {
        e.preventDefault();
        if (typeof window.closeEmailViewer === 'function') {
            window.closeEmailViewer();
        }
        return;
    }

    // Prev/next only when viewing an archive email
    if (!currentViewerContext || currentViewerContext.type !== 'folder') return;

    if (e.key === 'j') {
        e.preventDefault();
        window.viewerNavigate(1);
    } else if (e.key === 'k') {
        e.preventDefault();
        window.viewerNavigate(-1);
    } else if (e.key === 's') {
        e.preventDefault();
        if (typeof window.toggleStarFromViewer === 'function') {
            window.toggleStarFromViewer();
        }
    }
});


/**
 * Click handler for the viewer star button. Toggles the message's
 * flagged_at via PATCH /api/messages/<id>/flag, then updates local
 * state.emails so the renderer (and any subsequent re-render of the
 * email list) reflects the new value.
 */
window.toggleStarFromViewer = async function() {
    const ctx = currentViewerContext;
    if (!ctx || ctx.type !== 'folder' || !ctx.messageId) return;

    const emails = state.emails || [];
    const email = emails.find(e => (e.id == ctx.messageId));
    const isCurrentlyFlagged = !!(email && email.flagged_at);
    const newFlagged = !isCurrentlyFlagged;

    try {
        const response = await fetch(`/api/messages/${ctx.messageId}/flag`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ flagged: newFlagged }),
        });
        if (!response.ok) {
            console.error('Failed to toggle star:', response.status);
            return;
        }
        const data = await response.json();

        // Update local state so the indicator is in sync without a refetch
        if (email) {
            email.flagged_at = data.flagged_at;
        }

        // Refresh the viewer's star icon
        _updateStarButton(ctx);

        // Decide which renderer to call based on context. Calling
        // renderEmailList() while the user is in the Starred view would
        // overwrite the Starred template with the regular folder-list
        // template, which we very much do not want.
        let inStarredCtx = false;
        try {
            const starredModule = await import('./starred.js');
            inStarredCtx = starredModule.isInStarredContext();
            starredModule.updateStarredBadge();
            if (inStarredCtx) {
                // Starred view: if we just unstarred, drop the row (and
                // re-render via the Starred renderer). If we just starred
                // — possible after a previous unstar that left the row,
                // though we drop on unstar so this shouldn't actually
                // happen — do nothing.
                if (!newFlagged) {
                    starredModule.dropFromStarredList(ctx.messageId);
                }
            }
        } catch (e) {
            // Non-critical; badge will refresh on next view load
        }

        // For non-starred views, refresh the regular email list so the
        // indicator updates immediately on the visible rows.
        if (!inStarredCtx && typeof renderEmailList === 'function') {
            renderEmailList();
        }
    } catch (e) {
        console.error('Star toggle failed:', e);
    }
};
