import { useEffect, useRef, useState } from 'react';
import { request, type Project } from './client';
import './skills.css';

export default function ProjectArchives({project,onChanged,onRestored}:{project:Project|null;onChanged:(next:Project)=>void;onRestored:(next:Project,focus:boolean)=>void}) {
  const epoch=useRef(0);
  useEffect(()=>{epoch.current++;return()=>{epoch.current++;};},[]);
  const [backup,setBackup]=useState(''),[archive,setArchive]=useState(''),[target,setTarget]=useState('');
  const [busy,setBusy]=useState(false),[message,setMessage]=useState(''),[error,setError]=useState('');
  async function save(upgrade=false){
    if(!project||busy)return;const started=epoch.current;setBusy(true);setError('');setMessage('');
    try{
      await request(`/projects/${project.id}/${upgrade?'upgrade':'backup'}`,'POST',{path:backup});
      const next=await request<Project>(`/projects/${project.id}`);
      if(started!==epoch.current)return;
      onChanged(next);
      setMessage(upgrade?'升级完成；完整旧版本备份已保存，未自动执行任务':'一致备份已保存；包含已提交检查点与产物哈希，不含应用凭据');
    }catch(e){setError(e instanceof Error?e.message:'备份未完成，原数据保留');}finally{setBusy(false);}
  }
  async function restore(){
    if(busy)return;const started=epoch.current;setBusy(true);setError('');setMessage('');
    try{
      const restored=await request<Project>('/projects/restore','POST',{archivePath:archive,path:target});
      onRestored(restored,started===epoch.current);
      if(started!==epoch.current)return;
      setMessage('原项目已恢复；未自动执行。请从待处理项逐项选择。');
    }catch(e){setError(e instanceof Error?e.message:'恢复失败；未覆盖原件');}finally{setBusy(false);}
  }
  return <section className="wb-skill-resources" aria-label="项目备份与恢复"><h2>项目备份与恢复</h2><p>备份前先明确暂停活动与排队任务。完整保存工作台管理的对话、输入、任务检查点、脚本与产物；不复制项目外原件、其他根目录文件、应用模型凭据或资源信任。恢复不许可自动执行。</p><h3>一致备份与版本升级</h3><p>{project?`当前项目：${project.name} · 状态格式 ${project.stateFormat||1}`:'先选择需要备份的项目'}</p><label>新备份 ZIP 路径<input aria-label="新备份 ZIP 路径" value={backup} onChange={e=>setBackup(e.target.value)} placeholder="现有目录中的新文件，不覆盖"/></label><button className="button outline" disabled={busy||!project||!backup.trim()} onClick={()=>save()}>创建一致备份</button>{project?.stateFormat===1&&<button className="button outline" disabled={busy||!backup.trim()} onClick={()=>save(true)}>备份并升级状态格式</button>}<h3>核验并恢复</h3><p>恢复保留原UUID。原项目仍关联时先停止并移除关联；原目录不会删除。目标必须是现有空目录，验证失败不覆盖原件。</p><label>备份 ZIP 路径<input aria-label="备份 ZIP 路径" value={archive} onChange={e=>setArchive(e.target.value)}/></label><label>现有空恢复目录<input aria-label="现有空恢复目录" value={target} onChange={e=>setTarget(e.target.value)}/></label><button className="button outline" disabled={busy||!archive.trim()||!target.trim()} onClick={restore}>{busy?'正在核验…':'核验并恢复原项目'}</button><p>旧版无状态标记按格式1处理，显式升级仅增加格式2兼容封装、不重写pi-durable内部schema。工具或脚本环境变化时旧任务仅供检视，须明确新建任务，不混用旧结果。回滚使用升级前ZIP恢复到空目录，不原地降级。</p>{message&&<p role="status">{message}</p>}{error&&<p role="alert">{error}</p>}</section>;
}
