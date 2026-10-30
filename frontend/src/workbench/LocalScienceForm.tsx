import { useRef, useState } from 'react';
import { request, type Project } from './client';

export default function LocalScienceForm({ project, conversationId }: { project: Project; conversationId: string }) {
  const [versionId, setVersionId] = useState('');
  const [acknowledged, setAcknowledged] = useState(false);
  const [stopPolicy, setStopPolicy] = useState<'preserve' | 'add'>('preserve');
  const [avoid, setAvoid] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [started, setStarted] = useState(false);
  const identity = useRef<{ key: string; id: string } | null>(null);
  const versions = project.inputVersions.filter((item) => item.conversationId === conversationId);
  async function run() {
    if (busy) return;
    setBusy(true); setError('');
    const key = JSON.stringify({ project: project.id, conversationId, versionId, stopPolicy, avoid, acknowledged });
    if (identity.current?.key !== key) identity.current = { key, id: crypto.randomUUID() };
    try {
      await request(`/projects/${project.id}/tasks`, 'POST', {
        conversationId, requestId: identity.current.id,
        goal: '使用 ProteinFactory / D2P 专项的本地实验，按固定输入和所选终止符及避免位点处理、校验并导出。',
        workflow: 'd2p_local', specialtyAcknowledged: acknowledged, inputVersionId: versionId,
        authorizedTools: ['d2p_local'], parameters: { stopPolicy, avoid },
      });
      identity.current = null; setStarted(true);
    } catch (error) { setError((error as Error).message); }
    finally { setBusy(false); }
  }
  return <section className="wb-local-form" aria-label="D2P 专项本地实验任务">
    <h3>D2P 专项 · 本地实验</h3><p>实际计算来源：本地 Python 实验引擎。不会调用 ProteinFactory 远端。模型只编排工具，不自行生成 DNA。</p>
    <p>D2P 无细胞体系、pD2P_1.08t、预设插入位置专项；尚无载体校验，不能用于任意宿主或载体。</p>
    <label>固定输入版本<select value={versionId} disabled={busy} onChange={(event) => { setVersionId(event.target.value); setStarted(false); }}><option value="">请先在文件区固定 FASTA 输入</option>{versions.map((version) => <option key={version.id} value={version.id}>{version.id.slice(0, 8)} · {version.inputs.map((input) => `${input.name} v${input.version}`).join('、')}</option>)}</select></label>
    <label>终止符策略<select value={stopPolicy} disabled={busy} onChange={(event) => { setStopPolicy(event.target.value as 'preserve' | 'add'); setStarted(false); }}><option value="preserve">保留输入终止符，不自动补充</option><option value="add">明确补充末尾终止符 *</option></select></label>
    <label>正反向避免位点<input value={avoid} disabled={busy} placeholder="例如 GAATTC,GGTCTC" onChange={(event) => { setAvoid(event.target.value); setStarted(false); }} /></label>
    <label className="wb-scope-check"><input type="checkbox" checked={acknowledged} disabled={busy} onChange={(event) => setAcknowledged(event.target.checked)} />我明确使用 D2P 专项的本地实验，不使用远端</label>
    {error && <p role="alert">{error}</p>}
    <button className="button primary" disabled={busy || !acknowledged || !versionId || started} onClick={run}>{busy ? '正在提交…' : started ? '已提交本地任务' : '运行 D2P 专项本地实验'}</button>
  </section>;
}
