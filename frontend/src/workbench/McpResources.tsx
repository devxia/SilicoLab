import { useEffect, useRef, useState } from 'react';
import { request } from './client';
import './skills.css';

type Tool = { name: string; description?: string; inputSchema: Record<string,unknown>; annotations?: { readOnlyHint?: boolean } };
type Resource = { id: string; name?: string; source: string; path?: string; status: string; reason?: string; fingerprint?: string; type?: string; url?: string; script?: string; tools?: Tool[] };
export default function McpResources({ projectId, conversationId }: { projectId?: string; conversationId?: string | null }) {
  const [items,setItems]=useState<Resource[]>([]),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const [args,setArgs]=useState('{"text":"ABC"}'),[authorized,setAuthorized]=useState(false);
  const generation=useRef(0);
  async function refresh(){
    const current=++generation.current;if(!projectId)return;
    try{const result=await request<{resources:Resource[]}>(`/projects/${projectId}/resources/mcp`);if(current===generation.current)setItems(result.resources);}
    catch{if(current===generation.current)setError('MCP来源读取失败；未启动任何进程。');}
  }
  useEffect(()=>{setItems([]);void refresh();return()=>{generation.current++;};},[projectId]);
  async function operation(item:Resource,kind:'trust'|'connect'){
    if(busy)return;setBusy(true);setError('');
    if(kind==='connect')setItems(current=>current.map(resource=>resource.id===item.id?{...resource,status:'connecting',tools:undefined}:resource));
    try{await request(`/projects/${projectId}/resources/mcp/${item.id}/${kind}`,'POST',{fingerprint:item.fingerprint});await refresh();}
    catch{setError('MCP来源已改变、缺少信任或协议/权限不兼容；未自动回退启动。');await refresh();}
    finally{setBusy(false);}
  }
  return <section className="wb-skill-resources" aria-label="MCP资源目录"><h2>MCP 资源</h2><p>发现不连接、不执行命令。首次确认来源后可记住相同配置与脚本哈希；来源信任不是任务工具授权。本地仅受限独立Python单脚本stdio，其他命令拒绝；远端仅所列URL，不继承任何模型key或认证。</p><button className="button outline" disabled={!projectId||busy} onClick={refresh}>刷新 MCP 来源</button><label>本任务工具参数（JSON）<textarea aria-label="MCP工具参数JSON" value={args} onChange={e=>setArgs(e.target.value)}/></label><label><input type="checkbox" checked={authorized} onChange={e=>setAuthorized(e.target.checked)}/>明确授权所选工具及参数用于本任务，不授权科学提交或其他工具</label><ul>{items.map(item=><li key={item.id}><strong>{item.name||'不兼容来源'}</strong><span>{({discovered:'已发现，待信任',trusted:'来源已确认，尚未连接',connecting:'正在连接',callable:'已连接，可显式调用',failed:'连接失败',incompatible:'不兼容，未启动',needs_configuration:'需要显式连接配置',shadowed:'同名冲突，由高优先来源覆盖'} as Record<string,string>)[item.status]||item.status}</span><code>{item.source} / {item.path}</code>{item.url&&<code>实际接收方：{item.url}</code>}{item.script&&<code>受限脚本：{item.script}</code>}{item.fingerprint&&<code>配置身份：{item.fingerprint}</code>}{item.reason&&<p>{item.reason}</p>}{item.status==='discovered'&&<button disabled={busy} onClick={()=>operation(item,'trust')}>确认此来源与权限边界</button>}{['trusted','failed','callable'].includes(item.status)&&<button disabled={busy} onClick={()=>operation(item,'connect')}>连接并核对 MCP schema</button>}{item.tools?.map(tool=><div key={tool.name}><strong>{tool.name}</strong><p>{tool.description}</p><pre>{JSON.stringify(tool.inputSchema,null,2)}</pre><button disabled={busy||!conversationId||!authorized||!tool.annotations?.readOnlyHint} onClick={async()=>{
      setBusy(true);setError('');
      try{await request(`/projects/${projectId}/tasks`,'POST',{conversationId,requestId:crypto.randomUUID(),goal:`显式调用MCP ${item.name}/${tool.name}`,workflow:'mcp_tool',authorizedTools:['mcp_call'],mcpResourceId:item.id,mcpFingerprint:item.fingerprint,mcpTool:tool.name,mcpArguments:JSON.parse(args)});}
      catch{setError('MCP任务参数/schema或授权无效，未静默换工具。');}
      finally{setBusy(false);}
    }}>调用已授权工具 {tool.name}</button></div>)}</li>)}</ul>{!items.length&&<p>没有发现约定位置的独立MCP配置。</p>}{error&&<p role="alert">{error}</p>}</section>;
}
