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
            const err = await response.json().catch(() => ({}));
            await showAlert(
                'Could not find thread',
                err.error || `Server returned ${response.status}.`
            );
            return;
        }
        result = await response.json();
    } catch (e) {
        await showAlert('Could not find thread', `Network error: ${e.message}`);
        return;
    }

    const messages = result.thread || [];
    if (messages.length === 0) {
        await showAlert(
            'No thread found',
            'Could not locate this message on the server. It may have been moved or deleted.'
        );
        return;
    }

    // Build a confirmation message. For typical 2–6 message threads this
    // is just a "stage N to Folder" sanity check. For unusually large
    // threads (mailing-list style), reframe it as a question rather than
    // a confirmation.
    const confirmed = await _confirmStageCount({
        count: messages.length,
        destinationFolderId,
        truncated: result.truncated,
        timedOut: result.timed_out,
    });
    if (!confirmed) return;

    // Stage each message. Mirror the shape that staging.js produces for
    // IMAP-sourced emails: state.staged is a Map keyed by email id, value
    // is { email, destinationFolderId, sourceType, sourceAccountId,
    // sourceFolder }. The commit path reads sourceFolder to know which
    // IMAP folder to fetch from (see progress.py line 473).
    let added = 0;
    let skipped = 0;
    for (const m of messages) {
        // Use the message_id as the staged-map key when available; fall
        // back to a synthetic key combining folder+uid. The Review screen
        // doesn't care about the key, only that it's stable and unique.
        const key = m.message_id || `${m.folder}::${m.uid}`;
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

/**
 * Confirmation step between thread-find and the actual stage write.
 *
 * For small threads (≤ 10 messages) the confirm is reassurance ("about
 * to stage 4 to ClientName — go?"). For large threads it reframes
 * as caution ("47 messages — unusually large, continue?").
 */
async function _confirmStageCount({ count, destinationFolderId, truncated, timedOut }) {
    // Find the destination folder's name for the confirmation text
    const folder = (state.folders || []).find(f => String(f.id) === String(destinationFolderId));
    const destName = folder?.name || 'the chosen folder';

    let title;
    let body;
    if (count > 25 || truncated) {
        title = 'Stage large thread?';
        body = `Found ${count} message${count === 1 ? '' : 's'}`
            + (truncated ? ' (and stopped at the limit)' : '')
            + `. That's unusually large for a single conversation — `
            + `mailing-list threads can look like this. Continue staging them to ${destName}?`;
    } else {
        title = 'Stage thread';
        body = `Found ${count} message${count === 1 ? '' : 's'} in this thread. `
            + `Stage them to ${destName}?`;
    }
    if (timedOut) {
        body += ' (The search timed out, so some messages may be missing.)';
    }

    // Use a small inline confirm. showAlert returns void; we need a
    // proper yes/no, so use the same modal helper the rest of the app
    // uses for confirmations.
    const { showConfirm } = await import('../modals.js');
    return await showConfirm(title, body);
}

// Expose for inline onclick wiring from the viewer template
window.openStageThreadModal = openStageThreadModal;
