// The sale ticket as a PDF (to send by WhatsApp or download). The API checks the permission and the branch.
import type { APIRoute } from 'astro';
import { useTranslations } from '@/i18n';
import { ApiError } from '@/lib/api';
import { fetchLogo, pdfResponse } from '@/lib/pdfResponse';
import { ticketPdf } from '@/lib/pdf';
import { getSale } from '@/lib/sales';

const UUID = /^[0-9a-f-]{36}$/i;

export const GET: APIRoute = async ({ params, url, locals }) => {
  if (!locals.accessToken || !locals.session || !locals.branch || !UUID.test(params.id ?? '')) return new Response('Not found', { status: 404 });
  const locale = url.searchParams.get('lang') === 'en' ? 'en' : 'es';
  try {
    const [sale, logo] = await Promise.all([getSale(locals.accessToken, locals.branch.id, params.id!), fetchLogo(locals.session.logo)]);
    const bytes = await ticketPdf(sale, useTranslations(locale), locale, locals.session.user.timezone, logo);
    return pdfResponse(bytes, `ticket-${sale.folio}.pdf`, url.searchParams.has('download'));
  } catch (e) {
    if (e instanceof ApiError) return new Response('Not found', { status: e.status === 403 ? 403 : 404 });
    throw e;
  }
};
