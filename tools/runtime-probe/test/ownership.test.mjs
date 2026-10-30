import assert from 'node:assert/strict';
import test from 'node:test';
import { symlink } from 'node:fs/promises';
import { join } from 'node:path';
import { open, temporary, until } from './client.mjs';

for (const stop of [undefined, 'SIGKILL']) {
  test(`single owner excludes an alias opener and releases after ${stop ?? 'normal close'}`, { timeout: 25_000 }, async (t) => {
    const directory = await temporary(t);
    const alias = join(directory, 'same-storage');
    await symlink(directory, alias);
    const first = await open(t, directory);
    await first.call('submit', { requestId: 'owner-request', scenario: 'safe' });
    await until(first, (s) => s.entered.includes('safe'));
    await assert.rejects(open(t, alias), /already owned/);
    const stillOwned = await first.call('status');
    assert.equal(stillOwned.attempts.length, 1);
    await first.stop(stop);
    const second = await open(t, alias);
    assert.equal((await second.call('status')).scheduling, 'paused');
    await second.stop();
  });
}

test('persisted completed tool result is reused when later work was killed', { timeout: 25_000 }, async (t) => {
  const directory = await temporary(t);
  const first = await open(t, directory);
  const admitted = await first.call('submit', { requestId: 'two-step-request', scenario: 'sequence' });
  const before = await until(first, (s) => s.entered.includes('unsafe'));
  assert.equal(before.entries.filter((e) => e.kind === 'pi.tool-result').length, 1);
  assert.deepEqual(before.attempts.map((a) => a.replay), ['safe', 'unsafe']);
  await first.stop('SIGKILL');
  const second = await open(t, directory);
  await second.call('resume', { submissionId: admitted.submissionId });
  const after = await until(second, (s) => s.submissions.some((s) => s.status === 'done'));
  assert.deepEqual(after.attempts, before.attempts);
  assert.deepEqual(after.artifacts, before.artifacts);
  assert.equal(after.entries.filter((e) => e.kind === 'pi.tool-result').length, 2);
  await second.stop();
});
