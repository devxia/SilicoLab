import { useEffect,useRef,useState } from 'react';
import { request } from './client';
import { nativeAPI } from '../platform/native';
export type NotificationTarget={projectId:string;conversationId:string;taskId:string;decisionId:string};
type State={enabled:boolean;authorization:string;pending:number;delivered?:number;error?:string};
export default function DecisionNotifications({onSelect}:{onSelect:(target:NotificationTarget)=>Promise<boolean>}){
  const select=useRef(onSelect);select.current=onSelect;
  const [state,setState]=useState<State|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
  useEffect(()=>{
    let active=true,inflight=false;
    async function update(){
      if(inflight||!nativeAPI())return;inflight=true;
      try{
        const next=await request<State>('/notifications');if(active)setState(next);
        if(active){
          const target=await request<NotificationTarget|null>('/notifications/selection','POST',{});
          if(target&&active&&await select.current(target)){
            await request('/notifications/selection/ack','POST',target);
          }
        }
      }catch{if(active)setError('系统提醒或定位未确认；问题仍在应用待处理项。');}finally{inflight=false;}
    }
    void update();const timer=window.setInterval(update,1500);window.addEventListener('pywebviewready',update);
    return()=>{active=false;window.clearInterval(timer);window.removeEventListener('pywebviewready',update);};
  },[]);
  if(!state)return null;
  async function configure(enabled:boolean){setBusy(true);setError('');try{setState(await request<State>('/notifications','POST',{enabled}));}catch{setError('系统提醒设置未确认；应用内问题仍可答复。');}finally{setBusy(false);}}
  return <aside className="wb-desktop-state" aria-label="系统提醒设置"><span>必要决定系统提醒：{state.enabled?'已启用':'已关闭'} · {({authorized:'系统已允许',denied:'系统未允许，仍可在应用查看',not_requested:'尚未请求系统权限',unavailable:'原生组件不可用'} as Record<string,string>)[state.authorization]||state.authorization}。通知只包含固定摘要，不含序列、目标或凭据。</span><button disabled={busy} onClick={()=>configure(!state.enabled)}>{state.enabled?'关闭系统提醒':'启用系统提醒'}</button>{(error||state.error)&&<p role="alert">{error||state.error}</p>}</aside>;
}
