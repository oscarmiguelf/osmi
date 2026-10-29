// A product image for <img>: fetched from the API with the person's session (images are not public).
import type { APIRoute } from 'astro';
import { API_URL } from 'astro:env/server';

const UUID = /^[0-9a-f-]{36}$/i;

export const GET: APIRoute = async ({ params, locals }) => {
  if (!locals.accessToken || !UUID.test(params.id ?? '') || !UUID.test(params.imageId ?? '')) return new Response(null, { status: 404 });
  const res = await fetch(`${API_URL}/products/${params.id}/images/${params.imageId}`, { headers: { authorization: `Bearer ${locals.accessToken}` } });
  if (!res.ok) return new Response(null, { status: res.status === 403 ? 403 : 404 });
  return new Response(res.body, { headers: {
    'content-type': res.headers.get('content-type') ?? 'application/octet-stream',
    'cache-control': res.headers.get('cache-control') ?? 'private, max-age=3600',
  } });
};
