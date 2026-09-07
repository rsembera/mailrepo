/**
 * MailRepo - Toast notifications
 *
 * Non-blocking status messages: a small card slides up from the bottom of
 * the window, dismisses itself, and never takes focus or needs a click.
 *
 * Use showToast() for anything that only reports an outcome — "staged",
 * "commit complete", "folder name cannot be empty", "failed to delete
 * folder". Keep showAlert() / showConfirm() (modals.js) for anything the
 * user has to read and act on: multi-step instructions, failures with an
 * explanation, and every destructive-action confirm. A modal reserved for
 * decisions stays meaningful; one used for every success message trains
 * the user to dismiss dialogs unread.
 *
 *   showToast('Thread staged.');                       // info
 *   showToast('Commit complete.', 'success');
 *   showToast('Folder name cannot be empty.', 'warning');
 *   showToast('Failed to delete folder.', 'error');    // stays longer
 */

const DURATION_MS = { info: 4000, success: 4000, warning: 5000, error: 7000 };
const MAX_VISIBLE = 3;

const ICONS = {
    info: 'info',
    success: 'check-circle',
    warning: 'alert-triangle',
    error: 'x-circle',
};

let container = null;

function getContainer() {
    if (container) return container;
    container = document.createElement('div');
    container.id = 'toastContainer';
    container.className = 'toast-container';
    document.body.appendChild(container);
    return container;
}

/**
 * Show a toast.
 * @param {string} message - Plain text (never HTML)
 * @param {'info'|'success'|'warning'|'error'} [type='info']
 * @param {Object} [opts]
 * @param {number} [opts.duration] - Milliseconds before auto-dismiss; 0 keeps it until clicked
 * @returns {() => void} Dismiss function
 */
export function showToast(message, type = 'info', opts = {}) {
    if (!ICONS[type]) type = 'info';
    const root = getContainer();

    // Keep the stack short: drop the oldest when a new one would overflow.
    while (root.children.length >= MAX_VISIBLE) {
        dismissEl(root.firstElementChild, true);
    }

    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    // Errors interrupt screen readers; the rest wait their turn.
    el.setAttribute('role', type === 'error' ? 'alert' : 'status');
    el.setAttribute('aria-live', type === 'error' ? 'assertive' : 'polite');

    const icon = document.createElement('i');
    icon.setAttribute('data-lucide', ICONS[type]);
    icon.className = 'toast-icon';
    const text = document.createElement('span');
    text.className = 'toast-message';
    text.textContent = message;
    el.append(icon, text);
    root.appendChild(el);
    if (typeof lucide !== 'undefined') lucide.createIcons();

    // Next frame so the entrance transition runs.
    requestAnimationFrame(() => el.classList.add('toast-visible'));

    const duration = opts.duration ?? DURATION_MS[type];
    let timer = null;
    const arm = () => {
        if (duration > 0) timer = setTimeout(() => dismissEl(el), duration);
    };
    const disarm = () => {
        if (timer) { clearTimeout(timer); timer = null; }
    };
    // Hovering pauses the clock so a long message can be read.
    el.addEventListener('mouseenter', disarm);
    el.addEventListener('mouseleave', arm);
    el.addEventListener('click', () => dismissEl(el));
    arm();

    return () => dismissEl(el);
}

function dismissEl(el, immediate = false) {
    if (!el || el.dataset.dismissing) return;
    el.dataset.dismissing = '1';
    if (immediate) { el.remove(); return; }
    el.classList.remove('toast-visible');
    el.addEventListener('transitionend', () => el.remove(), { once: true });
    // Fallback in case transitionend never fires (reduced motion, hidden tab).
    setTimeout(() => el.remove(), 400);
}

// Available to any code that reaches showAlert through window as well.
window.showToast = showToast;
