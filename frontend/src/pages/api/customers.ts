// Customer search for pickers (e.g. linking a customer to an event). Same shape as /api/users.
import type { APIRoute } from 'astro';
import { ApiError } from '@/lib/api';
import { formatPhone, searchCustomers } from '@/lib/customers';

export const GET: APIRoute = async ({ url, locals }) => {
  const q = (url.searchParams.get('q') ?? '').trim();
  if (q.length < 2) return Response.json([]);
  try {
    const customers = await searchCustomers(locals.accessToken!, q.slice(0, 100));
    return Response.json(
      customers.map((c) => ({ id: c.id, title: c.full_name, subtitle: [c.company, formatPhone(c.phone)].filter(Boolean).join(', ') })),
    );
  } catch (e) {
    if (e instanceof ApiError && e.status === 403) return Response.json([]); // no customers.read
    throw e;
  }
};
