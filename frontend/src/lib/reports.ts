// Reports: the API's catalog and a generic runner, plus how each column type is shown (page and CSV alike).
import { money, type Dict, type Locale } from '@/i18n';
import { request } from './api';

export interface ReportSpec {
  name: string;
  columns: [string, string][];
  range?: boolean;
  paged?: boolean;
  extras?: string[];
  totals?: string[];
  admin?: boolean;
}

export interface ReportResult {
  report: string;
  generated_at: string;
  timezone: string;
  columns: { key: string; type: string }[];
  rows: Record<string, unknown>[];
  totals: Record<string, number | string>;
  page?: number;
  has_more?: boolean;
}

export const reportCatalog = (t: string) => request<ReportSpec[]>(t, '/reports');
export const runReport = (t: string, branch: string | undefined, name: string, params: URLSearchParams) =>
  request<ReportResult>(t, `/reports/${name}?${params}`, {}, branch);
export const reportDashboard = (t: string, branch: string | undefined, branchIds: string) =>
  request<any>(t, `/reports/dashboard?${new URLSearchParams(branchIds ? { branch_ids: branchIds } : {})}`, {}, branch);

/** The query a report page sends: only what the API knows about. */
export const REPORT_PARAMS = ['branch_ids', 'from', 'to', 'group', 'order', 'direction', 'days', 'product_id', 'customer_id', 'page'] as const;

/** One cell as text. csv: plain numbers (2 decimals, no currency sign) so spreadsheets read them as numbers. */
export function formatCell(type: string, value: unknown, locale: Locale, t: Dict, tz: string, csv = false): string {
  const r = t.reports;
  if (value === null || value === undefined || value === '') return csv ? '' : '—';
  const n = Number(value);
  switch (type) {
    case 'money': return csv ? n.toFixed(2) : money(locale, n);
    case 'int': return String(n);
    case 'number': return csv ? String(n) : n.toLocaleString(t.intl, { maximumFractionDigits: 3 });
    case 'signed': return `${n > 0 ? '+' : ''}${n}`;
    case 'percent': return `${Math.round(n * 10000) / 100} %`;
    case 'flag': return value ? r.noCost : '';
    case 'date': return csv ? String(value) : Temporal.PlainDate.from(String(value)).toLocaleString(t.intl, { dateStyle: 'medium' });
    case 'datetime': return csv
      ? Temporal.Instant.from(String(value)).toZonedDateTimeISO(tz).toPlainDateTime().toString({ smallestUnit: 'minute' }).replace('T', ' ')
      : new Intl.DateTimeFormat(t.intl, { dateStyle: 'medium', timeStyle: 'short', timeZone: tz }).format(new Date(String(value)));
    case 'weekday': return r.weekdays[n - 1] ?? String(n);
    case 'hour': return `${String(n).padStart(2, '0')}:00`;
    case 'method': return t.cash.methodNames[String(value)] ?? String(value);
    case 'report_name': return (r.names as Record<string, { title: string }>)[String(value)]?.title ?? String(value);
    default: {
      const labels = (r.enums as Record<string, Record<string, string>>)[type];
      return labels?.[String(value)] ?? String(value);
    }
  }
}

export const isNumeric = (type: string) => ['money', 'int', 'number', 'signed', 'percent'].includes(type);
