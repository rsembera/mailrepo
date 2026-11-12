// Run with: node --test tests/js/*.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';

const { createProgress } = await import('../../web/static/js/components/progress.js');

function sse(event, data) {
    return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

/** A fetch() that answers with the given chunks as a streamed body. */
function respondWith(chunks, { ok = true, status = 200, json = null } = {}) {
    const encoder = new TextEncoder();
    const queue = chunks.map(c => encoder.encode(c));
    globalThis.fetch = async () => ({
        ok,
        status,
        json: async () => {
            if (json === null) throw new Error('not json');
            return json;
        },
        body: {
            getReader: () => ({
                read: async () => (queue.length ? { done: false, value: queue.shift() } : { done: true }),
            }),
        },
    });
}

async function run() {
    const calls = { complete: [], error: [] };
    const progress = createProgress({ innerHTML: '' });
    await progress.startPostStream('/api/commit/stream', {}, {
        onComplete: d => calls.complete.push(d),
        onError: e => calls.error.push(e),
    });
    return calls;
}

test('a finished commit reports once', async () => {
    respondWith([sse('start', { total: 1 }), sse('complete', { message: 'Archived 1 email.' })]);
    const calls = await run();
    assert.equal(calls.complete.length, 1);
    assert.equal(calls.complete[0].message, 'Archived 1 email.');
    assert.deepEqual(calls.error, []);
});

test('an event split across network reads is still delivered', async () => {
    const whole = sse('complete', { message: 'done' });
    respondWith([whole.slice(0, 12), whole.slice(12, 30), whole.slice(30)]);
    const calls = await run();
    assert.equal(calls.complete.length, 1);
    assert.deepEqual(calls.error, []);
});

test("the server's own error is not replaced by 'connection lost'", async () => {
    respondWith([sse('error', { error: 'No items to commit' })]);
    const calls = await run();
    assert.deepEqual(calls.error, [{ error: 'No items to commit' }]);
});

test('a stream that just stops is reported as a lost connection', async () => {
    respondWith([sse('start', { total: 3 }), sse('progress', { current: 1, total: 3 })]);
    const calls = await run();
    assert.equal(calls.error.length, 1);
    assert.match(calls.error[0].error, /Connection to server was lost/);
    assert.deepEqual(calls.complete, []);
});

test('a refused request shows what the server said', async () => {
    respondWith([], { ok: false, status: 401, json: { error: 'Session locked' } });
    assert.deepEqual((await run()).error, [{ error: 'Session locked' }]);
    respondWith([], { ok: false, status: 502 });
    assert.deepEqual((await run()).error, [{ error: 'HTTP 502' }]);
});
