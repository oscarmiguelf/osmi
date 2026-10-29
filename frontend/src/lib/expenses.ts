// Server-side client for expenses of the working branch, and the shared "how was it paid" pieces (expenses and purchases).
import { request } from './api';

export interface OutgoingPayment {
  id: string;
  created_at: string;
  source: 'CASH' | 'OTHER';
  amount: string;
  notes: string | null;
  cash_register: string | null;
  created_by_email: string | null;
}
export interface PaidTotals { paid: string; paid_cash: string; owed: string; payments: OutgoingPayment[] }
export interface ExpenseRow {
  id: string;
  description: string;
  supplier_id: string | null;
  supplier: string | null;
  amount: string;
  spent_at: string;
  reference: string | null;
  deleted_at: string | null;
  paid: string;
  paid_cash: string;
  owed: string;
}
export interface Expense extends ExpenseRow, PaidTotals {
  notes: string | null;
  created_at: string;
  created_by_email: string;
  deleted_by_email: string | null;
  void_reason: string | null;
}
export interface PaymentInput { cash_amount: string; other_amount: string; notes?: string | null }

const json = (method: string, body: unknown = {}) => ({ method, body: JSON.stringify(body) });

export const listExpenses = (t: string, b: string, p: Record<string, string | number | boolean | undefined>) =>
  request<{ items: ExpenseRow[]; has_more: boolean }>(t, `/expenses?${new URLSearchParams(
    Object.entries(p).filter(([, v]) => v !== undefined && v !== '').map(([k, v]) => [k, String(v)]))}`, {}, b);
export const expensesSummary = (t: string, b: string, from?: string, to?: string) =>
  request<{ expenses: number; total: string; paid: string; owed: string }>(t, `/expenses/summary?${new URLSearchParams(
    Object.entries({ from, to }).filter(([, v]) => v) as [string, string][])}`, {}, b);
export const createExpense = (t: string, b: string, data: Record<string, unknown>) => request<Expense>(t, '/expenses', json('POST', data), b);
export const getExpense = (t: string, b: string, id: string) => request<Expense>(t, `/expenses/${id}`, {}, b);
export const updateExpense = (t: string, b: string, id: string, data: Record<string, unknown>) =>
  request<Expense>(t, `/expenses/${id}`, json('PATCH', data), b);
export const payExpense = (t: string, b: string, id: string, data: PaymentInput) =>
  request<Expense>(t, `/expenses/${id}/payments`, json('POST', data), b);
export const voidExpense = (t: string, b: string, id: string, reason: string | null) =>
  request<{ cash_returned: string }>(t, `/expenses/${id}`, json('DELETE', { reason }), b);

/** "How was it paid" fields of a form -> API payload (blank = 0). */
export const readPayment = (data: FormData) => ({
  cash_amount: String(data.get('cash_amount') ?? '').trim() || '0',
  other_amount: String(data.get('other_amount') ?? '').trim() || '0',
});

/** API error of a payment (expense, purchase or a later payment) -> what the person reads. */
export function paymentErrorText(detail: any, m: { noRegister: string; notEnoughCash: string; overOwed: string }, money: (n: number) => string): string | undefined {
  if (detail?.code === 'no_register') return m.noRegister;
  if (detail?.code === 'not_enough_cash') return m.notEnoughCash.replace('{available}', money(Number(detail.available)));
  if (detail?.code === 'over_owed') return m.overOwed.replace('{owed}', money(Number(detail.owed)));
  return undefined;
}
