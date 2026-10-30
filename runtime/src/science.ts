import { spawn } from 'node:child_process';

export type ScienceParameters = { stopPolicy: 'preserve' | 'add' | 'ask'; avoid: string };
export type ScienceOptions = { workflow?: 'validation' | 'd2p_local'; specialtyAcknowledged?: boolean; inputVersionId?: string; parameters?: ScienceParameters };
export type ScienceRecord = { name: string; protein: string; status: string; dna?: string; error?: string; checks?: Record<string, boolean> };
export type ScienceResult = { status: string; inputVersionId: string; engine_info: Record<string, string | number | boolean>; records: ScienceRecord[]; network_attempts: number; network_guard_self_test: string; scope: string; missingStopNames?: string[] };
export type ScienceResponse = { ok: boolean; error?: string; result: ScienceResult; files: { name: string; mediaType: string; contentBase64: string }[] };

/** Spawn only the trusted packaged scientific entry, never model-authored Python. */
export async function runScience(request: unknown, signal: AbortSignal | undefined, started: (pid: number) => Promise<void>): Promise<ScienceResponse> {
  const python = process.env.SILICOLAB_PYTHON;
  const backend = process.env.SILICOLAB_BACKEND;
  if (!python || !backend) throw new Error('科学 Python 运行时未配置');
  if (signal?.aborted) throw new Error('科学任务已取消');
  const child = spawn(python, ['-I', '-B', '-c', 'import sys;sys.path.insert(0,sys.argv[1]);from silicolab.science_worker import main;main()', backend], {
    env: { PATH: '/usr/bin:/bin', LANG: 'en_US.UTF-8' }, stdio: ['pipe', 'pipe', 'pipe'],
  });
  let stdout = '', stderr = '';
  return await new Promise<ScienceResponse>((resolve, reject) => {
    let failure: Error | undefined;
    const abort = () => { failure = new Error('科学任务已取消'); child.kill('SIGKILL'); };
    const timeout = setTimeout(() => { failure = new Error('科学工具执行超时'); child.kill('SIGKILL'); }, 60000);
    signal?.addEventListener('abort', abort, { once: true });
    child.on('error', (error) => { failure = error; });
    child.stdin.on('error', (error) => { if (!failure) failure = error; });
    child.stdout.on('data', (chunk) => {
      stdout += chunk;
      if (Buffer.byteLength(stdout) > 16 * 1024 * 1024) { failure = new Error('科学输出超过协议上限'); child.kill('SIGKILL'); }
    });
    child.stderr.on('data', (chunk) => { stderr = (stderr + chunk).slice(-8000); });
    child.on('close', (code) => {
      clearTimeout(timeout); signal?.removeEventListener('abort', abort);
      if (failure) { reject(failure); return; }
      if (code !== 0) { reject(new Error(`科学进程失败 (${code}): ${stderr}`)); return; }
      try {
        const response = JSON.parse(stdout) as ScienceResponse;
        if (!response.ok) throw new Error(response.error || '科学工具未完成');
        if (!Array.isArray(response.result.records) || !Array.isArray(response.files)) throw new Error('科学响应协议不完整');
        resolve(response);
      } catch (error) { reject(error); }
    });
    if (child.pid) void started(child.pid).then(() => child.stdin.end(JSON.stringify(request))).catch((error) => { failure = error; child.kill('SIGKILL'); });
  });
}
