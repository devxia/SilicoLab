import { useId, useState } from 'react';
import { nativeAPI } from '../platform/native';
import type { ResearchTask, ScienceResult } from './conversation';
import './results.css';

type Tab = '序列表' | 'DNA 与密码子' | '校验与来源';
const TABS: Tab[] = ['序列表', 'DNA 与密码子', '校验与来源'];
export default function ScientificResults({ projectId, tasks }: { projectId: string; tasks: ResearchTask[] }) {
  const candidates = tasks.flatMap((task) => task.toolExecutions.filter((execution) => execution.result?.records).map((execution) => ({ task, execution, result: execution.result as ScienceResult })));
  const [selection, setSelection] = useState('');
  const [recordIndex, setRecordIndex] = useState(0);
  const [tab, setTab] = useState<Tab>('序列表');
  const [notice, setNotice] = useState('');
  const tabId = useId();
  const selected = candidates.find((candidate) => candidate.execution.id === selection) || candidates.at(-1);
  if (!selected) return <p className="wb-result-empty">尚无实际科研结果。模型答复不会被当作科研产物。</p>;
  const { task, execution, result } = selected;
  const record = result.records[recordIndex] || result.records[0];
  const index = result.records.indexOf(record);
  const attempt = result.attempt || { id: execution.id, toolTaskId: execution.toolTaskId, callId: execution.callId };
  const terminalStopPresent = record?.terminal_stop_present ?? record?.protein.endsWith('*');
  const passed = result.records.filter((record) => record.status === 'completed').length;
  const artifact = (name: string) => execution.artifacts?.find((artifact) => artifact.name === name);
  const download = (name: string) => `/api/workbench/projects/${projectId}/tasks/${task.id}/artifacts/${execution.id}/${name}`;
  const status = result.status === 'partial' ? '部分完成' : result.status === 'completed' ? '计算与校验完成' : '计算失败';
  async function copy() {
    if (!record.dna) return;
    try {
      const bridge = nativeAPI();
      if (bridge) await bridge.copy_text(record.dna); else await navigator.clipboard.writeText(record.dna);
      setNotice(`已复制完整 DNA：${record.dna.length} bp`);
    } catch { setNotice('复制未完成，请使用 FASTA 下载完整序列。'); }
  }
  return <div className="wb-scientific-results" aria-label="真实科研结果">
    {candidates.length > 1 && <label>结果执行记录<select value={execution.id} onChange={(event) => { setSelection(event.target.value); setRecordIndex(0); setNotice(''); }}>{candidates.map((candidate) => <option key={candidate.execution.id} value={candidate.execution.id}>{candidate.task.id.slice(0, 8)} / {candidate.execution.id.slice(0, 8)}</option>)}</select></label>}
    <header><h3>{status}</h3><span>{passed} 条通过　{result.records.length - passed} 条失败</span></header>
    <p className="wb-result-source">{result.engine_info.label} · {result.engine_info.version}<br />固定输入 {result.inputVersionId.slice(0, 8)}<br />尝试 {execution.id.slice(0, 8)}</p>
    <div className="wb-result-downloads">{artifact('synthesis.xlsx') && <a href={download('synthesis.xlsx')} download>合成表 Excel</a>}{artifact('synthesis.fasta') && <a href={download('synthesis.fasta')} download>批量 DNA FASTA</a>}{artifact('records.zip') && <a href={download('records.zip')} download>完整记录包</a>}</div>
    <div role="tablist" aria-label="科研结果检视" className="wb-result-tabs">{TABS.map((item, itemIndex) => <button role="tab" id={`${tabId}-tab-${itemIndex}`} aria-controls={`${tabId}-panel-${itemIndex}`} tabIndex={tab === item ? 0 : -1} key={item} aria-selected={tab === item} onClick={() => setTab(item)} onKeyDown={(event) => {
      let next = itemIndex;
      if (event.key === 'ArrowRight') next = (itemIndex + 1) % TABS.length;
      else if (event.key === 'ArrowLeft') next = (itemIndex - 1 + TABS.length) % TABS.length;
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = TABS.length - 1;
      else return;
      event.preventDefault(); setTab(TABS[next]); document.getElementById(`${tabId}-tab-${next}`)?.focus();
    }}>{item}</button>)}</div>
    {TABS.filter((item) => item !== tab).map((item) => <div hidden role="tabpanel" id={`${tabId}-panel-${TABS.indexOf(item)}`} aria-labelledby={`${tabId}-tab-${TABS.indexOf(item)}`} key={item} />)}
    <div role="tabpanel" id={`${tabId}-panel-${TABS.indexOf(tab)}`} aria-labelledby={`${tabId}-tab-${TABS.indexOf(tab)}`} tabIndex={0}>
    <div className="wb-result-table-scroll" role="region" aria-label="序列结果表" tabIndex={0}><table><thead><tr><th>合成名</th><th>长度</th><th>GC</th><th>实际状态</th></tr></thead><tbody>{result.records.map((item, itemIndex) => <tr key={itemIndex} className={record === item ? 'selected' : ''}><td><button onClick={() => { setRecordIndex(itemIndex); setNotice(''); }} aria-label={`检视序列 ${item.name}`}>{item.name}</button></td><td>{item.dna ? `${item.dna.length} bp` : '无结果'}</td><td>{item.dna ? `${((item.dna.match(/[GC]/g) || []).length / item.dna.length * 100).toFixed(1)}%` : '—'}</td><td>{item.status === 'completed' ? '通过' : '失败'}</td></tr>)}</tbody></table></div>
    {record && <section className="wb-selected-result" aria-label="选中序列详情"><h4>{record.name}</h4>{record.error && <p role="alert" className="wb-result-error">{record.error}</p>}{record.dna ? <div className="wb-result-record-actions"><button onClick={copy}>复制完整 DNA</button>{artifact(`sequence-${String(index + 1).padStart(3, '0')}.fasta`) && <a href={download(`sequence-${String(index + 1).padStart(3, '0')}.fasta`)} download>单条 FASTA</a>}</div> : <p>没有通过校验的 DNA，不会列入合成导出。</p>}{notice && <p role="status">{notice}</p>}
      {tab !== '校验与来源' && record.dna && <><pre aria-label="完整 DNA 序列" className="wb-result-dna">{record.dna}</pre>{tab === 'DNA 与密码子' && <div className="wb-result-codons" aria-label="密码子对照">{Array.from({ length: record.dna.length / 3 }, (_, codonIndex) => <span key={codonIndex}><small>{codonIndex + 1}</small><b>{record.protein[codonIndex]}</b><code>{record.dna!.slice(codonIndex * 3, codonIndex * 3 + 3)}</code></span>)}</div>}</>}
      {tab === '校验与来源' && <><dl><dt>实际使用蛋白</dt><dd><code>{record.protein}</code></dd><dt>原始蛋白</dt><dd><code>{record.original_protein}</code></dd><dt>终止符策略</dt><dd>{record.parameters.stopPolicy === 'add' ? '明确补充末尾 *' : '保留输入，不自动添加'}；{terminalStopPresent ? '存在末尾终止符' : '未带末尾终止符'}</dd><dt>正反向避免位点</dt><dd>{record.parameters.avoid || '未指定'}</dd><dt>固定输入完整性</dt><dd><code>{record.source_sha256}</code></dd><dt>引擎映射指纹</dt><dd><code>{result.engine_info.mapping_sha256}</code></dd><dt>代码指纹</dt><dd><code>{result.engine_info.code_sha256}</code></dd><dt>执行身份</dt><dd><code>{task.id} / {attempt.id} / {attempt.toolTaskId} / {attempt.callId}</code></dd></dl>{record.checks && <ul aria-label="独立校验结果">{Object.entries(record.checks).map(([name, valid]) => <li key={name}>{({ characters: 'DNA 字符', length: '长度', translation: '翻译一致性', stop_policy: '终止符策略', avoid_both_strands: '正反向避免位点' } as Record<string, string>)[name] || name}：{valid ? '通过' : '未通过'}</li>)}</ul>}<details><summary>原始工具响应</summary><pre>{record.raw_response ? JSON.stringify(record.raw_response, null, 2) : record.status === 'completed' ? '此历史记录未保存原始响应字段；保留已有结果与来源，不会重跑补齐。' : '未生成成功响应；错误已保留。'}</pre></details></>}
    </section>}
    </div>
    <p className="wb-result-help">仅导出通过校验的条目，失败项仍保留在完整记录包。编码校验不代表表达效果已验证。</p>
  </div>;
}
