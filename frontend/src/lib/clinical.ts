// Patient records (health business type): background, consultation notes, prescriptions, studies, odontogram, consents.
// The content is encrypted in the database; the API decrypts it only for users with the "clinical" module.
import { request } from './api';

export type Vitals = Partial<Record<'weight' | 'height' | 'bp' | 'hr' | 'rr' | 'temp' | 'spo2', string>>;
export interface NoteBody { reason?: string; history?: string; exam?: string; vitals?: Vitals; diagnosis?: string; plan?: string }
export interface Prescription { id: string; note_id: string; customer_id: string; patient: string; created_at: string; author: string | null;
  patient_phone?: string | null; items: { name: string; dose: string; instructions: string }[]; doctor_header?: string; branch?: string; branch_address?: string | null;
  branch_phone?: string | null; diagnosis?: string | null }
export interface Note { id: string; customer_id: string; branch_id: string; appointment_id: string | null; kind: 'medical' | 'dental'; visit_at: string;
  author_id: string; author: string | null; signed_at: string | null; created_at: string; updated_at: string; body: NoteBody;
  addenda: { id: string; text: string; author: string | null; created_at: string }[]; prescriptions: Prescription[] }
export interface ToothEntry { tooth: number; surface: string | null; condition: string; note: string | null; recorded_at: string; recorded_by: string | null }
export interface Consent { id: string; kind: 'privacy' | 'treatment'; signer_name: string; signature_file: string | null; accepted_at: string;
  recorded_by: string | null; text_snapshot: string }
export interface ClinicalRecord {
  patient: { id: string; full_name: string; phone: string | null; email: string | null; extra: Record<string, unknown> | null };
  background: { data: Record<string, string>; updated_at: string | null; updated_by: string | null };
  notes: (Omit<Note, 'body' | 'addenda' | 'prescriptions'> & { reason: string | null; diagnosis: string | null })[];
  prescriptions: Prescription[];
  files: { id: string; label: string; content_type: string; size_bytes: number; note_id: string | null; created_at: string; uploaded_by: string | null }[];
  dental_chart: ToothEntry[];
  consents: Consent[];
  privacy_notice: string;
}
export interface RecentNote { id: string; customer_id: string; patient: string; kind: 'medical' | 'dental'; visit_at: string; signed_at: string | null;
  author_id: string; author: string | null; reason: string | null }

export const BACKGROUND = ['allergies', 'medications', 'pathological', 'hereditary', 'non_pathological', 'surgeries', 'gyneco', 'notes'] as const;
export const VITALS = ['weight', 'height', 'bp', 'hr', 'rr', 'temp', 'spo2'] as const;
export const CONDITIONS = ['healthy', 'caries', 'filled', 'crown', 'root_canal', 'missing', 'extraction', 'implant', 'fracture', 'sealant'] as const;
// FDI, as the dentist looks at the patient: upper right → upper left, lower right → lower left
export const ADULT_TEETH = [[18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28], [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]];
export const CHILD_TEETH = [[55, 54, 53, 52, 51, 61, 62, 63, 64, 65], [85, 84, 83, 82, 81, 71, 72, 73, 74, 75]];

const json = (method: string, body: unknown = {}) => ({ method, body: JSON.stringify(body) });
const P = (id: string) => `/clinical/patients/${id}`;

export const clinicalRecord = (t: string, customerId: string) => request<ClinicalRecord>(t, P(customerId));
export const saveBackground = (t: string, customerId: string, data: Record<string, string>) => request(t, `${P(customerId)}/background`, json('PUT', data));
export const recentNotes = (t: string, branchId: string) => request<RecentNote[]>(t, '/clinical/recent', {}, branchId);
export const createNote = (t: string, branchId: string, data: { customer_id: string; appointment_id?: string | null; kind: string }) =>
  request<Note>(t, '/clinical/notes', json('POST', data), branchId);
export const getNote = (t: string, id: string) => request<Note>(t, `/clinical/notes/${id}`);
export const updateNote = (t: string, id: string, body: NoteBody) => request<Note>(t, `/clinical/notes/${id}`, json('PATCH', body));
export const signNote = (t: string, id: string) => request<Note>(t, `/clinical/notes/${id}/sign`, json('POST'));
export const addAddendum = (t: string, id: string, text: string) => request<Note>(t, `/clinical/notes/${id}/addenda`, json('POST', { text }));
export const prescribe = (t: string, noteId: string, items: Prescription['items']) =>
  request<Prescription>(t, `/clinical/notes/${noteId}/prescriptions`, json('POST', { items }));
export const getPrescription = (t: string, id: string) => request<Prescription>(t, `/clinical/prescriptions/${id}`);
export const addDental = (t: string, customerId: string, entries: { tooth: number; surface: string | null; condition: string; note: string | null }[]) =>
  request<ToothEntry[]>(t, `${P(customerId)}/dental`, json('POST', { entries }));
export const addConsent = (t: string, customerId: string, data: { kind: string; signer_name: string; text: string; signature: string | null }) =>
  request(t, `${P(customerId)}/consents`, json('POST', data));
export const accessLog = (t: string, customerId: string) =>
  request<{ action: 'view' | 'print' | 'file'; at: string; email: string; name: string | null }[]>(t, `${P(customerId)}/access-log`);
export function uploadClinicalFile(t: string, customerId: string, file: File, label: string) {
  const body = new FormData();
  body.set('file', file);
  body.set('label', label);
  return request(t, `${P(customerId)}/files`, { method: 'POST', body });
}
