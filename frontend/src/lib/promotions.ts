// Server-side client for promotions (global; each one may be limited to some branches).
import { request } from './api';
import { localInputToInstant } from './time';

export type PromotionKind = 'PERCENT' | 'AMOUNT' | 'BUY_X_GET_Y';
export type PromotionStatus = 'ACTIVE' | 'SCHEDULED' | 'ENDED' | 'DISABLED';

export interface Promotion {
  id: string;
  name: string;
  description: string | null;
  kind: PromotionKind;
  percent: number | null;
  amount: number | null;
  buy_quantity: number | null;
  get_quantity: number | null;
  starts_at: string;
  ends_at: string;
  is_enabled: boolean;
  deleted_at: string | null;
  status: PromotionStatus;
  product_count: number;
  branch_count: number;
  lines_sold: number | null;
  units_sold: number | null;
  discount_given: number | null;
  products?: { id: string; name: string; price: number; deleted: boolean }[];
  branches?: { id: string; name: string }[];
}

const json = (method: string, body: unknown = {}) => ({ method, body: JSON.stringify(body) });
const qs = (p: Record<string, string | number | boolean | undefined>) =>
  new URLSearchParams(Object.entries(p).filter(([, v]) => v !== undefined && v !== '' && v !== false).map(([k, v]) => [k, String(v)]));

export const listPromotions = (t: string, p: Record<string, string | number | boolean | undefined>) =>
  request<{ items: Promotion[]; has_more: boolean }>(t, `/promotions?${qs({ page_size: 25, ...p })}`);
export const getPromotion = (t: string, id: string) => request<Promotion>(t, `/promotions/${id}`);
export const createPromotion = (t: string, body: unknown) => request<Promotion>(t, '/promotions', json('POST', body));
export const updatePromotion = (t: string, id: string, body: unknown) => request<Promotion>(t, `/promotions/${id}`, json('PATCH', body));
export const deletePromotion = (t: string, id: string) => request<void>(t, `/promotions/${id}`, { method: 'DELETE' });
export const restorePromotion = (t: string, id: string) => request<Promotion>(t, `/promotions/${id}/restore`, json('POST'));
export const promotionHistory = (t: string, id: string) =>
  request<{ items: { changed_at: string; entity_type: string; action: string; changed_by: string | null; changed_fields: string[] | null; target: string | null;
    new_data: Record<string, unknown> | null }[] }>(
    t, `/promotions/${id}/history?page_size=30`);

/** The form's fields (PromotionFields) -> API body. Dates are typed in the person's time zone. */
export function readPromotion(data: FormData, tz: string) {
  const v = (k: string) => String(data.get(k) ?? '').trim();
  const kind = v('kind') as PromotionKind;
  const instant = (k: string) => { try { return v(k) ? localInputToInstant(v(k), tz) : null; } catch { return null; } };
  return {
    name: v('name'), description: v('description') || null, kind,
    percent: kind === 'PERCENT' ? v('percent') || null : null,
    amount: kind === 'AMOUNT' ? v('amount') || null : null,
    buy_quantity: kind === 'BUY_X_GET_Y' ? v('buy_quantity') || null : null,
    get_quantity: kind === 'BUY_X_GET_Y' ? v('get_quantity') || null : null,
    starts_at: instant('starts_at'), ends_at: instant('ends_at'),
    is_enabled: data.has('is_enabled'),
    product_ids: data.getAll('product_id').map(String),
    branch_ids: data.getAll('branch_id').map(String),
  };
}

/** "15 %", "$5.00 por pieza", "3x2" */
export function describe(p: Pick<Promotion, 'kind' | 'percent' | 'amount' | 'buy_quantity' | 'get_quantity'>, money: (n: number) => string, perUnit: string) {
  if (p.kind === 'PERCENT') return `${Number(p.percent)} %`;
  if (p.kind === 'AMOUNT') return `${money(Number(p.amount))} ${perUnit}`;
  return `${Number(p.buy_quantity) + Number(p.get_quantity)}x${p.buy_quantity}`;
}

/** API error -> field messages + form message (our wording). */
export function promotionErrors(status: number, body: any, messages: Record<string, string>, fallback: string) {
  const detail = body?.detail;
  if (Array.isArray(detail)) {
    const fields = Object.fromEntries(detail.map((d: { loc?: unknown[] }) => {
      const name = String(d.loc?.[1] ?? '');
      return [name, messages[name] ?? fallback];
    }));
    return { fields, form: undefined };
  }
  if (detail?.field) return { fields: { [detail.field]: messages[detail.field] ?? fallback }, form: undefined };
  return { fields: {}, form: status === 404 ? messages.notFound : fallback };
}
