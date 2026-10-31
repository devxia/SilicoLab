import { useEffect, useRef, useState } from 'react';
import { request } from './client';
import './skills.css';

type Skill = { id: string; name?: string; description?: string; path: string; source: string; status: string; reason?: string; sha256?: string };
export default function SkillResources({ projectId }: { projectId?: string }) {
  const [snapshot, setSnapshot] = useState<{ projectId: string; skills: Skill[]; error: string; busy: boolean }>();
  const generation = useRef(0);
  const current = snapshot?.projectId === projectId ? snapshot : undefined;
  const skills = current?.skills || [];
  const error = current?.error || '';
  const busy = current?.busy || false;
  async function refresh() {
    if (!projectId) return;
    const requestGeneration = ++generation.current;
    setSnapshot({ projectId, skills: [], error: '', busy: true });
    try {
      const response = await request<{ skills: Skill[] }>(`/projects/${projectId}/resources/skills`);
      if (generation.current === requestGeneration) setSnapshot({ projectId, skills: response.skills, error: '', busy: false });
    } catch {
      if (generation.current === requestGeneration) setSnapshot({ projectId, skills: [], error: '技能来源无法读取，请检查项目目录并重试。', busy: false });
    }
  }
  useEffect(() => { void refresh(); return () => { generation.current++; }; }, [projectId]);
  return <section className="wb-skill-resources" aria-label="技能资源目录"><h2>Skills 资源</h2><p>只发现约定目录的 SKILL.md 描述，不启动进程、导入模型认证或安装插件。技能内容按任务需要渐进读取，不增加脚本、网络或科学专项权限。</p>{projectId ? <><button className="button outline" disabled={busy} onClick={refresh}>{busy ? '正在检查…' : '刷新技能来源'}</button>{!skills.length && <p>约定目录中未发现技能。</p>}<ul>{skills.map((skill) => <li key={skill.id}><strong>{skill.name || '不兼容资源'}</strong><span>{skill.status === 'available' ? '已发现，可按需加载' : skill.status === 'shadowed' ? '同名冲突，优先来源覆盖' : '格式或来源不兼容'}</span>{skill.description && <p>{skill.description}</p>}<small>来源 {skill.source}</small><code>{skill.path}</code>{skill.sha256 && <code>SHA-256 {skill.sha256}</code>}{skill.reason && <p>{skill.reason}</p>}</li>)}</ul></> : <p>打开项目后检查项目与用户约定目录，不扫描整个磁盘。</p>}{error && <p role="alert">{error}</p>}</section>;
}
