import { createHash, randomUUID } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';
import { BACKGROUND_CONTEXT } from '@earendil-works/chord/context';
import { Type } from '@earendil-works/pi-ai';
import { createModels } from '@earendil-works/pi-ai/models';
import { fauxAssistantMessage, fauxProvider, fauxToolCall } from '@earendil-works/pi-ai/providers/faux';
import { createRegistry, defineDoc, defineExtension, defineTool, LiveDoc, type ConversationId, type Harness, type SubmissionId } from '@earendil-works/pi-durable';
import { ProjectFiles } from './inputs.ts';

const ctx = BACKGROUND_CONTEXT;
type Execution = { id: string; toolTaskId: number; callId: string; tool: string; input: string; progress: number; status: string; error?: string; artifact?: { path: string; sha256: string; size: number }; result?: { characters: number } };
export type ResearchTask = { id: string; conversationId: string; requestId: string; goal: string; status: string; authorizedTools: string[]; createdAt: string; submissionId?: SubmissionId; toolExecutions: Execution[]; error?: string };
const Ledger = defineDoc<{ tasks: ResearchTask[]; modelRequests: number }>({
  kind: 'silicolab.tasks', version: 1, scope: 'session', initial: () => ({ tasks: [], modelRequests: 0 }), checkpointWhen: () => true,
});

/** Model adapter and controlled tools. Only pi-durable owns the agent loop. */
export function createLocalAgent(directory: string) {
  let harness: Harness;
  const files = new ProjectFiles(directory);
  const models = createModels();
  const registry = createRegistry();
  const faux = fauxProvider({ tokensPerSecond: 80 });
  models.setProvider(faux.provider);
  const response: Parameters<typeof faux.setResponses>[0][number] = async (transcript) => {
    faux.appendResponses([response]);
    await harness.commit(async (tx) => { (await tx.doc(Ledger)).modelRequests++; }, ctx);
    const last = transcript.messages.at(-1);
    if (last?.role === 'toolResult') return fauxAssistantMessage(last.isError
      ? '本机验证工具未完成，请检查错误。此答复不代表科研计算成功。'
      : '本机人工文本计数已生成可检查结果。这是验证模型，不是科研结论。');
    const user = transcript.messages.findLast((entry) => entry.role === 'user');
    const text = user?.role === 'user' && typeof user.content === 'string' ? user.content : '';
    return fauxAssistantMessage([fauxToolCall('synthetic_count', { text }, { id: randomUUID() })], { stopReason: 'toolUse' });
  };
  faux.setResponses([response]);
  registry.install(defineExtension({ name: 'silicolab.local-validation', tools: [defineTool({
    name: 'synthetic_count', description: '本机验证：统计人工文本 Unicode 字符数量并写出可核对 JSON，不进行生物学推断、科学服务上传或任意脚本。',
    parameters: Type.Object({ text: Type.String({ maxLength: 100000 }) }), replay: 'safe',
    execute: async (args, api, context) => {
      const ledger = await harness.snapshot(Ledger, ctx);
      const task = ledger?.tasks.findLast((item) => item.conversationId === String(api.conversationId) && item.status === 'running');
      if (!task || !task.authorizedTools.includes('synthetic_count')) throw new Error('需要用户决定：当前任务未授权本机验证工具');
      const id = randomUUID();
      await api.commit(async (tx) => {
        const saved = (await tx.doc(Ledger)).tasks.find((item) => item.id === task.id)!;
        saved.toolExecutions.push({ id, toolTaskId: api.taskId, callId: api.callId, tool: 'synthetic_count', input: args.text.slice(0, 160), status: 'running', progress: 0 });
      }, context);
      try {
        for (const progress of [25, 60, 90]) {
          await delay(150, undefined, { signal: context.abortSignal });
          api.output(`文本计数 ${progress}%\n`);
          await api.details({ progress, input: args.text.slice(0, 160) }, context);
          await api.commit(async (tx) => {
            const attempt = (await tx.doc(Ledger)).tasks.find((item) => item.id === task.id)!.toolExecutions.find((item) => item.id === id)!;
            attempt.progress = progress;
          }, context);
        }
        const result = { characters: [...args.text].length };
        const content = Buffer.from(JSON.stringify({ taskId: task.id, input: args.text, result }) + '\n');
        const path = `.silicolab/outputs/${task.id}/${api.taskId}-${id}.json`;
        await files.write(path, content);
        const artifact = { path, size: content.length, sha256: createHash('sha256').update(content).digest('hex') };
        await api.commit(async (tx) => {
          const execution = (await tx.doc(Ledger)).tasks.find((item) => item.id === task.id)!.toolExecutions.find((item) => item.id === id)!;
          execution.status = 'completed'; execution.progress = 100; execution.result = result; execution.artifact = artifact;
        }, context);
        return { output: [{ type: 'text', text: JSON.stringify(result) }], details: { artifact, result } };
      } catch (error) {
        // Close/abort preserves pending recovery; an ordinary tool failure is terminal evidence.
        if (!context.abortSignal?.aborted) await api.commit(async (tx) => {
          const execution = (await tx.doc(Ledger)).tasks.find((item) => item.id === task.id)!.toolExecutions.find((item) => item.id === id)!;
          execution.status = 'failed'; execution.error = String(error);
        }, context);
        throw error;
      }
    },
  })] }));

  async function tasks() { return (await harness.snapshot(Ledger, ctx))?.tasks || []; }
  async function start(conversationId: ConversationId, requestId: string, goal: string, authorizedTools: string[]) {
    const existing = (await tasks()).find((item) => item.conversationId === String(conversationId) && item.requestId === requestId);
    if (existing) {
      if (existing.goal !== goal || JSON.stringify(existing.authorizedTools) !== JSON.stringify(authorizedTools)) throw new Error('请求身份已用于不同目标或权限');
      return existing;
    }
    if ((await harness.inspect(ctx)).submissions.length) throw new Error('项目已有在途或待恢复任务，请先处理原任务');
    if (authorizedTools.some((tool) => tool !== 'synthetic_count')) throw new Error('本地验证不提供所请求工具');
    const task: ResearchTask = { id: randomUUID(), conversationId: String(conversationId), requestId, goal,
      authorizedTools, status: authorizedTools.includes('synthetic_count') ? 'running' : 'needs_decision',
      createdAt: new Date().toISOString(), toolExecutions: [] };
    await harness.commit(async (tx) => { (await tx.doc(Ledger)).tasks.push(task); }, ctx);
    if (task.status === 'needs_decision') return task;
    const conversation = (await harness.conversation(conversationId, ctx))!;
    await conversation.configure({ model: { provider: 'faux', modelId: 'faux-1' } }, ctx);
    const submission = await conversation.submit({ type: 'input', requestId, content: goal, whenBusy: 'reject' }, ctx);
    await harness.commit(async (tx) => { (await tx.doc(Ledger)).tasks.find((item) => item.id === task.id)!.submissionId = submission.id; }, ctx);
    // Observe the actual submission once. Viewer reconnect never reaches this path.
    void submission.wait(ctx).then(async (settled) => {
      await harness.commit(async (tx) => {
        const saved = (await tx.doc(Ledger)).tasks.find((item) => item.id === task.id)!;
        saved.status = settled.status === 'done' ? 'answered' : 'failed';
        if (settled.status !== 'done') saved.error = settled.reason;
      }, ctx);
    }).catch(() => { /* Closing leaves durable pending work; opening never resumes it here. */ });
    return { ...task, submissionId: submission.id };
  }
  async function conversation(conversationId: ConversationId) {
    const chat = (await harness.conversation(conversationId, ctx))!;
    const entries = [];
    let cursor;
    do {
      const page = await chat.entries({ order: 'ascending' }, 200, cursor, ctx);
      entries.push(...page.items); cursor = page.next;
    } while (cursor);
    const live = await harness.snapshot(LiveDoc, conversationId, ctx);
    return { conversationId: String(conversationId), entries, live: live || {},
      partial: live?.generation?.message?.content || [],
      tasks: (await tasks()).filter((task) => task.conversationId === String(conversationId)),
      modelRequests: (await harness.snapshot(Ledger, ctx))?.modelRequests || 0,
      scheduling: (await harness.inspect(ctx)).scheduling };
  }
  return { models, registry, bind(value: Harness) { harness = value; }, start, tasks, conversation,
    async modelRequests() { return (await harness.snapshot(Ledger, ctx))?.modelRequests || 0; } };
}
