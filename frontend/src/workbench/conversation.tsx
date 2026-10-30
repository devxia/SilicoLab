import { useEffect, useState } from 'react';
export type ToolExecution = { id: string; toolTaskId: number; callId: string; tool: string; input: string; status: string; progress: number; error?: string; result?: { characters: number }; artifact?: { path: string; sha256: string; size: number } };
export type ResearchTask = { id: string; conversationId: string; requestId: string; goal: string; status: string; submissionId?: number; toolExecutions: ToolExecution[] };
type Block = { type: string; text?: string; name?: string };
type Message = { role: string; content: string | Block[] };
export type ConversationState = { conversationId: string; entries: { id: number; kind: string; model?: Message[] }[]; partial: Block[]; tasks: ResearchTask[]; scheduling: string; modelRequests: number };
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
    stream.addEventListener('problem', (event) => { if (active) { setProblem(JSON.parse((event as MessageEvent).data).error); setConnected(false); stream.close(); } });
    return () => { active = false; stream.close(); };
  }, [projectId, conversationId]);
  // Do not show the old conversation between selection and the effect's reset.
  return { state: snapshot && snapshot.projectId === projectId && snapshot.data.conversationId === conversationId ? snapshot.data : null, connected, problem };
}
function text(content: string | Block[]) { return typeof content === 'string' ? content : content.filter((block) => block.type === 'text').map((block) => block.text || '').join(''); }
export function ConversationHistory({ state }: { state: ConversationState }) {
  return <div className="wb-transcript" aria-label="对话记录">
    {state.entries.map((entry) => <div key={entry.id}>{entry.model?.filter((message) => message.role !== 'system' && text(message.content)).map((message, index) => <article key={index} className={`wb-message wb-message-${message.role}`}><small>{message.role === 'user' ? '你' : message.role === 'toolResult' ? '工具结果' : 'SilicoLab · 本机验证模型'}</small><p>{text(message.content)}</p></article>)}</div>)}
    {state.partial.length > 0 && <article className="wb-message wb-partial"><small>本机验证模型 · 正在响应</small><p>{text(state.partial)}</p></article>}
    {state.tasks.map((task) => <TaskCard key={task.id} task={task} scheduling={state.scheduling} />)}
  </div>;
}
export function TaskCard({ task, scheduling }: { task: ResearchTask; scheduling: string }) {
  const status = task.status === 'running' && scheduling === 'paused' ? '等待选择恢复' : task.status === 'answered' ? '模型已答复' : task.status === 'needs_decision' ? '需要用户决定' : task.status === 'failed' ? '执行失败' : '正在执行';
  return <section className="wb-task-card" aria-label={`任务 ${task.id}`}><header><strong>{status}</strong><small>{task.id.slice(0, 8)}</small></header><p>{task.goal}</p>{task.status === 'needs_decision' && <p>当前任务未授权所需工具，尚未发起模型或执行请求。</p>}{task.toolExecutions.map((execution) => <div className="wb-tool-execution" key={execution.id}><strong>{execution.tool}</strong><small>输入：{execution.input}</small><progress max={100} value={execution.progress} aria-label="工具执行进度" /><span>{execution.status === 'completed' ? '工具已完成' : execution.status === 'failed' ? '工具执行失败' : '工具执行中'} · {execution.progress}%</span>{execution.error && <p role="alert">{execution.error}</p>}{execution.result && <p>实际字符数：{execution.result.characters}</p>}{execution.artifact && <details><summary>查看产物来源</summary><code>{execution.artifact.path}</code><code>SHA-256: {execution.artifact.sha256}</code><code>执行尝试：{execution.id} / 内核工具：{execution.toolTaskId}</code></details>}</div>)}<small>模型答复不等于科研任务完成；此处仅做本机人工验证。</small></section>;
}
