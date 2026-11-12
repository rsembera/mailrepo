import test from 'node:test';
import assert from 'node:assert/strict';

function element() {
    return { textContent: '', className: '', classList: { add() {}, remove() {} }, style: {}, value: '', focus() {}, select() {} };
}
const els = new Map();
const get = id => {
    if (!els.has(id)) els.set(id, element());
    return els.get(id);
};
globalThis.document = {
    getElementById: get,
    querySelector: sel => (sel === '#confirmModal [data-confirm="false"]' ? get('confirmCancelBtn') : null),
    addEventListener() {},
};
globalThis.window = globalThis;

const { showConfirm, resolveConfirm } = await import('../../web/static/js/modals.js');

async function ask(options) {
    const answer = showConfirm('Title', 'Message', options);
    const seen = {
        ok: get('confirmOkBtn').textContent,
        okClass: get('confirmOkBtn').className,
        cancel: get('confirmCancelBtn').textContent,
    };
    resolveConfirm(false);
    await answer;
    return seen;
}

test('the buttons say what the caller asked for', async () => {
    const seen = await ask({ confirmText: 'Resume', cancelText: 'Discard', confirmClass: 'btn-primary' });
    assert.deepEqual(seen, { ok: 'Resume', okClass: 'btn btn-primary', cancel: 'Discard' });
});

test('a destructive confirmation is styled as one, under either option name', async () => {
    assert.equal((await ask({ confirmText: 'Unstage All', confirmClass: 'btn-danger' })).okClass, 'btn btn-danger');
    assert.equal((await ask({ okText: 'Delete', danger: true })).okClass, 'btn btn-danger');
    assert.equal((await ask({ okText: 'Delete', danger: true })).ok, 'Delete');
});

test("one dialog's labels do not carry over to the next", async () => {
    await ask({ confirmText: 'Resume', cancelText: 'Discard' });
    assert.deepEqual(await ask(), { ok: 'OK', okClass: 'btn btn-primary', cancel: 'Cancel' });
});
