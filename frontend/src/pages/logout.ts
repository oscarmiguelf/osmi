import type { APIRoute } from 'astro';
import { getLocale, localePath } from '@/i18n';
import { endSession } from '@/lib/session';

export const POST: APIRoute = async ({ cookies, request, locals, redirect }) => {
  const form = await request.formData();
  await endSession(cookies, { ip: locals.clientIp, userAgent: request.headers.get('user-agent') });
  return redirect(localePath(getLocale(String(form.get('locale'))), '/login'), 303);
};
