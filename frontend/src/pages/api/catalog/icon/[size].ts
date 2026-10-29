// The installed app's icon made from the business logo (public: the home screen asks before anyone signs in).
// Without a logo, Osmi's own icon. ?v= is the logo's file name, so a new logo is never a stale icon.
import type { APIRoute } from 'astro';
import { call } from '@/lib/api';

const SIZES = new Set(['180', '192', '512']);

export const GET: APIRoute = async ({ params, url, redirect }) => {
  const size = params.size ?? '';
  if (!SIZES.has(size)) return new Response(null, { status: 404 });
  const maskable = url.searchParams.has('maskable');
  const res = await call(`/settings/logo/icon/${size}${maskable ? '?maskable=true' : ''}`, {}).catch(() => null);
  if (!res?.ok) return redirect(size === '180' ? '/icons/apple-touch-icon.png' : `/icons/${maskable ? 'maskable-512' : `icon-${size === '512' ? 512 : 192}`}.png`, 302);
  return new Response(res.body, { headers: { 'content-type': 'image/png',
    'cache-control': url.searchParams.has('v') ? 'public, max-age=31536000, immutable' : 'public, max-age=300' } });
};
