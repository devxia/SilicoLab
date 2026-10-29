import { useEffect, useMemo, useState } from 'react';
import { ChevronRight, FileCode2, History, Search, Trash2, X } from 'lucide-react';
import { ENGINE_LABELS, SPECIES, formatDate, type JobSummary } from './lib';
import { canDeleteJob, eligibleSelection, MAX_DELETE_BATCH } from './history';

const filters = [['all', '全部任务'], ['active', '进行中'], ['completed', '已完成'], ['other', '需处理']];

type Props = {
  jobs: JobSummary[];
  visibleJobs: JobSummary[];
  search: string;
  filter: string;
  onSearch: (value: string) => void;
  onFilter: (value: string) => void;
  onOpen: (id: string) => void;
  onDelete: (jobs: JobSummary[]) => void;
  deleting: boolean;
  badge: (status: string) => React.ReactNode;
};

export default function HistoryPanel({ jobs, visibleJobs, search, filter, onSearch, onFilter, onOpen, onDelete, deleting, badge }: Props) {
  const [managing, setManaging] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const eligible = useMemo(() => visibleJobs.filter(canDeleteJob), [visibleJobs]);
  const selected = eligibleSelection(selectedIds, visibleJobs);
  const selectedSet = new Set(selected);
  const allSelected = eligible.length > 0 && eligible.every(job => selectedSet.has(job.id));
  // Filters never keep invisible selections; SSE status changes remove newly active jobs.
  useEffect(() => { setSelectedIds([]); }, [search, filter]);
  useEffect(() => {
    setSelectedIds(current => {
      const next = eligibleSelection(current, visibleJobs);
      return current.length === next.length && current.every((id, i) => id === next[i]) ? current : next;
    });
  }, [visibleJobs]);
  function toggle(id: string) { setSelectedIds(current => current.includes(id) ? current.filter(value => value !== id) : [...current, id]); }
  function manage() { setManaging(value => !value); setSelectedIds([]); }
  return <>
    <div className="history-stats"><div><span>已保存任务</span><strong>{jobs.length}<small> 个</small></strong></div><div><span>已完成序列</span><strong>{jobs.reduce((sum, job) => sum + job.completed, 0)}<small> 条</small></strong></div><div><span>进行中</span><strong>{jobs.filter(job => !canDeleteJob(job)).length}<small> 个任务</small></strong></div></div>
    <section className={`panel history-panel ${managing ? 'is-managing' : ''}`}>
      <div className="history-toolbar"><div className="filter-pills">{filters.map(([value, label]) => <button key={value} className={filter === value ? 'active' : ''} onClick={() => onFilter(value)}>{label}</button>)}</div><div className="history-tools"><div className="search-field"><Search size={15} /><input aria-label="搜索历史任务" placeholder="搜索任务名称" value={search} onChange={event => onSearch(event.target.value)} /></div><button className="button outline compact" onClick={manage} disabled={deleting}>{managing ? <X size={13} /> : <Trash2 size={13} />}{managing ? '取消管理' : '管理记录'}</button></div></div>
      {managing && <div className="history-selection-bar"><label><input type="checkbox" aria-label="全选当前筛选结果中的可删除任务" checked={allSelected} ref={element => { if (element) element.indeterminate = selected.length > 0 && !allSelected; }} disabled={!eligible.length || eligible.length > MAX_DELETE_BATCH || deleting} onChange={() => setSelectedIds(allSelected ? [] : eligible.map(job => job.id))} />全选当前结果</label><span>已选 <strong>{selected.length}</strong> 项</span><button className="button outline compact delete-selected" disabled={!selected.length || deleting} onClick={() => onDelete(visibleJobs.filter(job => selectedSet.has(job.id)))}><Trash2 size={13} />删除已选</button><small>运行中任务不可选 · 每次最多 {MAX_DELETE_BATCH} 项</small></div>}
      {visibleJobs.length ? <div className="history-table"><div className="history-row table-head">{managing && <span className="history-selection-cell" />}<span className="history-name-heading">任务名称</span><span className="history-host">目标宿主</span><span className="history-count">完成序列</span><span className="history-status">状态</span><span className="history-date">创建时间</span><span className="history-actions-label">操作</span></div>{visibleJobs.map(item => {
        const removable = canDeleteJob(item);
        return <div key={item.id} data-job-id={item.id} className={`history-row ${selectedSet.has(item.id) ? 'checked' : ''}`} onClick={() => onOpen(item.id)}>
          {managing && <span className="history-selection-cell" onClick={event => event.stopPropagation()}><input type="checkbox" aria-label={`选择任务 ${item.name}`} checked={selectedSet.has(item.id)} disabled={!removable || deleting || (!selectedSet.has(item.id) && selected.length >= MAX_DELETE_BATCH)} title={removable ? '选择此任务' : '请先停止任务并等待结束'} onChange={() => toggle(item.id)} /></span>}
          <button className="history-name" aria-label={`打开任务 ${item.name}`} onClick={event => { event.stopPropagation(); onOpen(item.id); }}><span className="history-file-icon"><FileCode2 size={17} /></span><span className="history-name-content"><strong>{item.name}</strong><small>{ENGINE_LABELS[item.engine || 'remote']}</small></span></button>
          <span className="history-host">{SPECIES[item.species] || item.species}</span><span className="history-count">{item.completed} / {item.total}</span><span className="history-status">{badge(item.status)}</span><span className="history-date">{formatDate(item.created_at)}</span>
          <span className="history-row-actions" onClick={event => event.stopPropagation()}><button className="icon-button history-open" aria-label={`查看任务 ${item.name}`} title="打开任务" onClick={() => onOpen(item.id)}><ChevronRight size={15} /></button><button className="icon-button history-delete" aria-label={`删除任务 ${item.name}`} title={removable ? '删除任务' : '运行中任务不可删除，请先停止并等待结束'} disabled={!removable || deleting} onClick={() => onDelete([item])}><Trash2 size={15} /></button></span>
        </div>;
      })}</div> : <div className="empty-state"><div className="empty-icon"><History size={27} /></div><h3>{search || filter !== 'all' ? '没有匹配的任务' : '还没有优化任务'}</h3><p>{search || filter !== 'all' ? '试试调整搜索词或状态筛选。' : '新建一次优化后，输入、参数与结果都会保存在这里。'}</p></div>}
    </section>
  </>;
}
