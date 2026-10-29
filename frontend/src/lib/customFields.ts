// Custom fields: the extra data a business keeps about its customers (definitions in Settings, values in customers.extra).
import { request } from './api';

export type FieldType = 'text' | 'long_text' | 'number' | 'date' | 'select' | 'boolean';
export interface CustomField { id: string; label: string; field_type: FieldType; options: string[]; required: boolean; sort_order: number }

const json = (method: string, body: unknown = {}) => ({ method, body: JSON.stringify(body) });

export type FieldEntity = 'customer' | 'appointment';
/** customer: customers' data; appointment: each appointment's (an event's venue, guests...) */
export const listFields = (t: string, entity: FieldEntity = 'customer') =>
  request<CustomField[]>(t, entity === 'customer' ? '/custom-fields' : '/custom-fields/appointment');
export const createField = (t: string, data: Partial<CustomField> & { entity?: FieldEntity }) => request<CustomField>(t, '/custom-fields', json('POST', data));
export const updateField = (t: string, id: string, data: Partial<CustomField>) => request<CustomField>(t, `/custom-fields/${id}`, json('PATCH', data));
export const deleteField = (t: string, id: string) => request<void>(t, `/custom-fields/${id}`, { method: 'DELETE' });

/** The form's extra.<field id> inputs -> { id: value } for the API (an unchecked checkbox posts nothing: false). */
export function readExtra(data: FormData, fields: CustomField[]): Record<string, string | boolean> {
  return Object.fromEntries(fields.map((f) => [f.id, f.field_type === 'boolean' ? data.has(`extra.${f.id}`) : String(data.get(`extra.${f.id}`) ?? '').trim()]));
}

/** API 422 { errors: { id: code } } -> messages per field id. */
export function extraErrors(detail: any, messages: Record<string, string>): Record<string, string> {
  return Object.fromEntries(Object.entries(detail?.errors ?? {}).map(([id, code]) => [id, messages[code as string] ?? messages.invalid]));
}

/** A stored value as people read it. */
export function showExtra(f: CustomField, value: unknown, intl: string, yes: string, no: string): string {
  if (value === undefined || value === null || value === '') return '—';
  if (f.field_type === 'boolean') return value ? yes : no;
  if (f.field_type === 'date') return Temporal.PlainDate.from(String(value)).toLocaleString(intl, { dateStyle: 'long' });
  return String(value);
}
