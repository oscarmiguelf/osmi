// Product search for pickers. mode=available: only products with stock in the working branch (transfers);
// mode=sale: every product with its price (sales and quotes); default: products with stock of their own (purchases).
import type { APIRoute } from 'astro';
import { getLocale, useTranslations } from '@/i18n';
import { searchProducts } from '@/lib/products';
import { availableProducts } from '@/lib/transfers';

export const GET: APIRoute = async ({ url, locals }) => {
  const q = (url.searchParams.get('q') ?? '').trim().slice(0, 100);
  if (q.length < 2) return Response.json([]);
  const branch = locals.branch?.id;
  if (url.searchParams.get('mode') === 'available') {
    if (!branch) return Response.json([]);
    const rows = await availableProducts(locals.accessToken!, branch, q);
    return Response.json(rows.map((p) => ({ id: p.id, title: p.name, subtitle: `${Number(p.current_stock)} ${p.unit}`, unit: p.unit })));
  }
  const page = await searchProducts(locals.accessToken!, branch, { q, page_size: 10 });
  if (url.searchParams.get('mode') === 'sale') {
    // Everything can be sold or quoted (services and kits too); price and stock help choose
    const units = useTranslations(getLocale(url.searchParams.get('lang') ?? undefined)).products.unitNames;
    return Response.json(page.items.map((p) => {
      const unit = units[p.unit] ?? p.unit;
      return { id: p.id, title: p.name, unit, price: Number(p.price), tracks: p.tracks_stock && !p.is_kit, stock: Number(p.current_stock),
        subtitle: p.tracks_stock && !p.is_kit ? `$${Number(p.price).toFixed(2)} · ${Number(p.current_stock)} ${unit}` : `$${Number(p.price).toFixed(2)}` };
    }));
  }
  // Only products with stock of their own can be bought or moved (no services or kits)
  return Response.json(page.items.filter((p) => p.tracks_stock && !p.is_kit)
    .map((p) => ({ id: p.id, title: p.name, subtitle: `${Number(p.current_stock)} ${p.unit}`, unit: p.unit })));
};
