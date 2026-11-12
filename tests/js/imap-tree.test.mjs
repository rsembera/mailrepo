import test from 'node:test';
import assert from 'node:assert/strict';

const { buildImapFolderTree } = await import('../../web/static/js/imap-tree.js');

const names = nodes => nodes.map(n => n.name);
const find = (nodes, path) => {
    for (const n of nodes) {
        if (n.fullPath === path) return n;
        const below = find(n.children, path);
        if (below) return below;
    }
    return null;
};

test('folders nest by the separator the server reports', () => {
    const tree = buildImapFolderTree([
        { name: 'INBOX', delimiter: '.' },
        { name: 'INBOX.Clients', delimiter: '.' },
        { name: 'INBOX.Clients.Smith', delimiter: '.' },
    ]);
    assert.deepEqual(names(tree), ['INBOX']);
    assert.equal(find(tree, 'INBOX.Clients.Smith').name, 'Smith');
    assert.equal(find(tree, 'INBOX.Clients').noselect, false);
});

test('a level the server never listed cannot be opened or staged', () => {
    const tree = buildImapFolderTree([
        { name: 'INBOX', delimiter: '/' },
        { name: 'Projects/2024/Alpha', delimiter: '/' },
    ]);
    assert.equal(find(tree, 'Projects').noselect, true);
    assert.equal(find(tree, 'Projects/2024').noselect, true);
    assert.equal(find(tree, 'Projects/2024/Alpha').noselect, false);
    assert.equal(find(tree, 'INBOX').noselect, false);
});

test('a parent listed after its child is still a mailbox', () => {
    const tree = buildImapFolderTree([
        { name: 'A/B', delimiter: '/' },
        { name: 'A', delimiter: '/' },
    ]);
    assert.equal(find(tree, 'A').noselect, false);
    assert.equal(find(tree, 'A/B').noselect, false);
});

test("the server's own noselect is kept", () => {
    const tree = buildImapFolderTree([
        { name: '[Gmail]', delimiter: '/', noselect: true },
        { name: '[Gmail]/Sent Mail', delimiter: '/' },
    ]);
    assert.equal(find(tree, '[Gmail]').noselect, true);
    assert.equal(find(tree, '[Gmail]/Sent Mail').noselect, false);
});

test('the usual folders come first', () => {
    const tree = buildImapFolderTree(
        ['Zebra', 'Sent', 'Apple', 'INBOX', 'Trash'].map(name => ({ name, delimiter: '/' })),
    );
    assert.deepEqual(names(tree), ['INBOX', 'Sent', 'Trash', 'Apple', 'Zebra']);
});

test('a server with no hierarchy gives a flat list', () => {
    const tree = buildImapFolderTree([{ name: 'INBOX' }, { name: 'Clients.Smith' }]);
    assert.deepEqual(names(tree).sort(), ['Clients.Smith', 'INBOX']);
});
