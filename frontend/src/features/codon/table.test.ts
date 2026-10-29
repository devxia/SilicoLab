import { describe, expect, it } from 'vitest';
import { addTerminalStops, columnLabel, inferMapping, mapTable, preferredSheet, type TableSheet } from './table';

describe('table mapping', () => {
  it('recognizes the example columns and ignores unrelated fields', () => {
    const sheet = { name: '基因合成', rows: [['序号', '合成名', '长度', '序列'], ['1', 'CS_BC3_1', '3', 'MKT*']] };
    const mapping = inferMapping(sheet);
    expect(mapping).toEqual({ nameColumn: 1, sequenceColumn: 3, headerRow: 0, startRow: 1 });
    expect(mapTable(sheet, mapping)).toEqual([{ row: 2, record: { name: 'CS_BC3_1', sequence: 'MKT*' }, issues: [] }]);
  });
  it('finds reordered English headings after title rows', () => {
    const sheet = { name: 'Data', rows: [['Order for synthesis'], [], ['notes', 'Protein sequence', 'cost', 'Name'], ['note', ' m k t ', '10', 'test']] };
    const mapping = inferMapping(sheet);
    expect(mapping.headerRow).toBe(2); expect(mapping.nameColumn).toBe(3); expect(mapping.sequenceColumn).toBe(1);
    expect(mapTable(sheet, mapping)[0].record.sequence).toBe('MKT');
  });
  it('handles headerless data without dropping the first sequence', () => {
    const sheet = { name: 'Data', rows: [['1', 'Alpha-1', ' MKT* '], ['2', 'Beta-2', 'MEF']] };
    const mapping = inferMapping(sheet);
    expect(mapping.headerRow).toBeNull(); expect(mapping.startRow).toBe(0);
    expect(mapping.nameColumn).toBe(1); expect(mapping.sequenceColumn).toBe(2);
    expect(mapTable(sheet, mapping)).toHaveLength(2);
  });
  it('allows manual column mapping, late data start and no headers', () => {
    const sheet = { name: 'Sheet', rows: [['title'], ['MKT', '', '2', 'alpha'], ['MEF*', '', '3', 'beta']] };
    expect(mapTable(sheet, { nameColumn: 3, sequenceColumn: 0, headerRow: null, startRow: 1 }).map(row => row.record)).toEqual([{ name: 'alpha', sequence: 'MKT' }, { name: 'beta', sequence: 'MEF*' }]);
  });
  it('skips only rows with both selected columns empty and retains every other issue', () => {
    const sheet: TableSheet = { name: 'Sheet', rows: [['name', 'seq'], ['valid', 'MKT'], ['', '', 'metadata only'], ['missing', ''], ['', 'MK'], ['bad', 'MKX'], ['stop', 'MK*L'], ['lone-stop', '*']] };
    const mapped = mapTable(sheet, inferMapping(sheet));
    expect(mapped).toHaveLength(6); expect(mapped[0].issues).toEqual([]);
    expect(mapped.slice(1).every(row => row.issues.length > 0)).toBe(true);
    expect(mapped[1].row).toBe(4);
  });
  it('rejects a newline in synthesis name before creating FASTA', () => {
    expect(mapTable({ name: 's', rows: [['name', 'seq'], ['one\ntwo', 'MK']] }, { nameColumn: 0, sequenceColumn: 1, headerRow: 0, startRow: 1 })[0].issues).toContain('名称不能包含换行');
  });
  it('selects a sheet with recognizable sequence data rather than a cover sheet', () => {
    expect(preferredSheet({ filename: 'a.xlsx', sheets: [{ name: '封面', rows: [['说明']] }, { name: '序列', rows: [['合成名', '蛋白序列'], ['a', 'MKT*']] }] })).toBe(1);
  });
  it('formats columns beyond Z', () => { expect(columnLabel(0)).toBe('A'); expect(columnLabel(25)).toBe('Z'); expect(columnLabel(26)).toBe('AA'); expect(columnLabel(99)).toBe('CV'); });
});
describe('terminal stops', () => {
  it('adds exactly one terminal stop only to records lacking one and keeps originals intact', () => {
    const records = [{ name: 'a', sequence: 'MKT*' }, { name: 'b', sequence: 'MEF' }];
    const updated = addTerminalStops(records);
    expect(updated.map(row => row.sequence)).toEqual(['MKT*', 'MEF*']);
    expect(records[1].sequence).toBe('MEF'); expect(addTerminalStops(updated)).toEqual(updated);
  });
});
