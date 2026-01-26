/**
 * MailRepo - Email List Component
 * 
 * Handles rendering and interaction with the email list.
 */

import { escapeHtml, extractName, formatDate } from '../utils.js';
import { state } from '../state.js';

// Reference to DOM elements (set via init)
let emailListEl = null;
let onSelectionChange = null;

/**
 * Initialize the email list component.
 * @param {Object} config
 * @param {HTMLElement} config.emailList - Email list container
 * @param {Function} config.onSelectionChange - Callback when selection changes
 */
export function initEmailList(config) {
    emailListEl = config.emailList;
    onSelectionChange = config.onSelectionChange;
}

/**
 * Render the email list.
 */
export function renderEmailList() {
    if (!emailListEl) return;
    
    if (state.emails.length === 0) {
        emailListEl.innerHTML = `
            <div class="empty-state">
                <i data-lucide="mail-x" class="empty-icon"></i>
                <h3>No Emails</h3>
                <p>This folder is empty.</p>
            </div>
        `;
        if (typeof lucide !== 'undefined') lucide.createIcons();
        return;
    }
    
    emailListEl.innerHTML = state.emails.map(email => {
        const emailId = email.uid || email.id;
        const isStaged = state.staged.has(emailId);
        const isSelected = state.selectedEmails.has(emailId);
        
        // Determine which action buttons to show
        let actionsHtml = '';
        if (isStaged) {
            // Staged: select disabled, clear active (unstages)
            actionsHtml = `
                <button class="btn btn-sm btn-icon" disabled title="Already staged">
                    <i data-lucide="circle"></i>
                </button>
                <button class="btn btn-sm btn-icon" onclick="event.stopPropagation(); clearEmail('${emailId}')" title="Unstage">
                    <i data-lucide="x"></i>
                </button>
            `;
        } else if (isSelected) {
            // Selected: checkmark shown, clear active (deselects)
            actionsHtml = `
                <button class="btn btn-sm btn-icon btn-selected" disabled title="Selected">
                    <i data-lucide="check"></i>
                </button>
                <button class="btn btn-sm btn-icon" onclick="event.stopPropagation(); clearEmail('${emailId}')" title="Deselect">
                    <i data-lucide="x"></i>
                </button>
            `;
        } else {
            // Default: select active, clear disabled
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
            <div class="email-item ${isStaged ? 'staged' : ''} ${isSelected ? 'selected' : ''}" 
                 data-id="${emailId}">
                <div class="email-actions" onclick="event.stopPropagation()">
                    ${actionsHtml}
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
    
    if (typeof lucide !== 'undefined') lucide.createIcons();
    updateToolbarButtons();
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
