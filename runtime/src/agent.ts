import { createHash, randomUUID } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';
import { BACKGROUND_CONTEXT, type Context } from '@earendil-works/chord/context';
import { Type } from '@earendil-works/pi-ai';
import { createModels } from '@earendil-works/pi-ai/models';
import { fauxAssistantMessage, fauxProvider, fauxToolCall } from '@earendil-works/pi-ai/providers/faux';
import { createRegistry, defineDoc, defineExtension, defineTool, LiveDoc, type ConversationId, type Harness, type SubmissionId, type ToolExecutionApi } from '@earendil-works/pi-durable';
import { ProjectFiles } from './inputs.ts';
import { runScience, type ScienceOptions, type ScienceResult } from './science.ts';
import { stopDecision, toolDecision, type TaskDecision } from './decisions.ts';

const ctx = BACKGROUND_CONTEXT;
type Artifact = { path: string; sha256: string; size: number; name?: string; mediaType?: string };
type ExecutionResult = { characters: number } | ScienceResult;
type Execution = { id: string; toolTaskId: number; callId: string; tool: string; input: string; progress: number; status: string; error?: string; pythonPid?: number; artifact?: Artifact; artifacts?: Artifact[]; result?: ExecutionResult };
export type ResearchTask = ScienceOptions & { id: string; conversationId: string; requestId: string; goal: string; status: string; authorizedTools: string[]; createdAt: string; submissionId?: SubmissionId; toolExecutions: Execution[]; error?: string; decisions?: TaskDecision[]; admission?: { authorizedTools: string[]; options: ScienceOptions }; preflight?: { missingStopNames: string[]; inputVersionId: string } };
const Ledger = defineDoc<{ tasks: ResearchTask[]; modelRequests: number }>({
  kind: 'silicolab.tasks', version: 1, scope: 'session', initial: () => ({ tasks: [], modelRequests: 0 }), checkpointWhen: () => true,
});
type FixedInputs = Awaited<ReturnType<ProjectFiles['fixed']>>;

/** Model adapter and controlled tools. Only pi-durable owns the agent loop. */
export function createLocalAgent(directory: string, getInputs: (id: string, conversationId: string) => Promise<FixedInputs>) {
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
      ? '工具未完成，请查看实际错误和保留记录。模型答复不代表科研成功。'
      : last.toolName === 'd2p_local' ? '本地 D2P 专项已返回实际结果，请核对逐项校验和科研产物；表达效果仍需实验验证。'
      : '本机人工文本计数已生成可检查结果。这是验证模型，不是科研结论。');
    const user = transcript.messages.findLast((entry) => entry.role === 'user');
    const text = user?.role === 'user' && typeof user.content === 'string' ? user.content : '';
    const active = (await harness.inspect(ctx)).submissions.filter((submission) => submission.type === 'input' && submission.status === 'placed');
    if (active.length !== 1) throw new Error('本机验证模型无法确定唯一已准入任务');
    const task = await taskForSubmission(active[0].conversationId, active[0].id);
    const tool = task.workflow === 'd2p_local' ? 'd2p_local' : 'synthetic_count';
    return fauxAssistantMessage([fauxToolCall(tool, tool === 'synthetic_count' ? { text } : {}, { id: randomUUID() })], { stopReason: 'toolUse' });
  };
  faux.setResponses([response]);

  async function tracked(tool: string, input: string, api: ToolExecutionApi, context: Context,
    work: (task: ResearchTask, id: string, progress: (value: number, pythonPid?: number) => Promise<void>) => Promise<{ result: ExecutionResult; artifact?: Artifact; artifacts?: Artifact[]; isError?: boolean; error?: string }>) {
    const live = await harness.snapshot(LiveDoc, api.conversationId, ctx);
    if (live?.run?.inputs.length !== 1) throw new Error('工具无法关联唯一内核输入');
    const task = await taskForSubmission(api.conversationId, live.run.inputs[0]);
    if (!task.authorizedTools.includes(tool)) throw new Error('需要用户决定：当前任务未授权所需工具');
    const id = randomUUID();
    await api.commit(async (tx) => {
      (await tx.doc(Ledger)).tasks.find((item) => item.id === task.id)!.toolExecutions.push({ id, toolTaskId: api.taskId, callId: api.callId, tool, input, status: 'running', progress: 0 });
    }, context);
    const progress = async (value: number, pythonPid?: number) => {
      api.output(`处理进度 ${value}%\n`);
      await api.details({ progress: value, input }, context);
      await api.commit(async (tx) => {
        const attempt = (await tx.doc(Ledger)).tasks.find((item) => item.id === task.id)!.toolExecutions.find((item) => item.id === id)!;
        attempt.progress = value;
        if (pythonPid) attempt.pythonPid = pythonPid;
      }, context);
    };
    try {
      const outcome = await work(task, id, progress);
      await api.commit(async (tx) => {
        const execution = (await tx.doc(Ledger)).tasks.find((item) => item.id === task.id)!.toolExecutions.find((item) => item.id === id)!;
        execution.status = outcome.isError ? 'failed' : 'completed'; execution.progress = 100; execution.result = outcome.result;
        if (outcome.error) execution.error = outcome.error;
        if (outcome.artifact) execution.artifact = outcome.artifact;
        if (outcome.artifacts) execution.artifacts = outcome.artifacts;
      }, context);
      // Only bounded summary goes to the model. Full scientific records remain task evidence.
      const summary = 'records' in outcome.result ? { status: outcome.result.status, records: outcome.result.records.length } : outcome.result;
      return { isError: outcome.isError || false, output: [{ type: 'text' as const, text: JSON.stringify(summary) }], details: { result: outcome.result } };
    } catch (error) {
      if (!context.abortSignal?.aborted) await api.commit(async (tx) => {
        const execution = (await tx.doc(Ledger)).tasks.find((item) => item.id === task.id)!.toolExecutions.find((item) => item.id === id)!;
        execution.status = 'failed'; execution.error = String(error);
      }, context);
      throw error;
    }
  }
  const countTool = defineTool({
    name: 'synthetic_count', description: '本机验证：统计人工文本 Unicode 字符数量并写出可核对 JSON，不进行生物学推断、科学服务上传或任意脚本。',
    parameters: Type.Object({ text: Type.String({ maxLength: 100000 }) }), replay: 'safe',
    execute: (args, api, context) => tracked('synthetic_count', args.text.slice(0, 160), api, context, async (task, id, progress) => {
      for (const value of [25, 60, 90]) { await delay(150, undefined, { signal: context.abortSignal }); await progress(value); }
      const result = { characters: [...args.text].length };
      const content = Buffer.from(JSON.stringify({ taskId: task.id, input: args.text, result }) + '\n');
      const path = `.silicolab/outputs/${task.id}/${api.taskId}-${id}.json`;
      await files.write(path, content);
      return { result, artifact: { path, size: content.length, sha256: createHash('sha256').update(content).digest('hex') } };
    }),
  });
  const localTool = defineTool({
    name: 'd2p_local', description: '仅用户明确选择的 ProteinFactory/D2P 本地实验专项：D2P 无细胞体系、pD2P_1.08t、预设插入位置；不适用于普通反向翻译，不宣称已实现载体校验，不连接科学远端。输入与参数取自任务授权记录。',
    parameters: Type.Object({}), replay: 'safe',
    execute: (_args, api, context) => tracked('d2p_local', 'D2P 本地实验 · 固定输入版本', api, context, async (task, id, progress) => {
      if (task.workflow !== 'd2p_local' || !task.specialtyAcknowledged || !task.inputVersionId || !task.parameters) throw new Error('缺少明确专项、本地来源或固定输入授权');
      const fixed = await getInputs(task.inputVersionId, task.conversationId);
      await progress(10);
      const response = await runScience({ workflow: 'd2p_local', specialtyAcknowledged: true, inputVersionId: fixed.id, inputVersion: { id: fixed.id, conversationId: fixed.conversationId, createdAt: fixed.createdAt }, inputs: fixed.inputs, parameters: task.parameters,
        task: { id: task.id, conversationId: task.conversationId, requestId: task.requestId, goal: task.goal, createdAt: task.createdAt, parameters: task.parameters, inputVersionId: fixed.id },
        attempt: { id, toolTaskId: api.taskId, callId: api.callId } }, context.abortSignal,
        async (pid) => { await progress(30, pid); });
      await progress(85);
      const artifacts: Artifact[] = [];
      for (const item of response.files) {
        if (!['synthesis.fasta', 'synthesis.xlsx', 'records.zip'].includes(item.name) && !/^sequence-\d{3}\.fasta$/.test(item.name)) throw new Error('科学工具返回未声明的产物');
        const bytes = Buffer.from(item.contentBase64, 'base64');
        const path = `.silicolab/outputs/${task.id}/${id}/${item.name}`;
        await files.write(path, bytes);
        artifacts.push({ name: item.name, mediaType: item.mediaType, path, size: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex') });
      }
      const report = Buffer.from(JSON.stringify(response.result) + '\n');
      const reportPath = `.silicolab/outputs/${task.id}/${id}/record.json`;
      await files.write(reportPath, report);
      artifacts.push({ name: 'record.json', mediaType: 'application/json', path: reportPath, size: report.length, sha256: createHash('sha256').update(report).digest('hex') });
      return { result: response.result, artifacts, isError: response.result.status === 'failed', ...(response.result.status === 'failed' ? { error: '本地专项未产生通过校验的结果，请查看逐项错误' } : {}) };
    }),
  });
  registry.install(defineExtension({ name: 'silicolab.controlled-tools', tools: [countTool, localTool] }));

  async function tasks() { return (await harness.snapshot(Ledger, ctx))?.tasks || []; }
  async function taskForSubmission(conversationId: ConversationId, submissionId: SubmissionId) {
    const submission = await harness.submission(submissionId, ctx);
    const record = await submission?.status(ctx);
    const task = record?.conversationId === conversationId && record.requestId
      ? (await tasks()).find((item) => item.conversationId === String(conversationId) && item.requestId === record.requestId)
      : undefined;
    if (!task) throw new Error('内核提交未关联已保存任务');
    return task;
  }
  async function start(conversationId: ConversationId, requestId: string, goal: string, authorizedTools: string[], options: ScienceOptions = {}) {
    const existing = (await tasks()).find((item) => item.conversationId === String(conversationId) && item.requestId === requestId);
    if (existing) {
      const admitted = existing.admission || { authorizedTools: existing.authorizedTools, options: { workflow: existing.workflow, parameters: existing.parameters, inputVersionId: existing.inputVersionId, specialtyAcknowledged: existing.specialtyAcknowledged } };
      const original = admitted.options;
      if (existing.goal !== goal || JSON.stringify(admitted.authorizedTools) !== JSON.stringify(authorizedTools) || JSON.stringify(original.parameters) !== JSON.stringify(options.parameters) || original.inputVersionId !== options.inputVersionId || (original.workflow || 'validation') !== (options.workflow || 'validation') || Boolean(original.specialtyAcknowledged) !== Boolean(options.specialtyAcknowledged)) throw new Error('请求身份已用于不同目标、输入或权限');
      return existing;
    }
    if ((await harness.inspect(ctx)).submissions.length) throw new Error('项目已有在途或待恢复任务，请先处理原任务');
    const scientific = options.workflow === 'd2p_local';
    const requiredTool = scientific ? 'd2p_local' : 'synthetic_count';
    if (authorizedTools.some((tool) => tool !== requiredTool)) throw new Error('任务模式不提供所请求工具');
    const decisions: TaskDecision[] = [];
    let preflight: ResearchTask['preflight'];
    if (scientific) {
      if (!options.specialtyAcknowledged || !options.inputVersionId || !options.parameters || !['preserve', 'add', 'ask'].includes(options.parameters.stopPolicy)) throw new Error('请明确选择 D2P 专项本地实验、固定输入与终止符策略');
      const fixed = await getInputs(options.inputVersionId, String(conversationId));
      if (options.parameters.stopPolicy === 'ask') {
        const inspected = await runScience({ operation: 'preflight', workflow: 'd2p_local', specialtyAcknowledged: true, inputVersionId: fixed.id, inputs: fixed.inputs, parameters: options.parameters }, undefined, async () => {});
        preflight = { inputVersionId: fixed.id, missingStopNames: inspected.result.missingStopNames || [] };
        if (preflight.missingStopNames.length) decisions.push(stopDecision(preflight.missingStopNames));
      }
    }
    if (!authorizedTools.includes(requiredTool)) decisions.push(toolDecision(requiredTool));
    const task: ResearchTask = { ...options, workflow: options.workflow || 'validation', id: randomUUID(), conversationId: String(conversationId), requestId, goal,
      authorizedTools: [...authorizedTools], admission: { authorizedTools: [...authorizedTools], options }, decisions,
      status: decisions.length ? 'needs_decision' : 'admission_pending', createdAt: new Date().toISOString(), toolExecutions: [], ...(preflight ? { preflight } : {}) };
    if (task.parameters?.stopPolicy === 'ask' && !preflight?.missingStopNames.length) task.parameters = { ...task.parameters, stopPolicy: 'preserve' };
    await harness.commit(async (tx) => { (await tx.doc(Ledger)).tasks.push(task); }, ctx);
    if (task.status === 'needs_decision') return task;
    return launch(task);
  }
  async function launch(task: ResearchTask) {
    const conversationId = Number(task.conversationId) as ConversationId;
    // An explicit continuation reconciles any already-admitted input by stable identity.
    const existing = await harness.commit((tx) => tx.submissionByRequest(conversationId, task.requestId), ctx);
    const pending = (await harness.inspect(ctx)).submissions;
    if (pending.some((submission) => submission.id !== existing?.id)) throw new Error('项目已有在途或待恢复任务，请先处理原任务');
    const scientific = task.workflow === 'd2p_local';
    if (scientific) await getInputs(task.inputVersionId!, task.conversationId);
    const conversation = (await harness.conversation(conversationId, ctx))!;
    await conversation.configure({ model: { provider: 'faux', modelId: 'faux-1' }, tools: scientific ? [localTool] : [countTool] }, ctx);
    const submission = existing ? (await harness.submission(existing.id, ctx))!
      : await conversation.submit({ type: 'input', requestId: task.requestId, content: task.goal, whenBusy: 'reject' }, ctx);
    await harness.commit(async (tx) => {
      const saved = (await tx.doc(Ledger)).tasks.find((item) => item.id === task.id)!;
      saved.submissionId = submission.id; saved.status = 'running';
    }, ctx);
    void submission.wait(ctx).then(async (settled) => {
      await harness.commit(async (tx) => {
        const saved = (await tx.doc(Ledger)).tasks.find((item) => item.id === task.id)!;
        saved.status = settled.status === 'done' ? 'answered' : settled.reason === 'aborted' ? 'cancelled' : 'failed';
        if (settled.status !== 'done') saved.error = settled.reason;
      }, ctx);
    }).catch(() => { /* Opening never resumes pending work. */ });
    return { ...task, submissionId: submission.id, status: 'running' };
  }
  async function continueTask(taskId: string) {
    const task = (await tasks()).find((item) => item.id === taskId);
    if (!task) throw new Error('任务不存在');
    if (task.status !== 'admission_pending') return task;
    if (task.decisions?.some((decision) => decision.status !== 'answered')) throw new Error('仍有待答复问题');
    return launch(task);
  }
  async function answer(taskId: string, decisionId: string, value: string) {
    const task = (await tasks()).find((item) => item.id === taskId);
    const decision = task?.decisions?.find((item) => item.id === decisionId);
    if (!task || !decision) throw new Error('待决定项不存在');
    if (!decision.options.some((option) => option.value === value)) throw new Error('答复不在允许选项中');
    if (decision.status === 'answered') {
      if (decision.answer !== value) throw new Error('该决定已有不同答复，不能覆盖');
      return task;
    }
    if (task.status !== 'needs_decision') throw new Error('任务当前不等待决定');
    const last = task.decisions!.filter((item) => item.status === 'pending').length === 1;
    if (last && value !== 'decline') {
      if ((await harness.inspect(ctx)).submissions.length) throw new Error('项目正在执行或有待恢复任务，请稍后明确继续');
      if (task.workflow === 'd2p_local') await getInputs(task.inputVersionId!, task.conversationId);
    }
    await harness.commit(async (tx) => {
      const saved = (await tx.doc(Ledger)).tasks.find((item) => item.id === taskId)!;
      const question = saved.decisions!.find((item) => item.id === decisionId)!;
      question.status = 'answered'; question.answer = value; question.answeredAt = new Date().toISOString();
      if (question.kind === 'terminal_stop') saved.parameters = { ...saved.parameters!, stopPolicy: value as 'preserve' | 'add' };
      if (question.kind === 'tool_authorization' && value === 'grant') saved.authorizedTools = [saved.workflow === 'd2p_local' ? 'd2p_local' : 'synthetic_count'];
      if (value === 'decline') saved.status = 'cancelled';
      else if (!saved.decisions!.some((item) => item.status === 'pending')) saved.status = 'admission_pending';
    }, ctx);
    // Return the durable handoff before admission. The user's explicit continue action is retryable.
    return (await tasks()).find((item) => item.id === taskId)!;
  }
  async function cancel(taskId: string) {
    const task = (await tasks()).find((task) => task.id === taskId);
    if (!task) throw new Error('任务不存在');
    if (['needs_decision', 'admission_pending'].includes(task.status)) {
      await harness.commit(async (tx) => { (await tx.doc(Ledger)).tasks.find((item) => item.id === taskId)!.status = 'cancelled'; }, ctx);
      return (await tasks()).find((item) => item.id === taskId)!;
    }
    if (task.status !== 'running') return task;
    const chat = (await harness.conversation(Number(task.conversationId) as ConversationId, ctx))!;
    await chat.abort(ctx);
    await harness.commit(async (tx) => {
      const saved = (await tx.doc(Ledger)).tasks.find((item) => item.id === taskId)!;
      saved.status = 'cancelled';
      for (const execution of saved.toolExecutions) if (execution.status === 'running') execution.status = 'cancelled';
    }, ctx);
    return (await tasks()).find((task) => task.id === taskId)!;
  }
  async function artifact(taskId: string, executionId: string, name: string) {
    const task = (await tasks()).find((task) => task.id === taskId);
    const stored = task?.toolExecutions.find((execution) => execution.id === executionId)?.artifacts?.find((artifact) => artifact.name === name);
    if (!stored) throw new Error('产物不存在');
    const bytes = await files.read(stored.path);
    if (createHash('sha256').update(bytes).digest('hex') !== stored.sha256) throw new Error('产物完整性校验失败');
    return { ...stored, contentBase64: bytes.toString('base64') };
  }
  async function conversation(conversationId: ConversationId) {
    const chat = (await harness.conversation(conversationId, ctx))!;
    const entries = [];
    let cursor;
    do { const page = await chat.entries({ order: 'ascending' }, 200, cursor, ctx); entries.push(...page.items); cursor = page.next; } while (cursor);
    const live = await harness.snapshot(LiveDoc, conversationId, ctx);
    return { conversationId: String(conversationId), entries, live: live || {}, partial: live?.generation?.message?.content || [],
      tasks: (await tasks()).filter((task) => task.conversationId === String(conversationId)), modelRequests: (await harness.snapshot(Ledger, ctx))?.modelRequests || 0,
      scheduling: (await harness.inspect(ctx)).scheduling };
  }
  return { models, registry, bind(value: Harness) { harness = value; }, start, tasks, conversation, cancel, artifact, answer, continueTask,
    async modelRequests() { return (await harness.snapshot(Ledger, ctx))?.modelRequests || 0; } };
}
