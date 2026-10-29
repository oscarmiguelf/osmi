// Minimal .xlsx writer (one sheet): an Office Open XML package zipped with fflate. Numbers stay numbers and dates
// stay dates (Excel serials), so the spreadsheet can sum and filter them. Server-side only.
import { strToU8, zipSync } from 'fflate';

export type XlsxCell = string | number | Date | null | undefined | { value: number | Date; format: 'money' | 'date' | 'datetime' | 'number' };
export interface XlsxRow { cells: XlsxCell[]; bold?: boolean }

// Style indexes of styles.xml below
const STYLE = { text: 0, bold: 1, money: 2, date: 3, datetime: 4, number: 5, boldMoney: 6, boldNumber: 7 };
const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const column = (i: number): string => (i < 26 ? String.fromCharCode(65 + i) : column(Math.floor(i / 26) - 1) + column(i % 26));

/** Excel's day serial (1900 system) for a wall-clock date-time already in the person's zone. */
export function excelSerial(d: Date): number {
  return (Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(), d.getUTCHours(), d.getUTCMinutes(), d.getUTCSeconds())
    - Date.UTC(1899, 11, 30)) / 86_400_000;
}

function cellXml(ref: string, cell: XlsxCell, bold: boolean): string {
  if (cell === null || cell === undefined || cell === '') return '';
  if (typeof cell === 'number') return `<c r="${ref}" s="${bold ? STYLE.boldNumber : STYLE.number}"><v>${cell}</v></c>`;
  if (cell instanceof Date) return `<c r="${ref}" s="${STYLE.datetime}"><v>${excelSerial(cell)}</v></c>`;
  if (typeof cell === 'object') {
    const v = cell.value instanceof Date ? excelSerial(cell.value) : cell.value;
    const s = cell.format === 'money' ? (bold ? STYLE.boldMoney : STYLE.money) : cell.format === 'number' ? (bold ? STYLE.boldNumber : STYLE.number) : STYLE[cell.format];
    return `<c r="${ref}" s="${s}"><v>${v}</v></c>`;
  }
  return `<c r="${ref}" t="inlineStr" s="${bold ? STYLE.bold : STYLE.text}"><is><t xml:space="preserve">${esc(cell)}</t></is></c>`;
}

const STYLES = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="3"><numFmt numFmtId="164" formatCode="#,##0.00"/><numFmt numFmtId="165" formatCode="yyyy-mm-dd"/><numFmt numFmtId="166" formatCode="yyyy-mm-dd hh:mm"/></numFmts>
<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>
<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="8">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>
<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="166" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="164" fontId="1" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyFont="1"/>
<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>
</cellXfs>
</styleSheet>`;

/** The .xlsx bytes of one sheet. */
export function buildXlsx(sheetName: string, rows: XlsxRow[]): Uint8Array {
  // Column widths from the longest text in each column (capped)
  const widths: number[] = [];
  rows.forEach((row) => row.cells.forEach((c, i) => {
    const len = c === null || c === undefined ? 0 : typeof c === 'object' && !(c instanceof Date) ? 14 : c instanceof Date ? 16 : String(c).length;
    widths[i] = Math.min(Math.max(widths[i] ?? 8, len + 2), 60);
  }));
  const cols = widths.map((w, i) => `<col min="${i + 1}" max="${i + 1}" width="${w}" customWidth="1"/>`).join('');
  const body = rows.map((row, r) => `<row r="${r + 1}">${row.cells.map((c, i) => cellXml(`${column(i)}${r + 1}`, c, !!row.bold)).join('')}</row>`).join('');
  const sheet = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><cols>${cols}</cols><sheetData>${body}</sheetData></worksheet>`;
  const name = esc(sheetName.replace(/[\\/?*[\]:]/g, ' ').slice(0, 31));
  return zipSync({
    '[Content_Types].xml': strToU8(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>`),
    '_rels/.rels': strToU8(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>`),
    'xl/workbook.xml': strToU8(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="${name}" sheetId="1" r:id="rId1"/></sheets></workbook>`),
    'xl/_rels/workbook.xml.rels': strToU8(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>`),
    'xl/worksheets/sheet1.xml': strToU8(sheet),
    'xl/styles.xml': strToU8(STYLES),
  });
}
