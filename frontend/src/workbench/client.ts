import type { ResearchTask } from './conversation';
export type Conversation = { id: string; title: string; draft: string; revision: number; modelConfigurationId?: string };
export type ProjectIndex = { id: string; name: string; path: string };
export type ImportedFile = { id: string; name: string; path: string; size: number; sha256: string; importedAt: string };
export type FixedInput = { fileId: string; name: string; source: string; path: string; size: number; sha256: string; version: number; contentBase64?: string };
export type InputVersion = { id: string; conversationId: string; createdAt: string; inputs: FixedInput[] };
export type Project = ProjectIndex & { availability?: { status: string; reason?: string; progressSaved: boolean }; conversations: Conversation[]; files: ImportedFile[]; inputVersions: InputVersion[]; tasks: ResearchTask[]; scheduling: string; modelRequests: number };

export async function request<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(`/api/workbench${path}`, {
    method, headers: { 'Content-Type': 'application/json' },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '操作未完成，请检查输入后重试');
  return data;
}
