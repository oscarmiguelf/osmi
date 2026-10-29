// The customer's packages with sessions left (for the cart: "use the package").
import type { APIRoute } from 'astro';
import { request } from '@/lib/api';

const UUID = /^[0-9a-f-]{36}$/i;

export const GET: APIRoute = async ({ url, locals }) => {
  const id = url.searchParams.get('customer') ?? '';
  if (!locals.accessToken || !UUID.test(id)) return Response.json([]);
  try {
    const all = await request<any[]>(locals.accessToken, `/customers/${id}/benefits`);
    return Response.json(all.filter((b) => b.kind === 'package' && b.active)
      .map((b) => ({ id: b.id, service_product_id: b.service_product_id, product: b.product, sessions_left: b.sessions_left })));
  } catch {
    return Response.json([]);
  }
};
