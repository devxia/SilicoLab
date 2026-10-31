import { useState } from 'react';
import type { ResearchTask, ToolExecution } from './conversation';

export function AnalysisEvidence({ projectId, task, execution }: { projectId: string; task: ResearchTask; execution: ToolExecution }) {
  const [script, setScript] = useState('');
  const [error, setError] = useState('');
  const result = execution.result;
  return <section className="wb-science-summary" aria-label="受限分析实际证据"><strong>{execution.status === 'completed' ? '分析产物已独立核验' : '分析未确认完成，请核对实际错误'}</strong><p>脚本 SHA-256：{result?.script_sha256 || execution.artifacts?.find(a => a.name === 'analysis.py')?.sha256}</p><p>固定输入：{result?.inputVersionId}；独立运行时：{result?.environment?.python || '尚未运行'}</p>{result?.summary && <p>实际数值：count {result.summary.count} / sum {result.summary.sum} / mean {result.summary.mean}</p>}{result?.environment && <details><summary>依赖与环境</summary><pre>{JSON.stringify(result.environment,null,2)}</pre></details>}<button className="button outline small" onClick={async () => { try { const r=await fetch(`/api/workbench/projects/${projectId}/tasks/${task.id}/artifacts/${execution.id}/analysis.py`); if(!r.ok) throw new Error(); setScript(await r.text()); } catch { setError('脚本内容或完整性不可读取'); } }}>检视实际脚本</button>{script && <pre aria-label="实际分析脚本">{script}</pre>}{error && <p role="alert">{error}</p>}<small>计算完成来自实际文件与输入独立核验，不等于模型解释或表达实验结论。</small></section>;
}
export default function AnalysisResults({ projectId, tasks }: { projectId: string; tasks: ResearchTask[] }) {
  const entries=tasks.flatMap(task => task.toolExecutions.filter(e => e.tool==='python_analysis').map(execution=>({task,execution})));
  return <>{entries.map(({task,execution})=><AnalysisEvidence key={execution.id} projectId={projectId} task={task} execution={execution}/>)}</>;
}
