// A study (PDF/image) or a consent signature, streamed from the API with the user's token. The API logs the access.
import type { APIRoute } from 'astro';
import { call } from '@/lib/api';

const UUID = /^[0-9a-f-]{36}$/i;
const SIGNATURE = /^signature-[0-9a-f-]{36}\.png$/;

export const GET: APIRoute = async ({ url, locals }) => {
  const id = url.searchParams.get('id') ?? '';
  const patient = url.searchParams.get('patient') ?? '';
  const sig = url.searchParams.get('signature') ?? '';
  const path = UUID.test(id) ? `/clinical/files/${id}`
    : UUID.test(patient) && SIGNATURE.test(sig) ? `/clinical/patients/${patient}/signatures/${sig}` : null;
  if (!locals.accessToken || !path) return new Response('Not found', { status: 404 });
  const res = await call(path, { headers: { authorization: `Bearer ${locals.accessToken}` } });
  if (!res.ok) return new Response('Not found', { status: res.status === 403 ? 403 : 404 });
  return new Response(res.body, { headers: { 'content-type': res.headers.get('content-type') ?? 'application/octet-stream', 'cache-control': 'no-store',
    'content-disposition': 'inline' } });
};
