// Download the count sheet (CSV); the API decides the columns (no system quantity for counters).
import type { APIRoute } from 'astro';
import { exportSheet } from '@/lib/stocktakes';

export const GET: APIRoute = async ({ url, locals }) => {
  const id = url.searchParams.get('id') ?? '';
  const branch = locals.branch?.id;
  if (!branch || !/^[0-9a-f-]{36}$/.test(id)) return new Response(null, { status: 404 });
  const res = await exportSheet(locals.accessToken!, branch, id, url.searchParams.get('lang') === 'en' ? 'en' : 'es');
  if (!res.ok) return new Response(null, { status: res.status });
  return new Response(res.body, { headers: { 'content-type': 'text/csv; charset=utf-8', 'content-disposition': res.headers.get('content-disposition') ?? 'attachment' } });
};
