import test from 'node:test';
import assert from 'node:assert/strict';

const { computeArchivePaths, getFolderName, imapDelimiter } =
    await import('../../web/static/js/archive-paths.js');

test('a staged subfolder is archived inside its staged parent', () => {
    assert.deepEqual(
        computeArchivePaths(['Clients', 'Clients/Smith', 'Clients/Smith/2024', 'Other']),
        { Clients: 'Clients', 'Clients/Smith': 'Clients/Smith', 'Clients/Smith/2024': 'Clients/Smith/2024', Other: 'Other' },
    );
});

test('a subfolder staged without its parent stands alone', () => {
    assert.deepEqual(computeArchivePaths(['Clients/Smith', 'Clients/Jones']), {
        'Clients/Smith': 'Smith',
        'Clients/Jones': 'Jones',
    });
});

test('a skipped level is skipped in the archive too', () => {
    assert.deepEqual(computeArchivePaths(['A', 'A/B/C']), { A: 'A', 'A/B/C': 'A/C' });
});

test('a name that merely starts the same is not a parent', () => {
    assert.deepEqual(computeArchivePaths(['Client', 'Clients/Smith']), {
        Client: 'Client',
        'Clients/Smith': 'Smith',
    });
});

test('dot-separated servers keep their hierarchy', () => {
    assert.deepEqual(
        computeArchivePaths(['INBOX', 'INBOX.Clients', 'INBOX.Clients.Smith', 'Archive.2024'], '.'),
        {
            INBOX: 'INBOX',
            'INBOX.Clients': 'INBOX/Clients',
            'INBOX.Clients.Smith': 'INBOX/Clients/Smith',
            'Archive.2024': '2024',
        },
    );
});

test('with "/" as the separator a dot is part of the name', () => {
    assert.deepEqual(computeArchivePaths(['J. Smith', 'J. Smith/v1.2']), {
        'J. Smith': 'J. Smith',
        'J. Smith/v1.2': 'J. Smith/v1.2',
    });
});

test('a slash in a name on a dot-separated server does not make a level', () => {
    assert.equal(getFolderName('INBOX.A/B Ltd', '.'), 'A-B Ltd');
    assert.deepEqual(computeArchivePaths(['INBOX', 'INBOX.A/B Ltd'], '.'), {
        INBOX: 'INBOX',
        'INBOX.A/B Ltd': 'INBOX/A-B Ltd',
    });
});

test('Apple Mail: Parent.mbox is the parent of what sits in Parent/', () => {
    assert.deepEqual(
        computeArchivePaths(['/x/Fan Mail.mbox', "/x/Fan Mail/Peter O'Connor.mbox", '/x/Home.mbox']),
        {
            '/x/Fan Mail.mbox': 'Fan Mail',
            "/x/Fan Mail/Peter O'Connor.mbox": "Fan Mail/Peter O'Connor",
            '/x/Home.mbox': 'Home',
        },
    );
});

test('the separator comes from what the server reported', () => {
    const folders = new Map([
        [1, { folders: [{ name: 'INBOX', delimiter: '.' }] }],
        ['2', { folders: [{ name: 'INBOX' }, { name: 'A^B', delimiter: '^' }] }],
        [3, { folders: [] }],
    ]);
    assert.equal(imapDelimiter(folders, 1), '.');
    assert.equal(imapDelimiter(folders, '1'), '.');
    assert.equal(imapDelimiter(folders, 2), '^');
    assert.equal(imapDelimiter(folders, '2'), '^');
    assert.equal(imapDelimiter(folders, 3), '/');
    assert.equal(imapDelimiter(folders, 99), '/');
});
