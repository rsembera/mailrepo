/**
 * Template Bindings
 *
 * Replaces the inline onclick="..." handlers in index.html with a single
 * delegated click handler on document.body. Each template button uses a
 * data-tpl-action attribute; this module maps each action to the
 * appropriate ES-imported function.
 *
 * Why a separate module: the inline-onclick approach required every
 * template-callable function to be assigned to window.X so the inline
 * code could find it. That polluted the global namespace and made the
 * dependency graph invisible (you couldn't tell from any single JS file
 * which of its functions the template depended on). This module makes
 * every template binding explicit and grep-able.
 *
 * The delegated handler walks up from the click target with
 * closest('[data-tpl-action]') so clicks inside nested elements (e.g.
 * an <i> icon inside a <button>) still resolve to the parent button's
 * action.
 *
 * Conventions for handlers that take arguments:
 *   - data-tpl-action="closeModal" with data-modal-id="X" -> closeModal(X)
 *   - data-tpl-action="viewerNavigate" with data-direction="1" -> viewerNavigate(1)
 *   - data-tpl-action="resolveConfirm" with data-confirm="true" -> resolveConfirm(true)
 *   - data-tpl-action="resolvePrompt" with data-prompt-cancel -> resolvePrompt(null)
 *   - data-tpl-action="resolvePrompt" without data-prompt-cancel -> resolvePrompt(<input value>)
 *   - data-tpl-action="railView" with data-rail-view="X" -> clicks the rail button
 */

import { closeModal, resolvePrompt, resolveConfirm, resolveAlert } from './modals.js';
import {
    showArchiveSearch,
    closeEmailViewer,
    toggleStarFromViewer,
    stageThreadFromViewer,
    copyAsReply,
    viewEmailSource,
    downloadEmail,
    printEmail,
    loadRemoteContent,
    viewerNavigate,
} from './views/mail.js';
import { selectAllEmails, clearSelectedEmails } from './components/email-list.js';
import { dismissOverdueAlert, confirmRestoreFolder } from './views/vault.js';
import { showImportModal } from './components/imports.js';
import { confirmMoveFolder } from './views/folder-mgmt.js';
import { confirmMoveEmail } from './components/move-email-modal.js';
import { closeResetDatabaseModal, executeResetDatabase } from './views/settings.js';

/**
 * Programmatically click the rail button for the given view. Used by
 * "Add Account" / "View Vault" / sidebar "Settings" links in the
 * template that want to navigate to a side-rail view.
 */
function activateRailView(view) {
    const btn = document.querySelector(`.rail-btn[data-view="${view}"]`);
    if (btn) btn.click();
}

/**
 * Action -> handler map. Each handler receives (el, ev) where el is
 * the element with data-tpl-action and ev is the click event.
 */
const HANDLERS = {
    // Logout: handleLogout lives in app.js and stays on window for the
    // moment (app.js bootstraps the page; we don't import _from_ app.js
    // here to avoid a circular reference). app.js explicitly registers
    // this handler at init time -- see registerHandler below.

    // Sidebar / navigation
    showArchiveSearch: () => showArchiveSearch(),
    openImport: () => showImportModal(),
    dismissOverdueAlert: () => dismissOverdueAlert(),
    railView: (el) => activateRailView(el.dataset.railView),

    // Email-list toolbar
    selectAllEmails: () => selectAllEmails(),
    clearSelectedEmails: () => clearSelectedEmails(),

    // Email viewer buttons
    toggleStarFromViewer: () => toggleStarFromViewer(),
    stageThreadFromViewer: () => stageThreadFromViewer(),
    copyAsReply: () => copyAsReply(),
    viewEmailSource: () => viewEmailSource(),
    downloadEmail: () => downloadEmail(),
    printEmail: () => printEmail(),
    loadRemoteContent: () => loadRemoteContent(),
    viewerNavigate: (el) => viewerNavigate(Number(el.dataset.direction)),
    closeEmailViewer: () => closeEmailViewer(),

    // Generic modal close: needs data-modal-id="X"
    closeModal: (el) => closeModal(el.dataset.modalId),

    // Prompt/Confirm/Alert resolution
    resolvePrompt: (el) => {
        if (el.hasAttribute('data-prompt-cancel')) {
            resolvePrompt(null);
        } else {
            const input = document.getElementById('promptInput');
            resolvePrompt(input ? input.value : '');
        }
    },
    resolveConfirm: (el) => resolveConfirm(el.dataset.confirm === 'true'),
    resolveAlert: () => resolveAlert(),

    // Move modals
    confirmMoveFolder: () => confirmMoveFolder(),
    confirmMoveEmail: () => confirmMoveEmail(),

    // Vault
    confirmRestoreFolder: () => confirmRestoreFolder(),

    // Reset database (settings)
    closeResetDatabaseModal: () => closeResetDatabaseModal(),
    executeResetDatabase: () => executeResetDatabase(),
};

/**
 * Register an additional template-binding handler. Used for handlers
 * that live in modules we can't import here without creating a circular
 * dependency -- most notably handleLogout in app.js.
 */
export function registerHandler(action, fn) {
    HANDLERS[action] = fn;
}

/**
 * Wire up the single delegated click listener on document.body. Called
 * once at app init.
 */
export function initTemplateBindings() {
    document.body.addEventListener('click', (ev) => {
        const el = ev.target.closest('[data-tpl-action]');
        if (!el) return;
        const action = el.dataset.tplAction;
        const handler = HANDLERS[action];
        if (!handler) {
            console.warn(`[template-bindings] No handler for action: ${action}`);
            return;
        }
        handler(el, ev);
    });
}
