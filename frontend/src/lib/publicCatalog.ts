// Server-side client for the PUBLIC catalog (no session): products with stock, services, and the WhatsApp number.
import { API_URL } from 'astro:env/server';

export interface CatalogProduct {
  id: string;
  name: string;
  description: string | null;
  price: string;
  brand: string | null;
  category: string | null;
  unit: string;
  is_service: boolean;
  /** Never the exact stock: one / few (up to 5) / plenty; null for services */
  availability: 'one' | 'few' | 'plenty' | null;
  /** The order can't go past this (only when few are left); null = no cap */
  max_order: number | null;
  image_ids: string[];
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(API_URL + path);
  if (!res.ok) throw new Error(`catalog API ${res.status}`);
  return res.json() as Promise<T>;
}

export const catalogInfo = () =>
  get<{ whatsapp_number: string | null; ordering: boolean; categories: { id: string; name: string }[] }>('/public/catalog');
export const catalogProducts = (p: { q?: string; category_id?: string; kind?: string; page?: number }) =>
  get<{ items: CatalogProduct[]; has_more: boolean }>(`/public/catalog/products?${new URLSearchParams(
    Object.entries({ page_size: 24, ...p }).filter(([, v]) => v !== undefined && v !== '').map(([k, v]) => [k, String(v)]))}`);
export const catalogImageUrl = (productId: string, imageId: string) => `/api/catalog/images/${productId}/${imageId}`;
