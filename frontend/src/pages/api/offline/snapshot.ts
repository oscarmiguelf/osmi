// The catalog copy for selling without internet (needs sales.create and an occupied register of this branch).
import type { APIRoute } from 'astro';
import { call } from '@/lib/api';

export const GET: APIRoute = async ({ locals }) => {
  if (!locals.accessToken || !locals.branch) return Response.json({}, { status: 401 });
  const res = await call('/sales/offline/snapshot', { headers: { authorization: `Bearer ${locals.accessToken}`, 'x-branch-id': locals.branch.id } });
  return new Response(res.body, { status: res.status, headers: { 'content-type': 'application/json', 'cache-control': 'no-store' } });
};
