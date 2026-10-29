// Product search for the counting screen (picker shape). Uses the stocktake's own search: counters may not have
// access to the products module, and a blind count must not show stock.
import type { APIRoute } from 'astro';
import { getLocale, useTranslations } from '@/i18n';
import { ApiError, request } from '@/lib/api';

export const GET: APIRoute = async ({ url, locals }) => {
  const id = url.searchParams.get('id') ?? '';
  const q = (url.searchParams.get('q') ?? '').trim().slice(0, 100);
  const branch = locals.branch?.id;
  if (!branch || q.length < 2 || !/^[0-9a-f-]{36}$/.test(id)) return Response.json([]);
  const units = useTranslations(getLocale(url.searchParams.get('lang') ?? undefined)).products.unitNames;
  try {
    const rows = await request<{ id: string; name: string; barcode: string | null; unit: string }[]>(
      locals.accessToken!, `/stocktakes/${id}/products?q=${encodeURIComponent(q)}`, {}, branch);
    return Response.json(rows.map((p) => ({ id: p.id, title: p.name, subtitle: [p.barcode, units[p.unit] ?? p.unit].filter(Boolean).join(' · ') })));
  } catch (e) {
    if (e instanceof ApiError) return Response.json([]);
    throw e;
  }
};
