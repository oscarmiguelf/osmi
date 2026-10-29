// Fixed-window request counter per key (the visitor's IP).
// shortcut: in-memory, per web process; with several replicas move it to Redis or the API.

export function rateLimiter(limit: number, windowMs: number) {
  const hits = new Map<string, { count: number; resetAt: number }>();
  return (key: string | undefined): { ok: boolean; retryAfter: number } => {
    const now = Date.now();
    if (hits.size > 10_000) for (const [k, v] of hits) if (v.resetAt <= now) hits.delete(k); // keep memory bounded
    const k = key ?? '?';
    const entry = hits.get(k);
    if (!entry || entry.resetAt <= now) {
      hits.set(k, { count: 1, resetAt: now + windowMs });
      return { ok: true, retryAfter: 0 };
    }
    entry.count += 1;
    return { ok: entry.count <= limit, retryAfter: Math.ceil((entry.resetAt - now) / 1000) };
  };
}
