/**
 * MailRepo - Mail View Component
 * 
 * Handles:
 * - Loading emails from IMAP accounts
 * - Loading emails from archive folders
 * - Email viewer (reading full emails)
 * - View state management
 */

import { escapeHtml } from '../utils.js';
import { state } from '../state.js';
import { renderEmailList } from '../components/email-list.js';

/**
 * Escape a string for use in an onclick attribute.
 */
function escapeForOnclick(str) {
    return str.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
}

// DOM element references
let contextTitle = null;
let contextMeta = null;
let emailList = null;

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
        
        // Check for subfolders
        const subfolders = state.folders.filter(f => f.parent_id == folderId && !f.deleted_at);
        
        // Render subfolders + emails
        renderFolderContents(folderId, subfolders);
        
    } catch (error) {
        console.error('Error loading emails:', error);
        if (contextTitle) contextTitle.textContent = 'Error';
        showError(error.message);
    }
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
    
    try {
        let response;
        
        if (state.currentView?.type === 'account') {
            const accountId = state.currentView.id;
            const folder = state.currentView.folder || 'INBOX';
            const uid = email.uid || email.id;
            response = await fetch(`/api/accounts/${accountId}/emails/${uid}?folder=${encodeURIComponent(folder)}`);
        } else if (state.currentView?.type === 'folder') {
            const folderId = state.currentView.id;
            const messageId = email.id;
            response = await fetch(`/api/folders/${folderId}/emails/${messageId}`);
        } else if (state.currentView?.type === 'import') {
            // Get import details from mounted imports
            const imports = window.getMountedImports ? window.getMountedImports() : [];
            const imp = imports.find(i => i.id === state.currentView.id);
            if (!imp) {
                throw new Error('Import not found');
            }
            response = await fetch('/api/import/email', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    sourcePath: imp.path,
                    uid: email.uid || email.id,
                    importType: imp.type,
                    folderPath: state.currentView.folder || '',
                }),
            });
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

/**
 * Render email content in the viewer.
 */
function renderEmailContent(email) {
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
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }
    
    // Body
    const bodyDiv = document.getElementById('viewerBody');
    
    if (email.html_body) {
        const iframe = document.createElement('iframe');
        iframe.sandbox = 'allow-same-origin';
        iframe.style.width = '100%';
        iframe.style.border = 'none';
        bodyDiv.innerHTML = '';
        bodyDiv.appendChild(iframe);
        
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
        
        setTimeout(() => {
            iframe.style.height = doc.body.scrollHeight + 'px';
        }, 100);
        
    } else if (email.text_body) {
        bodyDiv.innerHTML = `<div class="email-text-body">${escapeHtml(email.text_body)}</div>`;
    } else {
        bodyDiv.innerHTML = '<div class="email-text-body">(No content)</div>';
    }
}

/**
 * Close the email viewer overlay.
 */
export function closeEmailViewer() {
    document.getElementById('emailViewerOverlay').classList.remove('active');
}

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
