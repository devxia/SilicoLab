import { createInterface } from 'node:readline';
import { randomUUID } from 'node:crypto';
import { join, resolve } from 'node:path';
import { BACKGROUND_CONTEXT } from '@earendil-works/chord/context';
import { createModels } from '@earendil-works/pi-ai/models';
import { createRegistry, defineDoc, Harness, type ConversationId } from '@earendil-works/pi-durable';
import { openNodeSqliteStorage } from '@earendil-works/pi-durable/storage/sqlite/node';

// The Python workbench owner holds the project lease across this process's lifetime.
// This protocol is private IPC; the application interface is the local workbench HTTP contract.
const ctx = BACKGROUND_CONTEXT;
const [directory, mode, name] = process.argv.slice(2);
if (!directory || !['create', 'open'].includes(mode)) throw new Error('project directory and mode required');
const Project = defineDoc<{ id: string; name: string; conversations: ConversationId[] }>({
  kind: 'silicolab.project', version: 1, scope: 'session',
  initial: () => ({ id: randomUUID(), name: name || '科研项目', conversations: [] }), checkpointWhen: () => true,
});
const Chat = defineDoc<{ title: string; draft: string; revision: number }>({
  kind: 'silicolab.conversation', version: 1, scope: 'conversation', history: 'latest', fork: 'initial',
  initial: () => ({ title: '新对话', draft: '', revision: 0 }), checkpointWhen: () => true,
});
const harness = await Harness.open(await openNodeSqliteStorage(join(resolve(directory), 'session.sqlite')), {
  models: createModels(), registry: createRegistry(),
}, ctx);
const existing = await harness.snapshot(Project, ctx);
if (!existing && mode !== 'create') { await harness.close(ctx); throw new Error('project identity missing'); }
await harness.commit((tx) => tx.doc(Project), ctx);

async function snapshot() {
  const project = (await harness.snapshot(Project, ctx))!;
  const conversations = await Promise.all(project.conversations.map(async (id) => ({ id: String(id), ...(await harness.snapshot(Chat, id, ctx))! })));
  const inspection = await harness.inspect(ctx);
  return { id: project.id, name: project.name, conversations, tasks: inspection.tasks, scheduling: inspection.scheduling, modelRequests: 0, runtimePid: process.pid };
}
async function chatId(value: unknown) {
  const project = (await harness.snapshot(Project, ctx))!;
  const id = project.conversations.find((id) => String(id) === value);
  if (id === undefined) throw new Error('对话不存在');
  return id;
}
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
    case 'close': await harness.close(ctx); return { closed: true };
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
      if (request.op === 'close') break;
    } catch (error) { console.log(JSON.stringify({ id, error: String(error) })); }
  }
} finally { await harness.close(ctx); lines.close(); }
