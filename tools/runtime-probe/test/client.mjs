import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';

const worker = fileURLToPath(new URL('../src/worker.ts', import.meta.url));
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export async function temporary(t) {
  const directory = await mkdtemp(join(tmpdir(), 'silicolab-runtime-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  return directory;
}

export async function open(t, directory) {
  // Only the executable and OS basics are inherited; no model/agent authentication.
  const child = spawn(process.execPath, [worker, directory], {
    env: { PATH: process.env.PATH, TMPDIR: tmpdir(), LANG: 'en_US.UTF-8' },
    stdio: ['pipe', 'pipe', 'pipe'],
  });
  let stderr = '';
  child.stderr.on('data', (data) => { stderr += data; });
  let next = 0;
  const pending = new Map();
  let resolveReady;
  let rejectReady;
  const ready = new Promise((resolve, reject) => { resolveReady = resolve; rejectReady = reject; });
  const lines = createInterface({ input: child.stdout });
  lines.on('line', (line) => {
    try {
      const response = JSON.parse(line);
      if (response.ready) resolveReady(response);
      else {
        const request = pending.get(response.id);
        if (!request) return;
        pending.delete(response.id);
        if (response.error) request.reject(new Error(response.error));
        else request.resolve(response.result);
      }
    } catch (error) { rejectReady(error); }
  });
  const exited = once(child, 'exit');
  child.on('error', rejectReady);
  child.on('exit', (code, signal) => {
    const error = new Error(`probe exited ${code ?? signal}: ${stderr}`);
    rejectReady(error);
    for (const request of pending.values()) request.reject(error);
    pending.clear();
    lines.close();
  });
  t.after(async () => {
    if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
    await exited;
  });
  const startupTimer = setTimeout(() => { child.kill('SIGKILL'); }, 10_000);
  try { await ready; } finally { clearTimeout(startupTimer); }
  return {
    async call(op, args = {}) {
      const id = ++next;
      let timer;
      try {
        return await new Promise((resolve, reject) => {
          timer = setTimeout(() => { pending.delete(id); reject(new Error(`timeout: ${op}; ${stderr}`)); }, 8_000);
          pending.set(id, { resolve, reject });
          child.stdin.write(`${JSON.stringify({ id, op, ...args })}\n`);
        });
      } finally { clearTimeout(timer); }
    },
    async stop(signal) {
      if (signal) child.kill(signal);
      else await this.call('close');
      return await exited;
    },
  };
}

export async function until(client, predicate) {
  const deadline = Date.now() + 8_000;
  let status;
  do {
    status = await client.call('status');
    if (predicate(status)) return status;
    await delay(15);
  } while (Date.now() < deadline);
  assert.fail(`status condition not reached: ${JSON.stringify(status)}`);
}

export { delay };
