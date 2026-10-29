import { CircleAlert } from 'lucide-react';
import type { JobSummary } from './lib';

export default function DeleteConfirmation({ jobs, busy, onCancel, onConfirm }: { jobs: JobSummary[]; busy: boolean; onCancel: () => void; onConfirm: () => void }) {
  return <>
    <div className="delete-dialog-title"><CircleAlert size={20} /><h3>删除{jobs.length === 1 ? `“${jobs[0].name}”` : `${jobs.length} 个历史任务`}？</h3></div>
    <p className="modal-description">将删除所选任务在本机保存的输入序列、参数、优化结果和尝试记录，删除后无法在应用内恢复。</p>
    {jobs.length > 1 && <div className="delete-task-list">{jobs.slice(0, 4).map(job => <span key={job.id}>{job.name}</span>)}{jobs.length > 4 && <span>另有 {jobs.length - 4} 个任务</span>}</div>}
    <div className="delete-scope"><span>共 {jobs.length} 个任务，{jobs.reduce((sum, job) => sum + job.total, 0)} 条序列</span><p>已导出的文件和参数预设不会删除；远端已有记录不受本地删除影响。</p></div>
    <div className="delete-dialog-actions"><button className="button outline" disabled={busy} onClick={onCancel}>取消</button><button className="button danger" disabled={busy} onClick={onConfirm}>{busy ? '正在删除…' : `删除${jobs.length > 1 ? ` ${jobs.length} 个任务` : '任务'}`}</button></div>
  </>;
}
