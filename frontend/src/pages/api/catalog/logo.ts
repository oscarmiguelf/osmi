// The business logo (public: the customer catalog shows it too). ?v= is the file name, so a new logo is never stale.
import type { APIRoute } from 'astro';
import { call } from '@/lib/api';

export const GET: APIRoute = async () => {
  const res = await call('/settings/logo', {});
  if (!res.ok) return new Response(null, { status: 404 });
  return new Response(res.body, { headers: { 'content-type': 'image/png', 'cache-control': 'public, max-age=31536000, immutable' } });
};
