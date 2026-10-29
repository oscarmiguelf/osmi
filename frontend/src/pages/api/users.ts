// People search for the share dialog. The browser can't call the API directly (the token lives in an HttpOnly cookie).
import type { APIRoute } from 'astro';
import { searchUsers } from '@/lib/calendar';

export const GET: APIRoute = async ({ url, locals }) => {
  const q = (url.searchParams.get('q') ?? '').trim();
  if (q.length < 2) return Response.json([]);
  const users = await searchUsers(locals.accessToken!, q.slice(0, 100));
  return Response.json(users.map((u) => ({ id: u.id, title: u.name, subtitle: u.email })));
};
