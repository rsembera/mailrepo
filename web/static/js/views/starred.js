/**
 * MailRepo - Starred View
 *
 * Shows all flagged emails across the archive, sorted by flagged_at DESC
 * (most recently flagged first). Each row shows the folder path so the
 * user can see where in the archive each starred email lives. Clicking
 * an email opens the standard archive viewer.
 *
 * Mirrors the trash view's structure (loadX -> renderX) but simpler
 * since there's only one list and no tabs.
 *
 * See docs/Flagging_Plan.md.
 */

import { escapeHtml, formatDate, extractName } from '../utils.js';
import { state } from '../state.js';

let contextTitle = null;
let contextMeta = null;
let emailList = null;
let starredEmails = [];
let searchQuery = '';
let inStarredContext = false;

/**
 * Initialize starred view. Called once at app startup with the DOM
 * references it needs.
 */
export function initStarredView(config) {
    contextTitle = config.contextTitle;
    contextMeta = config.contextMeta;
    emailList = config.emailList;
}

/**
 * Show the starred view. Called when the user clicks the Starred rail
 * button.
 */
export async function showStarredView() {
    const sidebar = document.getElementById('sidebar');
    const toolbar = document.querySelector('.content-toolbar');
    const headerActions = document.querySelector('.header-actions');
    const subfoldersBar = document.getElementById('subfoldersBar');

    sidebar.style.display = 'none';
    if (toolbar) toolbar.style.display = 'none';
    if (headerActions) headerActions.style.display = 'none';
    if (subfoldersBar) subfoldersBar.style.display = 'none';

    if (contextTitle) contextTitle.textContent = 'Starred';
    if (contextMeta) contextMeta.textContent = '';

    // Make sure currentView reflects this so other code knows we're not in
    // a folder/account/search context. Using 'starred' as a distinct type;
    // openEmailViewer treats it like a folder view (archive context).
    state.currentView = { type: 'starred' };
    inStarredContext = true;

    await loadStarredEmails();
    renderStarredView();
    updateStarredBadge();
}

async function loadStarredEmails() {
    try {
        const response = await fetch('/api/messages/flagged');
        if (response.ok) {
            const data = await response.json();
            starredEmails = data.emails || [];
        } else {
            console.error('Failed to load starred emails:', response.status);
            starredEmails = [];
        }
    } catch (error) {
        console.error('Error loading starred emails:', error);
        starredEmails = [];
    }
}

function renderStarredView() {
    const total = starredEmails.length;

    // Filter by search if active
    let emails = starredEmails;
    if (searchQuery) {
        const q = searchQuery.toLowerCase();
        emails = emails.filter(e =>
            (e.subject || '').toLowerCase().includes(q) ||
            (e.sender || '').toLowerCase().includes(q) ||
            (e.folder_path || '').toLowerCase().includes(q)
        );
    }

    // Context meta count
    if (contextMeta) {
        const showingFiltered = searchQuery && emails.length !== total;
        if (showingFiltered) {
            contextMeta.textContent = `${emails.length} of ${total} starred emails`;
        } else {
            contextMeta.textContent = `${total} starred email${total !== 1 ? 's' : ''}`;
        }
    }

    if (total === 0) {
        emailList.innerHTML = `
            <div class="empty-state">
                <i data-lucide="star" class="empty-icon"></i>
                <h3>No Starred Emails</h3>
                <p>Open any archived email and click the star icon to mark it as important. Starred emails appear here.</p>
            </div>
        `;
        if (typeof lucide !== 'undefined') lucide.createIcons();
        return;
    }

    let html = `
        <div class="trash-management-list">
            <div class="trash-management-toolbar">
                <div class="trash-toolbar-left">
                    <div class="trash-search">
                        <i data-lucide="search" class="search-icon"></i>
                        <input type="text"
                               id="starredSearch"
                               placeholder="Filter starred emails…"
                               value="${escapeHtml(searchQuery)}"
                               oninput="handleStarredSearch(this.value)">
                        ${searchQuery ? '<button class="search-clear" onclick="clearStarredSearch()"><i data-lucide="x"></i></button>' : ''}
                    </div>
                </div>
            </div>
    `;

    if (emails.length === 0) {
        html += `
            <div class="empty-state" style="padding: var(--space-xl);">
                <p>No starred emails match "${escapeHtml(searchQuery)}"</p>
            </div>
        `;
    } else {
        emails.forEach(email => {
            html += renderStarredEmailRow(email);
        });
    }

    html += '</div>';
    emailList.innerHTML = html;
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function renderStarredEmailRow(email) {
    const senderName = extractName(email.sender || '');
    const folderPath = email.folder_path || email.folder_name || '';
    const subject = email.subject || '(no subject)';
    return `
        <div class="folder-management-item email-list-item"
             onclick="openStarredEmail(${email.id}, ${email.folder_id})">
            <div class="email-list-content">
                <div class="email-list-main">
                    <div class="email-list-header-row">
                        <span class="email-sender">${escapeHtml(senderName)}</span>
                        <span class="email-list-meta">
                            <i data-lucide="star" class="email-list-star"></i>
                            <span class="email-date">${formatDate(email.date)}</span>
                        </span>
                    </div>
                    <span class="email-subject">${escapeHtml(subject)}</span>
                    <span class="email-folder-path">${escapeHtml(folderPath)}</span>
                </div>
            </div>
        </div>
    `;
}

/**
 * Open an email from the starred view. Delegates to the standard
 * archive viewer, but we need to set up the folder context first so
 * prev/next and the star button know which list they're in.
 */
window.openStarredEmail = async function(emailId, folderId) {
    // Synthesize a minimal state.emails containing just this email so the
    // viewer's context and current-position logic work. The user can use
    // the star button to unstar, but prev/next would have nowhere to go —
    // we'll set state.emails to the starred list so navigation walks the
    // starred set.
    state.currentView = { type: 'folder', id: folderId };
    state.emails = starredEmails.map(e => ({
        id: e.id,
        subject: e.subject,
        sender: e.sender,
        date: e.date,
        flagged_at: e.flagged_at,
    }));
    inStarredContext = true;
    if (typeof window.openEmailViewer === 'function') {
        await window.openEmailViewer(emailId);
    }
};

window.handleStarredSearch = function(value) {
    searchQuery = value || '';
    renderStarredView();
};

window.clearStarredSearch = function() {
    searchQuery = '';
    renderStarredView();
};

/**
 * Update the badge count on the Starred rail button. Called after
 * load and after any flag/unflag operation to keep the count current.
 */
export async function updateStarredBadge() {
    const badge = document.getElementById('starredBadge');
    if (!badge) return;
    try {
        const response = await fetch('/api/messages/flagged');
        if (!response.ok) return;
        const data = await response.json();
        const count = (data.emails || []).length;
        if (count > 0) {
            badge.textContent = String(count);
            badge.classList.remove('hidden');
        } else {
            badge.classList.add('hidden');
        }
    } catch (e) {
        // Badge stays as-is on error; not critical.
    }
}


/**
 * Remove an email from the in-memory starred list and re-render.
 * Called by toggleStarFromViewer when the user unstars an email while
 * viewing it from within the Starred context — without this, the row
 * would stay in the list visually contradicting its new (unflagged)
 * state.
 *
 * Safe to call when not in starred context; it just no-ops if the id
 * isn\'t in the list.
 */
export function dropFromStarredList(emailId) {
    if (!inStarredContext) return;
    const idx = starredEmails.findIndex(e => (e.id == emailId));
    if (idx < 0) return;
    starredEmails.splice(idx, 1);
    // Also drop from state.emails so prev/next walks the updated set.
    if (state.emails && Array.isArray(state.emails)) {
        const sidx = state.emails.findIndex(e => (e.id == emailId));
        if (sidx >= 0) state.emails.splice(sidx, 1);
    }
    // Re-render the view so the list under the viewer updates immediately.
    // Without this, the row stays visible until the user navigates away
    // and back. emailList might not be available if we got here via some
    // unexpected path \u2014 guard accordingly.
    if (emailList) {
        renderStarredView();
    }
}

/** Returns true if the user opened an email from the Starred view. */
export function isInStarredContext() {
    return inStarredContext;
}

/** Called when the user navigates away from the starred context. */
export function clearStarredContext() {
    inStarredContext = false;
}
