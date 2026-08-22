/**
 * Thread Stage component
 *
 * Wires the "Stage thread to..." button in the live email viewer:
 *   click → folder picker → POST /api/threads/find → confirm count →
 *   add all thread members to state.staged with the chosen destination.
 *
 * The user can then navigate to Review and commit the batch using the
 * existing pipeline. No new commit code; the Review screen and commit
 * stream already understand staged items with sourceType='imap',
 * sourceAccountId, and sourceFolder.
 *
 * See docs/Stage_Thread_Plan.md for the design rationale.
 *
 * @module components/thread-stage
 */

import { state, updateStagedBadge } from '../state.js';
import { showAlert } from '../modals.js';
import { openChangeDestinationModal } from './staging.js';
import { renderEmailList, clearEmail } from './email-list.js';

/**
 * Toggle the busy state on the Staged Items rail button.
 *
 * Stage Thread's server call (POST /api/threads/find) is a multi-second
 * IMAP round-trip. Without feedback, the UI sits silent until it
 * returns — which reads as a glitch. While busy, the rail button's icon
 * pulses and a spinner ring shows in the corner, so the click clearly
 * registered and the eventual badge bump reads as completion.
 *
 * @param {boolean} busy - true to show the busy state, false to clear it
 */
function _setStagedRailBusy(busy) {
    const btn = document.getElementById('stagedRailBtn');
    if (!btn) return;
    btn.classList.toggle('busy', busy);

    let spinner = btn.querySelector('.rail-btn-spinner');
    if (busy && !spinner) {
        spinner = document.createElement('span');
        spinner.className = 'rail-btn-spinner';
        btn.appendChild(spinner);
    } else if (!busy && spinner) {
        spinner.remove();
    }
}

/**
 * Open the Stage Thread flow.
 *
 * @param {Object} opts
 * @param {number} opts.accountId       - IMAP account ID of the message
 * @param {string} opts.folder          - IMAP folder name (e.g. "INBOX")
 * @param {string} opts.uid             - IMAP UID of the starting message
 * @param {string} [opts.subject]       - For the count-confirmation modal text
 */
export async function openStageThreadModal(opts) {
    const { accountId, folder, uid, subject } = opts || {};
    if (!accountId || !folder || !uid) {
        console.error('openStageThreadModal: missing required fields', opts);
        return;
    }

    // We reuse the existing change-destination tree-picker modal — same
    // folder-tree component the Stage modal and Move modals use. Passing
    // a callback rather than letting it run staging logic itself.
    openChangeDestinationModal({
        title: 'Stage thread to folder',
        confirmLabel: 'Stage',
        // No current destination to pre-highlight; user is making a fresh pick
        currentDestId: null,
        onConfirm: async (destinationFolderId) => {
            await _findAndStageThread({ accountId, folder, uid, subject, destinationFolderId });
        },
    });
}

/**
 * Run the thread-find and stage the results.
 * Called after the user has picked a destination.
 */
async function _findAndStageThread({ accountId, folder, uid, subject, destinationFolderId }) {
    let result;
    // Show the busy state on the Staged Items rail button while the
    // server round-trip is in flight. We clear it the moment the request
    // resolves — before any error alert — so the spinner's lifetime
    // matches the actual network work, not the time an error modal sits
    // open waiting to be dismissed.
    _setStagedRailBusy(true);
    try {
        const response = await fetch('/api/threads/find', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                account_id: accountId,
                folder,
                uid,
            }),
        });
        if (!response.ok) {
            _setStagedRailBusy(false);
            const err = await response.json().catch(() => ({}));
            await showAlert(
                'Could not find thread',
                err.error || `Server returned ${response.status}.`
            );
            return;
        }
        result = await response.json();
    } catch (e) {
        _setStagedRailBusy(false);
        await showAlert('Could not find thread', `Network error: ${e.message}`);
        return;
    }
    // Request succeeded — staging the results is fast, synchronous work.
    _setStagedRailBusy(false);

    const messages = result.thread || [];
    if (messages.length === 0) {
        await showAlert(
            'No thread found',
            'Could not find this message on the server — it may have been moved or deleted.'
        );
        return;
    }

    // Stage each message. Mirror the shape that staging.js produces for
    // IMAP-sourced emails: state.staged is a Map keyed by email id, value
    // is { email, destinationFolderId, sourceType, sourceAccountId,
    // sourceFolder }. The commit path reads sourceFolder to know which
    // IMAP folder to fetch from (see progress.py line 473).
    let added = 0;
    let skipped = 0;
    for (const m of messages) {
        // Key by UID to match the existing staging convention (see
        // staging.js line ~466: state.staged.set(emailId, ...) where
        // emailId is email.uid || email.id). This is what the email-list
        // renderer checks via state.staged.has(emailId) to gray out
        // staged rows.
        const key = m.uid;
        // If the user individually selected any of these messages before
        // staging the whole conversation, deselect them now — selected and
        // staged are mutually exclusive (selectEmail refuses staged
        // emails), and a stale selection here made confirmNavigation()
        // show a spurious "selected but not staged" warning after the
        // thread was in fact staged. clearEmail() also fires the
        // selection-count refresh. Selection keys come from dataset
        // attributes (strings), so probe both forms.
        const selKey = state.selectedEmails.has(key)
            ? key
            : state.selectedEmails.has(String(key))
                ? String(key)
                : null;
        if (selKey !== null) clearEmail(selKey);
        if (state.staged.has(key)) {
            skipped += 1;
            continue;
        }
        state.staged.set(key, {
            email: {
                uid: m.uid,
                id: m.uid,
                subject: m.subject || '(no subject)',
                from: m.from || '',
                date: m.date || '',
                message_id: m.message_id || '',
            },
            destinationFolderId,
            sourceType: 'imap',
            sourceAccountId: accountId,
            sourceFolder: m.folder,
        });
        added += 1;
    }

    // Persist to sessionStorage (same as staging.js does on its own writes)
    try {
        sessionStorage.setItem(
            'stagedEmails',
            JSON.stringify([...state.staged.entries()])
        );
    } catch (e) {
        // sessionStorage full or unavailable — staged state still lives in
        // memory for this session, which is good enough.
        console.warn('Could not persist staged emails:', e);
    }

    updateStagedBadge();
    // Repaint whichever screen currently owns the shared content area so the
    // newly staged thread appears immediately, rather than clobbering that
    // screen with the inbox list (the bug that showed a hybrid Inbox/Staged
    // view when navigating away mid-stage). If the user has moved to a screen
    // staging doesn't affect, leave it — it renders correctly on return.
    if (state.activeScreen === 'review') {
        const { renderReviewView } = await import('../views/review.js');
        renderReviewView();
    } else if (state.activeScreen === 'mail') {
        renderEmailList();
    }

    // Light status feedback. Skip the modal for the common case (no
    // duplicates, no truncation, no timeout) — the badge update is
    // enough.
    if (skipped > 0 || result.truncated || result.timed_out) {
        const notes = [];
        if (added > 0) notes.push(`Staged ${added} message${added === 1 ? '' : 's'}.`);
        if (skipped > 0) notes.push(`Skipped ${skipped} already staged.`);
        if (result.truncated) {
            notes.push('Thread is larger than the limit — some messages may not be staged.');
        }
        if (result.timed_out) {
            notes.push('Search timed out — some messages may not be staged.');
        }
        await showAlert('Thread staged', notes.join(' '));
    }
}

// Expose for inline onclick wiring from the viewer template
