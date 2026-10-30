import { randomUUID } from 'node:crypto';

export type TaskDecision = {
  id: string;
  kind: 'terminal_stop' | 'tool_authorization';
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
export function toolDecision(tool: string): TaskDecision {
  return { id: randomUUID(), kind: 'tool_authorization', question: `当前任务未授权 ${tool}。是否仅允许本任务使用该工具？`,
    options: [{ value: 'grant', label: '授权本任务并继续' }, { value: 'decline', label: '不授权，取消此任务' }], status: 'pending' };
}
