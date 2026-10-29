// Server-side client for transfers between branches (scoped to the working branch).
import { request } from './api';

export interface Transfer {
  id: string;
  folio: string;
  status: 'IN_TRANSIT' | 'RECEIVED' | 'CANCELLED';
  direction?: 'outgoing' | 'incoming';
  from_branch_id: string;
  from_branch: string;
  to_branch_id: string;
  to_branch: string;
  sent_by: string;
  last_updated_by: string;
  created_at: string;
  updated_at: string;
  item_count?: number;
  notes?: string | null;
  items?: { product_id: string; product: string; quantity: number }[];
  history?: { changed_at: string; from_status: string | null; to_status: string; changed_by: string }[];
}

export function listTransfers(t: string, b: string, p: { direction?: string; status?: string; page: number }) {
  const q = new URLSearchParams({ page: String(p.page), page_size: '25', ...(p.direction && { direction: p.direction }), ...(p.status && { status: p.status }) });
  return request<{ items: Transfer[]; has_more: boolean }>(t, `/transfers?${q}`, {}, b);
}
export const getTransfer = (t: string, b: string, id: string) => request<Transfer>(t, `/transfers/${id}`, {}, b);
export const sendTransfer = (t: string, b: string, data: Record<string, unknown>) =>
  request<Transfer>(t, '/transfers', { method: 'POST', body: JSON.stringify(data) }, b);
export const changeTransfer = (t: string, b: string, id: string, action: 'receive' | 'cancel') =>
  request<Transfer>(t, `/transfers/${id}/${action}`, { method: 'POST' }, b);
export const availableProducts = (t: string, b: string, q: string) =>
  request<{ id: string; name: string; unit: string; current_stock: number }[]>(t, `/transfers/available-products?${new URLSearchParams({ q, limit: '10' })}`, {}, b);
export const listBranches = (t: string) => request<{ id: string; name: string; code: string }[]>(t, '/branches');
