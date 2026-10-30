import assert from 'node:assert/strict';
import test from 'node:test';
import { delay, open, temporary, until } from './client.mjs';

test('completed result survives both normal close and a forced process kill', { timeout: 25_000 }, async (t) => {
  const directory = await temporary(t);
  const first = await open(t, directory);
  const { conversationId } = await first.call('create');
  const admitted = await first.call('submit', { requestId: 'literal-result-1', scenario: 'complete' });
  const done = await until(first, (s) => s.submissions.some((s) => s.status === 'done'));
  assert.deepEqual(done.artifacts.map((a) => a.content), ['synthetic-count=3\n']);
  assert.equal(done.entries.filter((e) => e.kind === 'pi.user').length, 1);
  assert.ok(done.entries.some((e) => e.kind === 'pi.tool-result'));
  assert.ok(done.modelRequests >= 2);
  await first.stop();

  const second = await open(t, directory);
  const saved = await second.call('status');
  assert.equal(saved.conversationId, conversationId);
  assert.equal(saved.scheduling, 'paused');
  assert.equal(saved.modelRequests, 0);
  assert.deepEqual(saved.artifacts, done.artifacts);
  assert.deepEqual(saved.entries, done.entries);
  const duplicate = await second.call('submit', { requestId: 'literal-result-1', scenario: 'complete' });
  assert.equal(duplicate.submissionId, admitted.submissionId);
  assert.equal((await second.call('status')).modelRequests, 0);
  const savedAgain = await second.call('status');
  assert.equal(savedAgain.scheduling, 'paused');
  await second.stop('SIGKILL');
  const third = await open(t, directory);
  const afterKill = await third.call('status');
  assert.equal(afterKill.scheduling, 'paused');
  assert.equal(afterKill.modelRequests, 0);
  assert.deepEqual(afterKill.artifacts, done.artifacts);
  assert.deepEqual(afterKill.entries, done.entries);
  await third.stop();
});

for (const stop of [undefined, 'SIGKILL']) {
  for (const scenario of ['safe', 'unsafe']) {
    test(`${stop ?? 'normal close'} during ${scenario} tool: reopen is inert, selected recovery preserves identity`, { timeout: 25_000 }, async (t) => {
      const directory = await temporary(t);
      const first = await open(t, directory);
      const admitted = await first.call('submit', { requestId: 'interrupted-1', scenario });
      const interrupted = await until(first, (s) => s.entered.includes(scenario));
      assert.equal(interrupted.attempts.length, 1);
      assert.equal(interrupted.entries.filter((e) => e.kind === 'pi.tool-result').length, 0);
      await first.stop(stop);

      const second = await open(t, directory);
      const saved = await second.call('status');
      assert.equal(saved.scheduling, 'paused');
      assert.equal(saved.modelRequests, 0);
      await delay(100);
      assert.deepEqual((await second.call('status')).attempts, interrupted.attempts);
      const duplicate = await second.call('submit', { requestId: 'interrupted-1', scenario });
      assert.equal(duplicate.submissionId, admitted.submissionId);
      assert.equal((await second.call('status')).scheduling, 'paused');
      await assert.rejects(second.call('resume', { submissionId: -999 }), /select the pending submission/);
      assert.equal((await second.call('status')).scheduling, 'paused');
      await second.call('release', { scenario });
      await second.call('resume', { submissionId: admitted.submissionId });
      const settled = await until(second, (s) => s.submissions.some((s) => s.status === 'done'));
      assert.deepEqual(settled.artifacts, interrupted.artifacts);
      assert.equal(settled.entries.filter((e) => e.kind === 'pi.user').length, 1);
      const results = settled.entries.filter((e) => e.kind === 'pi.tool-result');
      assert.equal(results.length, 1);
      assert.equal(Boolean(results[0].model[0].isError), scenario === 'unsafe');
      assert.equal(settled.attempts.length, scenario === 'safe' ? 2 : 1);
      assert.equal(new Set(settled.attempts.map((attempt) => attempt.taskId)).size, 1);
      if (scenario === 'unsafe') assert.match(JSON.stringify(results[0]), /interrupted/i);
      await second.stop();
    });
  }
}

for (const stop of [undefined, 'SIGKILL']) {
  for (const scenario of ['sleep', 'waiting']) {
    test(`${stop ?? 'normal close'} preserves durable ${scenario} without auto-waking on reopen`, { timeout: 25_000 }, async (t) => {
      const directory = await temporary(t);
      const first = await open(t, directory);
      const admitted = await first.call('submit', { requestId: 'durable-wait-1', scenario });
      const checkpoint = await until(first, (s) => s.tasks.some((task) => task.record.kind === 'probe.sleep' && task.state.kind === 'sleeping') &&
        (scenario !== 'waiting' || s.tasks.some((task) => task.record.kind === 'probe.join' && task.record.state.status === 'waiting')));
      const sleeping = checkpoint.tasks.find((task) => task.record.kind === 'probe.sleep');
      const deadline = sleeping.state.until;
      await first.stop(stop);
      const second = await open(t, directory);
      const saved = await second.call('status');
      assert.equal(saved.modelRequests, 0);
      assert.equal(saved.scheduling, 'paused');
      assert.deepEqual(saved.artifacts, []);
      await delay(Math.max(0, deadline - Date.now()) + 60);
      const unselected = await second.call('status');
      assert.equal(unselected.scheduling, 'paused');
      assert.equal(unselected.modelRequests, 0);
      assert.deepEqual(unselected.artifacts, []);
      await second.call('resume', { submissionId: admitted.submissionId });
      const done = await until(second, (s) => s.submissions.some((s) => s.status === 'done'));
      assert.deepEqual(done.artifacts.map((a) => a.content), ['durable-wake=1\n']);
      assert.ok(done.entries.some((e) => e.kind === 'probe.woke' && e.data.taskId === sleeping.record.id));
      assert.equal(done.entries.filter((e) => e.kind === 'probe.woke').length, 1);
      await second.stop();
    });
  }
}
