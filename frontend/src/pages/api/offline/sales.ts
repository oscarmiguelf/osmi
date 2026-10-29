// A sale made without internet, sent back. The branch is the one it was made in (the API checks the user belongs to it
// and occupies its register); the body is passed through as is and validated by the API.
import type { APIRoute } from 'astro';
import { call } from '@/lib/api';

const UUID = /^[0-9a-f-]{36}$/i;

export const POST: APIRoute = async ({ request, locals }) => {
  if (!locals.accessToken) return Response.json({}, { status: 401 });
  const branch = request.headers.get('x-branch-id') ?? '';
  if (!UUID.test(branch)) return Response.json({ detail: { code: 'branch' } }, { status: 422 });
  const body = await request.text();
  if (body.length > 200_000) return Response.json({ detail: { code: 'too_big' } }, { status: 413 });
  const res = await call('/sales/offline', { method: 'POST', body, headers: { authorization: `Bearer ${locals.accessToken}`, 'x-branch-id': branch } });
  return new Response(res.body, { status: res.status, headers: { 'content-type': 'application/json' } });
};
