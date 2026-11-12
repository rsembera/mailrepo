/**
 * MailRepo - Guard for asynchronous list loads
 *
 * A mailbox list arrives in pieces: cached rows at once, the server's
 * answer some seconds later. By then the reader may have opened another
 * folder, a search, or another screen altogether. A load that is no
 * longer the one on screen must not write its rows into state.emails:
 * they would be shown under the new folder's name and staged as if they
 * came from it.
 *
 * No DOM and no imports, so this can be exercised from Node.
 */

let latest = 0;

/**
 * Start a list load. Call after state.currentView is set for it.
 * @param {Object} state - the app state ({ currentView, activeScreen })
 * @returns {() => boolean} true while this is still the load on screen
 */
export function beginListLoad(state) {
    const token = ++latest;
    const view = state.currentView;
    return () => token === latest
        && state.currentView === view
        && state.activeScreen === 'mail';
}
