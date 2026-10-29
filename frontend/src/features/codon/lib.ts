export const DEFAULT_SPECIES = 'D2P(default)';
export const SPECIES: Record<string, string> = { 'D2P(default)': 'D2P 默认体系', 'Escherichia_coli': '大肠杆菌', 'Chinsese_hamster_ovary(CHO)_cells': '仓鼠卵巢细胞 CHO', 'Pichia_pastoris': '毕赤酵母', 'Saccharomyces_cerevisiae': '酿酒酵母', 'Bacillus_subtilis': '枯草芽孢杆菌', 'Clostridium_acetobutylicum': '丙酮丁醇梭菌', 'Kluyveromyces_lactis': '乳酸克鲁维酵母', 'Pseudomonas_fluorescens': '荧光假单胞菌' };
export const ENZYMES = [{ name: 'EcoRI', motif: 'GAATTC' }, { name: 'BamHI', motif: 'GGATCC' }, { name: 'HindIII', motif: 'AAGCTT' }, { name: 'BsaI', motif: 'GGTCTC' }, { name: 'BsmBI', motif: 'CGTCTC' }, { name: 'NotI', motif: 'GCGGCCGC' }, { name: 'NdeI', motif: 'CATATG' }, { name: 'XhoI', motif: 'CTCGAG' }];
export type Engine = 'remote' | 'local';
export const ENGINE_LABELS: Record<Engine, string> = { remote: 'ProteinFactory 远端', local: '本地实验' };
export type EngineInfo = { id: Engine; label: string; version: string; network_used: boolean; mapping_sha256?: string; model_sha256?: string; code_sha256?: string; constraint_strategy?: string };
export type SeqInput = { name: string; sequence: string };
export type Issue = { name: string; message: string; position?: number };
export type Checks = { translation: boolean; length: boolean; motifs: boolean; stop: boolean; gc: number; bp: number; aa: number; avoid_count: number };
export type SeqRecord = SeqInput & { original_sequence?: string; stop_added?: boolean; id: string; status: string; dna: string | null; checks: Checks | null; error: string | null; response: { log_id?: string } | null; elapsed?: number; attempts: unknown[] };
export type Job = { id: string; name: string; engine?: Engine; engine_info?: EngineInfo; species: string; avoid: string; status: string; created_at: string; updated_at: string; message: string | null; records: SeqRecord[] };
export type JobSummary = Omit<Job, 'records'> & { total: number; completed: number; failed: number; done: number; amino_acids: number };
export type Preset = { id: string; name: string; engine?: Engine; species: string; avoid: string; created_at: string };
export const ACTIVE = ['queued', 'running', 'stopping'];
export const STATUS: Record<string, string> = { pending: '等待中', queued: '排队中', running: '优化中', validating: '校验中', stopping: '正在停止', completed: '已完成', partial: '部分完成', failed: '失败', warning: '需检查', stopped: '已停止', interrupted: '已中断', paused: '已暂停' };
export const DEMO = '>Protein A · interface test\nMKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ\n\n>Protein B · restriction sites\nMEFEFEFKQLEELKKAGVEVEK*';

export function parseInput(text: string, fallback = 'Protein 1'): { records: SeqInput[]; issues: Issue[] } {
  const value = text.replace(/^\uFEFF/, '').trim();
  if (!value) return { records: [], issues: [] };
  const records: SeqInput[] = []; const issues: Issue[] = [];
  if (value.startsWith('>')) {
    let current: SeqInput | null = null;
    for (const line of value.split(/\r?\n/)) {
      if (!line.trim()) continue;
      if (line.startsWith('>')) {
        current = { name: line.slice(1).trim(), sequence: '' }; records.push(current);
      } else if (current) current.sequence += line.replace(/\s/g, '').toUpperCase();
    }
  } else { records.push({ name: fallback.trim() || 'Protein 1', sequence: value.replace(/\s/g, '').toUpperCase() }); }
  if (records.length > 200) issues.push({ name: '批量上限', message: '单次最多提交 200 条序列' });
  records.forEach((record, index) => {
    const name = record.name || `第 ${index + 1} 条`;
    if (!record.name) issues.push({ name, message: '缺少 FASTA 序列名称' });
    else if (record.name.length > 300 || /[\x00-\x1f]/.test(record.name)) issues.push({ name, message: '名称过长或含控制字符' });
    if (!record.sequence) issues.push({ name, message: '序列不能为空' });
    if (record.sequence === '*') issues.push({ name, message: '序列需要包含氨基酸' });
    if (record.sequence.length > 10000) issues.push({ name, message: '序列超过 10,000 字符' });
    const invalid = /[^ACDEFGHIKLMNPQRSTVWY*]/.exec(record.sequence);
    if (invalid) issues.push({ name, message: `第 ${invalid.index + 1} 位的 ${invalid[0]} 不是支持的氨基酸`, position: invalid.index });
    const stop = record.sequence.indexOf('*');
    if (stop >= 0 && stop !== record.sequence.length - 1) issues.push({ name, message: `第 ${stop + 1} 位存在内部终止符`, position: stop });
  });
  return { records, issues };
}

/** Map a normalized residue index back to the original editor character. */
export function sequenceOffset(text: string, recordIndex: number, position: number): number | null {
  const fasta = text.trimStart().startsWith('>');
  let record = fasta ? -1 : 0; let residue = 0;
  for (const match of text.matchAll(/[^\n]*(?:\n|$)/g)) {
    const line = match[0];
    if (fasta && line.trimStart().startsWith('>')) { record++; residue = 0; continue; }
    if (record !== recordIndex) continue;
    for (let char = 0; char < line.length; char++) {
      if (/\s/.test(line[char])) continue;
      if (residue++ === position) return match.index + char;
    }
  }
  return null;
}

export function normalizeMotifs(text: string): string[] {
  const expanded = text.toUpperCase().replace(/\s/g, '').replaceAll('GGT(A/T)ACC', 'GGTAACC,GGTTACC');
  const motifs = [...new Set(expanded.split(/[,，;；]+/).filter(Boolean))];
  if (motifs.some(motif => !/^[ACGT]+$/.test(motif))) throw new Error('位点请填写 A/C/G/T 序列，多个位点用逗号分隔');
  return motifs;
}

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); this.name = 'ApiError'; }
}

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch('/api' + path, { ...options, headers: { 'Content-Type': 'application/json', ...options?.headers } });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const detail = payload.detail;
    throw new ApiError(Array.isArray(detail) ? detail.map((item: { msg: string }) => item.msg).join('；') : detail || `请求失败 (${response.status})`, response.status);
  }
  return response.json();
}

export function formatDate(value: string, full = false) { return new Intl.DateTimeFormat('zh-CN', full ? { month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' } : { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value)); }
export function countAA(sequence: string) { return sequence.replace(/\*$/, '').length; }
