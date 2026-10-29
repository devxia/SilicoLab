import { useMemo, useState } from 'react';
import { Check, CircleAlert, FileSpreadsheet, Info } from 'lucide-react';
import { columnLabel, inferMapping, mapTable, preferredSheet, type Mapping, type TableFile } from './table';
import type { SeqInput } from './lib';

export default function TableImport({ file, onImport, onCancel }: { file: TableFile; onImport: (records: SeqInput[]) => void; onCancel: () => void }) {
  const [sheetIndex, setSheetIndex] = useState(() => preferredSheet(file));
  const [mapping, setMapping] = useState<Mapping>(() => inferMapping(file.sheets[preferredSheet(file)]));
  const [skipInvalid, setSkipInvalid] = useState(false);
  const sheet = file.sheets[sheetIndex];
  const mapped = useMemo(() => mapTable(sheet, mapping), [sheet, mapping]);
  const invalid = mapped.filter(row => row.issues.length);
  const valid = mapped.filter(row => !row.issues.length);
  const columns = Math.max(2, ...sheet.rows.map(row => row.length));
  const preview = sheet.rows.slice(Math.max(0, mapping.startRow - 2), Math.max(0, mapping.startRow - 2) + 8);
  const missingStops = valid.filter(row => !row.record.sequence.endsWith('*')).length;
  const selectedRows = skipInvalid ? valid : mapped;
  const canImport = mapping.nameColumn !== mapping.sequenceColumn && selectedRows.length > 0 && selectedRows.length <= 200 && (!invalid.length || skipInvalid);
  function columnName(column: number) {
    const header = mapping.headerRow !== null ? sheet.rows[mapping.headerRow]?.[column] : '';
    const example = sheet.rows[mapping.startRow]?.[column] || '';
    return `${columnLabel(column)} 列${header ? ` · ${header.slice(0, 24)}` : example ? ` · ${example.slice(0, 24)}` : ''}`;
  }
  return <div className="table-import">
    <p className="modal-description table-file-description"><FileSpreadsheet size={17} /><span>{file.filename}</span></p>
    <div className="mapping-controls">
      <label>工作表<select aria-label="工作表" value={sheetIndex} onChange={event => { const index = Number(event.target.value); setSheetIndex(index); setMapping(inferMapping(file.sheets[index])); setSkipInvalid(false); }}>{file.sheets.map((item, index) => <option value={index} key={index}>{item.name}（{item.rows.length} 行）</option>)}</select></label>
      <label>表头<select aria-label="表头" value={mapping.headerRow === null ? 'none' : mapping.headerRow} onChange={event => { const headerRow = event.target.value === 'none' ? null : Number(event.target.value); setMapping(current => ({ ...current, headerRow, startRow: headerRow === null ? 0 : headerRow + 1 })); }}><option value="none">没有表头</option>{sheet.rows.slice(0, 30).map((_, index) => <option key={index} value={index}>第 {index + 1} 行是表头</option>)}</select></label>
      <label>数据起始行<input aria-label="数据起始行" type="number" min={1} max={Math.max(1, sheet.rows.length)} value={mapping.startRow + 1} onChange={event => setMapping(current => ({ ...current, startRow: Math.max(0, Math.min(sheet.rows.length - 1, Number(event.target.value) - 1)) }))} /></label>
      <label>名称列<select aria-label="名称列" value={mapping.nameColumn} onChange={event => setMapping(current => ({ ...current, nameColumn: Number(event.target.value) }))}>{Array.from({ length: columns }, (_, column) => <option key={column} value={column}>{columnName(column)}</option>)}</select></label>
      <label>蛋白序列列<select aria-label="蛋白序列列" value={mapping.sequenceColumn} onChange={event => setMapping(current => ({ ...current, sequenceColumn: Number(event.target.value) }))}>{Array.from({ length: columns }, (_, column) => <option key={column} value={column}>{columnName(column)}</option>)}</select></label>
    </div>
    <div className="table-preview-wrap"><table className="table-preview"><thead><tr><th>行</th>{Array.from({ length: columns }, (_, column) => <th key={column} className={column === mapping.nameColumn ? 'name-column' : column === mapping.sequenceColumn ? 'protein-column' : ''}>{columnLabel(column)} {column === mapping.nameColumn ? '· 名称' : column === mapping.sequenceColumn ? '· 蛋白序列' : ''}</th>)}</tr></thead><tbody>{preview.map((row, index) => { const rowIndex = Math.max(0, mapping.startRow - 2) + index; return <tr key={rowIndex} className={rowIndex === mapping.headerRow ? 'header-preview-row' : rowIndex < mapping.startRow ? 'ignored-row' : ''}><th>{rowIndex + 1}</th>{Array.from({ length: columns }, (_, column) => <td title={row[column] || ''} className={column === mapping.nameColumn ? 'name-column' : column === mapping.sequenceColumn ? 'protein-column' : ''} key={column}>{(row[column] || '').slice(0, 160)}</td>)}</tr>; })}</tbody></table></div>
    <p className="table-preview-caption">预览仅显示附近 8 行；将读取所选起始行之后的全部数据。两列均为空的行会跳过，其余缺值或非法序列会明确提示。</p>
    <div className="mapping-summary"><span><Check size={14} />{valid.length} 条有效序列</span>{invalid.length > 0 && <span className="mapping-warning"><CircleAlert size={14} />{invalid.length} 行需要检查</span>}<span>{missingStops} 条缺少末尾 *</span></div>
    {mapping.nameColumn === mapping.sequenceColumn && <div className="mapping-error">名称列和蛋白序列列必须不同。</div>}
    {selectedRows.length > 200 && <div className="mapping-error">本次选择了 {selectedRows.length} 条，单次最多 200 条，请先拆分表格。</div>}
    {!!invalid.length && <div className="mapping-issues"><div>{invalid.slice(0, 4).map(row => <p key={row.row}>第 {row.row} 行 · {row.record.name || '未命名'}：{row.issues.join('；')}</p>)}{invalid.length > 4 && <p>另有 {invalid.length - 4} 行需要检查。</p>}</div><label><input type="checkbox" checked={skipInvalid} onChange={event => setSkipInvalid(event.target.checked)} />仅导入 {valid.length} 条有效序列，跳过上述 {invalid.length} 行</label></div>}
    <div className="table-import-note"><Info size={14} /><span>识别结果仅供推荐，请核对列映射。表格只在本机解析，确认导入不会提交优化请求。</span></div>
    <div className="mapping-actions"><button className="button outline" onClick={onCancel}>取消</button><button className="button primary" disabled={!canImport} onClick={() => onImport(selectedRows.map(row => row.record))}>导入 {selectedRows.length} 条序列</button></div>
  </div>;
}
