/**
 * MailRepo - Staged email keys
 *
 * A staged email is identified by where it came from as well as its id.
 * IMAP UIDs are only unique inside one folder of one account, and import
 * ids ("mbox-0", "eml-<file name>") only inside one folder of one import,
 * so the bare id is not enough: message 12 in Sent used to count as
 * "already staged" because message 12 in INBOX was.
 *
 * No DOM and no imports, so this can be exercised from Node.
 */

/**
 * @param {string} sourceType - 'imap' or 'import'
 * @param {number|string} sourceId - account id or import id
 * @param {string|null|undefined} folder - source folder
 * @param {number|string} uid - id of the email within that folder
 * @returns {string}
 */
export function stagedKey(sourceType, sourceId, folder, uid) {
    return JSON.stringify([sourceType, String(sourceId), folder || '', String(uid)]);
}

/**
 * Key of an entry in state.staged, from the entry itself.
 * @param {Object} item - { email, sourceType, sourceAccountId|sourceImportId, sourceFolder }
 * @returns {string}
 */
export function stagedKeyOfItem(item) {
    const email = item.email || {};
    const sourceId = item.sourceType === 'import' ? item.sourceImportId : item.sourceAccountId;
    return stagedKey(item.sourceType, sourceId, item.sourceFolder, email.uid || email.id);
}

/**
 * The source an email list view stages from, or null if the view is not
 * one emails can be staged from (archive folders, search, starred).
 * @param {Object|null} view - state.currentView
 * @returns {{sourceType: string, sourceId: number|string, folder: string|null}|null}
 */
export function viewSource(view) {
    if (!view) return null;
    if (view.type === 'account') {
        return { sourceType: 'imap', sourceId: view.id, folder: view.folder || 'INBOX' };
    }
    if (view.type === 'import') {
        return { sourceType: 'import', sourceId: view.id, folder: view.folder || null };
    }
    return null;
}

/**
 * Key for an email shown in the given view, or null if nothing in that
 * view can be staged.
 * @param {Object|null} view - state.currentView
 * @param {number|string} emailId - email.uid || email.id
 * @returns {string|null}
 */
export function stagedKeyInView(view, emailId) {
    const source = viewSource(view);
    if (!source) return null;
    return stagedKey(source.sourceType, source.sourceId, source.folder, emailId);
}
