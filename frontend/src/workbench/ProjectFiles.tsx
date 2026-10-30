import { useState, type ChangeEvent } from 'react';
import { Upload, FileText, LockKeyhole } from 'lucide-react';
import { request, type Project, type ImportedFile, type InputVersion } from './client';
import './files.css';

type Preview = ImportedFile & { text: string | null; truncated: boolean; currentSize: number };
export default function ProjectFiles({ project, conversationId, onChange }: { project: Project; conversationId: string | null; onChange: (project: Project) => void }) {
  const [selected, setSelected] = useState<string[]>([]);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [version, setVersion] = useState<InputVersion | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function perform(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true); setError('');
    try { await action(); } catch (error) { setError((error as Error).message); }
    finally { setBusy(false); }
  }
  const url = `/projects/${project.id}`;
  async function importFile(event: ChangeEvent<HTMLInputElement>) {
    const chosen = Array.from(event.target.files || []);
    event.target.value = '';
    await perform(async () => {
      for (const file of chosen) {
        if (file.size > 5 * 1024 * 1024) throw new Error(`${file.name} 超过 5 MB，请拆分后导入`);
        const bytes = new Uint8Array(await file.arrayBuffer());
        let binary = '';
        for (let index = 0; index < bytes.length; index += 0x8000) binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000));
        await request(url + '/files', 'POST', { name: file.name, contentBase64: btoa(binary) });
        // Each import is a durable operation. Publish its result before proceeding to a later file.
        onChange(await request<Project>(url));
      }
    });
  }
  async function freeze() {
    if (!conversationId) throw new Error('请先选择对话');
    const saved = await request<InputVersion>(url + '/input-versions', 'POST', { conversationId, fileIds: selected });
    setVersion(saved);
    onChange(await request<Project>(url));
  }
  function content(encoded?: string) {
    if (!encoded) return '';
    try { return new TextDecoder('utf-8', { fatal: true }).decode(Uint8Array.from(atob(encoded), (char) => char.charCodeAt(0))).slice(0, 8000); }
    catch { return '此输入为二进制，按完整字节和 SHA-256 固定保存。'; }
  }
  return <div className="wb-files">
    <label className="wb-file-import"><Upload size={16} />导入选定文件<input aria-label="导入项目文件" type="file" multiple disabled={busy} onChange={importFile} /></label>
    {error && <p role="alert" className="wb-file-error">{error}</p>}
    <p className="wb-file-help">复制所选内容到项目；同名文件独立保存，不读取外部父目录。</p>
    <ul>{project.files.map((file) => <li key={file.id}><input type="checkbox" aria-label={`选择文件 ${file.name} ${file.id.slice(0, 6)}`} checked={selected.includes(file.id)} disabled={busy} onChange={(event) => setSelected(event.target.checked ? [...selected, file.id] : selected.filter((id) => id !== file.id))} /><button disabled={busy} onClick={() => perform(async () => { setPreview(await request<Preview>(url + `/files/${file.id}`)); setVersion(null); })}><FileText size={15} /><span>{file.name}<small>{file.size} 字节　{file.sha256.slice(0, 10)}</small></span></button></li>)}</ul>
    <button className="button primary" disabled={!selected.length || !conversationId || busy} onClick={() => perform(freeze)}><LockKeyhole size={14} />{busy ? '正在保存…' : '固定任务输入'}</button>
    {!project.files.length && <p className="wb-file-help">尚无导入文件。固定输入不提交模型或启动计算。</p>}
    {preview && <div className="wb-file-preview"><h3>{preview.name}</h3><pre>{preview.text ?? '二进制文件，固定时保留完整字节。'}</pre>{preview.truncated && <small>预览截取前 8000 字节，固定和导出使用完整内容。</small>}</div>}
    <h3>任务输入版本</h3>
    {project.inputVersions.map((item) => <button className="wb-version" key={item.id} disabled={busy} onClick={() => perform(async () => { setVersion(await request<InputVersion>(url + `/input-versions/${item.id}`)); setPreview(null); })}><LockKeyhole size={13} /><span>{item.id.slice(0, 8)}<small>{item.inputs.map((input) => `${input.name} v${input.version}`).join('、')}</small></span></button>)}
    {version && <section className="wb-fixed-version" aria-label="固定输入详情"><strong>已固定输入 {version.id.slice(0, 8)}</strong><p>仅保存输入，不代表计算完成。</p>{version.inputs.map((input) => <article key={input.fileId}><h4>{input.name} · v{input.version}</h4><small>来源：{input.source}</small><code>SHA-256: {input.sha256}</code><pre>{content(input.contentBase64)}</pre></article>)}</section>}
  </div>;
}
