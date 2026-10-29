// Server-side client for suppliers: a global catalog; their purchases cover only the branches the person belongs to.
import { request } from './api';

export interface SupplierRow {
  id: string;
  name: string;
  phone: string | null;
  email: string | null;
  deleted_at: string | null;
  products: number;
  last_purchase_at: string | null;
}
export interface Supplier extends SupplierRow {
  created_at: string;
  purchases: number;
}
export interface SupplierInput { name: string; phone: string | null; email: string | null }
export interface SupplierHistoryEntry {
  changed_at: string;
  entity_type: 'supplier' | 'product_supplier';
  action: 'INSERT' | 'UPDATE' | 'DELETE' | 'RESTORE';
  changed_by_email: string | null;
  changed_fields: string[] | null;
  old_data: Record<string, unknown> | null;
  new_data: Record<string, unknown> | null;
  product: string | null;
}
type Paged<T> = { items: T[]; page: number; page_size: number; has_more: boolean };

const json = (method: string, body: unknown = {}) => ({ method, body: JSON.stringify(body) });

export const listSuppliers = (t: string, p: { q?: string; include_deleted?: boolean; page?: number; page_size?: number }) =>
  request<{ items: SupplierRow[]; total: number; page: number; page_size: number }>(t, `/suppliers?${new URLSearchParams(
    Object.entries(p).filter(([, v]) => v !== undefined && v !== '').map(([k, v]) => [k, String(v)]))}`);
export const getSupplier = (t: string, id: string) => request<Supplier>(t, `/suppliers/${id}`);
/** force: save even if another supplier has the same name (the API answers 409 duplicate_name otherwise). */
export const createSupplier = (t: string, data: SupplierInput, force = false) =>
  request<Supplier>(t, `/suppliers?force=${force}`, json('POST', data));
export const updateSupplier = (t: string, id: string, data: Partial<SupplierInput>, force = false) =>
  request<Supplier>(t, `/suppliers/${id}?force=${force}`, json('PATCH', data));
export const deleteSupplier = (t: string, id: string) => request<void>(t, `/suppliers/${id}`, { method: 'DELETE' });
export const restoreSupplier = (t: string, id: string) => request<Supplier>(t, `/suppliers/${id}/restore`, json('POST'));
export const supplierHistory = (t: string, id: string, page: number) =>
  request<Paged<SupplierHistoryEntry>>(t, `/suppliers/${id}/history?page=${page}&page_size=15`);
export const supplierProducts = (t: string, id: string, page: number) =>
  request<Paged<{ id: string; name: string; barcode: string | null; cost: string; price: string; linked_at: string }>>(
    t, `/suppliers/${id}/products?page=${page}&page_size=25`);
export const linkProduct = (t: string, id: string, productId: string) =>
  request<{ created: boolean }>(t, `/suppliers/${id}/products/${productId}`, json('POST'));
export const unlinkProduct = (t: string, id: string, productId: string) =>
  request<void>(t, `/suppliers/${id}/products/${productId}`, { method: 'DELETE' });
export const supplierPurchases = (t: string, id: string, page: number) =>
  request<Paged<{ id: string; purchased_at: string; branch_id: string; branch: string; total: string; reference: string | null; items: number }>>(
    t, `/suppliers/${id}/purchases?page=${page}&page_size=10`);
export const supplierSummary = (t: string, id: string) =>
  request<{ purchases: number; total_spent: string; avg_purchase: string; last_purchase_at: string | null }>(t, `/suppliers/${id}/summary`);
export const priceHistory = (t: string, id: string, productId: string) =>
  request<{ purchase_id: string; purchased_at: string; unit_cost: string; quantity: string; branch: string }[]>(
    t, `/suppliers/${id}/price-history/${productId}?limit=10`);

/** API error on save -> per-field messages (name, phone, email) and the duplicate-name matches, if that was it. */
export function supplierSaveError(status: number, detail: any, e: Record<string, string>) {
  if (status === 409 && detail?.code === 'duplicate_name') return { duplicate: (detail.matches ?? []) as { id: string; name: string }[] };
  if (status === 422 && Array.isArray(detail)) {
    const fields: Record<string, string> = {};
    for (const d of detail) {
      const f = String(d?.loc?.at(-1) ?? '');
      if (f in e) fields[f] = e[f];
    }
    if (Object.keys(fields).length) return { fields };
  }
  return {};
}
