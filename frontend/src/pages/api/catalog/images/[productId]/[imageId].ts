// Public product image for the customer catalog (the API only serves images of products the catalog shows).
import type { APIRoute } from 'astro';
import { API_URL } from 'astro:env/server';

const UUID = /^[0-9a-f-]{36}$/i;

export const GET: APIRoute = async ({ params }) => {
  if (!UUID.test(params.productId ?? '') || !UUID.test(params.imageId ?? '')) return new Response(null, { status: 404 });
  const res = await fetch(`${API_URL}/public/catalog/products/${params.productId}/images/${params.imageId}`);
  if (!res.ok) return new Response(null, { status: 404 });
  return new Response(res.body, { headers: {
    'content-type': res.headers.get('content-type') ?? 'application/octet-stream',
    'cache-control': res.headers.get('cache-control') ?? 'public, max-age=3600',
  } });
};
