import { parseInput, type SeqInput } from './lib';

export type TableSheet = { name: string; rows: string[][] };
export type TableFile = { filename: string; sheets: TableSheet[] };
export type Mapping = { nameColumn: number; sequenceColumn: number; headerRow: number | null; startRow: number };
export type MappedRow = { row: number; record: SeqInput; issues: string[] };
const nameHeaders = /^(合成名|合成名称|名称|名字|序列名|序列名称|基因名|蛋白名|蛋白名称|name|id|gene|protein[ _-]?name|sequence[ _-]?name|synthesis[ _-]?name)$/i;
const sequenceHeaders = /^(序列|蛋白序列|蛋白质序列|氨基酸序列|sequence|seq|protein[ _-]?sequence|amino[ _-]?acid[ _-]?sequence|aa[ _-]?(sequence|seq)?)$/i;
const compact = (value: string) => value.trim().replace(/[\s:：]/g, '');
const proteinLike = (value: string) => /^[ACDEFGHIKLMNPQRSTVWY]+\*?$/.test(value.replace(/\s/g, '').toUpperCase());

export function columnLabel(index: number): string {
  let n = index + 1, label = '';
  while (n > 0) { n--; label = String.fromCharCode(65 + n % 26) + label; n = Math.floor(n / 26); }
  return label;
}

export function inferMapping(sheet: TableSheet): Mapping {
  const rows = sheet.rows;
  for (let row = 0; row < Math.min(rows.length, 30); row++) {
    const names = rows[row].map(compact);
    const nameColumn = names.findIndex(value => nameHeaders.test(value));
    const sequenceColumn = names.findIndex(value => sequenceHeaders.test(value));
    if (nameColumn >= 0 && sequenceColumn >= 0 && nameColumn !== sequenceColumn) return { nameColumn, sequenceColumn, headerRow: row, startRow: row + 1 };
  }
  const width = Math.max(0, ...rows.map(row => row.length));
  let sequenceColumn = 0, score = -1;
  for (let column = 0; column < width; column++) {
    const values = rows.slice(0, 60).map(row => row[column]?.trim() || '').filter(Boolean);
    const proteins = values.filter(proteinLike);
    const columnScore = values.length ? proteins.reduce((total, value) => total + value.length, 0) / values.length * (proteins.length / values.length) : 0;
    if (columnScore > score) { sequenceColumn = column; score = columnScore; }
  }
  let nameColumn = rows.slice(0, 60).reduce<number>((candidate, row) => candidate >= 0 ? candidate : row.findIndex((value, column) => column !== sequenceColumn && !!value.trim() && !/^\d+(\.\d+)?$/.test(value.trim())), -1);
  if (nameColumn < 0) nameColumn = sequenceColumn === 0 ? 1 : 0;
  // A recognized standalone header still helps even if the other heading is unfamiliar.
  const first = rows[0] || [];
  const namedHeader = first.findIndex(value => nameHeaders.test(compact(value)));
  const seqHeader = first.findIndex(value => sequenceHeaders.test(compact(value)));
  const hasHeader = namedHeader >= 0 || seqHeader >= 0;
  if (namedHeader >= 0) nameColumn = namedHeader;
  if (seqHeader >= 0) sequenceColumn = seqHeader;
  return { nameColumn, sequenceColumn, headerRow: hasHeader ? 0 : null, startRow: hasHeader ? 1 : 0 };
}

export function preferredSheet(file: TableFile): number {
  let best = 0, bestScore = -1;
  file.sheets.forEach((sheet, index) => {
    const mapping = inferMapping(sheet);
    const score = (mapping.headerRow !== null ? 10000 : 0) + sheet.rows.slice(mapping.startRow, mapping.startRow + 100).filter(row => proteinLike(row[mapping.sequenceColumn] || '')).length;
    if (score > bestScore) { best = index; bestScore = score; }
  });
  return best;
}

export function mapTable(sheet: TableSheet, mapping: Mapping): MappedRow[] {
  return sheet.rows.flatMap((row, index) => {
    if (index < mapping.startRow || index === mapping.headerRow) return [];
    const name = (row[mapping.nameColumn] || '').trim();
    const sequence = (row[mapping.sequenceColumn] || '').replace(/\s/g, '').toUpperCase();
    if (!name && !sequence) return [];
    const issues: string[] = [];
    if (!name) issues.push('名称为空');
    if (!sequence) issues.push('蛋白序列为空');
    if (/[\r\n]/.test(name)) issues.push('名称不能包含换行');
    if (name && sequence) issues.push(...parseInput(`>${name}\n${sequence}`).issues.map(issue => issue.message));
    return [{ row: index + 1, record: { name, sequence }, issues }];
  });
}

export function addTerminalStops(records: SeqInput[]): SeqInput[] {
  return records.map(record => ({ ...record, sequence: record.sequence.endsWith('*') ? record.sequence : record.sequence + '*' }));
}
