import { createHash } from 'node:crypto';
import type { SimulationOptions } from './science.ts';

export type ExternalReceipt = { serviceId: string; requestKey: string; jobId: string; payloadHash: string; state: string; simulated: boolean; result?: { kind: string; requestKey: string; jobId: string; payloadHash: string; payload: string; characters: number } };
export type ExternalJob = { requestKey: string; payloadHash: string; serviceId: string; jobId?: string; state: string; result?: ExternalReceipt['result']; error?: string; submitStartedAt?: string; retryApproved?: boolean };
export class SimulatedJobClient {
  private readonly endpoint: string;
  private readonly serviceId: string;
  constructor() {
    const endpoint = process.env.SILICOLAB_SIMULATED_EXECUTOR;
    const serviceId = process.env.SILICOLAB_SIMULATED_EXECUTOR_ID;
    if (!endpoint || !serviceId) throw new Error('模拟执行器未配置');
    const url = new URL(endpoint);
    if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || !url.port || url.username || url.password || url.pathname !== '/') throw new Error('模拟执行器必须是宿主配置的回环服务');
    this.endpoint = url.origin; this.serviceId = serviceId;
  }
  identity() { return this.serviceId; }
  hash(payload: string) { return createHash('sha256').update(payload).digest('hex'); }
  private async request(path: string, body?: unknown) {
    const response = await fetch(this.endpoint + path, { method: body ? 'POST' : 'GET', signal: AbortSignal.timeout(6000),
      headers: { 'Content-Type': 'application/json' }, ...(body ? { body: JSON.stringify(body) } : {}) });
    if (!response.ok) throw new Error(`模拟作业回执不可确认 (HTTP ${response.status})`);
    return await response.json();
  }
  validate(value: ExternalReceipt, known: ExternalJob) {
    if (value.simulated !== true || value.serviceId !== known.serviceId || value.serviceId !== this.serviceId || value.requestKey !== known.requestKey || value.payloadHash !== known.payloadHash || !value.jobId || !['running', 'succeeded', 'cancelled'].includes(value.state)) throw new Error('模拟作业回执身份或内容不符');
    if (known.jobId && value.jobId !== known.jobId) throw new Error('模拟作业ID发生变化');
    if (value.result && (value.result.jobId !== value.jobId || value.result.requestKey !== value.requestKey || value.result.payloadHash !== value.payloadHash || this.hash(value.result.payload) !== value.payloadHash || [...value.result.payload].length !== value.result.characters)) throw new Error('模拟产物核验失败');
    return value;
  }
  async submit(options: SimulationOptions, known: ExternalJob, retry = false) {
    const receipt = await this.request('/submit', { ...options, requestKey: known.requestKey, ...(retry ? { responseMode: 'normal' } : {}) });
    return this.validate(receipt, known);
  }
  async find(known: ExternalJob) {
    const receipt = await this.request('/find?requestKey=' + encodeURIComponent(known.requestKey));
    if (receipt.serviceId !== known.serviceId || receipt.serviceId !== this.serviceId) throw new Error('模拟服务身份已改变，不能核对');
    return receipt.known ? { known: true as const, receipt: this.validate(receipt, known) } : { known: false as const, reason: String(receipt.reason) };
  }
  async cancel(known: ExternalJob) {
    const receipt = await this.request('/cancel', { requestKey: known.requestKey });
    if (receipt.serviceId !== known.serviceId || receipt.serviceId !== this.serviceId) throw new Error('模拟服务身份已改变');
    return receipt.known ? { known: true as const, receipt: this.validate(receipt, known) } : { known: false as const, reason: String(receipt.reason) };
  }
}
