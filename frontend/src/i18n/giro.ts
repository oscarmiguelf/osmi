// The business type (giro) of the current request, and how it renames things: a clinic has patients and
// consultations, not customers and appointments. Server-only: the middleware sets it for each request.
import { AsyncLocalStorage } from 'node:async_hooks';

export type BusinessType = 'retail' | 'beauty' | 'health' | 'music';
export const giroStore = new AsyncLocalStorage<BusinessType>();

// Whole-word renames, case kept (Cliente -> Paciente). Where the genders match (health) that's all; where they don't
// (cita -> evento), `fix` first turns the words around it masculine, only in texts that speak of a cita.
type Rules = { words: [RegExp, string][]; fix?: (s: string) => string };
const NOT_PLACEHOLDER = (word: string) => new RegExp(`(?<!\\{)\\b${word}\\b(?!\\})`, 'gi');
// The feminine words that go with "cita" in this app's texts (articles, demonstratives, adjectives, participles)
const CITA_GENDER: [RegExp, string][] = [
  [/\bde la (cita)\b/g, 'del $1'], [/\ba la (cita)\b/g, 'al $1'], [/\bLa (cita)\b/g, 'El $1'], [/\bla (cita)\b/g, 'el $1'], [/\bLas (citas)\b/g, 'Los $1'], [/\blas (citas)\b/g, 'los $1'],
  [/\b(u)na (cita)\b/gi, '$1n $2'],
  [/\b(e)sa (cita)\b/gi, '$1se $2'], [/\b(e)sta (cita)\b/gi, '$1ste $2'], [/\b(n)ueva (cita)\b/gi, '$1uevo $2'],
  [/\b(confirmad|agendad|cancelad|reagendad|marcad|cerrad|cobrad)a(s?)\b/gi, '$1o$2'], [/\babiertas\b/gi, 'abiertos'],
  [/\batendida\b/g, 'realizado'], [/"No asistió"/g, '"No se realizó"'], [/\bcancelado o no asistió/g, 'cancelado o no se realizó'],
  [/\botra, agenda una nueva\b/g, 'otro, agenda uno nuevo'],
];
const masculine = (s: string) => /\bcitas?\b/i.test(s)
  ? CITA_GENDER.reduce((out, [re, to]) => out.replace(re, to), s)
  : s;

const RENAMES: Partial<Record<BusinessType, Record<'es' | 'en', Rules>>> = {
  health: {
    // (?<!\{) / (?!\}): placeholders like {cliente} stay as they are (they are filled in later)
    es: { words: [[/(?<!\{)\bclientes\b(?!\})/gi, 'pacientes'], [/(?<!\{)\bcliente\b(?!\})/gi, 'paciente'],
         [/(?<!\{)\bcitas\b(?!\})/gi, 'consultas'], [/(?<!\{)\bcita\b(?!\})/gi, 'consulta']] },
    en: { words: [[/(?<!\{)\bcustomers\b(?!\})/gi, 'patients'], [/(?<!\{)\bcustomer\b(?!\})/gi, 'patient'],
         [/(?<!\{)\bappointments\b(?!\})/gi, 'consultations'], [/(?<!\{)\bappointment\b(?!\})/gi, 'consultation']] },
  },
  music: {
    es: { fix: masculine, words: [[NOT_PLACEHOLDER('citas'), 'eventos'], [NOT_PLACEHOLDER('cita'), 'evento']] },
    en: { fix: (t) => (/\bappointments?\b/i.test(t) ? t.replace(/\battended\b/g, 'held').replace(/\bno-show\b/gi, (m) => (m[0] === 'N' ? "Didn't happen" : "didn't happen")) : t),
          words: [[NOT_PLACEHOLDER('appointments'), 'events'], [NOT_PLACEHOLDER('appointment'), 'event']] },
  },
};

// Words that don't name the thing but agree with it (an event is "Realizado", not "Atendida"): set by key, after the renames
const OVERRIDES: Partial<Record<BusinessType, Record<'es' | 'en', Record<string, unknown>>>> = {
  music: {
    es: { appointments: {
      statuses: { SCHEDULED: 'Agendado', CONFIRMED: 'Confirmado', COMPLETED: 'Realizado', NO_SHOW: 'No se realizó', CANCELLED: 'Cancelado' },
      statusEvents: { SCHEDULED: 'Agendado', COMPLETED: 'Marcó como realizado', NO_SHOW: 'Marcó que no se realizó' },
      complete: 'Realizado', noShow: 'No se realizó', noShowTitle: '¿El evento no se realizó?',
      showCancelled: 'Mostrar cancelados', cancelledBecause: 'Cancelado: {reason}', rescheduledTimes: 'Reagendado {n}×', paidFull: 'Pagado completo', charged: 'Cobrado', chargedIn: 'Cobrado en la venta {folio}',
      reason: 'Evento', reasonHint: 'Ej. Boda, XV años, evento de empresa.', assignedTo: 'Responsable', fields: { assigned_to: 'responsable' },
    } },
    en: { appointments: {
      statuses: { COMPLETED: 'Held', NO_SHOW: "Didn't happen" },
      statusEvents: { COMPLETED: 'Marked as held', NO_SHOW: "Marked as didn't happen" },
      complete: 'Held', noShow: "Didn't happen", noShowTitle: "The event didn't happen?",
      reason: 'Event', reasonHint: 'E.g. Wedding, quinceañera, company party.', assignedTo: 'In charge', fields: { assigned_to: 'in charge' },
    } },
  },
};

function merge<T>(base: T, over: unknown): T {
  if (!over || typeof over !== 'object' || typeof base !== 'object' || base === null) return (over ?? base) as T;
  const out: Record<string, unknown> = { ...(base as Record<string, unknown>) };
  for (const [k, v] of Object.entries(over)) out[k] = merge(out[k], v);
  return out as T;
}

const keepCase = (match: string, to: string) => (match[0] === match[0].toUpperCase() ? to[0].toUpperCase() + to.slice(1) : to);

function rename<T>(value: T, rules: Rules): T {
  if (typeof value === 'string') {
    const text = rules.fix ? rules.fix(value) : (value as string);
    return rules.words.reduce((s, [re, to]) => s.replace(re, (m) => keepCase(m, to)), text) as T;
  }
  if (Array.isArray(value)) return value.map((v) => rename(v, rules)) as T;
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, rename(v, rules)])) as T;
  return value;
}

// Keyed by the dictionary object itself: a reloaded dictionary (dev hot reload) gets a fresh copy, never a stale one
const cache = new WeakMap<object, Map<BusinessType, unknown>>();
/** The dictionary as this business type calls things (computed once per dictionary and type). */
export function forGiro<T extends object>(dict: T, locale: 'es' | 'en', giro: BusinessType | undefined): T {
  const rules = giro && RENAMES[giro]?.[locale];
  if (!rules) return dict;
  const byGiro = cache.get(dict) ?? new Map<BusinessType, unknown>();
  cache.set(dict, byGiro);
  if (!byGiro.has(giro)) byGiro.set(giro, merge(rename(dict, rules), OVERRIDES[giro]?.[locale]));
  return byGiro.get(giro) as T;
}

/** Modules a business type doesn't use: hidden from the menu (permissions still decide access). */
export const HIDDEN_MODULES: Record<BusinessType, string[]> = {
  retail: ['appointments', 'clinical'],
  beauty: ['clinical'],
  health: ['promotions'],
  music: ['clinical'],
};
