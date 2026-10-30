import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { appendFile, mkdir, readFile, readdir, realpath, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import { BACKGROUND_CONTEXT } from '@earendil-works/chord/context';
import { createModels } from '@earendil-works/pi-ai/models';
import { fauxAssistantMessage, fauxProvider, fauxToolCall } from '@earendil-works/pi-ai/providers/faux';
import { Type } from '@earendil-works/pi-ai';
import { createRegistry, defineDoc, defineExtension, defineTask, defineTool, Harness, type SubmissionId, type TaskId } from '@earendil-works/pi-durable';
import { openNodeSqliteStorage } from '@earendil-works/pi-durable/storage/sqlite/node';

const context = BACKGROUND_CONTEXT;
const requestedDirectory = process.argv[2];
if (!requestedDirectory) throw new Error('Usage: node src/worker.ts TEMP_DIRECTORY');
await mkdir(requestedDirectory, { recursive: true });
const directory = await realpath(requestedDirectory);

// fcntl locks are released by the OS after normal exit or a broken parent pipe.
const owner = spawn('python3', [fileURLToPath(new URL('./owner.py', import.meta.url)), join(directory, '.owner.lock')], {
  stdio: ['pipe', 'pipe', 'pipe'],
  env: { PATH: process.env.PATH, LANG: 'en_US.UTF-8' },
});
let closingLease = false;
const ownerExit = once(owner, 'exit');
owner.on('exit', () => {
  if (!closingLease) {
    process.stderr.write('storage already owned or POSIX lease lost; refusing further writes\n');
    process.exit(1);
  }
});
await new Promise<void>((resolve, reject) => {
  owner.once('error', reject);
  owner.stdout.once('data', () => resolve());
  owner.once('exit', () => reject(new Error('storage already owned or Python POSIX lease unavailable')));
});

const outputDirectory = join(directory, 'artifacts');
await mkdir(outputDirectory, { recursive: true });
const attemptsFile = join(directory, 'attempts.jsonl');
const entered = new Set<string>();
const released = new Set<string>();
let modelRequests = 0;
const reports: { kind: string; message: string }[] = [];

function gate(name: string, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) { reject(new Error('invocation stopped')); return; }
    const timer = setInterval(() => {
      if (released.has(name)) { cleanup(); resolve(); }
    }, 10);
    const abort = () => { cleanup(); reject(new Error('invocation stopped')); };
    const cleanup = () => { clearInterval(timer); signal?.removeEventListener('abort', abort); };
    signal?.addEventListener('abort', abort, { once: true });
  });
}

const tools = (['safe', 'unsafe'] as const).map((replay) => defineTool({
  name: `probe_${replay}`,
  description: 'Write an artificial, independently checkable result. No scientific or network work.',
  parameters: Type.Object({ hold: Type.Boolean() }),
  replay,
  execute: async (args, api, taskContext) => {
    // The artificial effect is idempotent by durable tool identity; its receipt is not the tool-result commit.
    const artifact = `${api.taskId}.txt`;
    await appendFile(attemptsFile, `${JSON.stringify({ taskId: api.taskId, callId: api.callId, replay })}\n`);
    try { await writeFile(join(outputDirectory, artifact), 'synthetic-count=3\n', { flag: 'wx' }); }
    catch (error) { if ((error as NodeJS.ErrnoException).code !== 'EEXIST') throw error; }
    await api.details({ stage: 'effect-before-result', artifact }, taskContext);
    entered.add(replay);
    if (args.hold) await gate(replay, taskContext.abortSignal);
    return { output: [{ type: 'text' as const, text: `saved:${artifact}` }], details: { artifact } };
  },
}));
const Sleeper = defineTask<{ until: number }, { phase: 'start' } | { phase: 'deliver' }, string>({
  name: 'probe.sleep', version: 1,
  initial: () => ({ phase: 'start' }),
  phases: {
    start: (task, runtime, ctx) => runtime.sleepUntil(task.input.until, { phase: 'deliver' }, ctx),
    deliver: async (task, runtime, ctx) => {
      const artifact = `wake-${task.id}.txt`;
      // Safe deterministic replacement; no claim of atomicity between file and SQLite.
      await writeFile(join(outputDirectory, artifact), 'durable-wake=1\n');
      await runtime.commit(async (tx) => {
        await tx.appendEntry(runtime.conversationId, { kind: 'probe.woke', data: { taskId: task.id, artifact } });
        return { status: 'terminal', outcome: { status: 'completed', result: artifact } };
      }, ctx);
    },
  },
  abort: (_task, runtime, ctx) => runtime.commit(() => ({ status: 'terminal', outcome: { status: 'aborted' } }), ctx),
});
const Joiner = defineTask<{ until: number }, { phase: 'start' } | { phase: 'finish'; child: TaskId<string> }, string>({
  name: 'probe.join', version: 1,
  initial: () => ({ phase: 'start' }),
  phases: {
    start: (_task, runtime, ctx) => runtime.commit(async (tx) => {
      const child = await tx.createTask(Sleeper, _task.input, { ownership: { kind: 'task', taskId: runtime.taskId } });
      return { status: 'waiting', checkpoint: { phase: 'finish', child }, on: [child], policy: 'allSettled' };
    }, ctx),
    finish: async (task, runtime, ctx) => {
      const [outcome] = await runtime.outcomes([task.state.checkpoint.child], ctx);
      await runtime.commit(() => ({ status: 'terminal', outcome }), ctx);
    },
  },
  abort: (_task, runtime, ctx) => runtime.commit(() => ({ status: 'terminal', outcome: { status: 'aborted' } }), ctx),
});
const ChildLink = defineDoc<{ child: TaskId<string> | null }>({
  kind: 'probe.child', version: 1, scope: 'task',
  initial: () => ({ child: null }), checkpointWhen: () => true,
});
const waits = (['sleep', 'waiting'] as const).map((mode) => defineTool({
  name: `probe_${mode}`, description: 'Exercise durable sleep and a join on durable child work.',
  parameters: Type.Object({ until: Type.Number() }), replay: 'safe',
  execute: async (args, api, ctx) => {
    const child = await api.commit(async (tx) => {
      const link = await tx.doc(ChildLink, api.taskId);
      if (link.child !== null) return link.child;
      const ownership = { kind: 'task' as const, taskId: api.taskId };
      const id = mode === 'sleep'
        ? await tx.createTask(Sleeper, args, { ownership })
        : await tx.createTask(Joiner, args, { ownership });
      link.child = id;
      return id;
    }, ctx);
    const result = await api.waitForTask(child, ctx);
    return { output: [{ type: 'text', text: JSON.stringify(result.state.outcome) }] };
  },
}));
const registry = createRegistry();
registry.install(defineExtension({ name: 'synthetic-probe', tools: [...tools, ...waits], tasks: [Sleeper, Joiner] }));
const faux = fauxProvider({ tokensPerSecond: 0 });
const models = createModels();
models.setProvider(faux.provider);
// Factory derives the next reply from the durable transcript, not a per-process response index.
const response: Parameters<typeof faux.setResponses>[0][number] = async (transcript, options) => {
  modelRequests++;
  faux.appendResponses([response]);
  const last = transcript.messages.at(-1);
  const user = transcript.messages.findLast((message) => message.role === 'user');
  const scenario = user?.role === 'user' && typeof user.content === 'string' ? user.content : 'complete';
  if (scenario === 'model') {
    entered.add('model');
    await gate('model', options?.signal);
    return fauxAssistantMessage('Artificial generation released.');
  }
  if (scenario === 'sequence' && last?.role === 'toolResult' && last.toolName === 'probe_safe') {
    return fauxAssistantMessage([fauxToolCall('probe_unsafe', { hold: true }, { id: 'second-call' })], { stopReason: 'toolUse' });
  }
  if (last?.role === 'toolResult') return fauxAssistantMessage(last.isError ? 'Tool interrupted; result unknown.' : 'Synthetic result verified.');
  if (scenario === 'sleep' || scenario === 'waiting') {
    return fauxAssistantMessage([fauxToolCall(`probe_${scenario}`, { until: Date.now() + 2_000 }, { id: 'durable-wait-call' })], { stopReason: 'toolUse' });
  }
  return fauxAssistantMessage([fauxToolCall(scenario === 'unsafe' ? 'probe_unsafe' : 'probe_safe', { hold: scenario !== 'complete' && scenario !== 'sequence' }, { id: 'synthetic-call' })], { stopReason: 'toolUse' });
};
faux.setResponses([response]);
const harness = await Harness.open(await openNodeSqliteStorage(join(directory, 'session.sqlite')), {
  models, registry,
  settings: { compaction: { enabled: false }, retry: { maxRetries: 0 }, restartLimit: 3 },
  onReport: (error, info) => reports.push({ kind: info.type, message: String(error) }),
}, context);
let root = await harness.root(context, { agent: { model: { provider: 'faux', modelId: 'faux-1' } } });

async function readAttempts() {
  try { return (await readFile(attemptsFile, 'utf8')).trim().split('\n').filter(Boolean).map((line) => JSON.parse(line)); }
  catch (error) { if ((error as NodeJS.ErrnoException).code === 'ENOENT') return []; throw error; }
}

async function status() {
  const inspection = await harness.inspect(context); // Does not start scheduling.
  const entries = (await root.entries({ order: 'ascending' }, 1000, undefined, context)).items;
  const ids = new Set([
    ...entries.filter((e) => e.kind === 'probe.submission').map((e) => (e.data as { id: SubmissionId }).id),
    ...inspection.submissions.map((submission) => submission.id),
  ]);
  const submissions = await Promise.all([...ids].map(async (id) => (await harness.submission(id, context))!.status(context)));
  const artifacts = await Promise.all((await readdir(outputDirectory)).sort().map(async (name) => ({ name, content: await readFile(join(outputDirectory, name), 'utf8') })));
  return { conversationId: root.id, scheduling: inspection.scheduling, tasks: inspection.tasks, submissions, entries, artifacts,
    entered: [...entered], attempts: await readAttempts(), modelRequests, reports };
}

let shutdownPromise: Promise<void> | undefined;
function shutdown(): Promise<void> {
  return shutdownPromise ??= (async () => {
    await harness.close(context);
    closingLease = true;
    owner.stdin.end();
    await ownerExit;
  })();
}

async function dispatch(request: { op: string; requestId?: string; scenario?: string; submissionId?: SubmissionId }) {
  switch (request.op) {
    case 'create': return { conversationId: root.id };
    case 'status': return status();
    case 'submit': {
      if (!request.requestId || !['complete', 'safe', 'unsafe', 'sleep', 'waiting', 'sequence', 'model'].includes(request.scenario ?? '')) throw new Error('requestId and a known scenario are required');
      const existing = await root.commit((tx) => tx.submissionByRequest(root.id, request.requestId!), context);
      // A duplicate is a read, not permission to start the paused scheduler.
      if (existing) return { submissionId: existing.id };
      if ((await harness.inspect(context)).submissions.length) throw new Error('select recovery before new work');
      const submission = await root.submit({ type: 'input', content: request.scenario!, requestId: request.requestId }, context);
      await root.commit((tx) => tx.appendEntry(root.id, { kind: 'probe.submission', data: { id: submission.id } }), context);
      return { submissionId: submission.id };
    }
    case 'resume': {
      const pending = (await harness.inspect(context)).submissions;
      // This minimum probe admits only one unresolved submission per storage.
      if (pending.length !== 1 || pending[0].id !== request.submissionId) throw new Error('select the pending submission');
      harness.resume();
      return { selected: request.submissionId };
    }
    case 'release': released.add(request.scenario ?? 'safe'); return { released: true };
    case 'close': await shutdown(); return { closed: true };
    default: throw new Error('unknown operation');
  }
}

const input = createInterface({ input: process.stdin });
process.stdout.write(`${JSON.stringify({ ready: true })}\n`);
try {
  for await (const line of input) {
    let id: unknown = null;
    try {
      const request = JSON.parse(line);
      id = request.id;
      const result = await dispatch(request);
      process.stdout.write(`${JSON.stringify({ id, result })}\n`);
      if (request.op === 'close') break;
    } catch (error) { process.stdout.write(`${JSON.stringify({ id, error: String(error) })}\n`); }
  }
} finally {
  await shutdown();
  input.close();
}
