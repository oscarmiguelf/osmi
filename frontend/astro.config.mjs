import { defineConfig, envField } from 'astro/config';
import node from '@astrojs/node';

export default defineConfig({
  // Server-rendered: the middleware checks the session on every request (BFF in front of the API).
  output: 'server',
  adapter: node({ mode: 'standalone' }),
  // Behind Coolify / Dokploy the proxy terminates HTTPS: trust its X-Forwarded-Host / -Proto so form posts pass the
  // origin check. Any domain over https: the web container is only reachable through that proxy (it isn't published).
  security: {
    allowedDomains: [{ protocol: 'https' }],
    // Content-Security-Policy (production builds; Astro hashes its own scripts): only this app's scripts can run.
    // Styles allow 'unsafe-inline' for the few style="" attributes (bars, heat map); frame-ancestors goes as a header (middleware).
    csp: {
      directives: [
        "default-src 'self'",
        "img-src 'self' blob: data:",
        "font-src 'self'",
        "connect-src 'self'",
        "form-action 'self'",
        "base-uri 'self'",
        "object-src 'none'",
      ],
      styleDirective: { resources: ["'self'", "'unsafe-inline'"] },
    },
  },
  // The dev toolbar floats over the bottom of the page (it covered the catalog's order bar); production never has it
  devToolbar: { enabled: false },
  env: {
    schema: {
      // secret = read when the server starts (not baked in at build), so a container can point it at the API
      API_URL: envField.string({ context: 'server', access: 'secret', default: 'http://localhost:8000' }),
      // How many proxies in front of the web server append to X-Forwarded-For (Coolify / Dokploy: 1). See lib/clientIp.ts
      TRUSTED_PROXY_HOPS: envField.number({ context: 'server', access: 'secret', default: 0, int: true, min: 0 }),
    },
  },
  i18n: {
    locales: ['es', 'en'],
    defaultLocale: 'es',
    routing: { prefixDefaultLocale: false },
  },
});
