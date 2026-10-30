import { createInterface } from 'node:readline';
import { randomUUID } from 'node:crypto';
import { dirname, join, resolve } from 'node:path';
import { BACKGROUND_CONTEXT } from '@earendil-works/chord/context';
import { createLocalAgent } from './agent.ts';
import { closeScience, type ScienceOptions } from './science.ts';
import { defineDoc, Harness, type ConversationId } from '@earendil-works/pi-durable';
import { openNodeSqliteStorage } from '@earendil-works/pi-durable/storage/sqlite/node';
import { ProjectFiles, type ImportedFile, type InputVersion } from './inputs.ts';

// The Python workbench owner holds the project lease across this process's lifetime.
// This protocol is private IPC; the application interface is the local workbench HTTP contract.
const ctx = BACKGROUND_CONTEXT;
const [directory, mode, name] = process.argv.slice(2);
if (!directory || !['create', 'open'].includes(mode)) throw new Error('project directory and mode required');
const Project = defineDoc<{ id: string; name: string; conversations: ConversationId[]; files?: ImportedFile[]; inputVersions?: InputVersion[] }>({
  kind: 'silicolab.project', version: 1, scope: 'session',
  initial: () => ({ id: randomUUID(), name: name || '科研项目', conversations: [] }), checkpointWhen: () => true,
});
const Chat = defineDoc<{ title: string; draft: string; revision: number }>({
  kind: 'silicolab.conversation', version: 1, scope: 'conversation', history: 'latest', fork: 'initial',
  initial: () => ({ title: '新对话', draft: '', revision: 0 }), checkpointWhen: () => true,
});
const files = new ProjectFiles(dirname(resolve(directory)));
let durable: Harness;
const agent = createLocalAgent(dirname(resolve(directory)), async (versionId, conversationId) => {
  const project = (await durable.snapshot(Project, ctx))!;
  const version = project.inputVersions?.find((input) => input.id === versionId && input.conversationId === conversationId);
  if (!version) throw new Error('当前对话没有该固定输入版本');
  return files.fixed(version);
});
const harness = await Harness.open(await openNodeSqliteStorage(join(resolve(directory), 'session.sqlite')), {
  models: agent.models, registry: agent.registry,
  settings: { compaction: { enabled: false }, retry: { maxRetries: 0 }, restartLimit: 3, progress: { partialIntervalMs: 30, outputIntervalMs: 30 } },
}, ctx);
agent.bind(harness);
durable = harness;
const existing = await harness.snapshot(Project, ctx);
if (!existing && mode !== 'create') { await harness.close(ctx); throw new Error('project identity missing'); }
await harness.commit((tx) => tx.doc(Project), ctx);
await agent.reconcileOpen();

async function snapshot() {
  const project = (await harness.snapshot(Project, ctx))!;
  const conversations = await Promise.all(project.conversations.map(async (id) => ({ id: String(id), ...(await harness.snapshot(Chat, id, ctx))! })));
  const inspection = await agent.inspection();
  return { id: project.id, name: project.name, conversations, files: project.files || [], inputVersions: project.inputVersions || [], tasks: await agent.tasks(), activeTasks: inspection.tasks, scheduling: inspection.scheduling, modelRequests: await agent.modelRequests(), runtimePid: process.pid };
}
async function chatId(value: unknown) {
  const project = (await harness.snapshot(Project, ctx))!;
  const id = project.conversations.find((id) => String(id) === value);
  if (id === undefined) throw new Error('对话不存在');
  return id;
}
let stopAfterResponse = false;
async function dispatch(request: Record<string, unknown>) {
  switch (request.op) {
    case 'status': return snapshot();
    case 'conversation.create': {
      const title = String(request.title || '').trim();
      if (!title || title.length > 200) throw new Error('对话标题长度应为 1–200 字符');
      const chat = await harness.createConversation({ ownership: { kind: 'ownerless' }, init: async (tx, id) => {
        const project = await tx.doc(Project);
        const doc = await tx.doc(Chat, id);
        doc.title = title;
        project.conversations.push(id);
      } }, ctx);
      return { id: String(chat.id), ...(await harness.snapshot(Chat, chat.id, ctx))! };
    }
    case 'draft.save': {
      const id = await chatId(request.conversationId);
      const text = request.text;
      if (typeof text !== 'string' || text.length > 100000) throw new Error('草稿过长');
      return harness.commit(async (tx) => {
        const doc = await tx.doc(Chat, id);
        if (request.revision !== doc.revision) throw new Error('草稿已更新，请重新载入后保存');
        doc.draft = text;
        doc.revision++;
        return { id: String(id), title: doc.title, draft: doc.draft, revision: doc.revision };
      }, ctx);
    }
    case 'file.import': {
      const imported = await files.import(request.name, request.contentBase64);
      await harness.commit(async (tx) => { const project = await tx.doc(Project); if (!project.files) project.files = []; project.files.push(imported); }, ctx);
      return imported;
    }
    case 'file.preview': {
      const project = (await harness.snapshot(Project, ctx))!;
      const source = project.files?.find((file) => file.id === request.fileId);
      if (!source) throw new Error('文件不存在');
      const bytes = await files.read(source.path);
      let text: string | null;
      try { text = new TextDecoder('utf-8', { fatal: true }).decode(bytes.subarray(0, 8000), { stream: bytes.length > 8000 }); } catch { text = null; }
      return { ...source, text, truncated: bytes.length > 8000, currentSize: bytes.length };
    }
    case 'input.freeze': {
      const conversationId = await chatId(request.conversationId);
      const project = (await harness.snapshot(Project, ctx))!;
      if (!Array.isArray(request.fileIds) || !request.fileIds.length || request.fileIds.length > 20 || new Set(request.fileIds).size !== request.fileIds.length) throw new Error('请选择 1–20 个不同文件');
      const selected = request.fileIds.map((id) => { const source = project.files?.find((file) => file.id === id); if (!source) throw new Error('输入文件不存在'); return source; });
      const version = await files.freeze(String(conversationId), selected, project.inputVersions || []);
      await harness.commit(async (tx) => { const project = await tx.doc(Project); if (!project.inputVersions) project.inputVersions = []; project.inputVersions.push(version); }, ctx);
      return files.fixed(version);
    }
    case 'input.read': {
      const project = (await harness.snapshot(Project, ctx))!;
      const version = project.inputVersions?.find((version) => version.id === request.versionId);
      if (!version) throw new Error('输入版本不存在');
      return files.fixed(version);
    }
    case 'task.start': {
      const conversationId = await chatId(request.conversationId);
      if (typeof request.requestId !== 'string' || !request.requestId || request.requestId.length > 200 || typeof request.goal !== 'string' || !request.goal.trim() || request.goal.length > 100000 || !Array.isArray(request.authorizedTools) || !request.authorizedTools.every((tool) => typeof tool === 'string')) throw new Error('任务目标、身份或授权格式不合法');
      const options: ScienceOptions = { workflow: request.workflow === 'd2p_local' ? 'd2p_local' : request.workflow === 'simulated_external' ? 'simulated_external' : 'validation' };
      if (request.workflow && !['validation', 'd2p_local', 'simulated_external'].includes(String(request.workflow))) throw new Error('未知任务模式');
      if (request.workflow === 'd2p_local') {
        const parameters = request.parameters as Record<string, unknown> | undefined;
        if (!parameters || !['preserve', 'add', 'ask'].includes(String(parameters.stopPolicy)) || typeof parameters.avoid !== 'string' || parameters.avoid.length > 2000 || typeof request.inputVersionId !== 'string') throw new Error('本地专项参数不完整');
        options.parameters = { stopPolicy: parameters.stopPolicy as 'preserve' | 'add' | 'ask', avoid: parameters.avoid };
        options.inputVersionId = request.inputVersionId;
        options.specialtyAcknowledged = request.specialtyAcknowledged === true;
      }
      if (request.workflow === 'simulated_external') {
        const simulation = request.simulation as Record<string, unknown> | undefined;
        if (!simulation || typeof simulation.payload !== 'string' || simulation.payload.length > 10000 || !Number.isInteger(simulation.durationMs) || Number(simulation.durationMs) < 0 || Number(simulation.durationMs) > 60000 || typeof simulation.queryable !== 'boolean' || !['normal', 'lost', 'hold_after_accept'].includes(String(simulation.responseMode))) throw new Error('模拟外部作业参数不合法');
        options.simulation = { payload: simulation.payload, durationMs: Number(simulation.durationMs), queryable: simulation.queryable, responseMode: simulation.responseMode as 'normal' | 'lost' | 'hold_after_accept' };
      }
      return agent.start(conversationId, request.requestId, request.goal, request.authorizedTools, options);
    }
    case 'external.reconcile': return agent.reconcileExternal(String(request.taskId));
    case 'external.cancel': return agent.cancelExternal(String(request.taskId));
    case 'task.answer': return agent.answer(String(request.taskId), String(request.decisionId), String(request.answer));
    case 'task.continue': return agent.continueTask(String(request.taskId));
    case 'task.pause': {
      const prepared = await agent.preparePause(String(request.taskId));
      if (prepared.needsClose) { await agent.closeExecutions(); await harness.close(ctx); closeScience(); stopAfterResponse = true; return { pausedHost: true, taskId: request.taskId }; }
      return prepared.task;
    }
    case 'task.resume': return agent.resume(String(request.taskId));
    case 'task.cancel': return agent.cancel(String(request.taskId));
    case 'task.artifact': return agent.artifact(String(request.taskId), String(request.executionId), String(request.name));
    case 'conversation.status': return agent.conversation(await chatId(request.conversationId));
    case 'close': await agent.closeExecutions(); await harness.close(ctx); closeScience(); return { closed: true };
    default: throw new Error('unsupported operation');
  }
}
const lines = createInterface({ input: process.stdin });
console.log(JSON.stringify({ ready: true }));
try {
  for await (const line of lines) {
    let id: unknown = null;
    try {
      const request = JSON.parse(line); id = request.id;
      console.log(JSON.stringify({ id, result: await dispatch(request) }));
      if (request.op === 'close' || stopAfterResponse) break;
    } catch (error) { console.log(JSON.stringify({ id, error: String(error) })); }
  }
} finally { await agent.closeExecutions(); await harness.close(ctx); closeScience(); lines.close(); }
