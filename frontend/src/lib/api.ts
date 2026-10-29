// Server-side client for the backend auth API. Never imported by browser code.
import { API_URL } from 'astro:env/server';

/** Login payload: same shape as POST /auth/login and GET /auth/me. */
export interface Session {
  business_type: import('../i18n/giro').BusinessType;
  /** WhatsApp reminder text from Settings ('' = the app's default) */
  reminder_template: string;
  /** Logo file name from Settings ('' = none); also busts the cache of /api/catalog/logo */
  logo: string;
  user: { id: string; name: string; first_name: string; last_name: string; email: string; timezone: string; must_change_password: boolean };
  branches: { id: string; name: string; phone: string | null; address: string | null }[];
  modules: { code: string; name: string; route: string; icon: string; permissions: string[] }[];
}

export interface Tokens {
  access_token: string;
  expires_in: number;
  refresh_token: string;
}

/** The browser's address and agent, forwarded so the API's rate limits and audit see the real client. */
export interface ClientMeta {
  ip?: string;
  userAgent?: string | null;
}

export function call(path: string, init: RequestInit, meta: ClientMeta = {}) {
  const headers = new Headers(init.headers);
  if (!(init.body instanceof FormData)) headers.set('content-type', 'application/json'); // files: fetch sets the multipart boundary
  if (meta.ip) headers.set('x-forwarded-for', meta.ip);
  if (meta.userAgent) headers.set('user-agent', meta.userAgent);
  return fetch(API_URL + path, { ...init, headers });
}

export class ApiError extends Error {
  /** body: the parsed JSON error, e.g. FastAPI's 422 { detail: [{ loc, msg }] } */
  constructor(public status: number, public body?: any) {
    super(`API responded ${status}`);
  }
}

/**
 * Authenticated JSON call on the user's behalf. Throws ApiError on any non-2xx.
 * branchId: the working branch, sent as X-Branch-Id to branch-scoped endpoints (the API re-validates it).
 */
export async function request<T>(token: string, path: string, init: RequestInit = {}, branchId?: string): Promise<T> {
  const headers: Record<string, string> = { authorization: `Bearer ${token}` };
  if (branchId) headers['x-branch-id'] = branchId;
  const res = await call(path, { ...init, headers });
  if (!res.ok) throw new ApiError(res.status, await res.json().catch(() => undefined));
  return (res.status === 204 ? undefined : await res.json()) as T;
}

export async function login(email: string, password: string, meta: ClientMeta) {
  // x-client: mobile makes the API return the refresh token in the body; we store it in our own cookie.
  const res = await call('/auth/login', {
    method: 'POST',
    headers: { 'x-client': 'mobile' },
    body: JSON.stringify({ email, password }),
  }, meta);
  return res.ok ? { tokens: (await res.json()) as Tokens & Session } : { status: res.status };
}

/** New token pair, or null when the refresh token is no longer valid (expired, revoked, reused). */
export async function refresh(refreshToken: string, meta: ClientMeta): Promise<Tokens | null> {
  const res = await call('/auth/refresh', { method: 'POST', body: JSON.stringify({ refresh_token: refreshToken }) }, meta);
  if (res.status === 401) return null;
  if (!res.ok) throw new Error(`refresh failed: ${res.status}`);
  return res.json();
}

/** Fresh modules and branches for the access token, or null when the token is not valid. */
export async function me(accessToken: string): Promise<Session | null> {
  const res = await call('/auth/me', { headers: { authorization: `Bearer ${accessToken}` } });
  if (res.status === 401) return null;
  if (!res.ok) throw new Error(`me failed: ${res.status}`);
  return res.json();
}

export async function logout(refreshToken: string, meta: ClientMeta) {
  await call('/auth/logout', { method: 'POST', body: JSON.stringify({ refresh_token: refreshToken }) }, meta);
}

/** FastAPI 422 { detail: [{ loc: ['body', 'phone'], msg }] } -> { phone: <our wording> }. Empty when not a field error. */
export function apiFieldErrors(body: any, messages: Record<string, string>): Record<string, string> {
  if (!Array.isArray(body?.detail)) return {};
  return Object.fromEntries(
    body.detail.map((d: { loc?: unknown[]; msg?: string }) => {
      const name = String(d.loc?.at(-1) ?? '');
      return [name, messages[name] ?? d.msg ?? ''];
    }),
  );
}
