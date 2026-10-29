import { describe, expect, it } from 'vitest';
import { normalizeMotifs, parseInput, sequenceOffset } from './lib';

describe('protein input', () => {
  it('accepts plain protein with whitespace and a terminal stop', () => { expect(parseInput(' m k\nT* ', 'sample')).toEqual({ records: [{ name: 'sample', sequence: 'MKT*' }], issues: [] }); });
  it('parses multiline multi FASTA including BOM', () => { expect(parseInput('\uFEFF>one\nmk\nt\n>two\nMEF*').records).toEqual([{ name: 'one', sequence: 'MKT' }, { name: 'two', sequence: 'MEF*' }]); });
  it('keeps invalid characters and locates the error instead of silently removing them', () => { const result = parseInput('MKX'); expect(result.records[0].sequence).toBe('MKX'); expect(result.issues[0].position).toBe(2); });
  it('rejects empty FASTA records, missing names, internal stops and stop-only input', () => { for (const input of ['>one', '>\nMK', 'MK*L', '*']) expect(parseInput(input).issues.length).toBeGreaterThan(0); });
  it('enforces maximum sequence and batch size', () => { expect(parseInput('M'.repeat(10001)).issues.length).toBe(1); expect(parseInput(Array.from({ length: 201 }, (_, i) => `>${i}\nMK`).join('\n')).issues.length).toBe(1); });
});
describe('error selection', () => {
  it('maps residues through multiline FASTA and whitespace', () => { const text = '>one\r\nM K\r\n>two\r\nME\r\n FX'; const offset = sequenceOffset(text, 1, 3); expect(offset).not.toBeNull(); expect(text[offset!]).toBe('X'); });
  it('maps plain input and safely rejects nonexistent positions', () => { expect(sequenceOffset(' m k x ', 0, 2)).toBe(5); expect(sequenceOffset('MK', 0, 8)).toBeNull(); });
});
describe('avoid motifs', () => {
  it('normalizes, expands the webpage special motif and deduplicates', () => { expect(normalizeMotifs('gaattc，GGT(A/T)ACC; GAATTC')).toEqual(['GAATTC', 'GGTAACC', 'GGTTACC']); });
  it('rejects enzyme names and ambiguous motifs', () => { expect(() => normalizeMotifs('EcoRI')).toThrow(); expect(() => normalizeMotifs('GCN')).toThrow(); });
});
