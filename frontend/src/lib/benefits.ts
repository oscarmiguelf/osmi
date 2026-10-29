// Packages (sessions of a service) and memberships (validity + price list): set on a product, granted by selling it.
import { request } from './api';

export interface ProductBenefit { kind: 'package' | 'membership'; service_product_id: string | null; service: string | null; sessions: number | null;
  valid_days: number | null; price_list_id: string | null; price_list: string | null }
export interface CustomerBenefit { id: string; kind: 'package' | 'membership'; product: string; service: string | null; sessions_total: number | null;
  sessions_used: number; sessions_left: number | null; price_list: string | null; starts_at: string; ends_at: string | null; active: boolean;
  sale_id: string; sale_folio: string }

const json = (method: string, body: unknown = {}) => ({ method, body: JSON.stringify(body) });

export const setBenefit = (t: string, productId: string, data: Record<string, unknown>) => request(t, `/products/${productId}/benefit`, json('PUT', data));
export const clearBenefit = (t: string, productId: string) => request<void>(t, `/products/${productId}/benefit`, { method: 'DELETE' });
export const customerBenefits = (t: string, customerId: string) => request<CustomerBenefit[]>(t, `/customers/${customerId}/benefits`);
export const expiringMemberships = (t: string, days = 7) =>
  request<{ id: string; customer_id: string; customer: string; phone: string; product: string; ends_at: string }[]>(t, `/memberships/expiring?days=${days}`);
