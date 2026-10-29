// Server-side client for the cash API. Everything about registers is scoped to the working branch.
import { request } from './api';

export interface Register {
  id: string;
  branch_id: string;
  name: string;
  deleted_at: string | null;
  session_id: string | null;
  occupied_by: string | null;
  occupied_since: string | null;
  occupied_by_name: string | null;
  occupied_by_email: string | null;
}

export interface CashSession {
  id: string;
  cash_register_id: string;
  started_at: string;
  cash_register: string;
  branch_id: string;
  branch: string;
  /** Cash in the drawer: what an expense or a purchase can take from it */
  cash_balance: number;
}

export interface PaymentMethod {
  id: string;
  description: string;
  is_enabled: boolean;
  is_credit: boolean;
}

export interface Balance {
  payment_method_id: string;
  description: string;
  is_enabled: boolean;
  balance: number;
}

export type MovementType = 'Cash In' | 'Cash Out' | 'Sale' | 'Return' | 'Adjustment';

export interface Movement {
  id: string;
  created_at: string;
  movement_type: MovementType;
  payment_method: string;
  amount: number;
  balance_after: number;
  created_by_email: string;
  sale_id: string | null;
  notes: string | null;
}

export interface CutDetail {
  payment_method_id: string;
  payment_method: string;
  expected_amount: number;
  final_amount: number;
  difference: number;
}

export interface Cut {
  id: string;
  started_at: string;
  ended_at: string;
  notes: string | null;
  /** Cash taken out at the cut, and why */
  withdrawn: number;
  withdrawal_reason: string | null;
  performed_by: string;
  details: CutDetail[];
}

type Page<T> = { items: T[]; has_more: boolean };
const json = (body: unknown) => ({ body: JSON.stringify(body) });

export const listRegisters = (t: string, b: string) => request<Register[]>(t, '/cash-registers', {}, b);
export const getRegister = (t: string, b: string, id: string) => request<Register>(t, `/cash-registers/${id}`, {}, b);
export const createRegister = (t: string, b: string, name: string) =>
  request<Register>(t, '/cash-registers', { method: 'POST', ...json({ name }) }, b);
export const renameRegister = (t: string, b: string, id: string, name: string) =>
  request<Register>(t, `/cash-registers/${id}`, { method: 'PATCH', ...json({ name }) }, b);
export const deleteRegister = (t: string, b: string, id: string) =>
  request<void>(t, `/cash-registers/${id}`, { method: 'DELETE' }, b);

export const currentSession = (t: string) => request<CashSession | undefined>(t, '/cash-sessions/current');
export const occupyRegister = (t: string, b: string, id: string) =>
  request<CashSession>(t, `/cash-registers/${id}/occupy`, { method: 'POST' }, b);
export const releaseRegister = (t: string, b: string, id: string, force = false) =>
  request<unknown>(t, `/cash-registers/${id}/release?force=${force}`, { method: 'POST' }, b);

export const listPaymentMethods = (t: string, includeDisabled = false) =>
  request<PaymentMethod[]>(t, `/payment-methods?include_disabled=${includeDisabled}`);
export const updatePaymentMethod = (t: string, id: string, data: { description?: string; is_enabled?: boolean }) =>
  request<PaymentMethod>(t, `/payment-methods/${id}`, { method: 'PATCH', ...json(data) });

export const registerBalances = (t: string, b: string, id: string) => request<Balance[]>(t, `/cash-registers/${id}/balances`, {}, b);
export function registerMovements(t: string, b: string, id: string, page: number, type?: string) {
  const query = new URLSearchParams({ page: String(page), page_size: '20', ...(type && { type }) });
  return request<Page<Movement>>(t, `/cash-registers/${id}/movements?${query}`, {}, b);
}
export const addMovement = (
  t: string, b: string, id: string,
  data: { movement_type: string; payment_method_id: string; amount: string; notes: string | null },
) => request<Movement>(t, `/cash-registers/${id}/movements`, { method: 'POST', ...json(data) }, b);

export const registerCuts = (t: string, b: string, id: string, page = 1) =>
  request<Page<Cut>>(t, `/cash-registers/${id}/cuts?page=${page}&page_size=5`, {}, b);
export const createCut = (
  t: string, b: string, id: string, counts: { payment_method_id: string; counted: string }[], notes: string | null,
  withdrawal = '0', withdrawalReason: string | null = null,
) => request<Cut>(t, `/cash-registers/${id}/cuts`, { method: 'POST', ...json({ counts, notes, withdrawal, withdrawal_reason: withdrawalReason }) }, b);
