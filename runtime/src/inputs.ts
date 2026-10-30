import { createHash, randomUUID } from 'node:crypto';
import { constants } from 'node:fs';
import { lstat, mkdir, open, realpath, rm } from 'node:fs/promises';
import { dirname, join, relative, resolve } from 'node:path';

const MAX_BYTES = 5 * 1024 * 1024;
export type ImportedFile = { id: string; name: string; path: string; size: number; sha256: string; importedAt: string };
export type FixedInput = { fileId: string; name: string; source: string; path: string; size: number; sha256: string; version: number };
export type InputVersion = { id: string; conversationId: string; createdAt: string; inputs: FixedInput[] };
const digest = (bytes: Uint8Array) => createHash('sha256').update(bytes).digest('hex');

/** All paths are host-generated; never accept a file path from a model/client. */
export class ProjectFiles {
  readonly project: string;
  constructor(project: string) { this.project = project; }

  async directory(path: string) {
    let current = this.project;
    for (const part of path.split('/')) {
      current = join(current, part);
      await mkdir(current, { mode: 0o700 }).catch((error: NodeJS.ErrnoException) => { if (error.code !== 'EEXIST') throw error; });
      const info = await lstat(current);
      if (!info.isDirectory() || info.isSymbolicLink()) throw new Error('项目文件目录不是普通目录');
    }
    return current;
  }

  async read(path: string) {
    const target = resolve(this.project, path);
    const actual = await realpath(target);
    if (actual !== target || !relative(this.project, actual) || relative(this.project, actual).startsWith('..')) throw new Error('文件路径已改变或越出项目范围');
    const file = await open(target, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
    try {
      const info = await file.stat();
      if (!info.isFile() || info.size > MAX_BYTES) throw new Error('仅支持不超过 5 MB 的普通文件');
      const buffer = Buffer.alloc(MAX_BYTES + 1);
      let bytesRead = 0;
      while (bytesRead < buffer.length) {
        const chunk = await file.read(buffer, bytesRead, buffer.length - bytesRead, bytesRead);
        if (chunk.bytesRead === 0) break;
        bytesRead += chunk.bytesRead;
      }
      if (bytesRead > MAX_BYTES) throw new Error('文件超过 5 MB');
      if (info.size !== bytesRead || (await file.stat()).mtimeMs !== info.mtimeMs) throw new Error('文件在读取期间发生变化，请重试固定');
      return buffer.subarray(0, bytesRead);
    } finally { await file.close(); }
  }

  async write(path: string, bytes: Uint8Array) {
    await this.directory(relative(this.project, dirname(join(this.project, path))));
    const file = await open(join(this.project, path), 'wx', 0o600);
    try { await file.writeFile(bytes); await file.sync(); }
    finally { await file.close(); }
  }

  async import(name: unknown, encoded: unknown): Promise<ImportedFile> {
    if (typeof name !== 'string' || !name || name.length > 200 || /[\\/\x00-\x1f]/.test(name) || ['.', '..'].includes(name)) throw new Error('文件名称不合法');
    if (typeof encoded !== 'string' || encoded.length > 7 * 1024 * 1024 || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(encoded)) throw new Error('文件内容编码不合法');
    const bytes = Buffer.from(encoded, 'base64');
    if (bytes.length > MAX_BYTES) throw new Error('文件超过 5 MB');
    const id = randomUUID();
    const path = `.silicolab/files/${id}-${name}`;
    await this.write(path, bytes);
    return { id, path, name, size: bytes.length, sha256: digest(bytes), importedAt: new Date().toISOString() };
  }

  async freeze(conversationId: string, selected: ImportedFile[], previous: InputVersion[]): Promise<InputVersion> {
    const id = randomUUID();
    const inputs: FixedInput[] = [];
    const directory = await this.directory(`.silicolab/inputs/${id}`);
    try {
      for (const source of selected) {
        const bytes = await this.read(source.path);
        const path = `.silicolab/inputs/${id}/${source.id}.bin`;
        await this.write(path, bytes);
        const versions = previous.flatMap((inputVersion) => inputVersion.inputs).filter((input) => input.fileId === source.id).map((input) => input.version);
        inputs.push({ fileId: source.id, name: source.name, source: source.path, path, size: bytes.length, sha256: digest(bytes), version: Math.max(0, ...versions) + 1 });
      }
      return { id, conversationId, createdAt: new Date().toISOString(), inputs };
    } catch (error) { await rm(directory, { recursive: true, force: true }); throw error; }
  }

  async fixed(version: InputVersion) {
    return { ...version, inputs: await Promise.all(version.inputs.map(async (input) => {
      const bytes = await this.read(input.path);
      if (digest(bytes) !== input.sha256 || bytes.length !== input.size) throw new Error('固定输入内容完整性校验失败');
      return { ...input, contentBase64: bytes.toString('base64') };
    })) };
  }
}
