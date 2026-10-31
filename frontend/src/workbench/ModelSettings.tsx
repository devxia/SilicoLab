import { useEffect, useState } from 'react';
import { request } from './client';
import './models.css';

export type ModelConfiguration = { id: string; name: string; protocol: 'openai-responses' | 'anthropic-messages'; baseUrl: string; modelId: string; hasKey: boolean; verification: string; verifiedAt?: string };
export default function ModelSettings({ onChange }: { onChange: (items: ModelConfiguration[]) => void }) {
  const [items, setItems] = useState<ModelConfiguration[]>([]);
  const [name, setName] = useState('');
  const [protocol, setProtocol] = useState<ModelConfiguration['protocol']>('openai-responses');
  const [baseUrl, setBaseUrl] = useState('https://api.openai.com/v1');
  const [modelId, setModelId] = useState('');
  const [key, setKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function refresh() {
    const values = await request<ModelConfiguration[]>('/model-configs');
    setItems(values); onChange(values);
  }
  useEffect(() => { refresh().catch(() => setError('模型配置读取失败，请重开设置')); }, []);
  async function perform(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true); setError('');
    try { await action(); await refresh(); }
    catch { setError('模型设置操作失败：请检查输入、Keychain 许可、凭据或协议兼容性。未自动切换接收方。'); }
    finally { setBusy(false); }
  }
  return <section className="wb-model-settings" aria-label="应用模型设置">
    <h2>模型与凭据</h2>
    <p>配置仅属于 SilicoLab 应用。API key 存入本机 Keychain，不写入项目、提示词或普通日志；不导入其他软件账号。对话独立选择模型，不绑定项目。</p>
    <p>协议与地址是两项不同设置。OpenAI Responses 通常使用含 /v1 的基础地址；Anthropic Messages 使用服务根地址，SDK 添加 /v1/messages。自定义端点须明确兼容协议。未验证不代表不可选择，但实际调用会将对话内容发送到所选地址。</p>
    <ul>{items.map((item) => <li key={item.id}><strong>{item.name}</strong><span>{item.protocol} / {item.modelId}</span><code>{item.baseUrl}</code><small>{item.verification === 'verified_transport' ? '连接与协议已检查（不代表完整真实 provider 验收）' : '端点未验证'}；{item.hasKey ? '已保存 API key' : '缺少凭据'}</small><div><button disabled={busy} onClick={() => perform(async () => { await request(`/model-configs/${item.id}/verify`, 'POST'); })}>检查连接（发送人工文本）</button><button disabled={busy} onClick={() => perform(async () => { await request(`/model-configs/${item.id}`, 'DELETE'); })}>移除模型与凭据</button></div></li>)}</ul>
    {!items.length && <p>尚未配置账号。默认保留本机验证模型，不自动读取环境认证。</p>}
    <form onSubmit={(event) => { event.preventDefault(); const apiKey = key; setKey(''); void perform(async () => { await request('/model-configs', 'POST', { name, protocol, baseUrl, modelId, apiKey }); setName(''); setModelId(''); }); }}>
      <label>配置名称<input value={name} required maxLength={100} disabled={busy} autoComplete="off" onChange={(event) => setName(event.target.value)} /></label>
      <label>请求协议<select aria-label="请求协议" value={protocol} disabled={busy} onChange={(event) => { const next = event.target.value as ModelConfiguration['protocol']; setProtocol(next); setBaseUrl(next === 'openai-responses' ? 'https://api.openai.com/v1' : 'https://api.anthropic.com'); }}><option value="openai-responses">OpenAI Responses（含明确兼容端点）</option><option value="anthropic-messages">Anthropic Messages（含明确兼容端点）</option></select></label>
      <label>模型基础地址<input value={baseUrl} type="url" required maxLength={2000} disabled={busy} autoComplete="off" onChange={(event) => setBaseUrl(event.target.value)} /></label>
      <label>模型 ID<input value={modelId} required maxLength={200} disabled={busy} autoComplete="off" onChange={(event) => setModelId(event.target.value)} /></label>
      <label>API key<input value={key} type="password" required maxLength={8192} disabled={busy} autoComplete="new-password" onChange={(event) => setKey(event.target.value)} /></label>
      <button className="button primary" disabled={busy}>保存到 SilicoLab</button>
    </form>
    {error && <p role="alert">{error}</p>}
  </section>;
}
