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
export async function loadAccountEmails(accountId, folder = 'INBOX') {
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
    const streamUrl = `/api/accounts/${accountId}/emails/stream?folder=${encodeURIComponent(folder)}`;
    
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
    
    let html = `
        <div class="folder-management-list search-view">
            <div class="email-list-toolbar">
                <div class="email-filter">
                    <i data-lucide="search" class="search-icon"></i>
                    <input type="text" 
                           id="archiveSearchInput" 
                           placeholder="Search by subject, sender, recipient, or content..." 
                           value="${escapeHtml(query)}"
                           onkeydown="if(event.key==='Enter') executeArchiveSearch()">
                </div>
                <div class="toolbar-actions">
                    <button class="btn btn-primary" onclick="executeArchiveSearch()">
                        <i data-lucide="search"></i>
                        Search
                    </button>
                    <button class="btn btn-secondary" onclick="clearArchiveSearch()" ${!hasQuery ? 'disabled' : ''}>
                        <i data-lucide="x"></i>
                        Clear
                    </button>
                </div>
            </div>
    `;
    
    if (results === null) {
        // Initial state - show helpful text
        html += `
            <div class="search-help">
                <p>Type a search term and press Enter (or click Search) to find emails across your entire archive.</p>
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
    
    emailList.innerHTML = html;
    if (typeof lucide !== 'undefined') lucide.createIcons();
    
    // Focus the search input
    const input = document.getElementById('archiveSearchInput');
    if (input && !query) input.focus();
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
        const response = await fetch(`/api/search?q=${encodeURIComponent(query)}&limit=100`);
        
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
    if (contextMeta) contextMeta.textContent = 'Search all archived emails';
    renderSearchView(null, '');
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
 */
export async function openEmailViewer(emailId) {
    const email = state.emails.find(e => e.uid == emailId || e.id == emailId);
    if (!email) return;
    
    const overlay = document.getElementById('emailViewerOverlay');
    overlay.classList.add('active');
    
    document.getElementById('viewerSubject').textContent = email.subject || '(no subject)';
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
        
        if (state.currentView?.type === 'account') {
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
    
    if (email.html_body) {
        renderHtmlBody(bodyDiv, email.html_body, false);
    } else if (email.text_body) {
        bodyDiv.innerHTML = `<div class="email-text-body">${plainTextToHtml(email.text_body)}</div>`;
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
            <style>
                html, body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
                       font-size: 14px; line-height: 1.5; color: #333; margin: 0; padding: 0; }
                img { max-width: 100%; height: auto; }
                a { color: #1a73e8; }
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
    
    // Adjust iframe height to fit content (let parent container scroll)
    const adjustHeight = () => {
        try {
            const body = doc.body;
            const html = doc.documentElement;
            // Get the maximum of various height measurements
            const height = Math.max(
                body.scrollHeight || 0,
                body.offsetHeight || 0,
                html.scrollHeight || 0,
                html.offsetHeight || 0,
                300 // minimum height
            );
            iframe.style.height = height + 'px';
        } catch (e) {
            // Fallback if we can't access iframe content
            iframe.style.height = '500px';
        }
    };
    setTimeout(adjustHeight, 100);
    // Adjust again after images may have loaded
    setTimeout(adjustHeight, 500);
    setTimeout(adjustHeight, 1000);
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
    
    // Prefer HTML body when available - it's more reliably formatted than plain text,
    // which can have missing spaces or other formatting issues from the sender's system
    let textBody = email.html_body 
        ? htmlToPlainText(email.html_body)
        : (email.text_body || '');
    
    if (!textBody) {
        const { showAlert } = await import('../modals.js');
        showAlert('Copy as Reply', 'No text content available to quote.');
        return;
    }
    
    // Plain text version with > quoting
    const quotedLines = textBody.split('\n').map(line => `> ${line}`).join('\n');
    const plainText = `On ${date}, ${fromStr} wrote:\n${quotedLines}`;
    
    // HTML version with blockquote (for HTML compose mode)
    const htmlText = `<p>On ${escapeHtml(date)}, ${escapeHtml(fromStr)} wrote:</p>` +
        `<blockquote style="border-left: 2px solid #ccc; margin: 0 0 0 0.5em; padding: 0 0 0 0.5em; color: #555;">${plainTextToHtml(textBody)}</blockquote>`;
    
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
        body { font-family: monospace; white-space: pre-wrap; word-wrap: break-word; 
               padding: 20px; background: #1e1e1e; color: #d4d4d4; margin: 0; }
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
