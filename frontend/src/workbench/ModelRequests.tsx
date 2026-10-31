import type { ModelRequest } from './conversation';
import './models.css';

function known(value: number | null) { return value === null ? '未知' : String(value); }
export default function ModelRequests({ requests }: { requests: ModelRequest[] }) {
  return <section className="wb-model-requests" aria-label="模型请求来源与用量"><h4>模型请求与用量</h4>{requests.map((request) => <details key={request.id} open={request.status === 'running'}><summary>{request.model} · {request.protocol} · {request.status === 'running' ? '在途（来源已固定）' : request.status === 'completed' ? '已返回' : request.status === 'cancelled' ? '已取消' : request.status === 'interrupted' ? '中断，待恢复' : '请求错误'} · 尝试 {request.attempt}</summary><dl><dt>实际 provider</dt><dd>{request.provider}</dd><dt>实际端点</dt><dd>{request.endpoint || '本机，不联网'}</dd><dt>输入 / 输出 token</dt><dd>{known(request.usage.input)} / {known(request.usage.output)}</dd><dt>缓存读 / 写 token</dt><dd>{known(request.usage.cacheRead)} / {known(request.usage.cacheWrite)}</dd><dt>价格</dt><dd>未知（未配置价格，不以零估算）</dd><dt>请求参数</dt><dd>maxTokens {request.parameters.maxTokens}；{request.parameters.transport}；SDK重试 {request.parameters.maxRetries}</dd><dt>请求身份</dt><dd>{request.id}</dd></dl>{request.error && <p>{request.error}</p>}{request.retryAt && <p>有限退避重试：{request.retryAt}；不重复完成工具。</p>}</details>)}</section>;
}
