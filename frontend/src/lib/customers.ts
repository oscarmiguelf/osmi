// Server-side client for the customers API.
import { request } from './api';

export interface CustomerSummary {
  id: string;
  full_name: string;
  company: string | null;
  phone: string;
  email: string | null;
}

export async function searchCustomers(token: string, q: string, pageSize = 8) {
  const page = await request<{ items: CustomerSummary[] }>(
    token,
    `/customers?${new URLSearchParams({ q, page_size: String(pageSize) })}`,
  );
  return page.items;
}

/** 5512345678 -> 55 1234 5678 */
export const formatPhone = (phone: string) => phone.replace(/^(\d{2})(\d{4})(\d{4})$/, '$1 $2 $3');

export interface Customer extends CustomerSummary {
  credit_limit: number;
  created_at: string;
}

export interface CustomerPage {
  items: Customer[];
  total: number;
  page: number;
  page_size: number;
}

export interface CustomerInput {
  full_name: string;
  phone: string;
  email: string | null;
  company: string | null;
  address: string | null;
  additional_phone: string | null;
  credit_limit?: string;
  /** Custom field id -> value (Settings defines the fields) */
  extra?: Record<string, string | boolean>;
  price_list_id?: string | null;
}

export type CustomerWarning = { code: 'duplicate_phone'; count: number } | { code: string; [key: string]: unknown };

export function listCustomers(token: string, params: { q: string; page: number; pageSize: number; sort: string }) {
  const query = new URLSearchParams({ q: params.q, page: String(params.page), page_size: String(params.pageSize), sort: params.sort });
  return request<CustomerPage>(token, `/customers?${query}`);
}

export const createCustomer = (token: string, data: CustomerInput) =>
  request<Customer & { warnings: CustomerWarning[] }>(token, '/customers', { method: 'POST', body: JSON.stringify(data) });

export interface CustomerDetail extends Customer {
  address: string | null;
  additional_phone: string | null;
  deleted_at: string | null;
  extra: Record<string, unknown>;
  price_list_id: string | null;
  price_list: string | null;
}

export interface CreditSummary {
  credit_limit: number;
  balance: number;
  available_credit: number;
}

export interface HistoryEntry {
  changed_at: string;
  action: 'INSERT' | 'UPDATE' | 'DELETE' | 'RESTORE';
  changed_by_email: string | null;
  changed_fields: string[] | null;
  old_data: Record<string, unknown> | null;
  new_data: Record<string, unknown> | null;
}

export const getCustomer = (token: string, id: string) => request<CustomerDetail>(token, `/customers/${id}`);

export const updateCustomer = (token: string, id: string, data: Partial<CustomerInput>) =>
  request<CustomerDetail & { warnings: CustomerWarning[] }>(token, `/customers/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });

export const deleteCustomer = (token: string, id: string) => request<void>(token, `/customers/${id}`, { method: 'DELETE' });

export const restoreCustomer = (token: string, id: string) =>
  request<CustomerDetail>(token, `/customers/${id}/restore`, { method: 'POST' });

export const customerCredit = (token: string, id: string) => request<CreditSummary>(token, `/customers/${id}/credit`);

export const customerHistory = (token: string, id: string, page: number, pageSize = 15) =>
  request<{ items: HistoryEntry[]; has_more: boolean }>(token, `/customers/${id}/history?page=${page}&page_size=${pageSize}`);

