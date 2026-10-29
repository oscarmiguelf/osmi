// Record or correct one count from the counting screen (no page reload: scan, type, Enter, next).
import type { APIRoute } from 'astro';
import { getLocale, useTranslations } from '@/i18n';
import { ApiError } from '@/lib/api';
import { countProduct } from '@/lib/stocktakes';

export const POST: APIRoute = async ({ request, locals }) => {
  const { stocktake_id, product_id, counted_quantity, lang } = await request.json().catch(() => ({}));
  const t = useTranslations(getLocale(lang));
  const branch = locals.branch?.id;
  if (!branch || typeof stocktake_id !== 'string' || typeof product_id !== 'string') return Response.json({ error: t.ui.failed }, { status: 400 });
  try {
    return Response.json({ data: await countProduct(locals.accessToken!, branch, stocktake_id, product_id, { counted_quantity: String(counted_quantity) }) });
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    const code = e.body?.detail?.code;
    const st = t.stocktakes.errors;
    const error = code === 'whole_units' ? st.whole : code === 'not_countable' ? st.notCountable : code === 'not_open' ? st.notOpen
      : e.status === 422 ? st.quantity : e.status === 403 ? t.ui.forbidden : t.ui.failed;
    return Response.json({ error });
  }
};
