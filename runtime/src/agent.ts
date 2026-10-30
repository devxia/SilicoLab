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
import { ExecutionOwner, ExecutionStores } from './executions.ts';

const ctx = BACKGROUND_CONTEXT;
type Artifact = { path: string; sha256: string; size: number; name?: string; mediaType?: string };
type ExecutionResult = { characters: number } | ScienceResult;
type Execution = { id: string; toolTaskId: number; callId: string; tool: string; input: string; progress: number; status: string; error?: string; pythonPid?: number; artifact?: Artifact; artifacts?: Artifact[]; result?: ExecutionResult };
export type ResearchTask = ScienceOptions & { id: string; conversationId: string; requestId: string; goal: string; status: string; authorizedTools: string[]; createdAt: string; submissionId?: SubmissionId; toolExecutions: Execution[]; error?: string; pauseReason?: string; isolatedExecution?: boolean; queuedAt?: string; startedAt?: string; finishedAt?: string; decisions?: TaskDecision[]; admission?: { authorizedTools: string[]; options: ScienceOptions }; preflight?: { missingStopNames: string[]; inputVersionId: string } };
const Ledger = defineDoc<{ tasks: ResearchTask[]; modelRequests: number; queue?: string[] }>({
  kind: 'silicolab.tasks', version: 1, scope: 'session', initial: () => ({ tasks: [], modelRequests: 0 }), checkpointWhen: () => true,
});
type FixedInputs = Awaited<ReturnType<ProjectFiles['fixed']>>;

/** Model adapter and controlled tools. Only pi-durable owns the agent loop. */
export function createLocalAgent(directory: string, getInputs: (id: string, conversationId: string) => Promise<FixedInputs>) {
  let harness: Harness;
  const files = new ProjectFiles(directory);
  const models = createModels();
  const registry = createRegistry();
  let activeKernel: Harness | undefined;
  let activeTaskId: string | undefined;
  let pumping: Promise<void> | undefined;
  let stopping = false;
  const executions = new ExecutionStores(directory, () => ({ models, registry,
    settings: { compaction: { enabled: false }, retry: { maxRetries: 0 }, restartLimit: 3, progress: { partialIntervalMs: 30, outputIntervalMs: 30 } } }));
  const faux = fauxProvider({ tokensPerSecond: 30 });
  models.setProvider(faux.provider);
  const response: Parameters<typeof faux.setResponses>[0][number] = async (transcript, options) => {
    faux.appendResponses([response]);
    await harness.commit(async (tx) => { (await tx.doc(Ledger)).modelRequests++; }, ctx);
    const last = transcript.messages.at(-1);
    if (last?.role === 'toolResult') {
      // Faux adapter models an observable, cancellable in-flight final request.
      await delay(500, undefined, { signal: options?.signal });
      return fauxAssistantMessage(last.isError
        ? '工具未完成，请查看实际错误和保留记录。模型答复不代表科研成功。'
        : last.toolName === 'd2p_local' ? '本地 D2P 专项已返回实际结果，请核对逐项校验和科研产物；表达效果仍需实验验证。'
        : '本机人工文本计数已生成可检查结果。这是验证模型，不是科研结论。');
    }
    const user = transcript.messages.findLast((entry) => entry.role === 'user');
    const text = user?.role === 'user' && typeof user.content === 'string' ? user.content : '';
    const active = (await (activeKernel || harness).inspect(ctx)).submissions.filter((submission) => submission.type === 'input' && submission.status === 'placed');
    if (active.length !== 1) throw new Error('本机验证模型无法确定唯一已准入任务');
    const task = await taskForSubmission(active[0].conversationId, active[0].id);
    const tool = task.workflow === 'd2p_local' ? 'd2p_local' : 'synthetic_count';
    return fauxAssistantMessage([fauxToolCall(tool, tool === 'synthetic_count' ? { text } : {}, { id: randomUUID() })], { stopReason: 'toolUse' });
  };
  faux.setResponses([response]);

  async function verifyCompleted(execution: Execution, message: string) {
    for (const stored of [...(execution.artifacts || []), ...(execution.artifact ? [execution.artifact] : [])]) {
      const bytes = await files.read(stored.path);
      if (createHash('sha256').update(bytes).digest('hex') !== stored.sha256) throw new Error(message);
    }
  }
  async function tracked(tool: string, input: string, api: ToolExecutionApi, context: Context,
    work: (task: ResearchTask, id: string, progress: (value: number, pythonPid?: number) => Promise<void>) => Promise<{ result: ExecutionResult; artifact?: Artifact; artifacts?: Artifact[]; isError?: boolean; error?: string }>) {
    const live = await api.snapshot(LiveDoc, api.conversationId, ctx);
    if (live?.run?.inputs.length !== 1) throw new Error('工具无法关联唯一内核输入');
    const task = await taskForSubmission(api.conversationId, live.run.inputs[0]);
    if (!task.authorizedTools.includes(tool)) throw new Error('需要用户决定：当前任务未授权所需工具');
    const completed = task.toolExecutions.find((execution) => execution.toolTaskId === api.taskId && execution.status === 'completed');
    if (completed?.result) {
      await verifyCompleted(completed, '完成步骤产物完整性不符，需先核对');
      const summary = 'records' in completed.result ? { status: completed.result.status, records: completed.result.records.length } : completed.result;
      return { isError: false, output: [{ type: 'text' as const, text: JSON.stringify(summary) }], details: { result: completed.result, reused: true } };
    }
    const id = randomUUID();
    await harness.commit(async (tx) => {
      (await tx.doc(Ledger)).tasks.find((item) => item.id === task.id)!.toolExecutions.push({ id, toolTaskId: api.taskId, callId: api.callId, tool, input, status: 'running', progress: 0 });
    }, context);
    const progress = async (value: number, pythonPid?: number) => {
      api.output(`处理进度 ${value}%\n`);
      await api.details({ progress: value, input }, context);
      await harness.commit(async (tx) => {
        const attempt = (await tx.doc(Ledger)).tasks.find((item) => item.id === task.id)!.toolExecutions.find((item) => item.id === id)!;
        attempt.progress = value;
        if (pythonPid) attempt.pythonPid = pythonPid;
      }, context);
    };
    try {
      const outcome = await work(task, id, progress);
      await harness.commit(async (tx) => {
        const execution = (await tx.doc(Ledger)).tasks.find((item) => item.id === task.id)!.toolExecutions.find((item) => item.id === id)!;
        execution.status = outcome.isError ? 'failed' : 'completed'; execution.progress = 100; execution.result = outcome.result;
        if (outcome.error) execution.error = outcome.error;
        if (outcome.artifact) execution.artifact = outcome.artifact;
        if (outcome.artifacts) execution.artifacts = outcome.artifacts;
      }, context);
      // Only bounded summary goes to the model. Full scientific records remain task evidence.
      const summary = 'records' in outcome.result ? { status: outcome.result.status, records: outcome.result.records.length } : outcome.result;
      return { isError: outcome.isError || false, output: [{ type: 'text' as const, text: JSON.stringify(summary) }], details: { result: outcome.result, reused: false } };
    } catch (error) {
      if (!context.abortSignal?.aborted) await harness.commit(async (tx) => {
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
    const kernel = activeKernel || harness;
    const submission = await kernel.submission(submissionId, ctx);
    const record = await submission?.status(ctx);
    const owner = await kernel.snapshot(ExecutionOwner, ctx);
    const task = record?.conversationId === conversationId && record.requestId
      ? (await tasks()).find((item) => (owner?.taskId ? item.id === owner.taskId : item.conversationId === String(conversationId)) && item.requestId === record.requestId)
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
    if (stopping) throw new Error('项目正在关闭');
    if ((await tasks()).filter((task) => ['running', 'queued', 'needs_decision', 'admission_pending', 'paused'].includes(task.status)).length >= 100) throw new Error('项目未完成任务已达100项，请先处理');
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
      authorizedTools: [...authorizedTools], isolatedExecution: true, admission: { authorizedTools: [...authorizedTools], options }, decisions,
      status: decisions.length ? 'needs_decision' : 'admission_pending', createdAt: new Date().toISOString(), toolExecutions: [], ...(preflight ? { preflight } : {}) };
    if (task.parameters?.stopPolicy === 'ask' && !preflight?.missingStopNames.length) task.parameters = { ...task.parameters, stopPolicy: 'preserve' };
    await harness.commit(async (tx) => { (await tx.doc(Ledger)).tasks.push(task); }, ctx);
    if (task.status === 'needs_decision') return task;
    return enqueue(task.id);
  }
  async function kernelFor(task: ResearchTask) { return task.isolatedExecution ? executions.openPinned(task.id) : harness; }
  function borrowKernel<T>(task: ResearchTask, operation: (kernel: Harness) => Promise<T>): Promise<T> {
    return task.isolatedExecution ? executions.withStore(task.id, operation) : operation(harness);
  }
  async function enqueue(taskId: string) {
    await harness.commit(async (tx) => {
      const ledger = await tx.doc(Ledger);
      const task = ledger.tasks.find((task) => task.id === taskId)!;
      task.status = 'queued'; task.queuedAt = new Date().toISOString();
      ledger.queue = [...(ledger.queue || []).filter((id) => id !== taskId), taskId];
    }, ctx);
    await pump();
    return (await tasks()).find((task) => task.id === taskId)!;
  }
  async function pump() {
    if (pumping) return pumping;
    pumping = (async () => {
      while (!stopping && !activeTaskId) {
        const ledger = await harness.snapshot(Ledger, ctx);
        const task = (ledger?.queue || []).map((id) => ledger?.tasks.find((task) => task.id === id)).find((task) => task?.status === 'queued');
        if (!task) return;
        activeTaskId = task.id;
        try { await launch(task); }
        catch (error) {
          activeTaskId = undefined; activeKernel = undefined; executions.pin(undefined);
          await harness.commit(async (tx) => { const saved = (await tx.doc(Ledger)).tasks.find((item) => item.id === task.id)!; saved.status = 'paused'; saved.pauseReason = String(error); }, ctx);
        }
      }
    })().finally(() => { pumping = undefined; });
    return pumping;
  }
  async function launch(task: ResearchTask) {
    executions.pin(task.id);
    const kernel = await kernelFor(task);
    activeKernel = kernel;
    const conversationId = task.isolatedExecution ? (await kernel.root(ctx)).id : Number(task.conversationId) as ConversationId;
    // An explicit continuation reconciles any already-admitted input by stable identity.
    const existing = await kernel.commit((tx) => tx.submissionByRequest(conversationId, task.requestId), ctx);
    const pending = (await kernel.inspect(ctx)).submissions;
    if (pending.some((submission) => submission.id !== existing?.id)) throw new Error('项目已有在途或待恢复任务，请先处理原任务');
    const scientific = task.workflow === 'd2p_local';
    if (scientific) await getInputs(task.inputVersionId!, task.conversationId);
    // Queue time can be unbounded: recheck completed evidence at the actual admission boundary.
    for (const execution of task.toolExecutions) if (execution.status === 'completed') await verifyCompleted(execution, '完成产物已改变，准入前需核对');
    const conversation = (await kernel.conversation(conversationId, ctx))!;
    await conversation.configure({ model: { provider: 'faux', modelId: 'faux-1' }, tools: scientific ? [localTool] : [countTool] }, ctx);
    const submission = existing ? (await kernel.submission(existing.id, ctx))!
      : await conversation.submit({ type: 'input', requestId: task.requestId, content: task.goal, whenBusy: 'reject' }, ctx);
    await harness.commit(async (tx) => {
      const saved = (await tx.doc(Ledger)).tasks.find((item) => item.id === task.id)!;
      saved.submissionId = submission.id; saved.status = 'running'; saved.startedAt = new Date().toISOString();
    }, ctx);
    void submission.wait(ctx).then(async (settled) => {
      await harness.commit(async (tx) => {
        const saved = (await tx.doc(Ledger)).tasks.find((item) => item.id === task.id)!;
        saved.status = settled.status === 'done' ? 'answered' : settled.reason === 'aborted' ? 'cancelled' : 'failed';
        if (settled.status !== 'done') saved.error = settled.reason;
        saved.finishedAt = new Date().toISOString();
      }, ctx);
      if (activeTaskId === task.id) { activeTaskId = undefined; activeKernel = undefined; executions.pin(undefined); }
      void pump();
    }).catch(() => { /* Opening never resumes pending work. */ });
    return { ...task, submissionId: submission.id, status: 'running' };
  }
  async function reconcileOpen() {
    const saved = await tasks();
    const changes: { id: string; status: string; reason?: string }[] = [];
    for (const task of saved) {
      if (!['running', 'pausing', 'queued'].includes(task.status)) continue;
      if (task.status === 'queued') {
        changes.push({ id: task.id, status: 'paused', reason: '宿主重开；原排队任务等待明确选择恢复' });
        continue;
      }
      const submitted = await borrowKernel(task, async (kernel) => {
        const conversationId = task.isolatedExecution ? (await kernel.root(ctx)).id : Number(task.conversationId) as ConversationId;
        return kernel.commit((tx) => tx.submissionByRequest(conversationId, task.requestId), ctx);
      });
      changes.push({ id: task.id, status: submitted?.status === 'done' ? 'answered' : 'paused',
        reason: task.status === 'pausing' ? '用户暂停；本机执行已停止' : '宿主中断或退出；等待明确恢复' });
    }
    if (changes.length) await harness.commit(async (tx) => {
      const ledger = await tx.doc(Ledger);
      for (const change of changes) {
        const task = ledger.tasks.find((task) => task.id === change.id)!;
        task.status = change.status;
        if (change.status === 'paused') {
          task.pauseReason = change.reason!;
          for (const execution of task.toolExecutions) if (execution.status === 'running') execution.status = 'paused';
        }
      }
    }, ctx);
  }
  async function preparePause(taskId: string) {
    const task = (await tasks()).find((task) => task.id === taskId);
    if (!task) throw new Error('任务不存在');
    if (task.status === 'queued') {
      await harness.commit(async (tx) => { const saved = (await tx.doc(Ledger)).tasks.find((task) => task.id === taskId)!; saved.status = 'paused'; saved.pauseReason = '用户暂停排队任务'; }, ctx);
      return { needsClose: false, task: (await tasks()).find((task) => task.id === taskId)! };
    }
    if (task.status !== 'running') return { needsClose: false, task };
    await harness.commit(async (tx) => { (await tx.doc(Ledger)).tasks.find((task) => task.id === taskId)!.status = 'pausing'; }, ctx);
    if (task.isolatedExecution) {
      await executions.close(task.id);
      await harness.commit(async (tx) => {
        const saved = (await tx.doc(Ledger)).tasks.find((task) => task.id === taskId)!;
        saved.status = 'paused'; saved.pauseReason = '用户暂停；本机执行已停止';
        for (const execution of saved.toolExecutions) if (execution.status === 'running') execution.status = 'paused';
      }, ctx);
      if (activeTaskId === taskId) { activeTaskId = undefined; activeKernel = undefined; }
      await pump();
      return { needsClose: false, task: (await tasks()).find((task) => task.id === taskId)! };
    }
    return { needsClose: true, taskId };
  }
  async function resume(taskId: string) {
    const task = (await tasks()).find((task) => task.id === taskId);
    if (!task) throw new Error('任务不存在');
    if (task.status !== 'paused') return task;
    const { conversationId, pending } = await borrowKernel(task, async (kernel) => ({
      conversationId: task.isolatedExecution ? (await kernel.root(ctx)).id : Number(task.conversationId) as ConversationId,
      pending: await kernel.inspect(ctx),
    }));
    if (!task.isolatedExecution && pending.tasks.some((item) => String(item.record.conversationId) !== task.conversationId)) throw new Error('历史存储存在其他未获选择的执行，不能整体恢复');
    const blocked = pending.tasks.find((item) => item.record.conversationId === conversationId && item.state.kind === 'blocked');
    if (blocked?.state.kind === 'blocked') {
      const reason = `内核执行已停放：${blocked.state.reason}；未启动恢复，请先检查中断原因`;
      await harness.commit(async (tx) => { (await tx.doc(Ledger)).tasks.find((item) => item.id === taskId)!.pauseReason = reason; }, ctx);
      throw new Error(reason);
    }
    if (task.workflow === 'd2p_local') await getInputs(task.inputVersionId!, task.conversationId);
    for (const execution of task.toolExecutions) if (execution.status === 'completed') {
      await verifyCompleted(execution, '完成产物已改变，恢复前需核对');
    }
    return enqueue(task.id);
  }
  async function continueTask(taskId: string) {
    const task = (await tasks()).find((item) => item.id === taskId);
    if (!task) throw new Error('任务不存在');
    if (task.status !== 'admission_pending') return task;
    if (task.decisions?.some((decision) => decision.status !== 'answered')) throw new Error('仍有待答复问题');
    return enqueue(task.id);
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
    if (['needs_decision', 'admission_pending', 'queued', 'paused'].includes(task.status)) {
      await harness.commit(async (tx) => { (await tx.doc(Ledger)).tasks.find((item) => item.id === taskId)!.status = 'cancelled'; }, ctx);
      return (await tasks()).find((item) => item.id === taskId)!;
    }
    if (task.status !== 'running') return task;
    const kernel = await kernelFor(task);
    const conversationId = task.isolatedExecution ? (await kernel.root(ctx)).id : Number(task.conversationId) as ConversationId;
    const chat = (await kernel.conversation(conversationId, ctx))!;
    await chat.abort(ctx);
    await harness.commit(async (tx) => {
      const saved = (await tx.doc(Ledger)).tasks.find((item) => item.id === taskId)!;
      saved.status = 'cancelled';
      for (const execution of saved.toolExecutions) if (execution.status === 'running') execution.status = 'cancelled';
    }, ctx);
    if (activeTaskId === taskId) { activeTaskId = undefined; activeKernel = undefined; }
    await pump();
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
  async function inspection() { return (activeKernel || harness).inspect(ctx); }
  async function closeExecutions() { stopping = true; await executions.closeAll(); activeTaskId = undefined; activeKernel = undefined; }
  async function conversation(conversationId: ConversationId) {
    const chat = (await harness.conversation(conversationId, ctx))!;
    const entries = [];
    let cursor;
    do { const page = await chat.entries({ order: 'ascending' }, 200, cursor, ctx); entries.push(...page.items.map((entry) => ({ ...entry, id: `legacy-${entry.id}` }))); cursor = page.next; } while (cursor);
    const ownTasks = (await tasks()).filter((task) => task.conversationId === String(conversationId));
    let live = await harness.snapshot(LiveDoc, conversationId, ctx);
    for (const task of ownTasks.filter((task) => task.isolatedExecution && task.submissionId !== undefined)) {
      await borrowKernel(task, async (kernel) => {
        const handle = await kernel.root(ctx);
        let next;
        do { const page = await handle.entries({ order: 'ascending' }, 200, next, ctx); entries.push(...page.items.map((entry) => ({ ...entry, id: `${task.id}-${entry.id}` }))); next = page.next; } while (next);
        if (activeTaskId === task.id) live = await kernel.snapshot(LiveDoc, handle.id, ctx);
      });
    }
    entries.sort((left, right) => (left.model?.[0]?.timestamp || 0) - (right.model?.[0]?.timestamp || 0));
    return { conversationId: String(conversationId), entries, live: live || {}, partial: live?.generation?.message?.content || [],
      tasks: ownTasks, modelRequests: (await harness.snapshot(Ledger, ctx))?.modelRequests || 0,
      scheduling: (await inspection()).scheduling };
  }
  return { models, registry, bind(value: Harness) { harness = value; }, start, tasks, conversation, cancel, artifact, answer, continueTask, reconcileOpen, preparePause, resume, inspection, closeExecutions,
    async modelRequests() { return (await harness.snapshot(Ledger, ctx))?.modelRequests || 0; } };
}
