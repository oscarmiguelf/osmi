// A quote as a PDF (to send by WhatsApp or download). The API checks the permission and the branch.
import type { APIRoute } from 'astro';
import { useTranslations } from '@/i18n';
import { ApiError } from '@/lib/api';
import { quotePdf } from '@/lib/pdf';
import { fetchLogo, pdfResponse } from '@/lib/pdfResponse';
import { getQuote } from '@/lib/sales';

const UUID = /^[0-9a-f-]{36}$/i;

export const GET: APIRoute = async ({ params, url, locals }) => {
  if (!locals.accessToken || !locals.session || !locals.branch || !UUID.test(params.id ?? '')) return new Response('Not found', { status: 404 });
  const locale = url.searchParams.get('lang') === 'en' ? 'en' : 'es';
  try {
    const [quote, logo] = await Promise.all([getQuote(locals.accessToken, locals.branch.id, params.id!), fetchLogo(locals.session.logo)]);
    const bytes = await quotePdf(quote, useTranslations(locale), locale, locals.session.user.timezone, logo);
    return pdfResponse(bytes, `cotizacion-${quote.folio}.pdf`, url.searchParams.has('download'));
  } catch (e) {
    if (e instanceof ApiError) return new Response('Not found', { status: e.status === 403 ? 403 : 404 });
    throw e;
  }
};
