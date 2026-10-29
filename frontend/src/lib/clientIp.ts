// The visitor's real IP, for the login audit and rate limits.
import { TRUSTED_PROXY_HOPS } from 'astro:env/server';

/**
 * Behind N trusted proxies (Coolify / Dokploy: 1; Cloudflare in front of them: 2) each proxy APPENDS the address it saw
 * to X-Forwarded-For, so the client is the Nth entry from the END; anything before it was written by the client and is
 * ignored. With no proxy (0) it is the connection's address as Astro reports it.
 */
export function clientIp(headers: Headers, fallback: string | undefined): string | undefined {
  if (TRUSTED_PROXY_HOPS > 0) {
    const chain = (headers.get('x-forwarded-for') ?? '').split(',').map((s) => s.trim()).filter(Boolean);
    if (chain.length >= TRUSTED_PROXY_HOPS) return chain[chain.length - TRUSTED_PROXY_HOPS];
  }
  return fallback;
}
