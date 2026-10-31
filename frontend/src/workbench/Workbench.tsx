import { useEffect, useRef, useState } from 'react';
import { Dna, FolderOpen, FolderPlus, MessageSquare, PanelLeft, Plus, Files, ListChecks, FileOutput, X, ArrowUp, ChevronRight, Check, LoaderCircle, Settings, BookOpen } from 'lucide-react';
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
import SimulatedJobForm from './SimulatedJobForm';
import PythonAnalysisForm from './PythonAnalysisForm';
import AnalysisResults from './AnalysisResults';
import RecoveryItems from './RecoveryItems';
import DesktopLifecycle from './DesktopLifecycle';
import SkillResources from './SkillResources';
import ModelSettings, { type ModelConfiguration } from './ModelSettings';

const nativeStartup = new URLSearchParams(window.location.search).get('silicolabDesktop') === '1';
type WorkspaceTab = '文件' | '任务' | '结果';
export default function Workbench() {
  const [projects, setProjects] = useState<ProjectIndex[]>([]);
  const [nativeReady, setNativeReady] = useState(!nativeStartup);
  const [taskTarget, setTaskTarget] = useState<{ projectId: string; conversationId: string; taskId: string } | null>(null);
  const [settings, setSettings] = useState(false);
  const [resources, setResources] = useState(false);
  const [modelConfigurations, setModelConfigurations] = useState<ModelConfiguration[]>([]);
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
  const [dialog, setDialog] = useState<'create' | 'open' | 'conversation' | 'relocate' | null>(null);
  const [path, setPath] = useState('');
  const [name, setName] = useState('');
  const [manual, setManual] = useState(window.location.hash === '#manual');
  const form = useRef<HTMLFormElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const offline = project?.availability?.status === 'offline';
  const chat = project?.conversations.find((item) => item.id === conversationId);
  const conversation = useConversation(project?.id, conversationId);
  const selectedModelMissing = Boolean(chat?.modelConfigurationId && !modelConfigurations.some((item) => item.id === chat.modelConfigurationId));
  const inFlightRequest = conversation.state?.tasks.flatMap((task) => task.modelRequests || []).find((request) => request.status === 'running');
  const localDrafts = useRef(new Map<string, { draft: string; revision: number; saved: boolean }>());
  const nativeSelectionWrites = useRef<Promise<unknown>>(Promise.resolve());
  const restoredSelection = useRef(false);
  const sendIdentity = useRef<{ goal: string; id: string } | null>(null);

  useEffect(() => {
    let active = true;
    async function attachSelection() {
      try {
        const items = await request<ProjectIndex[]>('/projects');
        if (!active) return;
        setProjects(items);
        if (restoredSelection.current) return;
        const api = nativeAPI();
        if (nativeStartup && !api) return; // Cocoa injects the narrow bridge after navigation.
        const bootstrap = api ? await api.bootstrap() : null;
        if (active) setNativeReady(true);
        const selected = bootstrap ? bootstrap.selection : JSON.parse(localStorage.getItem('silicolab-workbench-selection') || 'null') as { projectId: string; conversationId: string } | null;
        if (!active || restoredSelection.current || !selected) return;
        if (!items.some((item) => item.id === selected.projectId)) throw new Error('所选项目未关联');
        const next = await request<Project>(`/projects/${selected.projectId}`);
        if (!active || restoredSelection.current) return;
        const chat = next.conversations.find((item) => item.id === selected.conversationId);
        if (!chat) throw new Error('所选对话不可读取');
        setProject(next); selectChat(chat, next.id);
        restoredSelection.current = true;
      } catch { if (active) setError('上次项目或对话暂不可附着，请从列表重新定位；未创建空会话或执行任务。'); }
    }
    void attachSelection();
    window.addEventListener('pywebviewready', attachSelection);
    request<ModelConfiguration[]>('/model-configs').then(setModelConfigurations).catch(() => {});
    return () => { active = false; window.removeEventListener('pywebviewready', attachSelection); };
  }, []);
  useEffect(() => {
    if (!project) return;
    let active = true;
    const identity = project.id;
    const observedPath = project.path;
    const timer = window.setInterval(() => {
      request<Project>(`/projects/${identity}`).then((next) => {
        if (active) setProject((current) => current?.id === identity && current.path === observedPath ? { ...current, availability: next.availability, tasks: next.tasks } : current);
      }).catch(() => {});
    }, 500);
    return () => { active = false; window.clearInterval(timer); };
  }, [project?.id, project?.path]);
  useEffect(() => {
    const update = () => setManual(window.location.hash === '#manual');
    window.addEventListener('hashchange', update); return () => window.removeEventListener('hashchange', update);
  }, []);
  useEffect(() => {
    if (!taskTarget || settings || resources || project?.id !== taskTarget.projectId || conversationId !== taskTarget.conversationId || conversation.state?.conversationId !== taskTarget.conversationId) return;
    const card = [...document.querySelectorAll<HTMLElement>('.wb-transcript [data-task-id]')].find((element) => element.dataset.taskId === taskTarget.taskId);
    if (card) { card.scrollIntoView({ block: 'center' }); card.focus({ preventScroll: true }); setTaskTarget(null); }
  }, [taskTarget, settings, resources, project?.id, conversationId, conversation.state]);
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
    if (offline) throw new Error('项目目录离线，草稿尚未保存；请先重新定位核对');
    const updated = await request<Conversation>(`/projects/${project.id}/conversations/${chat.id}/draft`, 'PUT', { text: draft, revision });
    localDrafts.current.set(`${project.id}/${chat.id}`, { draft: updated.draft, revision: updated.revision, saved: true });
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
  async function selectModel(configurationId: string) {
    if (!project || !chat) return;
    const selected = await request<Conversation>(`/projects/${project.id}/conversations/${chat.id}/model`, 'PUT', { configurationId: configurationId || null });
    setProject((current) => current ? { ...current, conversations: current.conversations.map((item) => item.id === selected.id ? selected : item) } : current);
  }
  function selectChat(item?: Conversation, owner = project?.id, rebase = false) {
    restoredSelection.current = true;
    if (project && conversationId) {
      const key = `${project.id}/${conversationId}`;
      const committed = localDrafts.current.get(key);
      if (!saved && !(committed?.saved && committed.draft === draft && committed.revision >= revision)) localDrafts.current.set(key, { draft, revision, saved });
      else if (saved) localDrafts.current.delete(key);
    }
    const selection = item && owner ? { projectId: owner, conversationId: item.id } : null;
    const bridge = nativeAPI();
    if (bridge?.save_selection) {
      nativeSelectionWrites.current = nativeSelectionWrites.current.then(() => bridge.save_selection!(selection)).catch(() => setError('当前项目/对话选择尚未保存到应用，请重试选择；未宣称可恢复。'));
    }
    if (!nativeStartup && !bridge) {
      try {
        if (selection) localStorage.setItem('silicolab-workbench-selection', JSON.stringify(selection));
        else localStorage.removeItem('silicolab-workbench-selection');
      } catch { /* Browser preferences are optional, never native restore authority. */ }
    }
    const cached = item && owner ? localDrafts.current.get(`${owner}/${item.id}`) : undefined;
    setConversationId(item?.id || null); setDraft(cached ? cached.draft : item?.draft || '');
    setRevision(rebase ? item?.revision ?? 0 : cached?.revision ?? item?.revision ?? 0); setSaved(cached?.saved ?? true);
  }
  async function openProject(item: ProjectIndex) {
    if (!offline) await saveDraft();
    const next = await request<Project>(`/projects/${item.id}`);
    setProject(next); selectChat(next.conversations[0], next.id);
  }
  async function acceptDialog() {
    if (dialog === 'relocate' && project) {
      const located = await request<Project>(`/projects/${project.id}/relocate`, 'POST', { path });
      setProject(located);
      selectChat(located.conversations.find((item) => item.id === conversationId) || located.conversations[0], located.id, true);
      setProjects(await request<ProjectIndex[]>('/projects'));
      setDialog(null); setPath(''); return;
    }
    if (!offline || dialog === 'conversation') await saveDraft();
    if (dialog === 'conversation' && project) {
      const created = await request<Conversation>(`/projects/${project.id}/conversations`, 'POST', { title: name });
      setProject(await request<Project>(`/projects/${project.id}`)); selectChat(created);
    } else {
      const next = await request<Project>(dialog === 'create' ? '/projects' : '/projects/open', 'POST', { path, name: name || '科研项目' });
      setProject(next); selectChat(next.conversations[0], next.id);
      setProjects(await request<ProjectIndex[]>('/projects'));
    }
    setDialog(null); setName(''); setPath('');
  }
  async function removeProject() {
    if (!project) return;
    if (!offline) await saveDraft();
    await request(`/projects/${project.id}`, 'DELETE');
    setProject(null); selectChat(); setProjects(await request<ProjectIndex[]>('/projects'));
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

  if (!nativeReady) return <main className="wb-welcome" role="status"><h1>正在连接本机功能…</h1><p>尚未读取项目选择或运行任务。若连接未完成，请重新打开窗口。</p>{error && <p role="alert">{error}</p>}</main>;
  if (manual) return <><a className="wb-return" href="#">返回项目与对话</a><CodonWorkbench /></>;
  return <div className={`wb-shell ${expanded ? 'wb-expanded' : 'wb-collapsed'} ${tab ? 'wb-analysis-open' : ''}`}>
    {expanded && <button className="wb-scrim" aria-label="收起导航覆盖层" onClick={() => setExpanded(false)} />}
    <aside className="wb-navigation" aria-label="项目与对话导航" data-expanded={expanded}>
      <div className="wb-brand"><span><Dna size={22} /></span>{expanded && <strong>SilicoLab</strong>}<button aria-label={expanded ? '收起导航' : '展开导航'} onClick={() => setExpanded(!expanded)}><PanelLeft size={18} /></button></div>
      <button className="wb-new" aria-label="新建对话" disabled={!project || busy} onClick={() => modal('conversation')}><Plus size={17} />{expanded && '新建对话'}</button>
      {project && <button className="wb-open" aria-label="移除项目关联" disabled={busy} onClick={() => perform(removeProject)}><X size={16} />{expanded && '移除项目关联'}</button>}
      <div className="wb-navigation-heading">{expanded && <span>项目</span>}<button aria-label="创建项目" onClick={() => modal('create')}><FolderPlus size={17} /></button></div>
      <nav>
        {projects.map((item) => <div key={item.id}>
          <button className={`wb-project ${project?.id === item.id ? 'selected' : ''}`} title={item.name} aria-label={`打开项目 ${item.name}`} disabled={busy} onClick={() => perform(() => openProject(item))}><FolderOpen size={17} />{expanded && <span>{item.name}</span>}</button>
          {expanded && project?.id === item.id && <div className="wb-conversations">{project.conversations.map((item) => <button key={item.id} className={chat?.id === item.id ? 'selected' : ''} disabled={busy} onClick={() => perform(async () => { if (!offline) await saveDraft(); const refreshed = await request<Project>(`/projects/${project.id}`); setProject(refreshed); selectChat(refreshed.conversations.find((chat) => chat.id === item.id)); })}><MessageSquare size={14} /><span>{item.title}</span></button>)}</div>}
        </div>)}
      </nav>
      <button className="wb-open" aria-label="打开项目目录" onClick={() => modal('open')}><Plus size={16} />{expanded && '打开项目目录'}</button>
      <div className="wb-functions">{expanded && <small>科研功能</small>}<a href="#manual" aria-label="ProteinFactory D2P 专项工作台"><Dna size={18} />{expanded && <span>ProteinFactory<small>D2P 专项工作台</small></span>} {expanded && <ChevronRight size={14} />}</a></div>
      <button className="wb-open" aria-label="模型设置" onClick={() => { setResources(false); setSettings(!settings); }}><Settings size={17} />{expanded && '模型设置'}</button>
      <button className="wb-open" aria-label="技能资源" onClick={() => { setSettings(false); setResources(!resources); }}><BookOpen size={17} />{expanded && '技能资源'}</button>
      <footer>{expanded ? <><span>本地工作空间</span><small>项目记录保存在所选目录</small></> : <span aria-label="本地工作空间">●</span>}</footer>
    </aside>
    <main className="wb-main">
      <header className="wb-header"><div><FolderOpen size={16} /><span>{project?.name || '选择一个科研项目'}</span><span className="wb-header-chat">/　{chat?.title || '对话'}</span></div><div>{(['文件', '任务', '结果'] as WorkspaceTab[]).map((item, index) => <button key={item} aria-label={`查看${item}`} aria-pressed={tab === item} onClick={() => analysis(item)}>{index === 0 ? <Files size={18} /> : index === 1 ? <ListChecks size={18} /> : <FileOutput size={18} />}</button>)}</div></header>
      <DesktopLifecycle />
      {project && <RecoveryItems project={project} onSelect={(id, taskId) => perform(async () => {
        if (!offline) await saveDraft();
        const refreshed=await request<Project>(`/projects/${project.id}`);
        const original=refreshed.conversations.find((item)=>item.id===id);
        if (!original) throw new Error('原任务对话不可访问；未新建替代对话');
        if (!refreshed.tasks.some((task) => task.id === taskId && task.conversationId === id)) throw new Error('原任务身份不可核对，未定位替代任务');
        setSettings(false); setResources(false);
        setProject(refreshed);selectChat(original,refreshed.id);
        setTaskTarget({projectId:refreshed.id,conversationId:id,taskId});
      })} />}
      {offline && <div role="alert" className="wb-error"><strong>项目目录离线</strong><p>{project?.availability?.reason}。只显示最后已观察状态；最新进度未确认保存。其他项目可继续使用。</p><button onClick={() => modal('relocate')}>重新定位原项目</button></div>}
      {error && <div role="alert" className="wb-error">{error}<button aria-label="关闭错误提示" onClick={() => setError('')}><X size={15} /></button></div>}
      {settings ? <ModelSettings onChange={setModelConfigurations} /> : resources ? <SkillResources projectId={project?.id} /> : <div className="wb-chat">
        {conversation.problem && <p role="alert" className="wb-error">{conversation.problem}</p>}
        {conversation.state && (conversation.state.entries.length > 0 || conversation.state.tasks.length > 0) ? <ConversationHistory state={conversation.state} projectId={project!.id} /> : <div className="wb-welcome"><Dna size={28} /><h1>{chat ? chat.title : '从一个科研问题开始'}</h1><p>{project ? chat ? '写下目标与需要保留的要求，草稿随对话保存。' : '为这个项目建立对话，组织研究思路。' : '选择本地目录，让对话、任务与结果归属于同一个项目。'}</p>{!project && <div className="wb-welcome-actions"><button className="button primary" onClick={() => modal('create')}>创建项目</button><button className="button outline" onClick={() => modal('open')}>打开项目目录</button></div>}{project && !chat && <button className="button primary" onClick={() => modal('conversation')}>新建对话</button>}</div>}
        <div className="wb-model-select"><label>当前对话模型<select aria-label="当前对话模型" disabled={!chat || busy} value={chat?.modelConfigurationId || ''} onChange={(event) => perform(() => selectModel(event.target.value))}><option value="">本机验证模型（不联网）</option>{selectedModelMissing && <option value={chat?.modelConfigurationId}>已移除或不可用的所选模型（未切换）</option>}{modelConfigurations.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.protocol} · {item.verification === 'unverified' ? '未验证' : '已检查连接'}</option>)}</select></label>{inFlightRequest && <p aria-label="在途模型与待生效选择">在途实际来源：{inFlightRequest.model} / {inFlightRequest.protocol} / {inFlightRequest.endpoint || '本机'}。{(chat?.modelConfigurationId || null) !== inFlightRequest.configurationId ? '新选择从下一次请求生效，当前请求和工具继续；选择即允许新接收方使用必要历史。' : '当前选择与在途接收方一致。'}</p>}</div><div className="wb-composer">{selectedModelMissing && <p role="alert">当前对话所选模型已移除或不可用。请明确选择其他模型，不会自动回退。</p>}<label className="visually-hidden" htmlFor="research-draft">研究目标草稿</label><textarea id="research-draft" placeholder="描述你的科研目标…" disabled={!chat || busy} value={draft} onChange={(event) => { setDraft(event.target.value); setSaved(false); }} /><div><span>{saved ? <Check size={14} /> : null}{saved ? '草稿已保存' : '有未保存修改'}</span><button className="button primary" disabled={!chat || busy || saved} onClick={() => perform(saveDraft)}>{busy ? <LoaderCircle size={16} /> : <ArrowUp size={16} />}保存草稿</button><button className="button outline" disabled={!chat || busy} onClick={() => analysis('任务')}>D2P 专项本地实验</button><button className="button primary" disabled={!chat || busy || !draft.trim() || selectedModelMissing} onClick={() => perform(runValidation)}>{chat?.modelConfigurationId ? '发送到所选模型' : '运行本机验证'}</button></div></div>
        <p className="wb-model-note">{chat?.modelConfigurationId ? '所选模型会接收本对话目标与已授权工具摘要；模型许可不授权科学服务上传。' : '本机验证模型 · 默认只调用文本计数；D2P 本地专项需在任务区明确选择，不自动调用科学远端。'}{chat && !conversation.connected ? ' 正在连接状态流…' : ''}</p>
        <p className="wb-caption">{project?.path || '项目内容保存在你选择的本地目录'}</p>
      </div>}
    </main>
    {tab && <aside className="wb-analysis" aria-label="分析工作区"><div className="wb-tabs" role="tablist" aria-label="分析区标签">{(['文件', '任务', '结果'] as WorkspaceTab[]).map((item) => <button role="tab" aria-selected={tab === item} key={item} onClick={() => analysis(item)}>{item}</button>)}<button aria-label="关闭分析区" onClick={closeAnalysis}><X size={17} /></button></div><section role="tabpanel"><small>{project?.name || '未选择项目'}</small><h2>{tab === '文件' ? '项目文件' : tab === '任务' ? '科研任务' : '科研产物'}</h2><p>{tab === '文件' ? '项目目录和对话记录已保存，选择文件导入后可在这里检视。' : tab === '任务' ? conversation.state?.tasks.length ? '下方记录来自实际内核与工具执行。模型答复不等于科研完成。' : '当前没有科研任务。保存对话草稿不会触发模型或计算。' : conversation.state?.tasks.some((task) => task.toolExecutions.some((execution) => execution.result?.records)) ? '结果来自已记录的科学执行，校验、输入和产物可逐项核对。' : '当前没有科研产物。完成实际计算与校验后，结果将在这里显示。'}</p>{tab === '结果' && project && <AnalysisResults projectId={project.id} tasks={conversation.state?.tasks || []} />}{tab === '结果' && project && <ScientificResults key={`${project.id}/${conversationId}`} projectId={project.id} tasks={conversation.state?.tasks || []} />}{tab === '任务' && project && chat && <PythonAnalysisForm key={`python-${project.id}/${chat.id}`} project={project} conversationId={chat.id} />}{tab === '任务' && project && chat && <SimulatedJobForm key={`sim-${project.id}/${chat.id}`} projectId={project.id} conversationId={chat.id} />}{tab === '任务' && project && chat && <><LocalScienceForm key={`remote-${project.id}/${chat.id}`} source="remote" project={project} conversationId={chat.id} /><LocalScienceForm key={`${project.id}/${chat.id}`} project={project} conversationId={chat.id} /></>}{tab === '任务' && conversation.state?.tasks.map((task) => <TaskCard key={task.id} task={task} scheduling={conversation.state!.scheduling} projectId={project!.id} />)}{tab === '文件' && project && <ProjectFiles key={project.id} project={project} conversationId={conversationId} onChange={(updated) => setProject((current) => current?.id === updated.id ? updated : current)} />}{project && <dl><dt>项目目录</dt><dd>{project.path}</dd><dt>对话</dt><dd>{project.conversations.length}</dd></dl>}</section></aside>}
    {dialog && <div className="wb-modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) setDialog(null); }}><form ref={form} role="dialog" aria-modal="true" aria-label={dialog === 'relocate' ? '重新定位原项目' : dialog === 'conversation' ? '建立新对话' : dialog === 'create' ? '建立科研项目' : '打开已有项目'} className="wb-modal" onSubmit={(e) => { e.preventDefault(); perform(acceptDialog); }} onKeyDown={(event) => {
      if (event.key === 'Escape' && !busy) setDialog(null);
      if (event.key === 'Tab') { const nodes = Array.from(form.current?.querySelectorAll<HTMLElement>('input,button:not(:disabled)') || []); const first = nodes[0], last = nodes.at(-1); if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); } }
    }}><h2>{dialog === 'relocate' ? '重新定位原项目' : dialog === 'conversation' ? '新建对话' : dialog === 'create' ? '创建项目' : '打开项目目录'}</h2>{dialog !== 'open' && dialog !== 'relocate' && <label>{dialog === 'conversation' ? '对话名称' : '项目名称'}<input required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} /></label>}{dialog !== 'conversation' && <label>项目目录<input required value={path} placeholder="输入已有本地目录的完整路径" onChange={(e) => setPath(e.target.value)} />{nativeAPI() && <button type="button" className="text-button" onClick={() => perform(chooseDirectory)}>选择本机目录</button>}</label>}<p>{dialog === 'conversation' ? '对话记录归属当前项目。' : '只使用所选目录，不扫描其外部文件。'}</p><div><button type="button" className="button outline" disabled={busy} onClick={() => setDialog(null)}>取消</button><button className="button primary" disabled={busy}>{busy ? '正在保存…' : '确认'}</button></div></form></div>}
  </div>;
}
