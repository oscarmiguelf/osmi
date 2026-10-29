// Server-side client for physical counts (working branch). Counters don't get system quantities (blind count).
import { API_URL } from 'astro:env/server';
import { request } from './api';

export type StocktakeStatus = 'OPEN' | 'COMPLETED' | 'CANCELLED';

export interface Stocktake {
  id: string;
  folio: string;
  branch: string;
  status: StocktakeStatus;
  notes: string | null;
  created_at: string;
  created_by: string;
  closed_at: string | null;
  closed_by: string | null;
  counted_items?: number;
}

export interface Totals {
  counted_items: number;
  items_with_difference?: number;
  surplus_units?: number;
  shortage_units?: number;
  surplus_value?: number;
  shortage_value?: number;
  difference_value_at_cost?: number;
}

export interface CountItem {
  id: string;
  product_id: string;
  product: string;
  barcode: string | null;
  unit: string;
  counted_quantity: number;
  system_quantity?: number;
  difference?: number;
  applied_adjustment?: number | null;
  notes: string | null;
  counted_by: string;
  updated_at: string;
}

const json = (method: string, body: unknown = {}) => ({ method, body: JSON.stringify(body) });
const qs = (p: Record<string, string | number | boolean | undefined>) =>
  new URLSearchParams(Object.entries(p).filter(([, v]) => v !== undefined && v !== '' && v !== false).map(([k, v]) => [k, String(v)]));

export const listStocktakes = (t: string, b: string, p: Record<string, string | number | undefined>) =>
  request<{ items: Stocktake[]; has_more: boolean }>(t, `/stocktakes?${qs({ page_size: 25, ...p })}`, {}, b);
export const currentStocktake = (t: string, b: string) => request<Stocktake | undefined>(t, '/stocktakes/current', {}, b);
export const openStocktake = (t: string, b: string, notes: string | null) => request<Stocktake>(t, '/stocktakes', json('POST', { notes }), b);
export const getStocktake = (t: string, b: string, id: string) =>
  request<Stocktake & { totals: Totals; can_see_system: boolean; uncounted: number | null }>(t, `/stocktakes/${id}`, {}, b);
export const stocktakeItems = (t: string, b: string, id: string, p: Record<string, string | number | boolean | undefined>) =>
  request<{ items: CountItem[]; has_more: boolean }>(t, `/stocktakes/${id}/items?${qs({ page_size: 100, ...p })}`, {}, b);
export const countProduct = (t: string, b: string, id: string, productId: string, body: { counted_quantity: string; notes?: string | null }) =>
  request<CountItem>(t, `/stocktakes/${id}/items/${productId}`, json('PUT', body), b);
export const removeCount = (t: string, b: string, id: string, productId: string) =>
  request<void>(t, `/stocktakes/${id}/items/${productId}`, { method: 'DELETE' }, b);
export const uncountedProducts = (t: string, b: string, id: string, p: Record<string, string | number | undefined>) =>
  request<{ items: { id: string; name: string; barcode: string | null; unit: string; current_stock: number; category: string | null }[]; has_more: boolean }>(
    t, `/stocktakes/${id}/uncounted?${qs({ page_size: 100, ...p })}`, {}, b);
export const completeStocktake = (t: string, b: string, id: string) => request<unknown>(t, `/stocktakes/${id}/complete`, json('POST'), b);
export const cancelStocktake = (t: string, b: string, id: string) => request<unknown>(t, `/stocktakes/${id}/cancel`, json('POST'), b);
export const stocktakeResult = (t: string, b: string, id: string) =>
  request<Stocktake & { totals: Totals; items: CountItem[]; movements: { product: string; quantity: number; stock_before: number; stock_after: number }[] }>(
    t, `/stocktakes/${id}/result`, {}, b);
export const stocktakeHistory = (t: string, b: string, id: string) =>
  request<{ items: { changed_at: string; entity_type: string; action: string; changed_by: string | null; changed_fields: string[] | null;
    product: string | null; old_counted: string | null; new_counted: string | null; status: string | null }[] }>(t, `/stocktakes/${id}/history?page_size=50`, {}, b);

/** The count sheet as the API sends it (CSV), passed straight through to the browser. */
export const exportSheet = (t: string, b: string, id: string, lang: string) =>
  fetch(`${API_URL}/stocktakes/${id}/export?lang=${lang}`, { headers: { authorization: `Bearer ${t}`, 'x-branch-id': b } });
