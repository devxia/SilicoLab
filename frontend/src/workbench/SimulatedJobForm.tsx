import { useRef, useState } from 'react';
import { request } from './client';
import './external.css';

export type ExternalJob = { requestKey: string; payloadHash: string; serviceId: string; jobId?: string; state: string; error?: string; result?: { characters: number; payload: string } };
export default function SimulatedJobForm({ projectId, conversationId }: { projectId: string; conversationId: string }) {
  const [payload, setPayload] = useState('ABC');
  const [mode, setMode] = useState<'normal' | 'lost'>('normal');
  const [queryable, setQueryable] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const identity = useRef<{ value: string; id: string } | null>(null);
  async function submit() {
    if (busy) return;
    setBusy(true); setError('');
    const value = JSON.stringify({ projectId, conversationId, payload, mode, queryable });
    if (identity.current?.value !== value) identity.current = { value, id: crypto.randomUUID() };
    try {
      await request(`/projects/${projectId}/tasks`, 'POST', { conversationId, requestId: identity.current.id,
        goal: '明确提交本机模拟外部作业，仅人工文本，不运行真实科学计算。', workflow: 'simulated_external', authorizedTools: ['simulated_external'],
        simulation: { payload, durationMs: 3500, queryable, responseMode: mode } });
      identity.current = null;
    } catch (error) { setError((error as Error).message); }
    finally { setBusy(false); }
  }
  return <section className="wb-local-form" aria-label="模拟外部作业表单"><h3>模拟外部作业</h3><p>仅使用本机假服务和人工文本。服务持久状态独立于智能体；这里不连接真实集群、GPU 或科学服务。</p><label>模拟输入文本<input value={payload} maxLength={10000} disabled={busy} onChange={(event) => setPayload(event.target.value)} /></label><label>模拟响应<select value={mode} disabled={busy} onChange={(event) => setMode(event.target.value as 'normal' | 'lost')}><option value="normal">正常接收回执</option><option value="lost">接受后丢失回执，演练对账</option></select></label><label className="wb-scope-check"><input type="checkbox" checked={queryable} disabled={busy} onChange={(event) => setQueryable(event.target.checked)} />假服务支持按稳定身份查询</label><button className="button outline" disabled={busy} onClick={submit}>{busy ? '正在提交…' : '提交人工模拟作业'}</button>{error && <p role="alert">{error}</p>}</section>;
}
export function ExternalJobStatus({ projectId, taskId, taskStatus, job }: { projectId: string; taskId: string; taskStatus: string; job: ExternalJob }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function operate(operation: 'reconcile' | 'cancel') {
    if (busy) return;
    setBusy(true); setError('');
    try { await request(`/projects/${projectId}/tasks/${taskId}/external/${operation}`, 'POST'); }
    catch (error) { setError((error as Error).message); }
    finally { setBusy(false); }
  }
  const state = ({ not_submitted: '尚未提交', submitting: '提交效果待确认', running: '独立作业运行中', succeeded: '独立作业已完成', cancelled: '独立作业已取消', unknown: '结果未知' } as Record<string, string>)[job.state] || job.state;
  return <div className="wb-external-status" aria-label="独立模拟作业状态"><strong>模拟作业 · {state}</strong><small>服务身份：{job.serviceId}</small><small>稳定请求：{job.requestKey}</small><small>作业 ID：{job.jobId || '未确认，必须先对账'}</small><small>输入 SHA-256：{job.payloadHash}</small>{job.error && <p>核对信息：{job.error}</p>}<div><button className="button outline small" disabled={busy || job.state === 'cancelled' || taskStatus === 'cancelled'} onClick={() => operate('reconcile')}>核对模拟作业</button><button className="button outline small" disabled={busy || job.state === 'cancelled' || job.state === 'succeeded'} onClick={() => operate('cancel')}>独立取消模拟作业</button></div>{job.result && <p>已核对模拟结果：字符数 {job.result.characters}（不是科学计算）</p>}{error && <p role="alert">{error}</p>}<small>暂停或停止本机任务不会自动取消独立作业。</small></div>;
}
