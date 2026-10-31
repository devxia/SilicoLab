import { useState } from 'react';
import { request, type Project } from './client';

export default function PythonAnalysisForm({ project, conversationId }: { project: Project; conversationId: string }) {
  const [versionId, setVersionId] = useState('');
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [identity, setIdentity] = useState<string | null>(null);
  return <section className="wb-local-form" aria-label="受限Python临时分析"><h3>临时分析 · 受限 Python</h3><p>先复用已有科学工具；此入口用于临时数值CSV摘要。模型生成可检视脚本，独立Python/Seatbelt实际执行；预装statistics/openpyxl，禁止网络、安装、原件写入、凭据与派生进程。不是任意宿主shell。</p><label>固定CSV输入<select aria-label="固定CSV输入" value={versionId} disabled={busy} onChange={(e) => { setVersionId(e.target.value); setIdentity(null); }}><option value="">选择已固定输入（一个CSV，仅value列）</option>{project.inputVersions.filter(v => v.conversationId === conversationId).map(v => <option key={v.id} value={v.id}>{v.id.slice(0,8)} · {v.inputs.map(i => i.name).join('、')}</option>)}</select></label><label className="wb-scope-check"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} disabled={busy} />仅授权本任务生成并受限运行临时分析脚本，不调用科学远端</label><button className="button primary" disabled={busy || !versionId || !ack} onClick={async () => {
    if (busy) return;
    setBusy(true); setError(''); const key = identity || crypto.randomUUID(); setIdentity(key);
    try { await request(`/projects/${project.id}/tasks`, 'POST', { conversationId, requestId:key, workflow:'python_analysis', inputVersionId:versionId, goal:'临时分析固定CSV的value数值列，生成脚本、JSON及Excel并独立校验', authorizedTools:['python_analysis'] }); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }}>{busy ? '正在提交…' : '运行受限临时分析'}</button>{error && <p role="alert">{error}</p>}</section>;
}
