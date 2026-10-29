// Price lists (mayoreo, frecuente...): a customer's list decides the price charged (worked out by the API).
import { request } from './api';

export interface PriceList { id: string; name: string; percent: string; customers: number; items_count: number }
export interface PriceListItem { product_id: string; product: string; general_price: string; min_quantity: string; price: string }
export interface PriceListDetail extends PriceList { items: PriceListItem[] }

const json = (method: string, body: unknown = {}) => ({ method, body: JSON.stringify(body) });

export const listPriceLists = (t: string) => request<PriceList[]>(t, '/price-lists');
export const getPriceList = (t: string, id: string) => request<PriceListDetail>(t, `/price-lists/${id}`);
export const createPriceList = (t: string, data: { name: string; percent: string }) => request<PriceListDetail>(t, '/price-lists', json('POST', data));
export const updatePriceList = (t: string, id: string, data: { name?: string; percent?: string }) =>
  request<PriceListDetail>(t, `/price-lists/${id}`, json('PATCH', data));
export const deletePriceList = (t: string, id: string) => request<void>(t, `/price-lists/${id}`, { method: 'DELETE' });
export const setPriceListItems = (t: string, id: string, items: { product_id: string; min_quantity: string; price: string }[]) =>
  request<PriceListDetail>(t, `/price-lists/${id}/items`, json('PUT', { items }));
