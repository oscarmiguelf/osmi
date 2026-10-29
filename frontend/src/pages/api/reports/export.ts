// A report as a file in the person's language: CSV, or Excel (.xlsx) with real numbers and dates.
// The API returns every row (export=csv|xlsx needs reports.export) and records who exported what.
import type { APIRoute } from 'astro';
import { getLocale, useTranslations } from '@/i18n';
import { ApiError } from '@/lib/api';
import { formatCell, REPORT_PARAMS, runReport } from '@/lib/reports';
import { buildXlsx, type XlsxCell } from '@/lib/xlsx';

const csvCell = (v: string) => (/[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);

/** A wall-clock instant in tz, as a Date whose UTC fields hold that local time (what Excel serials expect). */
function localDate(value: string, tz: string, withTime: boolean): Date {
  const d = withTime ? Temporal.Instant.from(value).toZonedDateTimeISO(tz).toPlainDateTime() : Temporal.PlainDate.from(value).toPlainDateTime();
  return new Date(Date.UTC(d.year, d.month - 1, d.day, d.hour, d.minute));
}

export const GET: APIRoute = async ({ url, locals }) => {
  const name = url.searchParams.get('name') ?? '';
  if (!/^[a-z]+\/[a-z-]+$/.test(name)) return new Response(null, { status: 404 });
  const format = url.searchParams.get('format') === 'xlsx' ? 'xlsx' : 'csv';
  const locale = getLocale(url.searchParams.get('lang') ?? undefined);
  const t = useTranslations(locale);
  const params = new URLSearchParams();
  for (const k of REPORT_PARAMS) if (url.searchParams.get(k) && k !== 'page') params.set(k, url.searchParams.get(k)!);
  params.set('export', format);
  try {
    const result = await runReport(locals.accessToken!, locals.branch?.id, name, params);
    const tz = result.timezone;
    const title = (t.reports.names as Record<string, { title: string }>)[name]?.title ?? name;
    const intro = [
      [title],
      [`${t.reports.period}: ${params.get('from') ?? '—'} – ${params.get('to') ?? '—'}`],
      [`${t.reports.generated}: ${formatCell('datetime', result.generated_at, locale, t, tz, true)} (${tz})`],
      [],
    ];
    const headers = result.columns.map((c) => t.reports.columns[c.key] ?? c.key);
    const file = `${name.replace('/', '-')}-${params.get('from') ?? new Date().toISOString().slice(0, 10)}`;

    if (format === 'csv') {
      const body = result.rows.map((row) => result.columns.map((c) => formatCell(c.type, row[c.key], locale, t, tz, true)));
      const csv = [...intro, headers, ...body].map((line) => line.map((v) => csvCell(String(v))).join(',')).join('\r\n');
      return new Response('﻿' + csv, { headers: { 'content-type': 'text/csv; charset=utf-8', 'content-disposition': `attachment; filename="${file}.csv"` } });
    }

    const cell = (type: string, v: unknown): XlsxCell => {
      if (v === null || v === undefined || v === '') return null;
      if (type === 'money') return { value: Number(v), format: 'money' };
      if (['int', 'number', 'signed'].includes(type)) return Number(v);
      if (type === 'date') return { value: localDate(String(v), tz, false), format: 'date' };
      if (type === 'datetime') return { value: localDate(String(v), tz, true), format: 'datetime' };
      return formatCell(type, v, locale, t, tz, true);
    };
    const totals = Object.keys(result.totals ?? {}).length
      ? [{ bold: true, cells: result.columns.map((c, i) => (c.key in result.totals ? cell(c.type, result.totals[c.key]) : i === 0 ? t.reports.total : null)) }]
      : [];
    const bytes = buildXlsx(title, [
      ...intro.map((line, i) => ({ cells: line, bold: i === 0 })),
      { cells: headers, bold: true },
      ...result.rows.map((row) => ({ cells: result.columns.map((c) => cell(c.type, row[c.key])) })),
      ...totals,
    ]);
    return new Response(bytes as Uint8Array<ArrayBuffer>, { headers: {
      'content-type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      'content-disposition': `attachment; filename="${file}.xlsx"`,
    } });
  } catch (e) {
    if (e instanceof ApiError) return new Response(t.ui.forbidden, { status: e.status });
    throw e;
  }
};
