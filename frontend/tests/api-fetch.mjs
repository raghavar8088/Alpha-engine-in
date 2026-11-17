// apiFetch request hygiene: in-flight GET sharing, hidden-tab pause, paused-module memory.
// Run: node tests/api-fetch.mjs
import assert from 'node:assert/strict';

let calls = [];
let failNext = false;
globalThis.fetch = async (url, init = {}) => {
  calls.push({ url, method: (init.method || 'GET').toUpperCase() });
  await new Promise((r) => setTimeout(r, 15));
  if (failNext) {
    failNext = false;
    return new Response(JSON.stringify({ detail: 'boom' }), { status: 500 });
  }
  return new Response(JSON.stringify({ url, rows: [3, 1, 2] }), { status: 200 });
};

const listeners = new Set();
globalThis.document = {
  hidden: false,
  addEventListener: (t, fn) => t === 'visibilitychange' && listeners.add(fn),
  removeEventListener: (t, fn) => listeners.delete(fn),
};
const setHidden = (h) => {
  document.hidden = h;
  for (const fn of [...listeners]) fn();
};

const { apiFetch, setPausedApiPrefixes, refreshing } = await import('../lib/api.ts');
const reset = () => { calls = []; };

// 1. identical GETs in flight share one request, and each caller gets its own copy
reset();
const [a, b] = await Promise.all([apiFetch('/api/x/list'), apiFetch('/api/x/list')]);
assert.equal(calls.length, 1, 'two identical GETs -> one request');
assert.deepEqual(a, b);
a.rows.sort();
assert.deepEqual(b.rows, [3, 1, 2], 'sorting one caller\'s copy does not touch the other');

// 2. after it settles, the next GET asks again (no hidden caching for ACTIVE modules)
reset();
await apiFetch('/api/x/list');
assert.equal(calls.length, 1, 'a later GET is a new request');

// 3. writes are never shared
reset();
await Promise.all([apiFetch('/api/x/run', { method: 'POST' }), apiFetch('/api/x/run', { method: 'POST' })]);
assert.equal(calls.length, 2, 'POSTs always go through');

// 4. a GET with its own AbortSignal is left alone
reset();
await Promise.all([
  apiFetch('/api/x/list', { signal: new AbortController().signal }),
  apiFetch('/api/x/list', { signal: new AbortController().signal }),
]);
assert.equal(calls.length, 2, 'caller-controlled GETs are not shared');

// 5. a hidden tab's polls wait, then collapse into one request when visible
reset();
setHidden(true);
const polls = [apiFetch('/api/x/poll'), apiFetch('/api/x/poll'), apiFetch('/api/x/poll')];
await new Promise((r) => setTimeout(r, 40));
assert.equal(calls.length, 0, 'nothing is sent while the tab is hidden');
setHidden(false);
const got = await Promise.all(polls);
assert.equal(calls.length, 1, 'three hidden polls -> one request on return');
assert.equal(got.length, 3);

// 6. an error reaches every sharer, and the next call tries again
reset();
failNext = true;
const errs = await Promise.allSettled([apiFetch('/api/x/err'), apiFetch('/api/x/err')]);
assert.ok(errs.every((e) => e.status === 'rejected' && /boom/.test(e.reason.message)), 'both sharers see the error');
await apiFetch('/api/x/err');
assert.equal(calls.length, 2, 'a failed request is not remembered');

// 7. a PAUSED module's reads are served from memory; Refresh still goes to the server
reset();
setPausedApiPrefixes(['/api/frozen']);
await apiFetch('/api/frozen/summary');
const again = await apiFetch('/api/frozen/summary');
assert.equal(calls.length, 1, 'repeat read of a paused module comes from memory');
assert.ok(again.rows, 'memory answer has the data');
await refreshing(() => apiFetch('/api/frozen/summary'));
assert.equal(calls.length, 2, 'Refresh (fresh=true) bypasses the memory');
assert.ok(calls[1].url.includes('fresh=true'));
await apiFetch('/api/frozen-other/summary');
await apiFetch('/api/frozen-other/summary');
assert.equal(calls.length, 4, 'prefix match is segment-bounded (/api/frozen-other is not paused)');
setPausedApiPrefixes([]);
await apiFetch('/api/frozen/summary');
assert.equal(calls.length, 5, 'switched back on: memory dropped, reads go to the server');

console.log('apiFetch sharing, hidden-tab pause, paused-module memory: all checks passed.');
