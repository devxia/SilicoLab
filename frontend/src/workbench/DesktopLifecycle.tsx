import { useEffect, useState } from 'react';
import { nativeAPI } from '../platform/native';
import './desktop.css';

export default function DesktopLifecycle() {
  const [state, setState] = useState<{ connected: boolean; backgroundPid: number | null } | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    async function update() {
      const api = nativeAPI();
      if (!api?.desktop_status) return;
      try { const next = await api.desktop_status(); if (active) setState(next); }
      catch { if (active) setState({ connected: false, backgroundPid: null }); }
    }
    void update();
    const timer = window.setInterval(update, 1000);
    window.addEventListener('pywebviewready', update);
    return () => { active = false; window.clearInterval(timer); window.removeEventListener('pywebviewready', update); };
  }, []);
  async function command(operation: 'reconnect_background' | 'quit_application') {
    setError('');
    try { await nativeAPI()?.[operation]?.(); }
    catch { setError('后台操作未确认，请检查应用日志；没有创建替代会话或自动恢复任务。'); }
  }
  if (!state) return null;
  return <aside className="wb-desktop-state" aria-label="桌面后台状态"><span>{state.connected ? `独立后台已连接 · PID ${state.backgroundPid}。关闭窗口后已授权任务继续。` : '后台连接已丢失；任务继续状态未确认，请明确重连后检查恢复项。'}</span>{!state.connected && <button onClick={() => command('reconnect_background')}>重新连接后台</button>}<button onClick={() => command('quit_application')}>完全退出 SilicoLab</button>{error && <p role="alert">{error}</p>}</aside>;
}
