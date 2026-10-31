import type { JsonObject } from '@earendil-works/pi-durable';
import { Socket } from 'node:net';
import { createInterface } from 'node:readline';
import { randomUUID } from 'node:crypto';

export type ScienceParameters = { stopPolicy: 'preserve' | 'add' | 'ask'; avoid: string };
export type SimulationOptions = { payload: string; durationMs: number; queryable: boolean; responseMode: 'normal' | 'lost' | 'hold_after_accept' };
export type ScienceOptions = { executionContract?: string; modelConfigurationId?: string; workflow?: 'validation' | 'd2p_local' | 'simulated_external' | 'protein_factory_remote' | 'python_analysis' | 'mcp_tool'; mcp?: JsonObject; mcpTool?: string; mcpArguments?: JsonObject; simulation?: SimulationOptions; specialtyAcknowledged?: boolean; inputVersionId?: string; parameters?: ScienceParameters };
export type ScienceRecord = { name: string; protein: string; status: string; dna?: string; error?: string; checks?: Record<string, boolean> };
export type ScienceResult = { status: string; inputVersionId: string; engine_info: Record<string, string | number | boolean>; records: ScienceRecord[]; network_attempts: number | null; network_guard_self_test?: string; scope: string; missingStopNames?: string[] };
export type ScienceResponse = { ok: boolean; error?: string; result: ScienceResult; files: { name: string; mediaType: string; contentBase64: string }[] };
export class ScienceFailure extends Error {
  readonly requestMayHaveExecuted?: boolean;
  constructor(message: string, requestMayHaveExecuted?: boolean) { super(message); this.requestMayHaveExecuted = requestMayHaveExecuted; }
}
type Pending = { resolve: (value: ScienceResponse) => void; reject: (error: Error) => void; started: (pid: number) => Promise<void>; failure?: Error; cleanup: () => void };
let channel: Socket | undefined;
const pending = new Map<string, Pending>();
function connection() {
  if (channel) return channel;
  const fd = Number(process.env.SILICOLAB_SCIENCE_FD);
  if (!Number.isInteger(fd) || fd < 0) throw new Error('科学执行监督器未配置');
  channel = new Socket({ fd, readable: true, writable: true });
  const incoming = createInterface({ input: channel });
  incoming.on('line', (line) => {
    try {
      const message = JSON.parse(line);
      const job = pending.get(message.id);
      if (!job) return;
      if (message.event === 'started') {
        void job.started(message.pid).catch((error) => { job.failure = error; channel!.write(JSON.stringify({ id: message.id, op: 'cancel' }) + '\n'); });
      } else if (message.event === 'finished') {
        pending.delete(message.id); job.cleanup();
        if (job.failure || message.error || !message.response?.ok) job.reject(job.failure || new ScienceFailure(message.error || message.response?.error || '科学工具未完成', message.response?.requestMayHaveExecuted));
        else if (!Array.isArray(message.response.result?.records) || !Array.isArray(message.response.files)) job.reject(new Error('科学响应协议不完整'));
        else job.resolve(message.response);
      }
    } catch { channel!.destroy(new Error('科学监督器响应无效')); }
  });
  const failed = (error: Error) => {
    for (const job of pending.values()) { job.cleanup(); job.reject(error); }
    pending.clear();
  };
  channel.on('error', failed);
  channel.on('close', () => { incoming.close(); failed(new Error('科学监督连接已关闭')); });
  channel.unref();
  return channel;
}

/** The application-owned supervisor reaps scientific children even if Node dies. */
export async function runScience(request: unknown, signal: AbortSignal | undefined, started: (pid: number) => Promise<void>): Promise<ScienceResponse> {
  if (signal?.aborted) throw new Error('科学任务已取消');
  const socket = connection();
  const id = randomUUID();
  return new Promise((resolve, reject) => {
    const cancel = () => { const job = pending.get(id); if (job) { job.failure = new Error('科学任务已停止'); socket.write(JSON.stringify({ id, op: 'cancel' }) + '\n'); } };
    const timer = setTimeout(cancel, (request as ScienceOptions)?.workflow === 'protein_factory_remote' ? 300000 : 60000);
    signal?.addEventListener('abort', cancel, { once: true });
    pending.set(id, { resolve, reject, started, cleanup: () => { clearTimeout(timer); signal?.removeEventListener('abort', cancel); } });
    socket.write(JSON.stringify({ id, op: 'start', request }) + '\n');
  });
}
export function closeScience() { channel?.end(); }
