// Payments to a sale from the abono dialog (one or several methods). Comes back to the page it was opened on, with a
// flash: paid (and change) or pay_error (the dialog opens again with it).
import type { APIRoute } from 'astro';
import { fmt, money, useTranslations } from '@/i18n';
import { ApiError } from '@/lib/api';
import { payBatch, saleErrorText } from '@/lib/sales';
import { setFlash } from '@/lib/session';

const UUID = /^[0-9a-f-]{36}$/i;
const amount = (v: FormDataEntryValue | null) => String(v ?? '').trim().replace(',', '.');

export const POST: APIRoute = async ({ request, locals, cookies, redirect }) => {
  const data = await request.formData();
  const back = String(data.get('back') ?? '/');
  const to = back.startsWith('/') && !back.startsWith('//') ? back : '/'; // only pages of this app
  const saleId = String(data.get('sale_id') ?? '');
  if (!locals.accessToken || !locals.branch || !UUID.test(saleId)) return redirect(to, 303);
  const locale = data.get('locale') === 'en' ? 'en' : 'es';
  const t = useTranslations(locale);
  const methods = data.getAll('method').map(String);
  const amounts = data.getAll('amount').map(amount);
  const refs = data.getAll('reference').map((r) => String(r).trim());
  const payments = methods.map((m, i) => ({ payment_method_id: m, amount: amounts[i] ?? '', amount_tendered: null as string | null, reference: refs[i] || null }))
    .filter((p) => Number(p.amount) > 0);
  // The cash handed over belongs to the cash line (the change is worked out from it)
  const tendered = amount(data.get('tendered'));
  const cashLine = payments.find((p) => p.payment_method_id === String(data.get('cash_method') ?? '')) ?? null;
  const fail = (text: string) => {
    setFlash(cookies, { pay_error: text, pay_sale: saleId });
    return redirect(to, 303);
  };
  if (!payments.length) return fail(t.sales.abono.none);
  try {
    const withTendered = payments.map((p) => (p === cashLine && Number(tendered) > Number(p.amount) ? { ...p, amount_tendered: tendered } : p));
    await payBatch(locals.accessToken, locals.branch.id, saleId, withTendered);
    const total = payments.reduce((s, p) => s + Number(p.amount), 0);
    const change = cashLine && Number(tendered) > Number(cashLine.amount) ? Number(tendered) - Number(cashLine.amount) : 0;
    setFlash(cookies, { paid: fmt(t.sales.abono.done, { amount: money(locale, total) }) + (change ? ` ${fmt(t.sales.abono.change, { amount: money(locale, change) })}` : '') });
    return redirect(to, 303);
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    const d = e.body?.detail;
    return fail(d?.outstanding !== undefined ? fmt(t.sales.abono.tooMuch, { amount: money(locale, Number(d.outstanding)) }) : saleErrorText(e.status, d, t).text);
  }
};
