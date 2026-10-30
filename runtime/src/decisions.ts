import { randomUUID } from 'node:crypto';

export type TaskDecision = {
  id: string;
  kind: 'terminal_stop' | 'tool_authorization' | 'external_retry';
  question: string;
  options: { value: string; label: string }[];
  status: 'pending' | 'answered';
  answer?: string;
  answeredAt?: string;
};
export function stopDecision(names: string[]): TaskDecision {
  return { id: randomUUID(), kind: 'terminal_stop',
    question: `${names.length} 条输入没有末尾终止符。仅对本任务选择保留原输入或补充末尾 *？`,
    options: [{ value: 'preserve', label: '保留原输入，不补终止符' }, { value: 'add', label: '为本任务补充末尾 *' }], status: 'pending' };
}
export function retryExternalDecision(): TaskDecision {
  return { id: randomUUID(), kind: 'external_retry', question: '独立作业可能已接受，但无法查询核对。仅在此模拟服务内是否按同一稳定请求身份重试回执？',
    options: [{ value: 'retry_same_identity', label: '明确按同一身份重试模拟回执' }, { value: 'keep_unknown', label: '保留结果未知，不重提' }], status: 'pending' };
}
export function toolDecision(tool: string): TaskDecision {
  return { id: randomUUID(), kind: 'tool_authorization', question: `当前任务未授权 ${tool}。是否仅允许本任务使用该工具？`,
    options: [{ value: 'grant', label: '授权本任务并继续' }, { value: 'decline', label: '不授权，取消此任务' }], status: 'pending' };
}
