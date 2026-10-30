import { useEffect, useRef, useState } from 'react';
import { Dna, FolderOpen, FolderPlus, MessageSquare, PanelLeft, Plus, Files, ListChecks, FileOutput, X, ArrowUp, ChevronRight, Check, LoaderCircle } from 'lucide-react';
import CodonWorkbench from '../app/App';
import { nativeAPI } from '../platform/native';
import { request, type Conversation, type Project, type ProjectIndex } from './client';
import './workbench.css';
import ProjectFiles from './ProjectFiles';
import { ConversationHistory, TaskCard, useConversation, type ResearchTask } from './conversation';
import './conversation.css';
import LocalScienceForm from './LocalScienceForm';
import './science.css';
import ScientificResults from './ScientificResults';

type WorkspaceTab = '文件' | '任务' | '结果';
export default function Workbench() {
  const [projects, setProjects] = useState<ProjectIndex[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [revision, setRevision] = useState(0);
  const [saved, setSaved] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [tab, setTab] = useState<WorkspaceTab | null>(null);
  const [expanded, setExpanded] = useState(true);
  const beforeAnalysis = useRef(true);
  const [dialog, setDialog] = useState<'create' | 'open' | 'conversation' | null>(null);
  const [path, setPath] = useState('');
  const [name, setName] = useState('');
  const [manual, setManual] = useState(window.location.hash === '#manual');
  const form = useRef<HTMLFormElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const chat = project?.conversations.find((item) => item.id === conversationId);
  const conversation = useConversation(project?.id, conversationId);
  const sendIdentity = useRef<{ goal: string; id: string } | null>(null);

  useEffect(() => { request<ProjectIndex[]>('/projects').then(setProjects).catch((e) => setError(e.message)); }, []);
  useEffect(() => {
    const update = () => setManual(window.location.hash === '#manual');
    window.addEventListener('hashchange', update); return () => window.removeEventListener('hashchange', update);
  }, []);
  useEffect(() => {
    if (!dialog) return;
    returnFocus.current = document.activeElement as HTMLElement;
    form.current?.querySelector<HTMLInputElement>('input')?.focus();
    return () => returnFocus.current?.focus();
  }, [dialog]);

  async function perform(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true); setError('');
    try { await action(); } catch (error) { setError((error as Error).message); }
    finally { setBusy(false); }
  }
  async function saveDraft() {
    if (!project || !chat || saved) return;
    const updated = await request<Conversation>(`/projects/${project.id}/conversations/${chat.id}/draft`, 'PUT', { text: draft, revision });
    setRevision(updated.revision); setSaved(true);
    setProject((current) => current ? { ...current, conversations: current.conversations.map((item) => item.id === updated.id ? updated : item) } : current);
  }
  async function runValidation() {
    if (!project || !chat || !draft.trim()) return;
    await saveDraft();
    if (sendIdentity.current?.goal !== `${project.id}/${chat.id}/${draft}`) sendIdentity.current = { goal: `${project.id}/${chat.id}/${draft}`, id: crypto.randomUUID() };
    await request<ResearchTask>(`/projects/${project.id}/tasks`, 'POST', { conversationId: chat.id, requestId: sendIdentity.current.id, goal: draft, authorizedTools: ['synthetic_count'] });
    sendIdentity.current = null;
  }
  function selectChat(item?: Conversation) { setConversationId(item?.id || null); setDraft(item?.draft || ''); setRevision(item?.revision || 0); setSaved(true); }
  async function openProject(item: ProjectIndex) {
    await saveDraft();
    const next = await request<Project>('/projects/open', 'POST', { path: item.path });
    setProject(next); selectChat(next.conversations[0]);
  }
  async function acceptDialog() {
    await saveDraft();
    if (dialog === 'conversation' && project) {
      const created = await request<Conversation>(`/projects/${project.id}/conversations`, 'POST', { title: name });
      setProject(await request<Project>(`/projects/${project.id}`)); selectChat(created);
    } else {
      const next = await request<Project>(dialog === 'create' ? '/projects' : '/projects/open', 'POST', { path, name: name || '科研项目' });
      setProject(next); selectChat(next.conversations[0]);
      setProjects(await request<ProjectIndex[]>('/projects'));
    }
    setDialog(null); setName(''); setPath('');
  }
  function analysis(next: WorkspaceTab) {
    if (!tab) { beforeAnalysis.current = expanded; setExpanded(false); }
    setTab(next);
  }
  function closeAnalysis() { setTab(null); setExpanded(beforeAnalysis.current); }
  function modal(type: typeof dialog) { setName(''); setPath(''); setDialog(type); }
  async function chooseDirectory() {
    const selected = await nativeAPI()?.choose_project_directory();
    if (selected) setPath(selected);
  }

  if (manual) return <><a className="wb-return" href="#">返回项目与对话</a><CodonWorkbench /></>;
  return <div className={`wb-shell ${expanded ? 'wb-expanded' : 'wb-collapsed'} ${tab ? 'wb-analysis-open' : ''}`}>
    {expanded && <button className="wb-scrim" aria-label="收起导航覆盖层" onClick={() => setExpanded(false)} />}
    <aside className="wb-navigation" aria-label="项目与对话导航" data-expanded={expanded}>
      <div className="wb-brand"><span><Dna size={22} /></span>{expanded && <strong>SilicoLab</strong>}<button aria-label={expanded ? '收起导航' : '展开导航'} onClick={() => setExpanded(!expanded)}><PanelLeft size={18} /></button></div>
      <button className="wb-new" aria-label="新建对话" disabled={!project || busy} onClick={() => modal('conversation')}><Plus size={17} />{expanded && '新建对话'}</button>
      <div className="wb-navigation-heading">{expanded && <span>项目</span>}<button aria-label="创建项目" onClick={() => modal('create')}><FolderPlus size={17} /></button></div>
      <nav>
        {projects.map((item) => <div key={item.id}>
          <button className={`wb-project ${project?.id === item.id ? 'selected' : ''}`} title={item.name} aria-label={`打开项目 ${item.name}`} disabled={busy} onClick={() => perform(() => openProject(item))}><FolderOpen size={17} />{expanded && <span>{item.name}</span>}</button>
          {expanded && project?.id === item.id && <div className="wb-conversations">{project.conversations.map((item) => <button key={item.id} className={chat?.id === item.id ? 'selected' : ''} disabled={busy} onClick={() => perform(async () => { await saveDraft(); const refreshed = await request<Project>(`/projects/${project.id}`); setProject(refreshed); selectChat(refreshed.conversations.find((chat) => chat.id === item.id)); })}><MessageSquare size={14} /><span>{item.title}</span></button>)}</div>}
        </div>)}
      </nav>
      <button className="wb-open" aria-label="打开项目目录" onClick={() => modal('open')}><Plus size={16} />{expanded && '打开项目目录'}</button>
      <div className="wb-functions">{expanded && <small>科研功能</small>}<a href="#manual" aria-label="ProteinFactory D2P 专项工作台"><Dna size={18} />{expanded && <span>ProteinFactory<small>D2P 专项工作台</small></span>} {expanded && <ChevronRight size={14} />}</a></div>
      <footer>{expanded ? <><span>本地工作空间</span><small>项目记录保存在所选目录</small></> : <span aria-label="本地工作空间">●</span>}</footer>
    </aside>
    <main className="wb-main">
      <header className="wb-header"><div><FolderOpen size={16} /><span>{project?.name || '选择一个科研项目'}</span><span className="wb-header-chat">/　{chat?.title || '对话'}</span></div><div>{(['文件', '任务', '结果'] as WorkspaceTab[]).map((item, index) => <button key={item} aria-label={`查看${item}`} aria-pressed={tab === item} onClick={() => analysis(item)}>{index === 0 ? <Files size={18} /> : index === 1 ? <ListChecks size={18} /> : <FileOutput size={18} />}</button>)}</div></header>
      {error && <div role="alert" className="wb-error">{error}<button aria-label="关闭错误提示" onClick={() => setError('')}><X size={15} /></button></div>}
      <div className="wb-chat">
        {conversation.problem && <p role="alert" className="wb-error">{conversation.problem}</p>}
        {conversation.state && (conversation.state.entries.length > 0 || conversation.state.tasks.length > 0) ? <ConversationHistory state={conversation.state} projectId={project!.id} /> : <div className="wb-welcome"><Dna size={28} /><h1>{chat ? chat.title : '从一个科研问题开始'}</h1><p>{project ? chat ? '写下目标与需要保留的要求，草稿随对话保存。' : '为这个项目建立对话，组织研究思路。' : '选择本地目录，让对话、任务与结果归属于同一个项目。'}</p>{!project && <div className="wb-welcome-actions"><button className="button primary" onClick={() => modal('create')}>创建项目</button><button className="button outline" onClick={() => modal('open')}>打开项目目录</button></div>}{project && !chat && <button className="button primary" onClick={() => modal('conversation')}>新建对话</button>}</div>}
        <div className="wb-composer"><label className="visually-hidden" htmlFor="research-draft">研究目标草稿</label><textarea id="research-draft" placeholder="描述你的科研目标…" disabled={!chat || busy} value={draft} onChange={(event) => { setDraft(event.target.value); setSaved(false); }} /><div><span>{saved ? <Check size={14} /> : null}{saved ? '草稿已保存' : '有未保存修改'}</span><button className="button primary" disabled={!chat || busy || saved} onClick={() => perform(saveDraft)}>{busy ? <LoaderCircle size={16} /> : <ArrowUp size={16} />}保存草稿</button><button className="button outline" disabled={!chat || busy} onClick={() => analysis('任务')}>D2P 专项本地实验</button><button className="button primary" disabled={!chat || busy || !draft.trim()} onClick={() => perform(runValidation)}>运行本机验证</button></div></div>
        <p className="wb-model-note">本机验证模型 · 默认只调用文本计数；D2P 本地专项需在任务区明确选择，不自动调用科学远端。{chat && !conversation.connected ? ' 正在连接状态流…' : ''}</p>
        <p className="wb-caption">{project?.path || '项目内容保存在你选择的本地目录'}</p>
      </div>
    </main>
    {tab && <aside className="wb-analysis" aria-label="分析工作区"><div className="wb-tabs" role="tablist" aria-label="分析区标签">{(['文件', '任务', '结果'] as WorkspaceTab[]).map((item) => <button role="tab" aria-selected={tab === item} key={item} onClick={() => analysis(item)}>{item}</button>)}<button aria-label="关闭分析区" onClick={closeAnalysis}><X size={17} /></button></div><section role="tabpanel"><small>{project?.name || '未选择项目'}</small><h2>{tab === '文件' ? '项目文件' : tab === '任务' ? '科研任务' : '科研产物'}</h2><p>{tab === '文件' ? '项目目录和对话记录已保存，选择文件导入后可在这里检视。' : tab === '任务' ? conversation.state?.tasks.length ? '下方记录来自实际内核与工具执行。模型答复不等于科研完成。' : '当前没有科研任务。保存对话草稿不会触发模型或计算。' : conversation.state?.tasks.some((task) => task.toolExecutions.some((execution) => execution.result?.records)) ? '结果来自已记录的科学执行，校验、输入和产物可逐项核对。' : '当前没有科研产物。完成实际计算与校验后，结果将在这里显示。'}</p>{tab === '结果' && project && <ScientificResults key={`${project.id}/${conversationId}`} projectId={project.id} tasks={conversation.state?.tasks || []} />}{tab === '任务' && project && chat && <LocalScienceForm key={`${project.id}/${chat.id}`} project={project} conversationId={chat.id} />}{tab === '任务' && conversation.state?.tasks.map((task) => <TaskCard key={task.id} task={task} scheduling={conversation.state!.scheduling} projectId={project!.id} />)}{tab === '文件' && project && <ProjectFiles key={project.id} project={project} conversationId={conversationId} onChange={(updated) => setProject((current) => current?.id === updated.id ? updated : current)} />}{project && <dl><dt>项目目录</dt><dd>{project.path}</dd><dt>对话</dt><dd>{project.conversations.length}</dd></dl>}</section></aside>}
    {dialog && <div className="wb-modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) setDialog(null); }}><form ref={form} role="dialog" aria-modal="true" aria-label={dialog === 'conversation' ? '建立新对话' : dialog === 'create' ? '建立科研项目' : '打开已有项目'} className="wb-modal" onSubmit={(e) => { e.preventDefault(); perform(acceptDialog); }} onKeyDown={(event) => {
      if (event.key === 'Escape' && !busy) setDialog(null);
      if (event.key === 'Tab') { const nodes = Array.from(form.current?.querySelectorAll<HTMLElement>('input,button:not(:disabled)') || []); const first = nodes[0], last = nodes.at(-1); if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); } }
    }}><h2>{dialog === 'conversation' ? '新建对话' : dialog === 'create' ? '创建项目' : '打开项目目录'}</h2>{dialog !== 'open' && <label>{dialog === 'conversation' ? '对话名称' : '项目名称'}<input required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} /></label>}{dialog !== 'conversation' && <label>项目目录<input required value={path} placeholder="输入已有本地目录的完整路径" onChange={(e) => setPath(e.target.value)} />{nativeAPI() && <button type="button" className="text-button" onClick={() => perform(chooseDirectory)}>选择本机目录</button>}</label>}<p>{dialog === 'conversation' ? '对话记录归属当前项目。' : '只使用所选目录，不扫描其外部文件。'}</p><div><button type="button" className="button outline" disabled={busy} onClick={() => setDialog(null)}>取消</button><button className="button primary" disabled={busy}>{busy ? '正在保存…' : '确认'}</button></div></form></div>}
  </div>;
}
