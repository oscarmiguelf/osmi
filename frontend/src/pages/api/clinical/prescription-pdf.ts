// A prescription as a PDF. The API checks the clinical permission and logs it as printed.
import type { APIRoute } from 'astro';
import { useTranslations } from '@/i18n';
import { ApiError } from '@/lib/api';
import { getPrescription } from '@/lib/clinical';
import { prescriptionPdf } from '@/lib/pdf';
import { fetchLogo, pdfResponse } from '@/lib/pdfResponse';

const UUID = /^[0-9a-f-]{36}$/i;

export const GET: APIRoute = async ({ url, locals }) => {
  const id = url.searchParams.get('id') ?? '';
  if (!locals.accessToken || !locals.session || !UUID.test(id)) return new Response('Not found', { status: 404 });
  const locale = url.searchParams.get('lang') === 'en' ? 'en' : 'es';
  try {
    const [rx, logo] = await Promise.all([getPrescription(locals.accessToken, id), fetchLogo(locals.session.logo)]);
    const bytes = await prescriptionPdf(rx, useTranslations(locale), locals.session.user.timezone, logo);
    return pdfResponse(bytes, `receta-${rx.created_at.slice(0, 10)}.pdf`, url.searchParams.has('download'));
  } catch (e) {
    if (e instanceof ApiError) return new Response('Not found', { status: e.status === 403 ? 403 : 404 });
    throw e;
  }
};
