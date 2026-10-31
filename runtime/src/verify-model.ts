import { createModels } from '@earendil-works/pi-ai/models';
import { configuredProvider, type ModelConfiguration } from './model-configuration.ts';

let raw = '';
for await (const chunk of process.stdin) {
  raw += chunk;
  if (raw.length > 32768) throw new Error('模型检查请求过大');
}
try {
  const configuration = JSON.parse(raw) as ModelConfiguration;
  const models = createModels({ authContext: { env: async () => undefined, fileExists: async () => false } });
  const provider = configuredProvider(configuration);
  models.setProvider(provider);
  const model = models.getModel(provider.id, configuration.modelId)!;
  const result = await models.completeSimple(model, { messages: [{ role: 'user', content: 'SilicoLab connection check with artificial text only. Reply OK.', timestamp: Date.now() }] }, { maxTokens: 128 });
  if (result.stopReason === 'error' || result.stopReason === 'aborted' || !result.content.length) throw new Error('invalid model response');
  console.log(JSON.stringify({ ok: true, protocol: configuration.protocol }));
} catch {
  console.log(JSON.stringify({ ok: false, error: '模型检查失败：凭据无效、网络不可用或协议不兼容；未切换接收方' }));
}
