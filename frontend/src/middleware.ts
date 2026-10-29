import { defineMiddleware, sequence } from 'astro:middleware';
import { getLocale, localePath } from '@/i18n';
import { giroStore } from '@/i18n/giro';
import { clientIp } from '@/lib/clientIp';
import { rateLimiter } from '@/lib/rateLimit';
import { activeBranch, resolveSession } from '@/lib/session';

const LOGIN_PATHS = new Set(['/login', '/en/login']);
const BRANCH_PATHS = new Set(['/branch', '/en/branch']);
const PASSWORD_PATHS = new Set(['/change-password', '/en/change-password']);
// Public: the customer catalog and its images, no sign-in
const PUBLIC_PATHS = new Set(['/catalog', '/en/catalog']);
const OFFLINE_POS = '/pos-offline';
// Anyone can open the catalog: a cap per visitor stops scraping and floods (a page is 1 request + up to 24 images)
const publicLimit = rateLimiter(300, 60_000);

const auth = defineMiddleware(async (ctx, next) => {
  // Pages live under [...lang]: only '' (Spanish) and 'en' are real; '/sales' must not render the home page.
  const { lang } = ctx.params;
  if (lang !== undefined && lang !== 'en') return new Response('Not found', { status: 404 });
  // The offline point of sale is a static page (prerendered, kept by the service worker): no session in it, its data is
  // on the device. Checked first: there is no client address while prerendering
  if (ctx.url.pathname.replace(/\/$/, '') === OFFLINE_POS) return next();

  ctx.locals.clientIp = clientIp(ctx.request.headers, ctx.clientAddress);
  const path = ctx.url.pathname.replace(/\/$/, '') || '/';
  if (PUBLIC_PATHS.has(path) || path.startsWith('/api/catalog/')) {
    const { ok, retryAfter } = publicLimit(ctx.locals.clientIp);
    return ok ? next() : new Response('Too many requests', { status: 429, headers: { 'retry-after': String(retryAfter) } });
  }
  if (path === '/logout') return next();

  const auth = await resolveSession(ctx.cookies, {
    ip: ctx.locals.clientIp,
    userAgent: ctx.request.headers.get('user-agent'),
  });
  const locale = getLocale(ctx.currentLocale);

  if (LOGIN_PATHS.has(path)) {
    return auth ? ctx.redirect(localePath(locale, '/')) : next();
  }
  if (!auth) return ctx.redirect(localePath(locale, '/login'));

  ctx.locals.session = auth.session;
  ctx.locals.accessToken = auth.accessToken;
  ctx.locals.branch = activeBranch(ctx.cookies, auth.session);

  // A temporary password (new user or admin reset) must be replaced before anything else opens.
  if (auth.session.user.must_change_password && !PASSWORD_PATHS.has(path) && !path.startsWith('/api/')) {
    return ctx.redirect(localePath(locale, '/change-password'));
  }
  if (PASSWORD_PATHS.has(path) && !auth.session.user.must_change_password) return ctx.redirect(localePath(locale, '/'));
  // The password comes first: the branch is chosen after it (sending /change-password to /branch looped forever)
  if (PASSWORD_PATHS.has(path)) return giroStore.run(auth.session.business_type, next);

  // With two or more branches, nothing else opens until one is chosen for this sign-in.
  const mustChoose = auth.session.branches.length > 1 && !ctx.locals.branch;
  if (mustChoose && !BRANCH_PATHS.has(path) && !path.startsWith('/api/')) {
    return ctx.redirect(localePath(locale, '/branch'));
  }
  if (BRANCH_PATHS.has(path) && auth.session.branches.length < 2) return ctx.redirect(localePath(locale, '/'));
  return giroStore.run(auth.session.business_type, next); // the page renders with this business type's words
});

// Headers for every response (pages, redirects, API routes). The rest of the CSP comes from Astro (astro.config.mjs).
const SECURITY_HEADERS: Record<string, string> = {
  'x-frame-options': 'DENY',
  'x-content-type-options': 'nosniff',
  'referrer-policy': 'strict-origin-when-cross-origin',
  'permissions-policy': 'camera=(), microphone=(), geolocation=(), payment=(), usb=()',
  'cross-origin-opener-policy': 'same-origin',
  ...(import.meta.env.PROD && { 'strict-transport-security': 'max-age=31536000; includeSubDomains' }), // HTTPS only
};

const securityHeaders = defineMiddleware(async (ctx, next) => {
  let res = await next();
  try {
    res.headers.set('x-content-type-options', 'nosniff');
  } catch {
    res = new Response(res.body, res); // some responses have read-only headers: copy them into a mutable one
  }
  for (const [k, v] of Object.entries(SECURITY_HEADERS)) res.headers.set(k, v);
  // Astro sends the page's CSP (script hashes); add to it, never replace it. frame-ancestors: no one can frame the app
  // to trick clicks (it only works as a header)
  const csp = res.headers.get('content-security-policy');
  res.headers.set('content-security-policy', csp ? `${csp}; frame-ancestors 'none'` : "frame-ancestors 'none'");
  // Signed-in pages must not be kept by the browser or a proxy (the back button after logging out)
  if (ctx.locals.session && !res.headers.has('cache-control')) res.headers.set('cache-control', 'no-store');
  return res;
});

export const onRequest = sequence(securityHeaders, auth);
