// Osmi service worker (installable app + point of sale without internet). Pages come from the network and are never
// stored: they carry the signed-in user's data. Kept on the device: Astro's hashed build files (they never change), an
// offline page, and the offline point of sale (/pos-offline, a static page without data: its catalog is in IndexedDB).
const VERSION = 'osmi-v3'; // change it when SHELL or this file's rules change
const SHELL = ['/offline.html', '/favicon.svg', '/icons/icon-192.png'];
const POS = '/pos-offline';
// Opening the point of sale without a connection lands on the offline one
const POS_PATHS = ['/', '/en', '/sales/new', '/en/sales/new', POS];
const MAX_ASSETS = 200; // each deploy adds new file names: keep the most recent ones only
const POS_REFRESH_MS = 3600_000;
let posFetchedAt = 0;

/** Stores the offline point of sale and the build files it loads, so it opens with no connection at all. */
async function cachePos() {
  posFetchedAt = Date.now();
  const res = await fetch(POS, { credentials: 'same-origin', cache: 'no-store' });
  if (!res.ok || res.redirected) return;
  const html = await res.clone().text();
  const found = (text) => text.match(/\/_astro\/[^"'\s)?#]+/g) ?? [];
  const assets = new Set(found(html));
  // The stylesheets' own files (fonts)
  for (const css of [...assets].filter((a) => a.endsWith('.css'))) {
    found(await (await fetch(css)).text()).forEach((a) => assets.add(a));
  }
  const c = await caches.open(VERSION);
  await c.addAll([...assets]);
  await c.put(POS, res);
}

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => cachePos().catch(() => {})).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  const path = url.pathname.replace(/\/$/, '') || '/';

  // Pages: network only. Without a connection: the offline point of sale for the sales pages, else the offline page
  if (req.mode === 'navigate') {
    event.respondWith(fetch(req).then((res) => {
      // Online: keep the offline point of sale up to date (after a deploy its build files change), at most hourly
      if (Date.now() - posFetchedAt > POS_REFRESH_MS) event.waitUntil(cachePos().catch(() => {}));
      return res;
    }).catch(async () => (POS_PATHS.includes(path) && (await caches.match(POS))) || caches.match('/offline.html')));
    return;
  }
  // The offline page's own files
  if (SHELL.includes(url.pathname)) {
    event.respondWith(caches.match(req).then((hit) => hit || fetch(req)));
    return;
  }
  // /_astro/* names change with their content: once fetched, serve them from the cache
  if (url.pathname.startsWith('/_astro/')) {
    event.respondWith(caches.open(VERSION).then(async (c) => {
      const hit = await c.match(req);
      if (hit) return hit;
      const res = await fetch(req);
      if (res.ok) {
        await c.put(req, res.clone());
        const keys = (await c.keys()).filter((k) => new URL(k.url).pathname.startsWith('/_astro/'));
        await Promise.all(keys.slice(0, Math.max(0, keys.length - MAX_ASSETS)).map((k) => c.delete(k)));
      }
      return res;
    }));
  }
  // Everything else (API routes, images, PDFs): straight to the network, as without a service worker
});
