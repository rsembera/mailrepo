// Run with: node --test tests/js
// (tests/test_frontend_js.py runs this from pytest when Node is installed.)
import test from 'node:test';
import assert from 'node:assert/strict';

// Just enough of a browser for state.js and its imports to load.
const store = new Map();
globalThis.sessionStorage = {
    getItem: k => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: k => store.delete(k),
};
globalThis.document = { getElementById: () => null, addEventListener: () => {} };

const { stagedKey, stagedKeyOfItem, stagedKeyInView, viewSource } =
    await import('../../web/static/js/staged-key.js');
const { state, isStagedInView, unstageInView, persistStaged, restoreStaged } =
    await import('../../web/static/js/state.js');
const { escapeHtml } = await import('../../web/static/js/utils.js');

function imapItem(account, folder, uid) {
    return {
        email: { uid, subject: `msg ${uid}` },
        destinationFolderId: 3,
        sourceType: 'imap',
        sourceAccountId: account,
        sourceFolder: folder,
    };
}

function reset() {
    state.staged = new Map();
    state.stagedFolders = [];
    state.currentView = null;
    store.clear();
}

test('the same UID in another folder or account is a different email', () => {
    const inbox = stagedKeyOfItem(imapItem(1, 'INBOX', '12'));
    assert.notEqual(inbox, stagedKeyOfItem(imapItem(1, 'Sent', '12')));
    assert.notEqual(inbox, stagedKeyOfItem(imapItem(2, 'INBOX', '12')));
    assert.equal(inbox, stagedKeyOfItem(imapItem(1, 'INBOX', 12)));
});

test('the same import id in another import or folder is a different email', () => {
    const item = (imp, folder) => ({
        email: { uid: 'mbox-0' }, sourceType: 'import', sourceImportId: imp, sourceFolder: folder,
    });
    assert.notEqual(stagedKeyOfItem(item('a', null)), stagedKeyOfItem(item('b', null)));
    assert.notEqual(stagedKeyOfItem(item('a', 'Work')), stagedKeyOfItem(item('a', 'Home')));
});

test('folder names cannot run into the id', () => {
    assert.notEqual(stagedKey('imap', 1, 'a', 'b|c'), stagedKey('imap', 1, 'a|b', 'c'));
    assert.notEqual(stagedKey('imap', 1, 'a","b', 'c'), stagedKey('imap', 1, 'a', 'b","c'));
});

test('a view key matches the key of what was staged from that view', () => {
    const view = { type: 'account', id: 1, folder: 'Sent' };
    assert.equal(stagedKeyInView(view, '12'), stagedKeyOfItem(imapItem(1, 'Sent', '12')));
    // An account view with no folder is the inbox, as staging records it.
    assert.equal(
        stagedKeyInView({ type: 'account', id: 1 }, 12),
        stagedKeyOfItem(imapItem(1, 'INBOX', '12')),
    );
    const imp = { email: { uid: 'eml-a.eml' }, sourceType: 'import', sourceImportId: 'x', sourceFolder: null };
    assert.equal(stagedKeyInView({ type: 'import', id: 'x' }, 'eml-a.eml'), stagedKeyOfItem(imp));
});

test('archive, search and starred views stage nothing', () => {
    for (const type of ['folder', 'search', 'starred', 'accountFolders']) {
        assert.equal(viewSource({ type, id: 1 }), null);
        assert.equal(stagedKeyInView({ type, id: 1 }, '12'), null);
    }
    assert.equal(stagedKeyInView(null, '12'), null);
});

test('a staged inbox message does not mark its namesake in Sent', () => {
    reset();
    const item = imapItem(1, 'INBOX', '12');
    state.staged.set(stagedKeyOfItem(item), item);

    state.currentView = { type: 'account', id: 1, folder: 'INBOX' };
    assert.equal(isStagedInView('12'), true);
    state.currentView = { type: 'account', id: 1, folder: 'Sent' };
    assert.equal(isStagedInView('12'), false);
    assert.equal(unstageInView('12'), false);
    assert.equal(state.staged.size, 1);
    state.currentView = { type: 'folder', id: 1 };
    assert.equal(isStagedInView('12'), false);
});

test('unstaging the last email removes it from storage', () => {
    reset();
    const item = imapItem(1, 'INBOX', '12');
    state.staged.set(stagedKeyOfItem(item), item);
    persistStaged();
    assert.ok(store.has('stagedEmails'));

    state.currentView = { type: 'account', id: 1, folder: 'INBOX' };
    assert.equal(unstageInView('12'), true);
    assert.equal(store.has('stagedEmails'), false);

    // Nothing comes back on the next page load.
    state.staged = new Map();
    restoreStaged();
    assert.equal(state.staged.size, 0);
});

test('staged emails and folders survive a page load', () => {
    reset();
    const a = imapItem(1, 'INBOX', '12');
    const b = imapItem(1, 'Sent', '12');
    state.staged.set(stagedKeyOfItem(a), a);
    state.staged.set(stagedKeyOfItem(b), b);
    state.stagedFolders = [{ sourceType: 'account', accountId: 1, folder: 'Old', destinationFolderId: 3 }];
    persistStaged();

    state.staged = new Map();
    state.stagedFolders = [];
    restoreStaged();
    assert.equal(state.staged.size, 2);
    assert.deepEqual(state.staged.get(stagedKeyOfItem(b)), b);
    assert.equal(state.stagedFolders.length, 1);

    state.stagedFolders = [];
    persistStaged();
    assert.equal(store.has('stagedFolders'), false);
});

test('entries saved under the old bare-id keys are rekeyed on load', () => {
    reset();
    const a = imapItem(1, 'INBOX', '12');
    store.set('stagedEmails', JSON.stringify([['12', a]]));
    restoreStaged();
    assert.deepEqual([...state.staged.keys()], [stagedKeyOfItem(a)]);
});

test('storage that refuses writes does not break staging', () => {
    reset();
    const item = imapItem(1, 'INBOX', '12');
    state.staged.set(stagedKeyOfItem(item), item);
    const original = sessionStorage.setItem;
    const warn = console.warn;
    sessionStorage.setItem = () => { throw new Error('quota'); };
    console.warn = () => {};
    try {
        assert.doesNotThrow(() => persistStaged());
    } finally {
        sessionStorage.setItem = original;
        console.warn = warn;
    }
});

// What a browser does to a double-quoted attribute value on the way back
// out through element.dataset.
function attributeValue(escaped) {
    return escaped
        .replace(/&quot;/g, '"').replace(/&#39;/g, "'")
        .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
}

test('a folder name survives the trip through a data attribute', () => {
    for (const name of ["Fan Mail/Peter O'Connor", 'back\\slash', 'say "hi"', 'R&D <old>', 'a&quot;b']) {
        const escaped = escapeHtml(name);
        assert.equal(/["'<>]/.test(escaped), false, escaped);
        assert.equal(attributeValue(escaped), name);
    }
});

test('an unparseable date comes back as given, so callers must escape it', async () => {
    const { formatDate } = await import('../../web/static/js/utils.js');
    const header = '<img src=x onerror=alert(1)>';
    assert.equal(formatDate(header), header);
    assert.equal(/[<>]/.test(escapeHtml(formatDate(header))), false);
});

function importItem(importId, uid) {
    return { email: { uid }, destinationFolderId: 3, sourceType: 'import', sourceImportId: importId, sourceFolder: null };
}

test('unmounting an import unstages what came from it and nothing else', async () => {
    const { unstageImport } = await import('../../web/static/js/state.js');
    reset();
    for (const item of [importItem('pst-1', 'mbox-0'), importItem('pst-1', 'mbox-1'), importItem('mbox-2', 'mbox-0'), imapItem(1, 'INBOX', '5')]) {
        state.staged.set(stagedKeyOfItem(item), item);
    }
    state.stagedFolders = [
        { sourceType: 'import', importId: 'pst-1', folder: 'Inbox', destinationFolderId: 3 },
        { sourceType: 'import', importId: 'mbox-2', folder: 'Old', destinationFolderId: 3 },
        { sourceType: 'account', accountId: 1, folder: 'pst-1', destinationFolderId: 3 },
    ];
    assert.equal(unstageImport('pst-1'), 3);
    assert.equal(state.staged.size, 2);
    assert.deepEqual(state.stagedFolders.map(sf => sf.importId || sf.accountId), ['mbox-2', 1]);
    assert.equal(JSON.parse(store.get('stagedEmails')).length, 2);
    assert.equal(unstageImport('pst-1'), 0);
});

test('items staged from a PST import do not come back after a page load', () => {
    reset();
    for (const item of [importItem('pst-1', 'mbox-0'), importItem('mbox-2', 'mbox-0'), imapItem(1, 'INBOX', '5')]) {
        state.staged.set(stagedKeyOfItem(item), item);
    }
    state.stagedFolders = [
        { sourceType: 'import', importId: 'pst-1', folder: 'Inbox' },
        { sourceType: 'import', importId: 'eml-9', folder: 'Old' },
    ];
    persistStaged();
    state.staged = new Map();
    state.stagedFolders = [];
    restoreStaged();
    assert.deepEqual([...state.staged.values()].map(i => i.sourceImportId || 'imap').sort(), ['imap', 'mbox-2']);
    assert.deepEqual(state.stagedFolders.map(sf => sf.importId), ['eml-9']);
});
