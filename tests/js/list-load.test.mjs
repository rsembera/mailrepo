import test from 'node:test';
import assert from 'node:assert/strict';

const { beginListLoad } = await import('../../web/static/js/list-load.js');

function mailState(folder) {
    return { activeScreen: 'mail', currentView: { type: 'account', id: 1, folder } };
}

test('a load is current until something else is opened', () => {
    const state = mailState('INBOX');
    const inbox = beginListLoad(state);
    assert.equal(inbox(), true);
});

test('opening another folder retires the first load', () => {
    const state = mailState('INBOX');
    const inbox = beginListLoad(state);
    state.currentView = { type: 'account', id: 1, folder: 'Sent' };
    const sent = beginListLoad(state);
    assert.equal(inbox(), false);
    assert.equal(sent(), true);
});

test('going back to the first folder does not revive its old load', () => {
    const state = mailState('INBOX');
    const first = beginListLoad(state);
    state.currentView = { type: 'account', id: 1, folder: 'Sent' };
    beginListLoad(state);
    state.currentView = { type: 'account', id: 1, folder: 'INBOX' };
    const second = beginListLoad(state);
    assert.equal(first(), false);
    assert.equal(second(), true);
});

test('refreshing the same folder retires the load it replaces', () => {
    const state = mailState('INBOX');
    const before = beginListLoad(state);
    const refresh = beginListLoad(state);
    assert.equal(before(), false);
    assert.equal(refresh(), true);
});

test('a view that loads nothing itself still retires the load', () => {
    // Search, an import folder and the staging picker replace
    // currentView without starting a load of their own.
    const state = mailState('INBOX');
    const inbox = beginListLoad(state);
    state.currentView = { type: 'search' };
    assert.equal(inbox(), false);
});

test('another screen retires the load', () => {
    for (const screen of ['review', 'settings', 'trash', 'vault', 'backups', 'starred', 'folderSelection']) {
        const state = mailState('INBOX');
        const inbox = beginListLoad(state);
        state.activeScreen = screen;
        assert.equal(inbox(), false, screen);
    }
});
