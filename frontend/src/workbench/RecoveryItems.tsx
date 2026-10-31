import type { Project } from './client';

export default function RecoveryItems({ project, onSelect }: { project: Project; onSelect: (conversationId: string, taskId: string) => void }) {
  const items=project.tasks.filter(task=>['paused','needs_decision','result_unknown','waiting_external','admission_pending'].includes(task.status));
  if (!items.length) return null;
  return <section className="wb-recovery-items" aria-label="项目待处理与恢复项"><details><summary>{items.length} 项待处理或待选择恢复</summary><p>此列表只附着已保存状态，不发起模型、重做工具或取消外部作业。打开原对话后逐项决定；未知远端效果须先核对。</p><ul>{items.map(task=><li key={task.id}><span>{task.id.slice(0,8)} · {task.status==='paused'?'已暂停':task.status==='needs_decision'?'等待用户决定':task.status==='waiting_external'?'独立作业等待中':task.status==='result_unknown'?'结果未知':'答复已保存，等待继续'}</span><button onClick={()=>onSelect(task.conversationId, task.id)}>查看原任务 {task.id.slice(0,8)}</button></li>)}</ul></details></section>;
}
