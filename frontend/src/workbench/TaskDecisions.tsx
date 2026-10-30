import { useState } from 'react';
import { request } from './client';
import './decisions.css';

export type TaskDecision = { id: string; kind: 'terminal_stop' | 'tool_authorization'; question: string; options: { value: string; label: string }[]; status: 'pending' | 'answered'; answer?: string; answeredAt?: string };
export default function TaskDecisions({ projectId, taskId, taskStatus, decisions }: { projectId: string; taskId: string; taskStatus: string; decisions: TaskDecision[] }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function answer(decision: TaskDecision, value: string) {
    if (busy) return;
    setBusy(true); setError('');
    try {
      const saved = await request<{ status: string }>(`/projects/${projectId}/tasks/${taskId}/decisions/${decision.id}`, 'POST', { answer: value });
      // The click authorizes continuation; the durable answer remains retryable if admission fails.
      if (saved.status === 'admission_pending') await request(`/projects/${projectId}/tasks/${taskId}/continue`, 'POST');
    }
    catch (error) { setError((error as Error).message); }
    finally { setBusy(false); }
  }
  async function continueTask() {
    if (busy) return;
    setBusy(true); setError('');
    try { await request(`/projects/${projectId}/tasks/${taskId}/continue`, 'POST'); }
    catch (error) { setError((error as Error).message); }
    finally { setBusy(false); }
  }
  return <div className="wb-task-decisions" aria-label="任务待决定事项">{decisions.map((decision) => <section key={decision.id} aria-label={`决定 ${decision.id}`}>
    <strong>{decision.question}</strong>
    {decision.status === 'answered' ? <p>已答复：{decision.options.find((option) => option.value === decision.answer)?.label || decision.answer}</p>
      : taskStatus === 'needs_decision' ? <div>{decision.options.map((option) => <button className="button outline small" key={option.value} disabled={busy} onClick={() => answer(decision, option.value)}>{option.label}</button>)}</div>
      : <p>该任务当前不接受答复。</p>}
    <small>决定仅作用于当前任务，不修改原始项目文件。{decision.id.slice(0, 8)}</small>
  </section>)}{taskStatus === 'admission_pending' && <button className="button primary small" disabled={busy} onClick={continueTask}>{busy ? '正在继续…' : '继续已答复任务'}</button>}{error && <p role="alert">{error}</p>}</div>;
}
