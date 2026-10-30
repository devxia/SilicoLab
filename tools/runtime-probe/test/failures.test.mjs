import assert from 'node:assert/strict';
import test from 'node:test';
import { delay, open, temporary, until } from './client.mjs';

test('admission identity persists when model generation is interrupted', { timeout: 25_000 }, async (t) => {
  const directory = await temporary(t);
  const first = await open(t, directory);
  const admitted = await first.call('submit', { requestId: 'pending-generation', scenario: 'model' });
  await until(first, (s) => s.entered.includes('model'));
  await first.stop('SIGKILL');
  const second = await open(t, directory);
  const saved = await second.call('status');
  assert.equal(saved.scheduling, 'paused');
  assert.equal(saved.modelRequests, 0);
  assert.deepEqual(saved.artifacts, []);
  assert.equal((await second.call('submit', { requestId: 'pending-generation', scenario: 'model' })).submissionId, admitted.submissionId);
  await second.call('resume', { submissionId: admitted.submissionId });
  // The installed package reissues a killed request on selected recovery even with maxRetries=0.
  // Observe that actual behavior, rather than asserting the newer source README's retry policy.
  const retried = await until(second, (s) => s.entered.includes('model'));
  assert.equal(retried.modelRequests, 1);
  assert.equal(retried.entries.filter((e) => e.kind === 'pi.user').length, 1);
  await second.call('release', { scenario: 'model' });
  const stopped = await until(second, (s) => s.submissions.some((s) => s.status === 'done'));
  assert.equal(stopped.modelRequests, 1);
  assert.deepEqual(stopped.artifacts, []);
  await second.stop();
});

test('repeated safe-tool crashes reach a visible bounded recovery stop', { timeout: 40_000 }, async (t) => {
  const directory = await temporary(t);
  let current = await open(t, directory);
  const admitted = await current.call('submit', { requestId: 'crash-loop', scenario: 'safe' });
  for (let attempt = 1; attempt <= 3; attempt++) {
    await until(current, (s) => s.attempts.length === attempt && s.entered.includes('safe'));
    await current.stop('SIGKILL');
    current = await open(t, directory);
    await current.call('resume', { submissionId: admitted.submissionId });
  }
  const stopped = await until(current, (s) => s.tasks.some((task) => task.state.kind === 'blocked' && task.state.reason === 'restart_limit') ||
    s.submissions.some((submission) => submission.status === 'unanswered' || submission.status === 'done'));
  assert.equal(stopped.attempts.length, 3);
  assert.match(JSON.stringify({ tasks: stopped.tasks, entries: stopped.entries }), /restart_limit/);
  await delay(100);
  assert.equal((await current.call('status')).attempts.length, 3);
  await current.stop();
});
