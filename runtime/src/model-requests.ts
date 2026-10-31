import { createAssistantMessageEventStream } from '@earendil-works/pi-ai/utils/event-stream';
import { setTimeout as delay } from 'node:timers/promises';
import { randomUUID } from 'node:crypto';
import type { ProviderStreams, Model, Api, TranscriptContext, AssistantMessage, SimpleStreamOptions } from '@earendil-works/pi-ai';
import { configuredProvider, type ModelConfiguration, type RequestUsage } from './model-configuration.ts';

export class RequestBoundaryError extends Error {}
export type ModelRequest = {
  id: string; taskId: string; configurationId: string | null; provider: string; protocol: string; endpoint: string | null; model: string;
  status: 'running' | 'completed' | 'error' | 'cancelled' | 'interrupted'; createdAt: string; finishedAt?: string; attempt: number;
  parameters: { maxTokens: number; transport: string; maxRetries: number }; usage: RequestUsage; cost: null;
  error?: string; retryAt?: string;
};
export type RequestBoundary = { taskId: string; configuration: ModelConfiguration | null; history: TranscriptContext['messages'] };
export function requestProvider(boundary: () => Promise<RequestBoundary>, record: (request: ModelRequest) => Promise<void>, local: ProviderStreams): ProviderStreams {
  function stream(_model: Model<Api>, context: TranscriptContext, options?: SimpleStreamOptions) {
    const output = createAssistantMessageEventStream();
    void (async () => {
      let last: AssistantMessage | undefined;
      for (let attempt = 1; attempt <= 3; attempt++) {
        if (options?.signal?.aborted) break;
        const selected = await boundary(); // each actual request consumes the latest conversation choice
        const messages = [...selected.history, ...context.messages];
        const config = selected.configuration;
        const usage: RequestUsage = { input: null, output: null, cacheRead: null, cacheWrite: null };
        const provider = config ? configuredProvider(config, (known) => Object.assign(usage, known)) : undefined;
        const model = provider?.getModels()[0] || _model;
        const request: ModelRequest = { id: randomUUID(), taskId: selected.taskId, configurationId: config?.id || null,
          provider: model.provider, protocol: model.api, endpoint: config?.baseUrl || null, model: model.id, status: 'running',
          attempt, createdAt: new Date().toISOString(), parameters: { maxTokens: model.maxTokens, transport: 'sse', maxRetries: 0 }, usage, cost: null };
        await record(request);
        const events = provider ? provider.streamSimple(model, { ...context, messages }, { ...options, apiKey: config!.apiKey }) : local.streamSimple(model, { ...context, messages }, options);
        for await (const event of events) if (event.type !== 'done' && event.type !== 'error') output.push(event);
        last = await events.result();
        const aborted = options?.signal?.aborted || last.stopReason === 'aborted';
        request.status = aborted ? 'cancelled' : last.stopReason === 'error' ? 'error' : 'completed';
        request.finishedAt = new Date().toISOString();
        if (last.errorMessage) request.error = last.errorMessage;
        const retry = !aborted && last.stopReason === 'error' && /限流|暂时|断流/.test(last.errorMessage || '') && attempt < 3;
        if (retry) request.retryAt = new Date(Date.now() + 100 * 2 ** (attempt - 1)).toISOString();
        await record(request);
        if (!retry) break;
        try { await delay(100 * 2 ** (attempt - 1), undefined, { signal: options?.signal }); }
        catch { break; }
      }
      if (!last) throw new Error('模型请求未生成终态');
      if (options?.signal?.aborted) last = { ...last, stopReason: 'aborted', errorMessage: '用户已取消模型请求' };
      output.push(last.stopReason === 'error' || last.stopReason === 'aborted' ? { type: 'error', reason: last.stopReason, error: last } : { type: 'done', reason: last.stopReason as 'stop' | 'length' | 'toolUse', message: last });
      output.end(last);
    })().catch((failure) => {
      const error: AssistantMessage = { role: 'assistant', content: [], api: _model.api, provider: _model.provider, model: _model.id,
        usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
        stopReason: 'error', errorMessage: failure instanceof RequestBoundaryError ? failure.message : '模型请求或必要历史不可用；已停止，未切换接收方或删除历史', timestamp: Date.now() };
      output.push({ type: 'error', reason: 'error', error }); output.end(error);
    });
    return output;
  }
  return { stream: (m, c, o) => stream(m, c, o as SimpleStreamOptions), streamSimple: stream };
}
