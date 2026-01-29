/**
 * MailRepo - Modal Helpers
 * Styled replacements for native prompt/confirm/alert
 */

let promptResolver = null;
let confirmResolver = null;
let alertResolver = null;

/**
 * Close a modal by ID.
 * @param {string} modalId - ID of modal element
 */
export function closeModal(modalId) {
    document.getElementById(modalId)?.classList.remove('active');
}

/**
 * Show a styled prompt modal.
 * @param {string} title - Modal title
 * @param {string} defaultValue - Default input value
 * @param {Object} options - Optional settings
 * @param {string} options.placeholder - Placeholder text for input
 * @returns {Promise<string|null>} User input or null if cancelled
 */
export function showPrompt(title, defaultValue = '', options = {}) {
    return new Promise(resolve => {
        promptResolver = resolve;
        const input = document.getElementById('promptInput');
        document.getElementById('promptTitle').textContent = title;
        input.value = defaultValue;
        input.placeholder = options.placeholder || '';
        document.getElementById('promptModal').classList.add('active');
        input.focus();
        input.select();
    });
}

/**
 * Resolve the current prompt modal.
 * @param {string|null} value - Value to resolve with
 */
export function resolvePrompt(value) {
    closeModal('promptModal');
    if (promptResolver) {
        promptResolver(value);
        promptResolver = null;
    }
}

/**
 * Show a styled confirm modal.
 * @param {string} title - Modal title
 * @param {string} message - Confirmation message
 * @param {Object} options - Optional settings
 * @param {string} options.okText - Text for OK button
 * @param {boolean} options.danger - Use danger styling
 * @returns {Promise<boolean>} True if confirmed
 */
export function showConfirm(title, message, options = {}) {
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

/**
 * Resolve the current confirm modal.
 * @param {boolean} value - Value to resolve with
 */
export function resolveConfirm(value) {
    closeModal('confirmModal');
    if (confirmResolver) {
        confirmResolver(value);
        confirmResolver = null;
    }
}

/**
 * Show a styled alert modal.
 * @param {string} title - Modal title
 * @param {string} message - Alert message
 * @returns {Promise<void>} Resolves when user clicks OK
 */
export function showAlert(title, message) {
    return new Promise(resolve => {
        alertResolver = resolve;
        document.getElementById('alertTitle').textContent = title;
        document.getElementById('alertMessage').textContent = message;
        document.getElementById('alertModal').classList.add('active');
    });
}

/**
 * Resolve the current alert modal.
 */
export function resolveAlert() {
    closeModal('alertModal');
    if (alertResolver) {
        alertResolver();
        alertResolver = null;
    }
}

/**
 * Initialize modal event listeners.
 * Call this once on DOMContentLoaded.
 */
export function initModalListeners() {
    // Handle Enter key in prompt
    document.getElementById('promptInput')?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            resolvePrompt(e.target.value);
        } else if (e.key === 'Escape') {
            resolvePrompt(null);
        }
    });
}

// Expose to window for inline onclick handlers
window.resolvePrompt = resolvePrompt;
window.resolveConfirm = resolveConfirm;
window.resolveAlert = resolveAlert;
window.closeModal = closeModal;
