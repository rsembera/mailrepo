/**
 * MailRepo - Email List Component
 * 
 * Handles rendering and interaction with the email list.
 */

import { escapeHtml, extractName, formatDate } from '../utils.js';
import { state } from '../state.js';

// Reference to DOM elements (set via init)
let emailListEl = null;
let selectAllEl = null;
let onSelectionChange = null;

/**
 * Initialize the email list component.
 * @param {Object} config
 * @param {HTMLElement} config.emailList - Email list container
 * @param {HTMLElement} config.selectAll - Select all checkbox
 * @param {Function} config.onSelectionChange - Callback when selection changes
 */
export function initEmailList(config) {
    emailListEl = config.emailList;
    selectAllEl = config.selectAll;
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

/**
 * Toggle selection of an email.
 * @param {string} emailId - ID of email to toggle
 */
export function toggleEmailSelection(emailId) {
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
    
    updateSelectAllState();
    if (onSelectionChange) onSelectionChange();
}

/**
 * Handle select all checkbox change.
 * @param {Event} e - Change event
 */
export function handleSelectAll(e) {
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
    if (onSelectionChange) onSelectionChange();
}

/**
 * Update the select all checkbox state.
 */
export function updateSelectAllState() {
    if (!selectAllEl) return;
    
    const available = state.emails.filter(e => !state.staged.has(e.id));
    const selectedCount = [...state.selectedEmails].filter(id => 
        available.some(e => e.id === id)
    ).length;
    
    selectAllEl.checked = available.length > 0 && selectedCount === available.length;
    selectAllEl.indeterminate = selectedCount > 0 && selectedCount < available.length;
}

// Expose to window for inline onclick handlers
window.toggleEmailSelection = toggleEmailSelection;
