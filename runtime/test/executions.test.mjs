import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { BACKGROUND_CONTEXT as ctx } from '@earendil-works/chord/context';
import { createModels } from '@earendil-works/pi-ai/models';
import { createRegistry, Harness } from '@earendil-works/pi-durable';
import { openNodeSqliteStorage } from '@earendil-works/pi-durable/storage/sqlite/node';
import { ExecutionOwner, ExecutionStores } from '../src/executions.ts';

const options = () => ({ models: createModels(), registry: createRegistry() });
async function directory(t) {
  const path = await mkdtemp(join(tmpdir(), 'silicolab-store-ownership-'));
  t.after(() => rm(path, { recursive: true, force: true }));
  return path;
}

test('concurrent misses beyond capacity share one real pinned owner and close that owner', async (t) => {
  const root = await directory(t);
  const opening = Promise.withResolvers();
  const release = Promise.withResolvers();
  let raceOpens = 0;
  let live = 0;
  let maximum = 0;
  const handles = [];
  const pool = new ExecutionStores(root, options, async (path, configuration) => {
    if (path.includes('/raced/')) { raceOpens++; opening.resolve(); await release.promise; }
    const host = await Harness.open(await openNodeSqliteStorage(path), configuration, ctx);
    live++; maximum = Math.max(maximum, live); handles.push(host);
    void host.closed.then(() => { live--; });
    return host;
  });
  try {
    for (let index = 0; index < 8; index++) await pool.withStore(`history-${index}`, async (host) => host.root(ctx));
    pool.pin('raced');
    const first = pool.openPinned('raced');
    const second = pool.openPinned('raced');
    const observer = pool.withStore('raced', async (host) => host.snapshot(ExecutionOwner, ctx));
    await opening.promise;
    assert.equal(raceOpens, 1);
    release.resolve();
    const [one, two, owner] = await Promise.all([first, second, observer]);
    assert.equal(one, two);
    assert.deepEqual(owner, { taskId: 'raced' });
    assert.equal(maximum, 8);
    await Promise.all(Array.from({ length: 12 }, (_, index) => pool.withStore(`additional-${index}`, async (host) => host.root(ctx))));
    assert.deepEqual(await one.snapshot(ExecutionOwner, ctx), { taskId: 'raced' });
    assert.ok(maximum <= 8);
    await pool.close('raced');
    assert.equal((await one.closed).reason, 'closed');
  } finally { release.resolve(); await pool.closeAll(); }
  await Promise.all(handles.map((host) => host.closed));
  assert.equal(live, 0);
});

test('borrowed history is not evicted during a barrier read or replaced during automatic admission', async (t) => {
  const root = await directory(t);
  const pool = new ExecutionStores(root, options);
  const entered = Promise.withResolvers();
  const release = Promise.withResolvers();
  let borrowed;
  try {
    for (let index = 0; index < 8; index++) await pool.withStore(`old-${index}`, async (host) => host.root(ctx));
    const history = pool.withStore('old-0', async (host) => {
      borrowed = host; entered.resolve(); await release.promise;
      return host.snapshot(ExecutionOwner, ctx);
    });
    await entered.promise;
    pool.pin('old-0');
    const admitted = pool.openPinned('old-0');
    const churn = Promise.all(Array.from({ length: 10 }, (_, index) => pool.withStore(`new-${index}`, async (host) => host.root(ctx))));
    release.resolve();
    const [identity, actual] = await Promise.all([history, admitted, churn]);
    assert.deepEqual(identity, { taskId: 'old-0' });
    assert.equal(actual, borrowed);
    await pool.close('old-0');
    assert.equal((await actual.closed).reason, 'closed');
  } finally { release.resolve(); await pool.closeAll(); }
});

test('owner validation failure closes the opened real harness and does not cache it', async (t) => {
  const root = await directory(t);
  const original = new ExecutionStores(root, options);
  await original.withStore('mismatch', async (host) => host.commit(async (tx) => { (await tx.doc(ExecutionOwner)).taskId = 'different'; }, ctx));
  await original.closeAll();
  const opened = [];
  const pool = new ExecutionStores(root, options, async (path, configuration) => {
    const host = await Harness.open(await openNodeSqliteStorage(path), configuration, ctx);
    opened.push(host);
    return host;
  });
  try {
    await assert.rejects(pool.withStore('mismatch', async (host) => host.root(ctx)), /任务身份不符/);
    assert.equal((await opened[0].closed).reason, 'closed');
    await assert.rejects(pool.withStore('mismatch', async (host) => host.root(ctx)), /任务身份不符/);
    assert.equal(opened.length, 2);
    assert.equal((await opened[1].closed).reason, 'closed');
    await pool.withStore('valid', async (host) => assert.deepEqual(await host.snapshot(ExecutionOwner, ctx), { taskId: 'valid' }));
  } finally { await pool.closeAll(); }
});
