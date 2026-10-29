// Server-side client for sales, deliveries, credit payments, returns and quotes.
import { fmt, type Dict } from '@/i18n';
import { request } from './api';

export type SaleStatus = 'PAID' | 'PENDING' | 'RETURNED';

export interface SaleSummary {
  id: string;
  folio: string;
  sold_at: string;
  total: number;
  status: SaleStatus;
  customer: string | null;
  seller: string;
  cash_register: string;
  reserved_items: number;
}

export interface SaleItem {
  id: string;
  product_id: string;
  product: string;
  unit: string;
  quantity: number;
  unit_price: number;
  discount: number;
  line_total: number;
  tax_rate: number;
  tax_amount: number;
  fulfillment: 'DELIVERED' | 'RESERVED';
  promotion: string | null;
  returned_quantity: number;
  returnable_quantity: number;
}

export interface Sale extends SaleSummary {
  appointment_id?: string | null;
  customer_phone?: string | null;
  offline_folio?: string | null;
  appointment_at?: string | null;
  subtotal: number;
  discount: number;
  tax_total: number;
  branch: string;
  branch_address: string | null;
  branch_phone: string | null;
  customer_id: string | null;
  credit_outstanding: number;
  quote_id: string | null;
  quote_folio: string | null;
  items: SaleItem[];
  payments: { id: string; created_at: string; kind: 'sale' | 'credit_payment'; method: string; is_credit: boolean; amount: number;
    amount_tendered: number | null; change_given: number | null; reference: string | null; created_by: string }[];
  returns: { id: string; folio: string; created_at: string; refund_total: number; reason: string | null; processed_by: string }[];
  tax_breakdown: { tax_name: string; tax_rate: number; taxable_base: number; tax_amount: number; gross_amount: number }[];
}

export interface Preview {
  lines: { product_id: string; product: string; quantity: number; unit_price: number; discount: number; promotion: string | null;
    line_total: number; tax_amount: number }[];
  subtotal: number;
  discount: number;
  total: number;
  tax_total: number;
  stock_warnings?: { product: string; needed: number; available: number }[];
}

export interface Promotion {
  promotion_id: string;
  product_id: string;
  product: string;
  name: string;
  kind: 'PERCENT' | 'AMOUNT' | 'BUY_X_GET_Y';
  percent: number | null;
  amount: number | null;
  buy_quantity: number | null;
  get_quantity: number | null;
}

export interface SaleReturn {
  id: string;
  folio: string;
  created_at: string;
  refund_total: number;
  reason: string | null;
  sale_id: string;
  sale_folio: string;
  processed_by: string;
  customer?: string | null;
  cash_register?: string;
  items?: { sale_item_id: string; product: string; quantity: number; refund_amount: number }[];
  refunds?: { method: string; is_credit: boolean; amount: number; reference: string | null }[];
}

const json = (method: string, body: unknown = {}) => ({ method, body: JSON.stringify(body) });
const qs = (p: Record<string, string | number | boolean | undefined | null>) =>
  new URLSearchParams(Object.entries(p).filter(([, v]) => v !== undefined && v !== null && v !== '').map(([k, v]) => [k, String(v)]));

// --- sales (working branch) ---
export const previewSale = (t: string, b: string, body: unknown) => request<Preview>(t, '/sales/preview', json('POST', body), b);
export const createSale = (t: string, b: string, body: unknown) => request<Sale>(t, '/sales', json('POST', body), b);
export const listSales = (t: string, b: string, p: Record<string, string | number | undefined>) =>
  request<{ items: SaleSummary[]; has_more: boolean }>(t, `/sales?${qs({ page_size: 25, ...p })}`, {}, b);
export const getSale = (t: string, b: string, id: string) => request<Sale>(t, `/sales/${id}`, {}, b);
export const saleHistory = (t: string, b: string, id: string) =>
  request<{ status: { changed_at: string; from_status: string | null; to_status: SaleStatus; changed_by: string }[];
    fulfillment: { changed_at: string; product: string; from_status: string | null; to_status: string; changed_by: string }[] }>(
    t, `/sales/${id}/history`, {}, b);
export const deliverItems = (t: string, b: string, id: string, ids: string[]) =>
  request<Sale>(t, `/sales/${id}/deliver`, json('POST', { sale_item_ids: ids }), b);
export const addAbono = (t: string, b: string, id: string, body: unknown) => request<Sale>(t, `/sales/${id}/payments`, json('POST', body), b);
/** Several payments (methods) to one sale at once: an appointment's deposit part cash, part card */
export const payBatch = (t: string, b: string, saleId: string, payments: { payment_method_id: string; amount: string; amount_tendered: string | null; reference: string | null }[]) =>
  request<Sale>(t, `/sales/${saleId}/payments/batch`, json('POST', { payments }), b);
export const customerAbono = (t: string, b: string, body: unknown) =>
  request<{ applied: { folio: string; amount: number }[]; change: number | null; owed_after: number }>(t, '/sales/credit-payments', json('POST', body), b);
export const pendingCredit = (t: string, b: string, customerId?: string) =>
  request<{ sale_id: string; folio: string; sold_at: string; total: number; credit_outstanding: number; customer_id: string; customer: string }[]>(
    t, `/sales/pending-credit${customerId ? `?customer_id=${customerId}` : ''}`, {}, b);
export const pendingDeliveries = (t: string, b: string) =>
  request<{ sale_id: string; folio: string; sold_at: string; customer: string | null; sale_item_id: string; product: string; quantity: number }[]>(
    t, '/sales/pending-deliveries', {}, b);
export const salesReport = (t: string, b: string, from: string, to: string) =>
  request<{ totals: { sales: number; total: number; tax: number; sale_discounts: number; returns: number; net: number };
    by_method: { method: string; is_credit: boolean; payments: number; amount: number }[];
    by_seller: { seller: string; sales: number; total: number }[];
    top_products: { product_id: string; product: string; quantity: number; total: number; margin: number }[];
    promotions: { name: string; lines: number; discount_given: number }[] }>(t, `/sales/report?${qs({ from, to })}`, {}, b);
export const activePromotions = (t: string, b: string) => request<Promotion[]>(t, '/promotions/active', {}, b);
export const previewReturn = (t: string, b: string, id: string, items: unknown) =>
  request<{ items: { sale_item_id: string; product: string; quantity: number; refund_amount: number }[]; refund_total: number;
    credit_refund: number; money_refund: number; completes_sale: boolean }>(t, `/sales/${id}/returns/preview`, json('POST', { items }), b);
export const createReturn = (t: string, b: string, id: string, body: unknown) =>
  request<SaleReturn>(t, `/sales/${id}/returns`, json('POST', body), b);
export const listReturns = (t: string, b: string, p: Record<string, string | number | undefined>) =>
  request<{ items: SaleReturn[]; has_more: boolean }>(t, `/returns?${qs({ page_size: 25, ...p })}`, {}, b);

// --- quotes (working branch) ---
export type QuoteStatus = 'OPEN' | 'CONVERTED' | 'CANCELLED';

export interface QuoteSummary {
  id: string;
  folio: string;
  created_at: string;
  valid_until: string;
  total: number;
  status: QuoteStatus;
  is_expired: boolean;
  customer: string | null;
  created_by: string;
  item_count: number;
}

export interface Quote extends QuoteSummary {
  /** The appointment / event it belongs to */
  appointment_id?: string | null;
  appointment_title?: string | null;
  appointment_at?: string | null;
  branch: string;
  branch_address: string | null;
  branch_phone: string | null;
  customer_id: string | null;
  customer_name: string | null;
  customer_phone: string | null;
  customer_email: string | null;
  subtotal: number;
  discount: number;
  notes: string | null;
  sale_id: string | null;
  sale_folio: string | null;
  items: { id: string; product_id: string; product: string; unit: string; quantity: number; unit_price: number; discount: number;
    line_total: number; current_price: number; product_active: boolean }[];
  tax_breakdown: { tax_name: string; tax_rate: number; tax_amount: number }[];
}

export interface QuoteDraft {
  appointment_id?: string | null;
  appointment_at?: string | null;
  quote_id: string;
  folio: string;
  customer_id: string | null;
  customer: string | null;
  discount: number;
  items: { product_id: string; product: string; unit: string; quantity: number; unit_price: number; discount: number;
    current_price: number; price_changed: boolean; available: boolean }[];
  stock_warnings: { product: string; needed: number; available: number }[];
  removed_products: string[];
}

export const previewQuote = (t: string, b: string, body: unknown) => request<Preview & { valid_until: string }>(t, '/quotes/preview', json('POST', body), b);
export const createQuote = (t: string, b: string, body: unknown) =>
  request<Quote & { stock_warnings: Preview['stock_warnings'] }>(t, '/quotes', json('POST', body), b);
export const listQuotes = (t: string, b: string, p: Record<string, string | number | undefined>) =>
  request<{ items: QuoteSummary[]; has_more: boolean }>(t, `/quotes?${qs({ page_size: 25, ...p })}`, {}, b);
export const getQuote = (t: string, b: string, id: string) => request<Quote>(t, `/quotes/${id}`, {}, b);
export const cancelQuote = (t: string, b: string, id: string) => request<Quote>(t, `/quotes/${id}/cancel`, json('POST'), b);
export const quoteHistory = (t: string, b: string, id: string) =>
  request<{ changed_at: string; entity_type: string; action: string; changed_by: string | null; to_status: string | null }[]>(t, `/quotes/${id}/history`, {}, b);
export const duplicateQuote = (t: string, b: string, id: string) =>
  request<{ customer_id: string | null; customer_name: string | null; customer: string | null; discount: number; notes: string | null;
    items: { product_id: string; product: string; unit: string; quantity: number; unit_price: number; discount: number; current_price: number }[] }>(
    t, `/quotes/${id}/duplicate`, json('POST'), b);
export const convertDraft = (t: string, b: string, id: string) => request<QuoteDraft>(t, `/quotes/${id}/convert-draft`, {}, b);
export const convertQuote = (t: string, b: string, id: string, body: unknown) =>
  request<{ sale: Sale; quote: Quote }>(t, `/quotes/${id}/convert`, json('POST', body), b);

/**
 * API error -> what the person reads (shared by the pages and the live preview endpoints).
 * detail: the API's error detail; t: the dictionary of the person's language.
 */
export function saleErrorText(status: number, detail: any, t: Dict): { text: string; items?: string[] } {
  const s = t.sales;
  if (status === 403) return { text: typeof detail === 'string' && detail.includes('prices') ? s.errors.prices : t.ui.forbidden };
  if (detail?.code === 'register') return { text: s.errors.register };
  if (detail?.code === 'quote_status') return { text: s.errors.quoteStatus };
  if (detail?.code === 'quote_expired') return { text: s.errors.quoteExpired };
  if (detail?.code === 'appointment_charged') return { text: s.errors.appointmentCharged };
  if (detail?.code === 'appointment_status') return { text: s.errors.appointmentStatus };
  if (Array.isArray(detail?.products)) {
    return { text: s.errors.stock, items: detail.products.map((p: any) => fmt(s.errors.stockItem, { product: p.product, needed: Number(p.needed), available: Number(p.available) })) };
  }
  if (detail?.credit_limit !== undefined) return { text: fmt(s.errors.creditLimit, { available: Number(detail.available).toFixed(2) }) };
  const field: string = detail?.field ?? '';
  const message: string = typeof detail?.message === 'string' ? detail.message : '';
  if (message.includes('whole units')) return { text: fmt(s.errors.whole, { product: message.replace(' is counted in whole units', '') }) };
  if (field === 'payments') return { text: s.errors.payments };
  if (field === 'customer_id') return { text: message.includes('customer of the quote') ? s.errors.quoteCustomer : s.errors.creditCustomer };
  if (field.endsWith('unit_price')) return { text: s.errors.price };
  if (field.endsWith('promotion_id')) return { text: s.errors.promotion };
  if (field.endsWith('discount') || field === 'discount') return { text: s.errors.discount };
  if (field.includes('amount_tendered')) return { text: s.errors.tendered };
  if (field === 'items' && message.startsWith('add')) return { text: s.errors.noItems };
  if (field === 'valid_until') return { text: t.quotes.errors.validity };
  if (status === 422) return { text: t.ui.formError };
  return { text: t.ui.failed };
}

/** What didn't match when a sale made without internet came back (stock that wasn't there, a price that changed). */
export interface OfflineIssue { id: string; sale_id: string; folio: string; offline_folio: string; sold_at: string; kind: 'stock' | 'price';
  detail: { product: string; needed?: string; available?: string; charged?: string; current?: string }; created_at: string;
  resolved_at: string | null; note: string | null; resolved_by: string | null }
export const offlineIssues = (t: string, branchId: string, resolved = false) =>
  request<OfflineIssue[]>(t, `/sales/offline/issues?resolved=${resolved}`, {}, branchId);
export const resolveOfflineIssue = (t: string, branchId: string, id: string, note: string | null) =>
  request<void>(t, `/sales/offline/issues/${id}/resolve`, { method: 'POST', body: JSON.stringify({ note }) }, branchId);
