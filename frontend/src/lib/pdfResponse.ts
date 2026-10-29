// Shared bits of the PDF routes: the business logo and the response headers.
import { call } from './api';

/** The logo bytes from Settings, or null when there is none (or it can't be read: the PDF goes without it). */
export async function fetchLogo(name: string) {
  if (!name) return null;
  const res = await call('/settings/logo', {}).catch(() => null);
  return res?.ok ? new Uint8Array(await res.arrayBuffer()) : null;
}

export function pdfResponse(bytes: Uint8Array, fileName: string, download: boolean) {
  return new Response(bytes as BodyInit, { headers: {
    'content-type': 'application/pdf',
    'content-disposition': `${download ? 'attachment' : 'inline'}; filename="${fileName.replace(/[^\w.-]/g, '_')}"`,
    'cache-control': 'no-store', // customer data: never kept by a browser or proxy
  } });
}
