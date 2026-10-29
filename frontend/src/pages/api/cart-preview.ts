// Live totals for the sale / quote cart: the API prices it (same math it saves with); errors come back already worded.
import type { APIRoute } from 'astro';
import { getLocale, useTranslations } from '@/i18n';
import { ApiError } from '@/lib/api';
import { previewQuote, previewSale, saleErrorText } from '@/lib/sales';

export const POST: APIRoute = async ({ request, locals }) => {
  const { mode, payload, lang } = await request.json().catch(() => ({}));
  const t = useTranslations(getLocale(lang));
  const branch = locals.branch?.id;
  if (!branch || !payload) return Response.json({ error: { text: t.ui.failed } }, { status: 400 });
  try {
    const data = await (mode === 'quote' ? previewQuote : previewSale)(locals.accessToken!, branch, payload);
    return Response.json({ data });
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    return Response.json({ error: saleErrorText(e.status, e.body?.detail, t) });
  }
};
