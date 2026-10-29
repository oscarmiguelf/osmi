// Server-side client for products, catalogs, inventory and purchases.
import { fmt, money, type Locale } from '@/i18n';
import type { OutgoingPayment, PaymentInput } from './expenses';
import { ApiError, request } from './api';

export interface ProductImage { id: string; content_type: string; size_bytes: number }
export interface Product {
  id: string;
  name: string;
  /** Package / membership it gives when sold */
  benefit?: import('./benefits').ProductBenefit | null;
  /** Services: how long it takes (minutes) */
  duration_minutes?: number | null;
  /** Main image (first in order), null when it has none */
  image_id?: string | null;
  images?: ProductImage[];
  description: string | null;
  barcode: string | null;
  brand_id: string | null;
  brand: string | null;
  cost: number;
  price: number;
  min_stock: number;
  product_type_id: string;
  type: string;
  tracks_stock: boolean;
  is_kit: boolean;
  unit_of_measure_id: string;
  unit: string;
  category_id: string | null;
  category: string | null;
  tax_rate_id: string;
  tax_rate_name: string;
  tax_rate: number;
  current_stock: number;
  is_low_stock: boolean;
  deleted_at: string | null;
  suppliers?: { id: string; name: string }[];
  components?: { product_id: string; name: string; quantity: number }[];
}

export type CatalogKey = 'categories' | 'units' | 'product-types' | 'suppliers' | 'tax-rates' | 'brands';
export interface CatalogItem {
  id: string;
  name: string;
  deleted_at: string | null;
  phone?: string | null;
  email?: string | null;
  rate?: number;
  is_default?: boolean;
  tracks_stock?: boolean;
  is_kit?: boolean;
  /** Brands: active products using it */
  products?: number;
}

export interface Movement {
  id: string;
  created_at: string;
  movement_type: string;
  product_id: string;
  product: string;
  quantity: number;
  stock_after: number;
  created_by_email: string;
  notes: string | null;
  reference: string | null;
}

export interface Purchase {
  id: string;
  purchased_at: string;
  total: number;
  reference: string | null;
  notes?: string | null;
  supplier_id: string | null;
  supplier: string | null;
  created_by_email: string;
  item_count?: number;
  deleted_at?: string | null;
  items?: { product_id: string; product: string; quantity: number; unit_cost: number; line_total: number }[];
  /** What is still owed to the supplier (total - payments) */
  owed?: number | string;
  paid?: number | string;
  payments?: OutgoingPayment[];
}

const json = (method: string, body: unknown = {}) => ({ method, body: JSON.stringify(body) });
const qs = (p: Record<string, string | number | boolean | undefined | null>) =>
  new URLSearchParams(Object.entries(p).filter(([, v]) => v !== undefined && v !== null && v !== '').map(([k, v]) => [k, String(v)]));

// --- catalogs ---
export const listCatalog = (t: string, key: CatalogKey, includeDeleted = false) =>
  // Suppliers have their own paginated API; /options is the whole list for selectors
  request<CatalogItem[]>(t, `/${key === 'suppliers' ? 'suppliers/options' : key}?include_deleted=${includeDeleted}`);
export const createCatalog = (t: string, key: CatalogKey, data: Record<string, unknown>) =>
  request<CatalogItem>(t, `/${key}`, json('POST', data));
export const updateCatalog = (t: string, key: CatalogKey, id: string, data: Record<string, unknown>) =>
  request<CatalogItem>(t, `/${key}/${id}`, json('PATCH', data));
export const mergeBrands = (t: string, fromIds: string[], toId: string) =>
  request<{ products_moved: number; brands_removed: number }>(t, '/brands/merge', json('POST', { from_ids: fromIds, to_id: toId }));
export const deleteCatalog = (t: string, key: CatalogKey, id: string) => request<void>(t, `/${key}/${id}`, { method: 'DELETE' });
export const restoreCatalog = (t: string, key: CatalogKey, id: string) =>
  request<CatalogItem>(t, `/${key}/${id}/restore`, json('POST'));

// --- products (stock of the working branch when a branch is sent) ---
export const searchProducts = (t: string, b: string | undefined, p: Record<string, string | number | boolean | undefined>) =>
  request<{ items: Product[]; total: number }>(t, `/products?${qs({ page_size: 25, ...p })}`, {}, b);
export const getProduct = (t: string, b: string | undefined, id: string) => request<Product>(t, `/products/${id}`, {}, b);
export const createProduct = (t: string, b: string | undefined, data: Record<string, unknown>) =>
  request<Product>(t, '/products', json('POST', data), b);
export const updateProduct = (t: string, b: string | undefined, id: string, data: Record<string, unknown>) =>
  request<Product>(t, `/products/${id}`, json('PATCH', data), b);
export const deleteProduct = (t: string, id: string) => request<void>(t, `/products/${id}`, { method: 'DELETE' });
export const restoreProduct = (t: string, id: string) => request<Product>(t, `/products/${id}/restore`, json('POST'));
export const setProductSuppliers = (t: string, id: string, ids: string[]) =>
  request<unknown>(t, `/products/${id}/suppliers`, json('PUT', { supplier_ids: ids }));
export const setKitComponents = (t: string, id: string, components: { product_id: string; quantity: string }[]) =>
  request<unknown>(t, `/products/${id}/kit-components`, json('PUT', { components }));
export const uploadProductImage = (t: string, id: string, file: File) => {
  const body = new FormData();
  body.set('file', file);
  return request<ProductImage[]>(t, `/products/${id}/images`, { method: 'POST', body });
};
export const deleteProductImage = (t: string, id: string, imageId: string) =>
  request<ProductImage[]>(t, `/products/${id}/images/${imageId}`, { method: 'DELETE' });
export const orderProductImages = (t: string, id: string, imageIds: string[]) =>
  request<ProductImage[]>(t, `/products/${id}/images/order`, json('PUT', { image_ids: imageIds }));
export const MAX_IMAGES = 5;
/** The files of a form's "images" field (an empty file input posts one empty entry). */
export const imageFiles = (data: FormData) => data.getAll('images').filter((f): f is File => f instanceof File && f.size > 0);
/** Uploads up to `room` files one by one; the names of those that didn't go (wrong type, too big, no room) come back. */
export async function uploadImages(t: string, id: string, files: File[], room: number) {
  let uploaded = 0;
  const failed: string[] = files.slice(Math.max(room, 0)).map((f) => f.name);
  for (const file of files.slice(0, Math.max(room, 0))) {
    try {
      await uploadProductImage(t, id, file);
      uploaded += 1;
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
      failed.push(file.name);
    }
  }
  return { uploaded, failed };
}
/** Where the browser loads an image from (through this server, with the person's session). */
export const imageUrl = (productId: string, imageId: string) => `/api/products/${productId}/images/${imageId}`;
export const productHistory = (t: string, id: string) =>
  request<{ items: { changed_at: string; entity_type: string; action: string; changed_by_email: string | null; changed_fields: string[] | null; old_data: Record<string, unknown> | null; new_data: Record<string, unknown> | null }[] }>(t, `/products/${id}/history?page_size=15`);

// --- inventory (working branch) ---
export const productStockByBranch = (t: string, id: string) =>
  request<{ branch_id: string; branch: string; current_stock: number }[]>(t, `/products/${id}/stock`);
export const kardex = (t: string, b: string, id: string, page = 1) =>
  request<{ items: Movement[]; has_more: boolean }>(t, `/products/${id}/kardex?page=${page}&page_size=15`, {}, b);
export const branchStock = (t: string, b: string, p: Record<string, string | number | boolean | undefined>) =>
  request<{ items: (Product & { id: string })[]; total: number }>(t, `/stock?${qs({ page_size: 25, ...p })}`, {}, b);
export const inventoryMovements = (t: string, b: string, p: Record<string, string | number | undefined>) =>
  request<{ items: Movement[]; has_more: boolean }>(t, `/inventory/movements?${qs({ page_size: 25, ...p })}`, {}, b);
export const adjustStock = (t: string, b: string, data: { product_id: string; quantity: string; notes: string }) =>
  request<unknown>(t, '/inventory/adjustments', json('POST', data), b);

// --- purchases (working branch) ---
/** The moving average cost changes on every purchase and void; the API says which products moved. */
export type CostChange = { product_id: string; product: string; old_cost: number; new_cost: number };
export const listPurchases = (t: string, b: string, p: Record<string, string | number | boolean | undefined>) =>
  request<{ items: Purchase[]; has_more: boolean }>(t, `/purchases?${qs({ page_size: 25, ...p })}`, {}, b);
export const getPurchase = (t: string, b: string, id: string) => request<Purchase>(t, `/purchases/${id}`, {}, b);
export const createPurchase = (t: string, b: string, data: Record<string, unknown>) =>
  request<Purchase & { cost_changes: CostChange[] }>(t, '/purchases', json('POST', data), b);
/** 'Cemento $50.00 → $60.00, ...' for a flash message (a cookie: capped at 5 products). */
export function costChangesText(changes: CostChange[], locale: Locale, template: string): string {
  const shown = changes.slice(0, 5).map((c) =>
    fmt(template, { product: c.product, from: money(locale, Number(c.old_cost)), to: money(locale, Number(c.new_cost)) }));
  return changes.length > 5 ? `${shown.join(', ')}…` : shown.join(', ');
}
export const updatePurchase = (t: string, b: string, id: string, data: Record<string, unknown>) =>
  request<Purchase>(t, `/purchases/${id}`, json('PATCH', data), b);
export const voidPurchase = (t: string, b: string, id: string) =>
  request<{ voided: boolean; cost_changes: CostChange[]; cash_returned: number }>(t, `/purchases/${id}`, { method: 'DELETE' }, b);
export const payPurchase = (t: string, b: string, id: string, data: PaymentInput) =>
  request<Purchase>(t, `/purchases/${id}/payments`, json('POST', data), b);
export const purchaseHistory = (t: string, b: string, id: string) =>
  request<{ items: { changed_at: string; entity_type: string; action: string; changed_by_email: string | null; changed_fields: string[] | null }[] }>(t, `/purchases/${id}/history?page_size=50`, {}, b);
export const purchaseSummary = (t: string, b: string, from: string, to: string, tz: string) =>
  request<{ total: number; by_supplier: { supplier_id: string | null; supplier: string | null; purchases: number; total: number }[]; by_day: { day: string; purchases: number; total: number }[] }>(
    t, `/purchases/summary?${qs({ from, to, tz })}`, {}, b);
export const lastPurchasePrice = (t: string, id: string) =>
  request<{ unit_cost: number; purchased_at: string; supplier: string | null; branch: string; purchase_id: string } | null>(t, `/products/${id}/purchase-price`);
export const productPurchases = (t: string, b: string, id: string) =>
  request<{ items: { purchase_id: string; purchased_at: string; reference: string | null; supplier: string | null; quantity: number; unit_cost: number; line_total: number }[]; has_more: boolean }>(
    t, `/products/${id}/purchases?page_size=10`, {}, b);

/** Rows posted by ItemsEditor: parallel item_product / item_name / item_qty (/ item_cost) fields. */
export function readItems(data: FormData) {
  const names = data.getAll('item_name').map(String);
  const qtys = data.getAll('item_qty').map(String);
  const costs = data.getAll('item_cost').map(String);
  return data.getAll('item_product').map((id, i) => ({
    product_id: String(id), name: names[i] ?? '', quantity: qtys[i] ?? '', ...(costs.length && { unit_cost: costs[i] ?? '' }),
  }));
}

export const PRODUCT_FIELDS = ['name', 'product_type_id', 'unit_of_measure_id', 'category_id', 'brand_id', 'barcode', 'min_stock',
  'price', 'cost', 'tax_rate_id', 'description', 'duration_minutes'] as const;

/** Form -> API body. Disabled fields aren't posted, so they're left out (the API keeps them). Prices only with products.prices. */
export function productPayload(data: FormData, canPrice: boolean) {
  const body: Record<string, string | null> = {};
  for (const f of PRODUCT_FIELDS) {
    if (!data.has(f) || (!canPrice && ['price', 'cost', 'tax_rate_id'].includes(f))) continue;
    const v = String(data.get(f) ?? '').trim();
    body[f] = v === '' ? (f === 'min_stock' || f === 'price' || f === 'cost' ? '0' : null) : v;
  }
  return body;
}

export function productValues(p?: Partial<Product>): Record<string, string> {
  return Object.fromEntries(PRODUCT_FIELDS.map((f) => [f, p?.[f] === null || p?.[f] === undefined ? '' : String(p[f])]));
}
