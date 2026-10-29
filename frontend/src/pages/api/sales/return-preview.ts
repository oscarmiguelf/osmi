// Live refund for the return screen (the DB function computes it; nothing is written).
import type { APIRoute } from 'astro';
import { getLocale, useTranslations } from '@/i18n';
import { ApiError } from '@/lib/api';
import { previewReturn } from '@/lib/sales';

export const POST: APIRoute = async ({ request, locals }) => {
  const { sale_id, items, lang } = await request.json().catch(() => ({}));
  const t = useTranslations(getLocale(lang));
  const branch = locals.branch?.id;
  if (!branch || typeof sale_id !== 'string' || !Array.isArray(items)) return Response.json({ error: t.ui.failed }, { status: 400 });
  try {
    return Response.json({ data: await previewReturn(locals.accessToken!, branch, sale_id, items) });
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    const detail = e.body?.detail;
    return Response.json({ error: detail?.returnable !== undefined ? t.sales.returns.tooMany : t.ui.failed });
  }
};
