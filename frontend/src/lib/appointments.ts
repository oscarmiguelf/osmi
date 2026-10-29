// Server-side client for appointments (citas) of the working branch.
import { ApiError, request } from './api';
import { extraErrors, readExtra, type CustomField } from './customFields';
import { listCatalog, searchProducts } from './products';
import { localInputToInstant } from './time';

export type AppointmentStatus = 'SCHEDULED' | 'CONFIRMED' | 'COMPLETED' | 'CANCELLED' | 'NO_SHOW';
export const OPEN_STATUSES: AppointmentStatus[] = ['SCHEDULED', 'CONFIRMED'];

export interface AppointmentService { product_id: string; product: string; quantity: string; price: string; duration_minutes: number | null; unit: string }
export interface Appointment {
  id: string;
  sale_id?: string | null;
  reminded_at?: string | null;
  services_text?: string | null;
  sale_folio?: string | null;
  /** The sale that charged it (a deposit when it was charged before it started) and what's still owed */
  sale_total?: string | null;
  sale_balance?: string | null;
  /** The business's data of the appointment (custom fields with entity 'appointment') */
  extra?: Record<string, unknown>;
  /** Its quote: converting it charges the appointment */
  quote_id?: string | null;
  quote_folio?: string | null;
  quote_total?: string | null;
  quote_status?: 'OPEN' | 'CONVERTED' | 'CANCELLED' | null;
  quote_expired?: boolean | null;
  /** Booking: why its sale couldn't be made then (register, permission). Cancelling: what's left to do with its sale */
  sale_pending?: string | null;
  sale_followup?: string | null;
  services?: AppointmentService[];
  customer_id: string;
  customer: string;
  customer_phone: string | null;
  title: string;
  notes: string | null;
  starts_at: string;
  ends_at: string;
  status: AppointmentStatus;
  cancel_reason: string | null;
  reschedule_count: number;
  assigned_id: string | null;
  assigned_to: string | null;
  created_by: string;
  created_at: string;
  branch?: string;
  note_count?: number;
  follow_up?: { id: string; note: string; created_at: string; created_by: string | null }[];
  history?: { action: 'CREATED' | 'RESCHEDULED' | 'STATUS' | 'UPDATED'; from_status: AppointmentStatus | null; to_status: AppointmentStatus | null;
    from_starts_at: string | null; to_starts_at: string | null; reason: string | null; changed_fields: string[] | null;
    changed_by: string; changed_at: string }[];
}

const json = (method: string, body: unknown = {}) => ({ method, body: JSON.stringify(body) });
const qs = (p: Record<string, string | boolean | undefined>) =>
  new URLSearchParams(Object.entries(p).filter(([, v]) => v !== undefined && v !== '' && v !== false).map(([k, v]) => [k, String(v)]));

export const listAppointments = (t: string, b: string, p: Record<string, string | boolean | undefined>) =>
  request<Appointment[]>(t, `/appointments?${qs(p)}`, {}, b);
export const appointmentStaff = (t: string, b: string) => request<{ id: string; name: string | null; email: string }[]>(t, '/appointments/staff', {}, b);
export const createAppointment = (t: string, b: string, body: unknown) => request<Appointment>(t, '/appointments', json('POST', body), b);
export const getAppointment = (t: string, b: string, id: string) => request<Appointment>(t, `/appointments/${id}`, {}, b);
export const markReminded = (t: string, b: string, id: string) => request<Appointment>(t, `/appointments/${id}/reminded`, json('POST'), b);
/** A quote with the appointment's services for its customer, valid until it starts, tied to it */
export const quoteFromAppointment = (t: string, b: string, id: string) => request<Appointment>(t, `/appointments/${id}/quote`, json('POST'), b);
/** Its sale (all on credit) when it couldn't be made at booking */
export const makeAppointmentSale = (t: string, b: string, id: string) => request<Appointment>(t, `/appointments/${id}/sale`, json('POST'), b);
export const updateAppointment = (t: string, b: string, id: string, body: unknown) => request<Appointment>(t, `/appointments/${id}`, json('PATCH', body), b);
export const rescheduleAppointment = (t: string, b: string, id: string, body: unknown) =>
  request<Appointment>(t, `/appointments/${id}/reschedule`, json('POST', body), b);
export const appointmentAction = (t: string, b: string, id: string, action: 'confirm' | 'complete' | 'no-show') =>
  request<Appointment>(t, `/appointments/${id}/${action}`, json('POST'), b);
export const cancelAppointment = (t: string, b: string, id: string, reason: string) =>
  request<Appointment>(t, `/appointments/${id}/cancel`, json('POST', { reason }), b);
export const addAppointmentNote = (t: string, b: string, id: string, note: string) =>
  request<Appointment>(t, `/appointments/${id}/notes`, json('POST', { note }), b);
export const customerAppointments = (t: string, customerId: string) =>
  request<{ items: Appointment[]; has_more: boolean }>(t, `/customers/${customerId}/appointments?page_size=10`);

/** API error -> what the person reads. */
export function appointmentErrorText(status: number, detail: any, e: Record<string, string>, fallback: string): string {
  if (detail?.code === 'clash') return e.clash;
  if (detail?.code === 'closed') return e.closed;
  if (detail?.code === 'same_status') return e.alreadyConfirmed;
  if (detail?.code === 'no_services') return e.no_services;
  if (detail?.code === 'has_payments') return e.has_payments;
  if (detail?.code === 'register') return e.register;
  if (['quote_status', 'quote_taken', 'quote_customer', 'has_quote'].includes(detail?.code)) return e.quote_status;
  const field = detail?.field ?? (Array.isArray(detail) ? String(detail[0]?.loc?.at(-1) ?? '') : '');
  if (field === 'ends_at') return e.range;
  if (field === 'starts_at' && status === 422 && typeof detail?.message === 'string' && detail.message.includes('same time')) return e.sameTime;
  if (field === 'customer_id') return e.customer;
  if (field === 'assigned_to') return e.assigned;
  if (field === 'reason') return e.reason;
  if (field === 'title') return e.title;
  return fallback;
}

export interface NewAppointmentValues {
  customer_id: string; customer_label: string; title: string; start: string; duration: string; assigned_to: string; notes: string; confirmed: boolean;
  services: string[];
  extra: Record<string, unknown>;
  quote_id?: string;
}

/** An empty "New appointment" form: starting at the next whole hour, 30 minutes. */
export function newAppointmentValues(tz: string, customer?: { id: string; title: string }): NewAppointmentValues {
  const nextHour = Temporal.Now.zonedDateTimeISO(tz).round({ smallestUnit: 'hour', roundingMode: 'ceil' });
  return { customer_id: customer?.id ?? '', customer_label: customer?.title ?? '', title: '',
    start: nextHour.toPlainDateTime().toString({ smallestUnit: 'minute' }), duration: '30', assigned_to: '', notes: '', confirmed: false,
    services: [], extra: {} };
}

/** Creates the appointment posted by NewAppointmentDialog; `error` (what the person reads) when it can't. */
export async function saveNewAppointment(token: string, branchId: string, tz: string, data: FormData, e: Record<string, string>, failed: string,
  fields: CustomField[] = [], extraMessages: Record<string, string> = {}):
  Promise<{ values: NewAppointmentValues; error?: string; extraErrors?: Record<string, string>; created?: Appointment }> {
  const v = (k: string) => String(data.get(k) ?? '').trim();
  const values = { customer_id: v('customer'), customer_label: v('customer_label'), title: v('title'), start: v('start'), duration: v('duration'),
    assigned_to: v('assigned_to'), notes: v('notes'), confirmed: data.has('confirmed'), services: data.getAll('service').map(String),
    extra: readExtra(data, fields), quote_id: v('quote_id') || undefined };
  if (!values.customer_id) return { values, error: e.customer };
  if (!values.title) return { values, error: e.title };
  try {
    const starts = Temporal.Instant.from(localInputToInstant(values.start, tz));
    const created = await createAppointment(token, branchId, {
      customer_id: values.customer_id, title: values.title, starts_at: starts.toString(),
      ends_at: starts.add({ minutes: Number(values.duration) || 30 }).toString(),
      assigned_to: values.assigned_to || null, notes: values.notes || null, status: values.confirmed ? 'CONFIRMED' : 'SCHEDULED',
      services: values.services.map((product_id) => ({ product_id })), extra: values.extra, quote_id: values.quote_id ?? null,
    });
    return { values, created };
  } catch (err) {
    if (err instanceof RangeError) return { values, error: e.start }; // the date-time input was empty or malformed
    if (!(err instanceof ApiError)) throw err;
    if (err.body?.detail?.field === 'extra') return { values, error: e.extra, extraErrors: extraErrors(err.body.detail, extraMessages) };
    return { values, error: appointmentErrorText(err.status, err.body?.detail, e, failed) };
  }
}

/** Services that can be booked (with their price and duration), for the appointment forms. */
export async function bookableServices(token: string) {
  const type = (await listCatalog(token, 'product-types')).find((t) => !t.tracks_stock && !t.is_kit);
  if (!type) return [];
  const page = await searchProducts(token, undefined, { type_id: type.id, page_size: 100 });
  return page.items.map((p) => ({ id: p.id, name: p.name, price: Number(p.price), duration: p.duration_minutes ?? null }));
}
export type BookableService = Awaited<ReturnType<typeof bookableServices>>[number];

/** wa.me link to the customer's WhatsApp with the reminder (10-digit Mexican numbers get the 52 country code). */
export function reminderLink(phone: string, text: string) {
  const digits = phone.replace(/\D/g, '');
  return `https://wa.me/${digits.length === 10 ? `52${digits}` : digits}?text=${encodeURIComponent(text)}`;
}

/** The reminder text: the business's template (Settings) or the default, with its {placeholders} filled. */
export function reminderText(template: string, fallback: string, v: { cliente: string; fecha: string; hora: string; sucursal: string; servicios: string }) {
  // {paciente} is the same as {cliente} (a clinic may write it that way)
  return (template || fallback).replace(/\{(cliente|paciente|fecha|hora|sucursal|servicios)\}/g,
    (_, k: string) => v[(k === 'paciente' ? 'cliente' : k) as keyof typeof v]);
}
