import { useEffect, useState } from 'react';
import { request } from './client';
import TaskDecisions, { type TaskDecision } from './TaskDecisions';
import { ExternalJobStatus, type ExternalJob } from './SimulatedJobForm';
export type Artifact = { path: string; sha256: string; size: number; name?: string; mediaType?: string };
export type ScienceRecord = { name: string; protein: string; original_protein: string; dna?: string; status: string; error?: string; checks?: Record<string, boolean>; terminal_stop_present?: boolean; source_file_id: string; source_sha256: string; parameters: { stopPolicy: string; avoid: string }; raw_response?: Record<string, unknown> };
export type ScienceResult = { status: string; inputVersionId: string; engine_info: { label: string; id: string; version: string; network_used: boolean; mapping_sha256?: string; code_sha256?: string }; network_attempts: number; attempt?: { id: string; toolTaskId: number; callId: string }; records: ScienceRecord[] };
export type ToolExecution = { id: string; toolTaskId: number; callId: string; tool: string; input: string; status: string; progress: number; error?: string; result?: { characters?: number } & Partial<ScienceResult>; artifact?: Artifact; artifacts?: Artifact[] };
export type ResearchTask = { id: string; conversationId: string; requestId: string; goal: string; status: string; workflow?: string; submissionId?: number; toolExecutions: ToolExecution[]; decisions?: TaskDecision[]; pauseReason?: string; externalJob?: ExternalJob };
type Block = { type: string; text?: string; name?: string };
type Message = { role: string; provider?: string; model?: string; content: string | Block[] };
export type ConversationState = { conversationId: string; entries: { id: number | string; kind: string; model?: Message[] }[]; partial: Block[]; tasks: ResearchTask[]; scheduling: string; modelRequests: number };
export function useConversation(projectId?: string, conversationId?: string | null) {
  const [snapshot, setSnapshot] = useState<{ projectId: string; data: ConversationState } | null>(null);
  const [connected, setConnected] = useState(false);
  const [problem, setProblem] = useState('');
  useEffect(() => {
    setSnapshot(null); setConnected(false); setProblem('');
    if (!projectId || !conversationId) return;
    let active = true;
    const stream = new EventSource(`/api/workbench/projects/${projectId}/conversations/${conversationId}/events`);
    stream.onmessage = (event) => { if (active) { setSnapshot({ projectId, data: JSON.parse(event.data) }); setConnected(true); setProblem(''); } };
    stream.onerror = () => { if (active) setConnected(false); };
    stream.addEventListener('problem', (event) => { if (active) { setProblem(JSON.parse((event as MessageEvent).data).error); setConnected(false); } });
    return () => { active = false; stream.close(); };
  }, [projectId, conversationId]);
  // Do not show the old conversation between selection and the effect's reset.
  return { state: snapshot && snapshot.projectId === projectId && snapshot.data.conversationId === conversationId ? snapshot.data : null, connected, problem };
}
function text(content: string | Block[]) { return typeof content === 'string' ? content : content.filter((block) => block.type === 'text').map((block) => block.text || '').join(''); }
export function ConversationHistory({ state, projectId }: { state: ConversationState; projectId: string }) {
  return <div className="wb-transcript" aria-label="对话记录">
    {state.entries.map((entry) => <div key={entry.id}>{entry.model?.filter((message) => message.role !== 'system' && text(message.content)).map((message, index) => <article key={index} className={`wb-message wb-message-${message.role}`}><small>{message.role === 'user' ? '你' : message.role === 'toolResult' ? '工具结果' : message.provider && message.provider !== 'faux' ? `SilicoLab · ${message.model || '所选模型'}` : 'SilicoLab · 本机验证模型'}</small><p>{text(message.content)}</p></article>)}</div>)}
    {state.partial.length > 0 && <article className="wb-message wb-partial"><small>模型正在响应</small><p>{text(state.partial)}</p></article>}
    {state.tasks.map((task) => <TaskCard key={task.id} task={task} scheduling={state.scheduling} projectId={projectId} />)}
  </div>;
}
export function TaskCard({ task, scheduling, projectId }: { task: ResearchTask; scheduling: string; projectId: string }) {
  const [cancelError, setCancelError] = useState('');
  const [cancelling, setCancelling] = useState(false);
  async function cancel() {
    setCancelling(true); setCancelError('');
    try { await request(`/projects/${projectId}/tasks/${task.id}/cancel`, 'POST'); }
    catch (error) { setCancelError((error as Error).message); }
    finally { setCancelling(false); }
  }
  async function control(operation: 'pause' | 'resume' | 'reconcile') {
    if (cancelling) return;
    setCancelling(true); setCancelError('');
    try { await request(`/projects/${projectId}/tasks/${task.id}/${operation}`, 'POST'); }
    catch (error) { setCancelError((error as Error).message); }
    finally { setCancelling(false); }
  }
  const status = task.status === 'waiting_external' ? '等待独立外部作业' : task.status === 'result_unknown' ? '结果未知，等待核对' : task.status === 'external_submitting' ? '正在核对提交回执' : task.status === 'queued' ? '已排队，等待项目执行位置' : task.status === 'paused' ? '已暂停，等待选择恢复' : task.status === 'pausing' ? '正在停止本机执行' : task.status === 'running' && scheduling === 'paused' ? '等待选择恢复' : task.status === 'answered' ? task.workflow === 'protein_factory_remote' ? '科学请求已返回，请核对校验' : '模型已答复' : task.status === 'needs_decision' ? '需要用户决定' : task.status === 'admission_pending' ? '答复已保存，等待明确继续' : task.status === 'failed' ? '执行失败' : task.status === 'cancelled' ? '任务已取消' : '正在执行';
  return <section className="wb-task-card" aria-label={`任务 ${task.id}`}><header><strong>{status}</strong><small>{task.id.slice(0, 8)}</small>{['running', 'queued', 'waiting_external', 'result_unknown'].includes(task.status) && <button disabled={cancelling} onClick={() => control('pause')}>暂停本机任务</button>}{task.status === 'paused' && <button disabled={cancelling} onClick={() => control('resume')}>恢复此任务</button>}{['running', 'waiting_external', 'result_unknown'].includes(task.status) && <button disabled={cancelling} onClick={cancel}>{cancelling ? '正在取消…' : '取消本机任务'}</button>}</header>{cancelError && <p role="alert">{cancelError}</p>}<p>{task.goal}</p>{task.externalJob && <ExternalJobStatus projectId={projectId} taskId={task.id} taskStatus={task.status} job={task.externalJob} />}{task.workflow === 'protein_factory_remote' && <div className="wb-science-summary"><strong>计算来源：ProteinFactory 远端科学服务（非模型 provider）</strong>{['result_unknown', 'paused'].includes(task.status) && <><p>本机停止不代表远端未执行。没有已验证的服务查询接口，不自动重提或回退。</p><button disabled={cancelling} onClick={() => control('reconcile')}>核对远端请求记录</button></>}</div>}{task.pauseReason && <p>暂停原因：{task.pauseReason}</p>}{task.status === 'needs_decision' && <p>任务等待必要决定，尚未发起后续模型或工具请求。</p>}{task.decisions?.length ? <TaskDecisions projectId={projectId} taskId={task.id} taskStatus={task.status} decisions={task.decisions} /> : null}{task.toolExecutions.map((execution) => <div className="wb-tool-execution" key={execution.id}><strong>{execution.tool}</strong><small>输入：{execution.input}</small><progress max={100} value={execution.progress} aria-label="工具执行进度" /><span>{execution.status === 'unknown' ? '结果未知，不自动重试' : execution.status === 'completed' ? '工具已完成' : execution.status === 'failed' ? '工具执行失败' : execution.status === 'cancelled' ? '工具已取消' : execution.status === 'paused' ? '步骤已暂停，恢复时核对并重做未完成部分' : '工具执行中'} · {execution.progress}%</span>{execution.error && <p role="alert">{execution.error}</p>}{typeof execution.result?.characters === 'number' && <p>实际字符数：{execution.result.characters}</p>}{execution.result?.records && <div className="wb-science-summary"><strong>实际计算来源：{execution.result.engine_info?.label} · {execution.result.engine_info?.version}</strong><small>固定输入：{execution.result.inputVersionId}；网络请求：{execution.result.network_attempts}</small>{execution.result.records.map((record, index) => <article key={index}><h4>{record.name} · {record.status === 'completed' ? '已校验' : record.status === 'unknown' ? '结果未知' : record.status === 'not_attempted' ? '尚未发送' : '失败'}</h4>{record.dna && <pre>{record.dna}</pre>}{record.error && <p role="alert">{record.error}</p>}</article>)}</div>}{execution.artifacts?.filter((artifact) => !artifact.name?.startsWith('sequence-')).map((artifact) => <a className="button outline small" key={artifact.path} href={`/api/workbench/projects/${projectId}/tasks/${task.id}/artifacts/${execution.id}/${artifact.name}`} download>{artifact.name === 'synthesis.xlsx' ? '下载合成表 Excel' : artifact.name === 'synthesis.fasta' ? '下载 DNA FASTA' : artifact.name === 'records.zip' ? '下载完整记录包' : artifact.name === 'simulated-result.json' ? '下载模拟结果' : '下载来源记录'}</a>)}{execution.artifact && <details><summary>查看产物来源</summary><code>{execution.artifact.path}</code><code>SHA-256: {execution.artifact.sha256}</code><code>执行尝试：{execution.id} / 内核工具：{execution.toolTaskId}</code></details>}</div>)}<small>模型答复不等于科研任务完成；计算结果以实际产物和独立校验为准。</small></section>;
}
