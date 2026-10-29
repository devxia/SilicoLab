import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Activity, ArrowDownToLine, ArrowRight, BookOpen, Check, CheckCheck, CheckCircle2, ChevronDown, ChevronRight, CircleAlert, Clock3, Copy, Cpu, Cloud, Dna, FileCode2, FileSpreadsheet, FileText, History, Info, Layers3, LoaderCircle, Plus, RotateCcw, Settings2, ShieldCheck, SlidersHorizontal, Square, Trash2, Upload, X, FolderOpen } from 'lucide-react';
import TableImport from '../features/codon/TableImport';
import HistoryPanel from '../features/codon/HistoryPanel';
import DeleteConfirmation from '../features/codon/DeleteConfirmation';
import { nativeAPI } from '../platform/native';
import { addTerminalStops, type TableFile } from '../features/codon/table';
import { ACTIVE, DEFAULT_SPECIES, DEMO, ENGINE_LABELS, ENZYMES, SPECIES, STATUS, api, countAA, formatDate, normalizeMotifs, parseInput, sequenceOffset, ApiError, type Engine, type Job, type JobSummary, type Preset, type SeqRecord } from '../features/codon/lib';

type Page = 'workspace' | 'history' | 'presets';
type Modal = 'preset' | 'settings' | 'help' | 'table' | 'stop' | 'delete' | null;
const draftKey = 'silicolab-draft';
function initialDraft() { try { return JSON.parse(localStorage.getItem(draftKey) || '{}'); } catch { return {}; } }
const initial = initialDraft();

function IconButton({ children, label, onClick, disabled = false }: { children: ReactNode; label: string; onClick?: () => void; disabled?: boolean }) {
  return <button type="button" className="icon-button" title={label} aria-label={label} onClick={onClick} disabled={disabled}>{children}</button>;
}
function StatusBadge({ status }: { status: string }) {
  const busy = ['running', 'validating', 'stopping'].includes(status);
  return <span className={`status-badge status-${status}`}>{busy ? <LoaderCircle size={12} className="spin" /> : status === 'completed' ? <Check size={12} /> : ['failed', 'warning', 'paused'].includes(status) ? <CircleAlert size={12} /> : <span className="status-dot" />}{STATUS[status] || status}</span>;
}
function Empty({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return <div className="empty-state"><div className="empty-icon">{icon}</div><h3>{title}</h3><p>{children}</p></div>;
}
function ModalFrame({ title, children, onClose, wide = false }: { title: string; children: ReactNode; onClose: () => void; wide?: boolean }) {
  const root = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    root.current?.querySelector<HTMLElement>('button, input, select, textarea, a')?.focus();
    function key(event: KeyboardEvent) {
      if (event.key === 'Escape') onCloseRef.current();
      if (event.key === 'Tab') {
        const nodes = Array.from(root.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select, textarea, a[href]') || []);
        const first = nodes[0], last = nodes[nodes.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    }
    document.addEventListener('keydown', key);
    return () => { document.removeEventListener('keydown', key); previous?.focus(); };
  }, []);
  return <div className="modal-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}><div className={`modal ${wide ? 'modal-wide' : ''}`} role="dialog" aria-modal="true" aria-label={title} ref={root}><div className="panel-heading"><h2>{title}</h2><IconButton label="关闭弹窗" onClick={onClose}><X size={18} /></IconButton></div>{children}</div></div>;
}

export default function App() {
  const [page, setPage] = useState<Page>('workspace');
  const [nativeReady, setNativeReady] = useState(false);
  const [name, setName] = useState<string>(initial.name || '');
  const [text, setText] = useState<string>(initial.text || '');
  const [engine, setEngine] = useState<Engine>(initial.engine === 'local' ? 'local' : 'remote');
  const [species, setSpecies] = useState<string>(initial.engine === 'local' ? DEFAULT_SPECIES : initial.species || DEFAULT_SPECIES);
  const [motifs, setMotifs] = useState<string[]>(initial.motifs || []);
  const [customMotif, setCustomMotif] = useState('');
  const [speciesItems, setSpeciesItems] = useState(Object.keys(SPECIES));
  const [service, setService] = useState<boolean | null>(null);
  const [connected, setConnected] = useState(true);
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [activeId, setActiveId] = useState<string | null>(() => { try { return sessionStorage.getItem('silicolab-active-job'); } catch { return null; } });
  const [recordId, setRecordId] = useState<string | null>(null);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [modal, setModal] = useState<Modal>(null);
  const [deleteCandidates, setDeleteCandidates] = useState<JobSummary[]>([]);
  const [deleting, setDeleting] = useState(false);
  const [presetName, setPresetName] = useState('');
  const [tab, setTab] = useState<'dna' | 'codons' | 'checks'>('dna');
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [inputMode, setInputMode] = useState<'paste' | 'file' | 'table'>('paste');
  const [tableFile, setTableFile] = useState<TableFile | null>(null);
  const [readingTable, setReadingTable] = useState(false);
  const [filename, setFilename] = useState('');
  const [search, setSearch] = useState('');
  const [historyFilter, setHistoryFilter] = useState('all');
  const [toast, setToast] = useState<{ message: string; error: boolean } | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const fileRef = useRef<HTMLInputElement>(null);
  const tableRef = useRef<HTMLInputElement>(null);
  const editorRef = useRef<HTMLTextAreaElement>(null);
  const jobRef = useRef(activeId);
  const refreshBusy = useRef(false);
  const refreshPending = useRef(false);
  jobRef.current = activeId;
  const parsed = useMemo(() => parseInput(text, name || 'Protein 1'), [text, name]);
  const selected = job?.records.find(record => record.id === recordId) || job?.records[0] || null;
  const missingStops = parsed.records.filter(record => !record.sequence.endsWith('*'));
  const canAddStops = missingStops.every(record => record.sequence.length < 10000);
  const totalAA = parsed.records.reduce((sum, record) => sum + countAA(record.sequence), 0);
  const completed = job?.records.filter(record => record.status === 'completed').length || 0;
  const done = job?.records.filter(record => ['completed', 'warning', 'failed', 'stopped', 'interrupted'].includes(record.status)).length || 0;
  const active = job ? ACTIVE.includes(job.status) : false;
  const notify = useCallback((message: string, error = false) => { clearTimeout(toastTimer.current); setToast({ message, error }); toastTimer.current = setTimeout(() => setToast(null), 4200); }, []);

  useEffect(() => {
    const restore = async () => {
      const bridge = nativeAPI(); if (!bridge) return;
      try {
        const { draft } = await bridge.bootstrap();
        if (draft) { setName(draft.name || ''); setText(draft.text || ''); setEngine(draft.engine === 'local' ? 'local' : 'remote'); setSpecies(draft.engine === 'local' ? DEFAULT_SPECIES : draft.species || DEFAULT_SPECIES); setMotifs(Array.isArray(draft.motifs) ? draft.motifs : []); }
        setNativeReady(true);
      } catch { notify('无法恢复上次草稿，请检查应用数据目录', true); }
    };
    void restore(); window.addEventListener('pywebviewready', restore);
    return () => window.removeEventListener('pywebviewready', restore);
  }, [notify]);
  useEffect(() => {
    const draft = { name, text, species, motifs, engine };
    try { localStorage.setItem(draftKey, JSON.stringify(draft)); } catch { /* Draft remains in memory if browser storage is full. */ }
    if (nativeReady) void nativeAPI()?.save_draft(draft).catch(() => {});
  }, [name, text, species, motifs, engine, nativeReady]);
  useEffect(() => () => clearTimeout(toastTimer.current), []);
  useEffect(() => { try { if (activeId) sessionStorage.setItem('silicolab-active-job', activeId); else sessionStorage.removeItem('silicolab-active-job'); } catch { /* Selection stays in memory. */ } }, [activeId]);
  useEffect(() => {
    function shortcut(event: KeyboardEvent) { if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'n') { event.preventDefault(); setPage('workspace'); setActiveId(null); jobRef.current = null; setJob(null); setRecordId(null); window.scrollTo({ top: 0 }); } }
    window.addEventListener('keydown', shortcut); return () => window.removeEventListener('keydown', shortcut);
  }, []);
  const clearOpenedJob = useCallback((expectedId: string) => {
    if (jobRef.current !== expectedId) return;
    jobRef.current = null; setActiveId(null); setJob(null); setRecordId(null);
    try { sessionStorage.removeItem('silicolab-active-job'); } catch { /* Selection stays in memory. */ }
  }, []);
  const refresh = useCallback(async () => {
    if (refreshBusy.current) { refreshPending.current = true; return; }
    refreshBusy.current = true;
    try {
      do {
        refreshPending.current = false;
        const requestedId = jobRef.current;
        let missing = false;
        const [list, detail] = await Promise.all([
          api<JobSummary[]>('/jobs'),
          requestedId ? api<Job>(`/jobs/${requestedId}?compact=true`).catch(error => {
            if (error instanceof ApiError && error.status === 404) { missing = true; return null; }
            throw error;
          }) : Promise.resolve(null),
        ]);
        setJobs(list); setConnected(true);
        if (missing && requestedId) clearOpenedJob(requestedId);
        else if (detail && detail.id === jobRef.current) setJob(detail);
      } while (refreshPending.current);
    } catch { setConnected(false); }
    finally { refreshBusy.current = false; }
  }, [clearOpenedJob]);
  const refreshSpecies = useCallback(async (force = false) => {
    setRefreshing(true);
    try { const data = await api<{ items: string[]; online: boolean }>('/species' + (force ? '?refresh=true' : '?cached=true')); setSpeciesItems(data.items); setService(data.online); }
    catch { setService(false); }
    finally { setRefreshing(false); }
  }, []);
  useEffect(() => {
    void refresh(); void refreshSpecies();
    api<Preset[]>('/presets').then(setPresets).catch(() => {});
    const events = new EventSource('/api/events');
    events.addEventListener('change', () => { void refresh(); });
    events.onopen = () => { setConnected(true); };
    events.onerror = () => setConnected(false);
    return () => events.close();
  }, [refresh, refreshSpecies]);

  function selectEngine(value: Engine) {
    setEngine(value);
    if (value === 'local' && species !== DEFAULT_SPECIES) { setSpecies(DEFAULT_SPECIES); notify('本地实验仅支持 D2P，已切换为默认体系'); }
  }
  function showHistory() { setModal(null); setDeleteCandidates([]); setPage('history'); }
  async function openJob(id: string) {
    jobRef.current = id; setActiveId(id); setRecordId(null); setTab('dna');
    try { const detail = await api<Job>(`/jobs/${id}?compact=true`); if (jobRef.current === id) { setJob(detail); setPage('workspace'); } }
    catch (error) {
      if (error instanceof ApiError && error.status === 404) { clearOpenedJob(id); notify('该任务已被删除', true); await refresh(); }
      else notify((error as Error).message, true);
    }
  }
  function newTask() { setPage('workspace'); setActiveId(null); jobRef.current = null; setJob(null); setRecordId(null); }
  async function submit(stopPolicy?: 'preserve' | 'add') {
    if (!parsed.records.length || parsed.issues.length || busy) return;
    if (missingStops.length && !stopPolicy) { setModal('stop'); return; }
    setModal(null);
    setBusy(true);
    try {
      const created = await api<Job>('/jobs', { method: 'POST', body: JSON.stringify({ name: name.trim() || `优化任务 ${new Date().toLocaleDateString('zh-CN')}`, engine, species, avoid: motifs.join(','), stop_policy: stopPolicy || 'preserve', records: parsed.records }) });
      jobRef.current = created.id; setActiveId(created.id); setJob(created); setRecordId(created.records[0].id); setTab('dna');
      await refresh(); notify(`已加入队列，共 ${created.records.length} 条序列`);
      setTimeout(() => document.getElementById('task-results')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 100);
    } catch (error) { notify((error as Error).message, true); }
    finally { setBusy(false); }
  }
  async function jobAction(action: 'stop' | 'retry') {
    if (!job || busy) return;
    setBusy(true);
    try { const updated = await api<Job>(`/jobs/${job.id}/${action}`, { method: 'POST' }); setJob(updated); await refresh(); notify(action === 'stop' ? '已停止后续处理，当前序列完成后保存' : '未完成的序列已重新加入队列'); }
    catch (error) { notify((error as Error).message, true); }
    finally { setBusy(false); }
  }
  async function importFile(file: File) {
    if (/\.(xlsx|xls|csv|tsv)$/i.test(file.name)) { await importTable(file); return; }
    if (file.size > 5 * 1024 * 1024) { notify('文件超过 5 MB，请分批导入', true); return; }
    try { const content = await file.text(); setText(content); setFilename(file.name); setInputMode('file'); if (!name) setName(file.name.replace(/\.[^.]+$/, '')); notify(`已导入 ${file.name}`); }
    catch { notify('无法读取文件，请重新选择', true); }
  }
  async function importTable(file: File) {
    if (file.size > 5 * 1024 * 1024) { notify('文件超过 5 MB，请分批导入', true); return; }
    setReadingTable(true);
    try {
      const response = await fetch(`/api/import/table?filename=${encodeURIComponent(file.name)}`, { method: 'POST', body: file, headers: { 'Content-Type': 'application/octet-stream' } });
      if (!response.ok) { const error = await response.json(); throw new Error(error.detail || '表格读取失败'); }
      setTableFile(await response.json()); setModal('table');
    } catch (error) { notify((error as Error).message, true); }
    finally { setReadingTable(false); }
  }
  function confirmTableImport(records: { name: string; sequence: string }[]) {
    setText(records.map(record => `>${record.name}\n${record.sequence}`).join('\n\n'));
    setFilename(tableFile?.filename || ''); setInputMode('table');
    if (!name && tableFile) setName(tableFile.filename.replace(/\.[^.]+$/, ''));
    setModal(null); notify(`已导入 ${records.length} 条蛋白序列，请核对终止符与参数`);
  }
  function fillStops() {
    if (parsed.issues.length || !canAddStops) return;
    setText(addTerminalStops(parsed.records).map(record => `>${record.name}\n${record.sequence}`).join('\n\n'));
    notify(`已为 ${missingStops.length} 条序列补充末尾 *`);
  }
  function addCustomMotifs() { try { setMotifs(current => [...new Set([...current, ...normalizeMotifs(customMotif)])]); setCustomMotif(''); } catch (error) { notify((error as Error).message, true); } }
  function toggleMotif(motif: string) { setMotifs(current => current.includes(motif) ? current.filter(item => item !== motif) : [...current, motif]); }
  async function savePreset() {
    if (!presetName.trim() || busy) return;
    setBusy(true);
    try { const saved = await api<Preset>('/presets', { method: 'POST', body: JSON.stringify({ name: presetName, engine, species, avoid: motifs.join(',') }) }); setPresets(current => [saved, ...current]); setModal(null); setPresetName(''); notify('参数预设已保存'); }
    catch (error) { notify((error as Error).message, true); }
    finally { setBusy(false); }
  }
  async function deletePreset(id: string) { try { await api(`/presets/${id}`, { method: 'DELETE' }); setPresets(current => current.filter(item => item.id !== id)); notify('已移除预设'); } catch (error) { notify((error as Error).message, true); } }
  function usePreset(preset: Preset) { setEngine(preset.engine || 'remote'); setSpecies(preset.species); setMotifs(preset.avoid.split(',').filter(Boolean)); newTask(); notify(`已应用「${preset.name}」`); }
  function duplicateJob() { if (!job) return; setName(`${job.name} 副本`); setText(job.records.map(record => `>${record.name}\n${record.sequence}`).join('\n\n')); setEngine(job.engine || 'remote'); setSpecies(job.species); setMotifs(job.avoid.split(',').filter(Boolean)); newTask(); window.scrollTo({ top: 0, behavior: 'smooth' }); notify('已复制序列和参数，可编辑后重新提交'); }
  async function copyDNA() { if (!selected?.dna) return; try { const bridge = nativeAPI(); if (bridge) await bridge.copy_text(selected.dna); else await navigator.clipboard.writeText(selected.dna); notify('DNA 序列已复制'); } catch { notify('复制失败，请使用导出 FASTA', true); } }
  async function download(format: 'fasta' | 'zip' | 'xlsx', single = false) {
    if (!job) return;
    try {
      const bridge = nativeAPI();
      const safeName = (single && selected ? selected.name : job.name).replace(/[<>:"/\\|?*\x00-\x1f]/g, '_');
      const filename = `${safeName}${format === 'xlsx' ? '-基因合成.xlsx' : format === 'zip' ? '.zip' : '.dna.fasta'}`;
      if (bridge) {
        const result = await bridge.save_export({ job_id: job.id, format, record_id: single && selected ? selected.id : null, filename });
        if (result.saved) notify(`已保存到下载目录（SilicoLab 文件夹）`);
        return;
      }
      const response = await fetch(`/api/jobs/${job.id}/export?format=${format}${single && selected ? `&record_id=${selected.id}` : ''}`);
      if (!response.ok) { const error = await response.json(); throw new Error(error.detail || '导出失败'); }
      const url = URL.createObjectURL(await response.blob()); const link = document.createElement('a'); link.href = url;
      link.download = filename; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); notify(format === 'xlsx' ? '基因合成 Excel 已导出' : format === 'zip' ? '完整记录包已导出' : 'DNA FASTA 已导出');
    } catch (error) { notify((error as Error).message, true); }
  }
  function confirmDelete(items: JobSummary[]) { if (!items.length || !items.every(item => !ACTIVE.includes(item.status))) return; setDeleteCandidates(items); setModal('delete'); }
  async function executeDelete() {
    if (!deleteCandidates.length || deleting) return;
    const ids = deleteCandidates.map(item => item.id);
    const latest = new Map(jobs.map(item => [item.id, item.status]));
    if (ids.some(id => latest.get(id) === undefined)) { notify('部分任务已不存在，请刷新列表后重试', true); await refresh(); setModal(null); return; }
    if (ids.some(id => ACTIVE.includes(latest.get(id) || 'running'))) { notify('请先停止运行中的任务并等待结束；本次未删除任何任务', true); await refresh(); setModal(null); return; }
    setDeleting(true);
    try {
      const result = ids.length === 1
        ? await api<{ deleted_ids: string[]; deleted_count: number }>(`/jobs/${ids[0]}`, { method: 'DELETE' })
        : await api<{ deleted_ids: string[]; deleted_count: number }>('/jobs/bulk-delete', { method: 'POST', body: JSON.stringify({ ids }) });
      if (jobRef.current && result.deleted_ids.includes(jobRef.current)) clearOpenedJob(jobRef.current);
      setJobs(current => current.filter(item => !result.deleted_ids.includes(item.id)));
      setModal(null); setDeleteCandidates([]); await refresh(); notify(`已删除 ${result.deleted_count} 个任务`);
    } catch (error) {
      setModal(null); setDeleteCandidates([]); await refresh(); notify((error as Error).message, true);
    } finally { setDeleting(false); }
  }
  const visibleJobs = jobs.filter(item => {
    const matchesSearch = !search || item.name.toLowerCase().includes(search.toLowerCase());
    const matchesStatus = historyFilter === 'all' || (historyFilter === 'active' ? ACTIVE.includes(item.status) : historyFilter === 'completed' ? item.status === 'completed' : ['partial', 'failed', 'paused', 'stopped', 'interrupted'].includes(item.status));
    return matchesSearch && matchesStatus;
  });

  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="#" onClick={event => { event.preventDefault(); newTask(); }}><span className="brand-icon"><Dna size={24} strokeWidth={1.8} /></span><span>Silico<span className="brand-light">Lab</span></span></a>
      <div className="sidebar-section-label">工作空间</div>
      <nav className="main-nav" aria-label="主导航">
        <button aria-label="新建优化" title="新建优化" className={page === 'workspace' ? 'nav-item selected' : 'nav-item'} onClick={newTask}><Plus size={18} /><span>新建优化</span>{page === 'workspace' && <span className="nav-key">⌘ N</span>}</button>
        <button aria-label="历史记录" title="历史记录" className={page === 'history' ? 'nav-item selected' : 'nav-item'} onClick={() => showHistory()}><History size={18} /><span>历史记录</span><span className="nav-count">{jobs.length}</span></button>
        <button aria-label="参数预设" title="参数预设" className={page === 'presets' ? 'nav-item selected' : 'nav-item'} onClick={() => setPage('presets')}><SlidersHorizontal size={18} /><span>参数预设</span></button>
      </nav>
      <div className="sidebar-recent"><div className="sidebar-section-label">最近任务 <span>{jobs.length > 0 ? jobs.length : ''}</span></div>{jobs.length ? jobs.slice(0, 4).map(item => <button key={item.id} className={`recent-item ${activeId === item.id && page === 'workspace' ? 'current' : ''}`} onClick={() => void openJob(item.id)}><span className={`recent-dot ${item.status === 'completed' ? 'green' : ACTIVE.includes(item.status) ? 'pulse' : ''}`} /><span>{item.name}</span><ChevronRight size={13} /></button>) : <p className="recent-empty">你的优化任务会保存在这里</p>}</div>
      <div className="sidebar-bottom"><div className="local-card"><span className="local-card-icon"><ShieldCheck size={19} /></span><strong>本地工作空间</strong><p>任务与结果保存在这台电脑</p><span className="local-card-line"><span /> SQLite 存储已就绪</span></div><button className="nav-item" aria-label="使用指南" title="使用指南" onClick={() => setModal('help')}><BookOpen size={17} /><span>使用指南</span><ArrowRight size={14} /></button><div className="sidebar-footer"><span className="avatar">S</span><div><strong>SilicoLab</strong><small>个人实验工作台</small></div><span className="version">v0.1.3</span></div></div>
    </aside>

    <div className="main-shell">
      <header className="topbar"><div className="breadcrumb">工作空间 <ChevronRight size={13} /><span>{page === 'history' ? '历史记录' : page === 'presets' ? '参数预设' : '密码子优化'}</span></div><div className="topbar-actions"><span className={`connection ${!connected ? 'offline' : engine === 'local' || service === true ? 'online' : ''}`}><span />{!connected ? '本地服务连接中' : engine === 'local' ? '本地计算已就绪' : refreshing ? '正在检查服务' : service === true ? '远端服务可用' : service === false ? '远端服务待检查' : '远端服务未检测'}</span><span className="topbar-divider" /><IconButton label="工作台设置" onClick={() => setModal('settings')}><Settings2 size={18} /></IconButton></div></header>
      <main className="main-content">
        <div className="page-heading"><div><div className="heading-context"><span className="tiny-dna"><Dna size={13} /></span>{page === 'workspace' ? '从氨基酸，到表达设计' : page === 'history' ? '每一次优化，都有迹可循' : '把常用设置留给下一次'}</div><h1>{page === 'history' ? '历史记录' : page === 'presets' ? '参数预设' : '密码子优化'}</h1><p>{page === 'workspace' ? '专注序列本身，让重复的工作交给工作台。' : page === 'history' ? '查看已保存的任务、校验结果与原始记录。' : '保存目标宿主与避免位点，一次设置，随时复用。'}</p></div>{page === 'workspace' ? <button className="button outline small" onClick={() => { setText(DEMO); if (!name) setName('示例蛋白优化'); setInputMode('paste'); notify('已载入两条接口测试序列，点击开始优化即可运行'); }}><FileCode2 size={15} />载入示例</button> : <button className="button primary small" onClick={page === 'history' ? newTask : () => { setPresetName(''); setModal('preset'); }}><Plus size={15} />{page === 'history' ? '新建优化' : '保存当前参数'}</button>}</div>

        {page === 'workspace' && <>
          <div className="workspace-grid">
            <section className="panel input-panel">
              <div className="panel-heading"><div className="title-with-icon"><span className="section-icon"><FileText size={18} /></span><h2>输入蛋白序列</h2></div><span className="subtle-badge">氨基酸 → DNA</span></div>
              <div className="input-tabs" role="tablist" aria-label="输入方式"><button role="tab" aria-selected={inputMode === 'paste'} className={inputMode === 'paste' ? 'active' : ''} onClick={() => setInputMode('paste')}><FileCode2 size={14} />粘贴序列</button><button role="tab" aria-selected={inputMode === 'file'} className={inputMode === 'file' ? 'active' : ''} onClick={() => setInputMode('file')}><Upload size={14} />导入 FASTA</button><button role="tab" aria-selected={inputMode === 'table'} className={inputMode === 'table' ? 'active' : ''} onClick={() => setInputMode('table')}><FileSpreadsheet size={14} />导入表格</button><span>支持单条或多条序列</span></div>
              <label className="field-label" htmlFor="task-name">任务名称 <span>可选</span></label><input id="task-name" className="field task-name" placeholder="例如：EGFP 表达优化" value={name} maxLength={200} onChange={event => setName(event.target.value)} />
              {inputMode === 'file' && <button className={`file-drop ${dragging ? 'dragging' : ''}`} onClick={() => fileRef.current?.click()} onDragOver={event => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={event => { event.preventDefault(); setDragging(false); if (event.dataTransfer.files[0]) void importFile(event.dataTransfer.files[0]); }}><span className="upload-round"><Upload size={20} /></span><span><strong>{filename || '拖入 FASTA 文件，或点击选择'}</strong><small>.fa、.fasta、.faa、.txt，最大 5 MB</small></span><Plus size={17} /></button>}
              {inputMode === 'table' && <button className={`file-drop ${dragging ? 'dragging' : ''}`} disabled={readingTable} onClick={() => tableRef.current?.click()} onDragOver={event => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={event => { event.preventDefault(); setDragging(false); if (event.dataTransfer.files[0]) void importTable(event.dataTransfer.files[0]); }}><span className="upload-round">{readingTable ? <LoaderCircle size={20} className="spin" /> : <FileSpreadsheet size={20} />}</span><span><strong>{readingTable ? '正在读取表格…' : filename && /\.(xlsx|csv|tsv)$/i.test(filename) ? filename : '选择或拖入表格，预览并选择名称与序列列'}</strong><small>.xlsx、.csv、.tsv · 支持多工作表、有表头或无表头</small></span><Plus size={17} /></button>}
              <div className="editor-label"><label className="field-label" htmlFor="sequence-input">{parsed.records.length > 1 ? '蛋白序列 · FASTA' : '氨基酸序列'}</label>{text && <button className="text-button muted" onClick={() => { setText(''); setFilename(''); }}>清空</button>}</div>
              <div className={`sequence-editor ${parsed.issues.length ? 'has-error' : ''}`} onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); if (event.dataTransfer.files[0]) void importFile(event.dataTransfer.files[0]); }}><div className="editor-gutter" aria-hidden="true">{Array.from({ length: 6 }, (_, index) => <span key={index}>{String(index + 1).padStart(2, '0')}</span>)}</div><textarea id="sequence-input" ref={editorRef} spellCheck={false} aria-describedby="input-validation" placeholder={'>Protein_name\nMKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ\n\n粘贴氨基酸序列，或拖入 FASTA 文件…'} value={text} onChange={event => setText(event.target.value)} /><span className="editor-language">Protein / FASTA</span></div>
              <div id="input-validation" className={`editor-footer ${parsed.issues.length ? 'invalid' : ''}`} aria-live="polite"><span>{parsed.issues.length ? <CircleAlert size={14} /> : parsed.records.length ? <CheckCircle2 size={14} /> : <Info size={14} />}{parsed.issues.length ? `${parsed.issues.length} 处输入需要检查` : parsed.records.length ? `${parsed.records.length} 条序列已通过输入校验` : '支持 20 种标准氨基酸与末尾终止符 *'}</span><span>{totalAA.toLocaleString()} aa</span></div>
              {parsed.issues.length > 0 && <div className="input-issues">{parsed.issues.slice(0, 4).map((issue, index) => <button key={index} onClick={() => { editorRef.current?.focus(); if (issue.position !== undefined) { const recordIndex = Math.max(0, parsed.records.findIndex(record => record.name === issue.name)); const offset = sequenceOffset(text, recordIndex, issue.position); if (offset !== null) editorRef.current?.setSelectionRange(offset, offset + 1); } }}><CircleAlert size={13} /><span><strong>{issue.name}</strong>：{issue.message}</span></button>)}</div>}
              {missingStops.length > 0 && !parsed.issues.length && <div className="stop-reminder"><CircleAlert size={15} /><div><strong>{missingStops.length} 条序列缺少末尾终止符 *</strong><p>需要终止密码子时请补充；融合表达等场景也可保持不添加。</p></div><button className="text-button" disabled={!canAddStops} title={canAddStops ? '仅补充缺少末尾 * 的序列' : '补充后会超过 10,000 字符，请先缩短序列'} onClick={fillStops}>一键补齐</button></div>}
              <div className="input-summary"><div><span className="summary-icon"><Layers3 size={17} /></span><span><small>本次序列</small><strong>{parsed.records.length || '—'} <em>条</em></strong></span></div><div><span className="summary-icon"><Dna size={17} /></span><span><small>氨基酸总长度</small><strong>{totalAA ? totalAA.toLocaleString() : '—'} <em>aa</em></strong></span></div><div><span className="summary-icon"><ShieldCheck size={17} /></span><span><small>输出校验</small><strong className="summary-text">自动验证</strong></span></div></div>
              <input type="file" className="visually-hidden" ref={tableRef} accept=".xlsx,.csv,.tsv" aria-label="选择表格文件" onChange={event => { if (event.target.files?.[0]) void importTable(event.target.files[0]); event.target.value = ''; }} />
              <input type="file" className="visually-hidden" ref={fileRef} accept=".fa,.fasta,.faa,.txt" aria-label="选择 FASTA 文件" onChange={event => { if (event.target.files?.[0]) void importFile(event.target.files[0]); event.target.value = ''; }} />
            </section>

            <section className="panel parameters-panel"><div className="panel-heading"><div className="title-with-icon"><span className="section-icon"><SlidersHorizontal size={18} /></span><h2>优化参数</h2></div><button className="text-button" onClick={() => { setPresetName(''); setModal('preset'); }}>保存预设</button></div>
              <fieldset className="engine-choice"><legend className="field-label">计算方式</legend><div className="engine-options"><label className={engine === 'remote' ? 'selected' : ''}><input type="radio" name="engine" value="remote" checked={engine === 'remote'} onChange={() => selectEngine('remote')} /><Cloud size={15} /><span>ProteinFactory 远端</span></label><label className={engine === 'local' ? 'selected' : ''}><input type="radio" name="engine" value="local" checked={engine === 'local'} onChange={() => selectEngine('local')} /><Cpu size={15} /><span>本地实验</span></label></div></fieldset>
              {engine === 'local' && <div className="engine-notice"><ShieldCheck size={14} /><p>在本机计算，不上传序列。有避免位点时，DNA 可能与远端不同；失败不会自动切换到远端。</p></div>}
              <label className="field-label" htmlFor="species-select">目标宿主</label><div className="select-wrap"><select id="species-select" className="field" value={species} disabled={engine === 'local'} onChange={event => setSpecies(event.target.value)}>{(engine === 'local' ? [DEFAULT_SPECIES] : speciesItems).map(item => <option key={item} value={item}>{SPECIES[item] || item}</option>)}</select><ChevronDown size={15} /></div><p className="field-help">{engine === 'local' ? '本地实验目前仅支持 D2P 默认体系' : species === DEFAULT_SPECIES ? '与 ProteinFactory 网页默认设置一致' : species}</p>
              <div className="parameters-rule" /><div className="field-label">避免酶切位点 <span>{motifs.length ? `已选 ${motifs.length} 个` : '可选'}</span></div><div className="enzyme-options">{ENZYMES.map(enzyme => <button key={enzyme.name} className={`enzyme-chip ${motifs.includes(enzyme.motif) ? 'chosen' : ''}`} title={enzyme.motif} aria-pressed={motifs.includes(enzyme.motif)} onClick={() => toggleMotif(enzyme.motif)}>{motifs.includes(enzyme.motif) && <Check size={11} />}{enzyme.name}</button>)}</div><div className="custom-motif"><input className="field" aria-label="自定义避免位点" placeholder="自定义位点，如 GAATTC" value={customMotif} onChange={event => setCustomMotif(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') addCustomMotifs(); }} /><IconButton label="添加自定义位点" onClick={addCustomMotifs} disabled={!customMotif.trim()}><Plus size={16} /></IconButton></div>{motifs.length > 0 && <div className="motif-values">{motifs.map(motif => <button title="移除此位点" onClick={() => toggleMotif(motif)} key={motif}>{motif}<X size={10} /></button>)}</div>}
              <div className="stop-option"><span className="stop-check"><Check size={12} /></span><div><strong>保留已有末尾终止符 *</strong><span>缺少时会提示添加，不会自动添加起始 M</span></div><span className="subtle-badge">默认</span></div>
              {presets.length > 0 && <div className="preset-selector"><label htmlFor="quick-preset">使用已存预设</label><select id="quick-preset" value="" onChange={event => { const preset = presets.find(item => item.id === event.target.value); if (preset) usePreset(preset); }}><option value="">选择预设…</option>{presets.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></div>}
              <button className="button primary start-button" onClick={() => void submit()} disabled={!parsed.records.length || !!parsed.issues.length || busy || !connected}>{busy ? <LoaderCircle size={15} className="spin" /> : <Dna size={17} />}开始优化{parsed.records.length > 0 && <span className="button-count">{parsed.records.length}</span>}<ArrowRight size={16} /></button><p className="privacy-note"><ShieldCheck size={12} />{engine === 'local' ? '序列只在本机计算与保存' : '序列将发送至 ProteinFactory 进行优化'}</p>
            </section>
          </div>

          <section id="task-results" className="panel results-panel"><div className="panel-heading"><div className="title-with-icon"><span className="section-icon"><Activity size={18} /></span><h2>{job ? job.name : '优化结果'}</h2>{job && <StatusBadge status={job.status} />}</div><div className="result-heading-actions">{job && <IconButton label="复制此任务参数与序列" onClick={duplicateJob}><Copy size={15} /></IconButton>}{job && !active && job.records.some(record => record.status !== 'completed') && <button className="button outline compact" onClick={() => void jobAction('retry')} disabled={busy}><RotateCcw size={13} />重试未完成项</button>}{active && <button className="button outline compact" onClick={() => void jobAction('stop')} disabled={busy || job?.status === 'stopping'}><Square size={11} />停止后续提交</button>}{job && <button className="button outline compact" onClick={() => void download('zip')}><ArrowDownToLine size={14} />记录包</button>}{completed > 0 && <button className="button outline compact" onClick={() => void download('xlsx')}><FileSpreadsheet size={14} />导出 Excel</button>}{job && nativeAPI() && <button className="button outline compact" onClick={() => { void nativeAPI()?.open_export_directory().catch(error => notify(error.message, true)); }}><FolderOpen size={14} />打开导出目录</button>}{completed > 0 && <button className="button primary compact" onClick={() => void download('fasta')}><ArrowDownToLine size={14} />导出全部</button>}</div></div>
            {!job ? <div className="results-empty"><div className="empty-orbit"><Dna size={30} strokeWidth={1.3} /><span /><span /></div><h3>下一段序列，从这里开始</h3><p>输入蛋白序列并开始优化，结果会自动显示在这里。</p><div className="empty-checks"><span><Check size={12} />翻译一致性</span><span><Check size={12} />避免位点</span><span><Check size={12} />DNA 长度</span></div></div> : <>
              <div className="job-engine-summary"><span className={`engine-tag ${job.engine === 'local' ? 'local' : ''}`}>{job.engine === 'local' ? <Cpu size={13} /> : <Cloud size={13} />}{ENGINE_LABELS[job.engine || 'remote']}</span><span>{job.engine === 'local' ? '在本机处理，未上传序列' : '由 ProteinFactory 远端计算'}</span></div>
              <div className="job-progress"><div><span>{active ? '正在处理序列' : '本次优化'}<strong>{done} / {job.records.length}</strong></span><span>{completed} 条通过校验{job.created_at && <small>{formatDate(job.created_at)}</small>}</span></div><div className="progress-track"><span style={{ width: `${done / job.records.length * 100}%` }} /></div></div>
              {job.message && <div className="job-message"><CircleAlert size={16} />{job.message}</div>}
              <div className="results-layout"><div className="sequence-list"><div className="sequence-list-heading">序列列表<span>{job.records.length}</span></div>{job.records.map((record, index) => <button className={`sequence-item ${selected?.id === record.id ? 'selected' : ''}`} key={record.id} onClick={() => setRecordId(record.id)}><span className="sequence-index">{String(index + 1).padStart(2, '0')}</span><span className="sequence-item-content"><strong>{record.name}</strong><span>{countAA(record.sequence).toLocaleString()} aa <StatusBadge status={record.status} /></span></span><ChevronRight size={14} /></button>)}</div><div className="result-detail">{selected && <><div className="detail-title"><div><h3>{selected.name}</h3><span>{SPECIES[job.species] || job.species}{selected.elapsed !== undefined && <span>用时 {selected.elapsed}s</span>}</span></div><div>{selected.status === 'completed' && <><IconButton label="复制 DNA" onClick={() => void copyDNA()}><Copy size={15} /></IconButton><IconButton label="导出当前 DNA FASTA" onClick={() => void download('fasta', true)}><ArrowDownToLine size={16} /></IconButton></>}</div></div>
                {selected.status === 'completed' && selected.dna && selected.checks ? <><div className="result-metrics"><span><strong>{selected.checks.bp.toLocaleString()}</strong> bp</span><span>GC <strong>{selected.checks.gc.toFixed(1)}%</strong></span><span className="verified"><ShieldCheck size={13} />校验通过</span></div><div className="result-tabs" role="tablist" aria-label="结果视图">{([['dna', 'DNA 序列'], ['codons', '密码子对照'], ['checks', '校验详情']] as const).map(([value, label]) => <button key={value} role="tab" aria-selected={tab === value} className={tab === value ? 'active' : ''} onClick={() => setTab(value)}>{label}</button>)}</div>
                  {tab === 'dna' && <DnaView record={selected} />}
                  {tab === 'codons' && <CodonView record={selected} />}
                  {tab === 'checks' && <div className="checks-view"><CheckRow label="翻译一致性" detail="按标准遗传密码表翻译，与输入氨基酸逐位一致" /><CheckRow label="DNA 长度" detail={`${selected.checks.bp} bp，与输入 ${selected.sequence.length} 个字符相匹配`} /><CheckRow label="避免位点" detail={job.avoid ? `已检查正反两条链：${job.avoid.split(',').join('、')}` : '本次未设置避免位点'} /><CheckRow label="终止符" detail={selected.stop_added ? '已按提交时的选择补充末尾终止符 *' : selected.checks.stop ? '已保留输入末尾的终止符' : '输入未带终止符，未额外添加终止密码子'} /><div className="engine-provenance"><div><span>计算引擎</span><strong>{ENGINE_LABELS[job.engine || 'remote']}</strong></div>{job.engine === 'local' ? <><div><span>版本</span><code>{job.engine_info?.version || '—'}</code></div><div><span>密码子表 SHA-256</span><code>{job.engine_info?.mapping_sha256 || '—'}</code></div><p>本地约束修复采用尽量少修改首选密码子的策略，结果可能与远端不同。</p></> : <div><span>服务端记录</span><code>{selected.response?.log_id || '—'}</code></div>}</div></div>}
                  <div className="detail-footer"><span><CheckCheck size={13} />结果已保存到本机</span><button className="text-button" onClick={() => void copyDNA()}>复制 DNA <Copy size={12} /></button></div>
                </> : selected.status === 'running' || selected.status === 'validating' ? <Empty icon={<LoaderCircle size={25} className="spin" />} title={selected.status === 'validating' ? '正在校验返回结果' : '正在优化这条序列'}>计算完成后会自动检查翻译与避免位点，请稍候。</Empty> : selected.status === 'pending' ? <Empty icon={<Clock3 size={25} />} title="等待优化">队列会逐条处理，完成后自动保存结果。</Empty> : <div className="failure-state"><span className="failure-icon"><CircleAlert size={23} /></span><h3>{STATUS[selected.status]}</h3><p>{selected.error || '此序列尚未完成，可重试未完成项。'}</p>{!active && <button className="button outline small" onClick={() => void jobAction('retry')} disabled={busy}><RotateCcw size={14} />重试未完成项</button>}{selected.response && <details><summary>查看服务端响应</summary><pre>{JSON.stringify(selected.response, null, 2)}</pre></details>}</div>}
              </>}</div></div>
            </>}
          </section>
          <div className="workspace-bottom"><span><ShieldCheck size={13} />任务自动保存，无需手动保存</span><span>{engine === 'local' ? '本地 D2P 实验方案' : '由 ProteinFactory 提供优化计算'} <span className="bottom-dot">·</span> 标准遗传密码表校验</span></div>
        </>}

        {page === 'history' && <HistoryPanel jobs={jobs} visibleJobs={visibleJobs} search={search} filter={historyFilter} onSearch={setSearch} onFilter={setHistoryFilter} onOpen={id => void openJob(id)} onDelete={confirmDelete} deleting={deleting} badge={status => <StatusBadge status={status} />} />}

        {page === 'presets' && <><div className="presets-intro"><span className="section-icon"><SlidersHorizontal size={20} /></span><div><strong>让每次实验，从熟悉的设置开始</strong><p>预设包含计算方式、目标宿主和避免位点，不包含序列。</p></div></div><div className="presets-grid">{presets.map(preset => <article className="panel preset-card" key={preset.id}><div className="panel-heading"><span className="section-icon"><SlidersHorizontal size={19} /></span><IconButton label={`删除预设 ${preset.name}`} onClick={() => void deletePreset(preset.id)}><Trash2 size={15} /></IconButton></div><h2>{preset.name}</h2><p>{SPECIES[preset.species] || preset.species} · {ENGINE_LABELS[preset.engine || 'remote']}</p><div className="preset-motifs">{preset.avoid ? preset.avoid.split(',').map(motif => <span key={motif}>{ENZYMES.find(item => item.motif === motif)?.name || motif}</span>) : <span>无避免位点</span>}</div><button className="button primary" onClick={() => usePreset(preset)}>应用到新任务<ArrowRight size={15} /></button></article>)}<button className="preset-add" onClick={() => { setPresetName(''); setModal('preset'); }}><span><Plus size={24} /></span><strong>保存当前参数</strong><p>{SPECIES[species] || species} · {motifs.length} 个避免位点</p></button></div></>}
      </main>
    </div>
    {toast && <div className={`toast ${toast.error ? 'error' : ''}`} role={toast.error ? 'alert' : 'status'}>{toast.error ? <CircleAlert size={16} /> : <CheckCircle2 size={16} />}<span>{toast.message}</span><button aria-label="关闭提示" onClick={() => setToast(null)}><X size={14} /></button></div>}
    {modal === 'table' && tableFile && <ModalFrame title="导入表格 · 选择数据列" wide onClose={() => setModal(null)}><TableImport file={tableFile} onImport={confirmTableImport} onCancel={() => setModal(null)} /></ModalFrame>}
    {modal === 'stop' && <ModalFrame title="是否补充末尾终止符？" onClose={() => setModal(null)}><p className="modal-description">本次 {parsed.records.length} 条序列中，有 {missingStops.length} 条缺少末尾 *。* 表示终止密码子；需要翻译终止时建议添加，融合表达等设计可选择不添加。</p><div className="stop-name-list">{missingStops.slice(0, 6).map((record, index) => <span key={index}>{record.name}</span>)}{missingStops.length > 6 && <span>另有 {missingStops.length - 6} 条</span>}</div>{!canAddStops && <p className="mapping-error">部分序列已达 10,000 字符，补充后会超限，请先缩短序列。</p>}<button className="button primary full-width" disabled={busy || !canAddStops} onClick={() => void submit('add')}>补充末尾 * 并开始优化</button><button className="button outline full-width" disabled={busy} onClick={() => void submit('preserve')}>保持原序列，直接优化</button><button className="text-button stop-cancel" onClick={() => setModal(null)}>返回编辑</button></ModalFrame>}
    {modal === 'delete' && <ModalFrame title="删除历史任务" onClose={() => { if (!deleting) { setModal(null); setDeleteCandidates([]); } }}><DeleteConfirmation jobs={deleteCandidates} busy={deleting} onCancel={() => { setModal(null); setDeleteCandidates([]); }} onConfirm={() => void executeDelete()} /></ModalFrame>}
    {modal === 'preset' && <ModalFrame title="保存参数预设" onClose={() => setModal(null)}><p className="modal-description">为当前的计算方式、宿主与避免位点起一个名字。</p><form onSubmit={event => { event.preventDefault(); void savePreset(); }}><label className="field-label" htmlFor="preset-name">预设名称</label><input className="field" id="preset-name" value={presetName} maxLength={80} placeholder="例如：大肠杆菌 · Golden Gate" onChange={event => setPresetName(event.target.value)} /><div className="preset-preview"><span>计算方式<strong>{ENGINE_LABELS[engine]}</strong></span><span>目标宿主<strong>{SPECIES[species] || species}</strong></span><span>避免位点<strong>{motifs.length ? motifs.join('、') : '未设置'}</strong></span></div><button className="button primary full-width" disabled={!presetName.trim() || busy} type="submit">{busy ? '正在保存…' : '保存预设'}</button><button className="button outline full-width" type="button" onClick={() => setModal(null)}>取消</button></form></ModalFrame>}
    {modal === 'settings' && <ModalFrame title="工作台设置" onClose={() => setModal(null)}><div className="settings-section"><div><strong>ProteinFactory 优化服务</strong><StatusBadge status={service ? 'completed' : 'paused'} /></div><p>检测接口连通性并更新可选宿主，不提交序列。</p><button className="button outline small" onClick={() => void refreshSpecies(true)} disabled={refreshing}><RotateCcw size={14} className={refreshing ? 'spin' : ''} />{refreshing ? '正在检查…' : '重新检查服务'}</button></div><div className="settings-section"><strong>任务与数据</strong><p>任务、参数、原始响应保存在本机 SQLite 数据库。关闭界面不会停止本地服务中的任务；停止程序后，未完成项会标记为中断。</p><div className="settings-values"><span>同时提交请求<strong>1 条</strong></span><span>远端请求间隔<strong>0.5 秒</strong></span><span>远端单次超时<strong>120 秒</strong></span></div></div><div className="notice"><Info size={16} /><p>选择远端时序列会发送至 ProteinFactory；选择本地实验时仅在本机处理。目前本地仅支持 D2P，约束修复不是官方算法，失败不会自动上传远端。</p></div></ModalFrame>}
    {modal === 'help' && <ModalFrame title="使用 SilicoLab" onClose={() => setModal(null)}><div className="help-steps">{[['输入蛋白序列', '粘贴氨基酸或 FASTA，也可导入 Excel/CSV 表格并选择名称与序列列。支持多条序列，最多 200 条。'], ['选择计算方式与参数', '默认使用远端；本地实验仅支持 D2P，在本机处理。可选择常用酶切位点或自定义 DNA 位点。'], ['优化、校验、导出', '工作台按所选引擎逐条处理，独立检查 DNA 翻译和避免位点。通过后可复制 DNA，或导出 FASTA 与基因合成 Excel。']].map(([title, detail], index) => <div key={title}><span>{index + 1}</span><div><strong>{title}</strong><p>{detail}</p></div></div>)}</div><div className="notice"><Info size={16} /><p>输入末尾的 * 会保留为终止密码子；缺少时会提示，可选择批量补充或保持原序列。不会自动补充起始 M。通过校验不代表实际表达效果已被实验验证。</p></div><button className="button primary full-width" onClick={() => setModal(null)}>开始使用</button></ModalFrame>}
  </div>;
}

function CheckRow({ label, detail }: { label: string; detail: string }) { return <div className="check-row"><span><Check size={13} /></span><div><strong>{label}</strong><p>{detail}</p></div><span className="check-word">通过</span></div>; }
function DnaView({ record }: { record: SeqRecord }) {
  const [limit, setLimit] = useState(1200);
  useEffect(() => setLimit(1200), [record.id]);
  const dna = record.dna || '';
  return <div className="dna-view" aria-label="优化后的 DNA 序列">{Array.from({ length: Math.ceil(Math.min(dna.length, limit) / 60) }, (_, index) => <div className="dna-line" key={index}><span className="line-number">{index * 60 + 1}</span><span>{dna.slice(index * 60, Math.min(index * 60 + 60, limit)).match(/.{1,3}/g)?.map((codon, codonIndex) => <span key={codonIndex} className={codonIndex % 2 ? 'codon light' : 'codon'}>{codon}</span>)}</span></div>)}{dna.length > limit && <button className="button outline small" onClick={() => setLimit(current => current + 1200)}>显示更多（剩余 {dna.length - limit} bp；复制与导出包含完整序列）</button>}</div>;
}

function CodonView({ record }: { record: SeqRecord }) {
  const [limit, setLimit] = useState(120);
  useEffect(() => setLimit(120), [record.id]);
  return <div className="codon-view"><p className="codon-hint">上行为氨基酸，下行为对应密码子。按输入顺序逐位对照。</p><div className="codon-alignment">{Array.from({ length: Math.min(record.sequence.length, limit) }, (_, index) => <div key={index} className="alignment-cell"><small>{index + 1}</small><strong>{record.sequence[index]}</strong><span>{record.dna?.slice(index * 3, index * 3 + 3)}</span></div>)}</div>{record.sequence.length > limit && <button className="button outline small" onClick={() => setLimit(current => current + 300)}>显示更多（剩余 {record.sequence.length - limit} 位）</button>}</div>;
}
