import { Socket } from 'node:net';
import { createInterface } from 'node:readline';
import { randomUUID } from 'node:crypto';
import { createProvider, type Provider } from '@earendil-works/pi-ai/models';
import { createAssistantMessageEventStream } from '@earendil-works/pi-ai/utils/event-stream';
import { openAIResponsesApi } from '@earendil-works/pi-ai/api/openai-responses.lazy';
import { anthropicMessagesApi } from '@earendil-works/pi-ai/api/anthropic-messages.lazy';
import type { ProviderStreams, Model, Api, AssistantMessageEvent, SimpleStreamOptions, ApiStreamOptions, TranscriptContext } from '@earendil-works/pi-ai';

export type ModelConfiguration = { id: string; name: string; protocol: 'openai-responses' | 'anthropic-messages'; baseUrl: string; modelId: string; apiKey: string };
let channel: Socket | undefined;
const waiting = new Map<string, { resolve: (config: ModelConfiguration) => void; reject: (error: Error) => void; timer: ReturnType<typeof setTimeout> }>();
export function resolveModel(configurationId: string): Promise<ModelConfiguration> {
  if (!channel) {
    const fd = Number(process.env.SILICOLAB_MODEL_FD);
    if (!Number.isInteger(fd) || fd < 0) throw new Error('SilicoLab 模型凭据通道未配置');
    channel = new Socket({ fd, readable: true, writable: true });
    const input = createInterface({ input: channel });
    input.on('line', (line) => {
      try {
        const message = JSON.parse(line);
        const job = waiting.get(message.id);
        if (!job) return;
        waiting.delete(message.id); clearTimeout(job.timer);
        if (message.error) job.reject(new Error('所选模型凭据不可用；请检查设置，未切换接收方'));
        else job.resolve(message.result);
      } catch { channel!.destroy(); }
    });
    const failed = () => { for (const job of waiting.values()) { clearTimeout(job.timer); job.reject(new Error('模型凭据通道已关闭')); } waiting.clear(); };
    channel.on('error', failed);
    channel.on('close', () => { input.close(); failed(); });
    channel.unref();
  }
  const socket = channel;
  const id = randomUUID();
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { waiting.delete(id); reject(new Error('模型凭据读取超时；未切换接收方')); }, 10000);
    waiting.set(id, { resolve, reject, timer });
    socket.write(JSON.stringify({ id, configurationId }) + '\n');
  });
}
export function closeModels() { channel?.end(); }

/** Only these protocol adapters dispatch; base URL never guesses a protocol. */
export type RequestUsage = { input: number | null; output: number | null; cacheRead: number | null; cacheWrite: number | null };
export function configuredProvider(config: ModelConfiguration, observeUsage?: (usage: Partial<RequestUsage>) => void): Provider {
  const providerId = `silicolab-${config.id}`;
  const api = config.protocol;
  const adapter = api === 'openai-responses' ? openAIResponsesApi() : api === 'anthropic-messages' ? anthropicMessagesApi() : undefined;
  if (!adapter) throw new Error('所选模型协议不支持');
  const model: Model<Api> = { id: config.modelId, name: config.name, provider: providerId, api, baseUrl: config.baseUrl,
    reasoning: false, input: ['text'], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 128000, maxTokens: 4096 };
  const endpoint = new URL(config.baseUrl);
  const safeFetch: typeof fetch = (input, options) => {
    const url = new URL(input instanceof Request ? input.url : String(input));
    if (url.origin !== endpoint.origin || !(url.pathname === endpoint.pathname || url.pathname.startsWith(endpoint.pathname.replace(/\/$/, '') + '/'))) throw new Error('模型接收方与所选端点不符');
    return fetch(input, { ...options, redirect: 'error' });
  };
  function failureMessage(value: unknown, sawProtocolEvent: boolean) {
    const message = String(value);
    if (/401|403|authentication_error|invalid_api_key/i.test(message)) return '所选模型凭据无效（401/403）；请更新 API key，未自动切换接收方';
    if (/429|rate_limit|too many requests/i.test(message)) return '模型限流（429）；未自动切换接收方';
    if (/500|502|503|504|overloaded|service unavailable/i.test(message)) return '模型服务暂时不可用（503）；未自动切换接收方';
    if (/stream ended before|terminal response|message_stop/i.test(message)) return sawProtocolEvent ? '模型断流：响应不完整；未自动切换接收方' : '所选端点协议不兼容；未自动切换接收方';
    if (/terminated|socket|UND_ERR|timeout|timed out|ECONNRESET|ECONNREFUSED|connection error|fetch failed/i.test(message)) return '模型暂时网络错误；未自动切换接收方';
    if (/invalid json|unexpected token|parse|protocol/i.test(message)) return '所选端点协议不兼容或响应不完整；请核对协议，未自动切换接收方';
    return '所选模型调用失败：网络不可用或协议不兼容；未自动切换接收方';
  }
  function clean(value: unknown): unknown {
    if (typeof value === 'string') return value.split(config.apiKey).join('[REDACTED]');
    if (Array.isArray(value)) return value.map(clean);
    if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key, item]) => [key.split(config.apiKey).join('[REDACTED]'), clean(item)]));
    return value;
  }
  function stream(method: 'stream' | 'streamSimple', requested: Model<Api>, context: TranscriptContext, options?: SimpleStreamOptions | ApiStreamOptions<Api>) {
    const output = createAssistantMessageEventStream();
    void (async () => {
      let sawProtocolEvent = false;
      try {
        const onProviderStreamEvent = (event: unknown) => {
          const raw = event as { type?: string; response?: { usage?: Record<string, unknown> }; message?: { usage?: Record<string, unknown> }; usage?: Record<string, unknown> };
          if (raw.type === 'response.created' || raw.type === 'message_start') sawProtocolEvent = true;
          const usage = raw.response?.usage || raw.message?.usage || raw.usage;
          if (!usage) return;
          const known: Partial<RequestUsage> = {};
          for (const [field, source] of [['input', 'input_tokens'], ['output', 'output_tokens'], ['cacheRead', 'cache_read_input_tokens'], ['cacheWrite', 'cache_creation_input_tokens']] as const) {
            if (typeof usage[source] === 'number') known[field] = usage[source] as number;
          }
          const details = usage.input_tokens_details as { cached_tokens?: number } | undefined;
          if (typeof details?.cached_tokens === 'number') known.cacheRead = details.cached_tokens;
          observeUsage?.(known);
        };
        const safeOptions = { ...options, fetch: safeFetch, maxRetries: 0, timeoutMs: 30000, transport: 'sse' as const, onProviderStreamEvent, onPayload: undefined, onResponse: undefined };
        const events = method === 'streamSimple'
          ? adapter!.streamSimple(requested, context, safeOptions as SimpleStreamOptions)
          : adapter!.stream(requested, context, safeOptions);
        for await (const event of events) {
          const sanitized = clean(event) as AssistantMessageEvent;
          if (sanitized.type === 'error' && event.type === 'error') sanitized.error.errorMessage = failureMessage(event.error.errorMessage, sawProtocolEvent);
          output.push(sanitized);
        }
        output.end(clean(await events.result()) as Awaited<ReturnType<typeof events.result>>);
      } catch {
        const error = { role: 'assistant' as const, content: [], api, provider: providerId, model: config.modelId,
          usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
          stopReason: 'error' as const, errorMessage: '所选模型调用失败：凭据、网络或协议不兼容；未自动切换接收方', timestamp: Date.now() };
        output.push({ type: 'error', reason: 'error', error }); output.end(error);
      }
    })();
    return output;
  }
  const streams: ProviderStreams = { stream: (m, c, o) => stream('stream', m, c, o), streamSimple: (m, c, o) => stream('streamSimple', m, c, o) };
  return createProvider({ id: providerId, name: config.name, models: [model], baseUrl: config.baseUrl,
    auth: { apiKey: { name: 'SilicoLab Keychain', resolve: async () => ({ auth: { apiKey: config.apiKey }, source: 'SilicoLab Keychain' }) } }, api: streams });
}
