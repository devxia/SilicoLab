import { open, lstat, readdir } from 'node:fs/promises';
import { constants } from 'node:fs';
import { createHash } from 'node:crypto';
import { relative, resolve, join, sep } from 'node:path';

export type SkillRoot = { path: string; anchor: string; source: string };
export type SkillResource = { id: string; path: string; source: string; name?: string; description?: string; sha256?: string; status: 'available' | 'shadowed' | 'incompatible'; reason?: string };
const hash = (text: string | Buffer) => createHash('sha256').update(text).digest('hex');
async function noLinks(path: string, anchor: string) {
  const suffix = relative(resolve(anchor), resolve(path));
  if (suffix.startsWith('..') || suffix.startsWith(sep)) throw new Error('source escapes skill root');
  let current = resolve(anchor);
  for (const part of [undefined, ...suffix.split(sep).filter(Boolean)]) {
    if (part) current = join(current, part);
    const info = await lstat(current);
    if (info.isSymbolicLink()) throw new Error('symbolic links are unsupported');
  }
}
async function bytes(path: string, anchor: string) {
  await noLinks(path, anchor);
  const handle = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const info = await handle.stat();
    if (!info.isFile() || info.size > 256 * 1024) throw new Error('SKILL.md must be a regular file at most 256KiB');
    const buffer = Buffer.alloc(256 * 1024 + 1);
    const { bytesRead } = await handle.read(buffer, 0, buffer.length, 0);
    if (bytesRead > 256 * 1024) throw new Error('SKILL.md exceeds 256KiB');
    const content = buffer.subarray(0, bytesRead);
    return { text: new TextDecoder('utf-8', { fatal: true }).decode(content), sha256: hash(content) };
  } finally { await handle.close(); }
}
function metadata(text: string) {
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  const end = lines.indexOf('---', 1);
  if (lines[0] !== '---' || end < 1 || lines.slice(0, end).join('\n').length > 8192) throw new Error('missing or oversized YAML frontmatter');
  const fields: Record<string, string> = {};
  for (let i = 1; i < end; i++) {
    if (!lines[i].trim() || lines[i].startsWith('#')) continue;
    const entry = /^([a-zA-Z][\w-]*):\s*(.*)$/.exec(lines[i]);
    if (!entry) throw new Error('unsupported frontmatter structure');
    let [, key, value] = entry;
    if (fields[key] !== undefined) throw new Error('duplicate frontmatter field');
    if (/^[>|][-+]?$/.test(value)) {
      const folded: string[] = [];
      while (i + 1 < end && (/^\s/.test(lines[i + 1]) || !lines[i + 1])) folded.push(lines[++i].trim());
      value = folded.join(' ');
    } else if (value.startsWith('"')) {
      try { value = JSON.parse(value); } catch { throw new Error('invalid quoted frontmatter field'); }
    } else if (value.startsWith("'")) {
      if (!/^'(?:[^']|'')*'$/.test(value)) throw new Error('invalid quoted frontmatter field');
      value = value.slice(1, -1).replace(/''/g, "'");
    } else {
      value = value.replace(/(?:^|\s+)#.*$/, '').trimEnd();
      if (/^[\[{!&*]/.test(value)) throw new Error(`unsupported ${key} frontmatter format`);
    }
    fields[key] = value;
  }
  if (!/^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$/.test(fields.name || '')) throw new Error('name must be an ASCII skill identifier');
  if (!fields.description?.trim() || fields.description.length > 2000) throw new Error('description must be a scalar of 1–2000 characters');
  return { name: fields.name, description: fields.description.trim() };
}

/** Bounded exact roots; discovery never imports code or reads other configuration files. */
export class SkillCatalog {
  readonly roots: SkillRoot[];
  constructor(roots: SkillRoot[]) { this.roots = roots; }
  async list(): Promise<{ skills: SkillResource[] }> {
    const skills: SkillResource[] = [];
    const names = new Set<string>();
    for (const root of this.roots) {
      let folders;
      try { await noLinks(root.path, root.anchor); folders = await readdir(root.path, { withFileTypes: true }); }
      catch (error) {
        if ((error as NodeJS.ErrnoException).code === 'ENOENT') continue;
        skills.push({ id: hash(root.path), path: root.path, source: root.source, status: 'incompatible', reason: String(error) }); continue;
      }
      const candidates = folders.filter((item) => item.isDirectory() || item.isSymbolicLink()).sort((a, b) => a.name.localeCompare(b.name, 'en'));
      for (const folder of candidates.slice(0, 200)) {
        const path = join(root.path, folder.name, 'SKILL.md');
        const item: SkillResource = { id: hash(path), path, source: root.source, status: 'incompatible' };
        try {
          const content = await bytes(path, root.anchor);
          Object.assign(item, metadata(content.text), { sha256: content.sha256 });
          item.status = names.has(item.name!) ? 'shadowed' : 'available';
          if (item.status === 'available') names.add(item.name!);
          else item.reason = 'same name is provided by an earlier priority source';
        } catch (error) { item.reason = String(error); }
        skills.push(item);
      }
      if (candidates.length > 200) skills.push({ id: hash(root.path + ':limit'), path: root.path, source: root.source, status: 'incompatible', reason: 'root exceeds 200 skill directories; remaining entries not scanned' });
    }
    return { skills };
  }
  async load(id: string, expectedHash: string) {
    const item = (await this.list()).skills.find((item) => item.id === id);
    if (!item || item.status !== 'available' || item.sha256 !== expectedHash) throw new Error('技能来源已改变或不兼容，请刷新资源目录后重新选择');
    const root = this.roots.find((root) => root.source === item.source && resolve(item.path).startsWith(resolve(root.path) + sep));
    if (!root) throw new Error('技能来源不属于声明目录');
    const content = await bytes(item.path, root.anchor);
    if (content.sha256 !== expectedHash) throw new Error('技能在读取时已改变，未加载');
    return { ...item, content: content.text, status: 'loaded' as const };
  }
}
