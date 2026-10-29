// Session = two HttpOnly cookies on the frontend's own domain. JavaScript in the browser never sees a token.
import type { AstroCookies } from 'astro';
import { logout, me, refresh, type ClientMeta, type Session, type Tokens } from './api';

const ACCESS = 'osmi_at';
const REFRESH = 'osmi_rt';
const BRANCH = 'osmi_branch'; // branch chosen for this sign-in, when the user has more than one
const REFRESH_MAX_AGE = 30 * 24 * 60 * 60; // the API's absolute session cap

const cookieOptions = {
  path: '/',
  httpOnly: true,
  secure: import.meta.env.PROD,
  // Lax, not Strict: opening the app from a link elsewhere still finds the session. Astro's checkOrigin blocks cross-site POSTs.
  sameSite: 'lax',
} as const;

export function saveTokens(cookies: AstroCookies, tokens: Tokens) {
  cookies.set(ACCESS, tokens.access_token, { ...cookieOptions, maxAge: tokens.expires_in });
  cookies.set(REFRESH, tokens.refresh_token, { ...cookieOptions, maxAge: REFRESH_MAX_AGE });
}

function clearTokens(cookies: AstroCookies) {
  cookies.delete(ACCESS, { path: '/' });
  cookies.delete(REFRESH, { path: '/' });
  cookies.delete(BRANCH, { path: '/' });
}

/** A new sign-in asks for the branch again. */
export function startSession(cookies: AstroCookies, tokens: Tokens) {
  saveTokens(cookies, tokens);
  cookies.delete(BRANCH, { path: '/' });
}

export function saveBranch(cookies: AstroCookies, branchId: string) {
  cookies.set(BRANCH, branchId, { ...cookieOptions, maxAge: REFRESH_MAX_AGE });
}

/** The branch the user works in: their only one, or the one they picked (if they still belong to it). */
export function activeBranch(cookies: AstroCookies, session: Session) {
  if (session.branches.length === 1) return session.branches[0];
  const chosen = cookies.get(BRANCH)?.value;
  return session.branches.find((b) => b.id === chosen);
}

/** The signed-in user's session (and a valid access token), refreshing the pair when the access token has expired. */
export async function resolveSession(
  cookies: AstroCookies,
  meta: ClientMeta,
): Promise<{ session: Session; accessToken: string } | null> {
  const access = cookies.get(ACCESS)?.value;
  if (access) {
    const session = await me(access);
    if (session) return { session, accessToken: access };
  }
  const refreshToken = cookies.get(REFRESH)?.value;
  if (!refreshToken) return null;

  const tokens = await refreshOnce(refreshToken, meta);
  if (!tokens) {
    clearTokens(cookies);
    return null;
  }
  saveTokens(cookies, tokens);
  const session = await me(tokens.access_token);
  return session && { session, accessToken: tokens.access_token };
}

export async function endSession(cookies: AstroCookies, meta: ClientMeta) {
  const refreshToken = cookies.get(REFRESH)?.value;
  if (refreshToken) await logout(refreshToken, meta).catch(() => {}); // the cookies go away regardless
  clearTokens(cookies);
}

// Refresh tokens are single use: two parallel requests (tabs, prefetch) sending the same one would trip the
// API's reuse detection and end the session. Requests with the same token share one refresh, and the result
// is kept briefly for requests that arrive before the browser has stored the new cookies.
// shortcut: per-process memory; with several frontend instances, move this to a shared store (Redis).
const inflight = new Map<string, Promise<Tokens | null>>();

function refreshOnce(refreshToken: string, meta: ClientMeta) {
  let pending = inflight.get(refreshToken);
  if (!pending) {
    pending = refresh(refreshToken, meta);
    inflight.set(refreshToken, pending);
    const forget = () => setTimeout(() => inflight.delete(refreshToken), 10_000);
    pending.then(forget, forget);
  }
  return pending;
}

// One-time message for the next page (e.g. a generated temporary password): never in the URL, read once, gone.
const FLASH = 'osmi_flash';

export function setFlash(cookies: AstroCookies, data: Record<string, string>) {
  cookies.set(FLASH, JSON.stringify(data), { ...cookieOptions, maxAge: 60 });
}

export function takeFlash(cookies: AstroCookies): Record<string, string> {
  const raw = cookies.get(FLASH)?.value;
  if (!raw) return {};
  cookies.delete(FLASH, { path: '/' });
  try {
    return JSON.parse(raw);
  } catch {
    return {};
  }
}
