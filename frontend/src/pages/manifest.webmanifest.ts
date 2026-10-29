// The installable app's manifest. Its icons come from the business logo (Settings) when there is one; otherwise Osmi's.
import type { APIRoute } from 'astro';
import { catalogInfo } from '@/lib/publicCatalog';

export const GET: APIRoute = async () => {
  const logo = await catalogInfo().then((i) => i.logo).catch(() => null);
  const icon = (size: number, maskable = false) => (logo
    ? `/api/catalog/icon/${size}?v=${encodeURIComponent(logo)}${maskable ? '&maskable=1' : ''}`
    : `/icons/${maskable ? 'maskable' : 'icon'}-${size}.png`);
  const manifest = {
    name: 'Osmi',
    short_name: 'Osmi',
    description: 'Punto de venta, inventario, citas y expediente',
    lang: 'es',
    start_url: '/',
    scope: '/',
    display: 'standalone',
    background_color: '#ffffff',
    theme_color: '#284b63',
    icons: [
      { src: icon(192), sizes: '192x192', type: 'image/png' },
      { src: icon(512), sizes: '512x512', type: 'image/png' },
      { src: icon(512, true), sizes: '512x512', type: 'image/png', purpose: 'maskable' },
    ],
  };
  return new Response(JSON.stringify(manifest), {
    headers: { 'content-type': 'application/manifest+json', 'cache-control': 'public, max-age=300' },
  });
};
