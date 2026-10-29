import { getRelativeLocaleUrl } from 'astro:i18n';
import es from './es';
import en from './en';
import { forGiro, giroStore } from './giro';

export type Dict = typeof es;
export type Locale = 'es' | 'en';

const dictionaries: Record<Locale, Dict> = { es, en };

export function getLocale(currentLocale: string | undefined): Locale {
  return currentLocale === 'en' ? 'en' : 'es';
}

export function useTranslations(locale: Locale) {
  return forGiro(dictionaries[locale], locale, giroStore.getStore()); // a clinic says "pacientes", not "clientes"
}

/** Fills {placeholders}: fmt('Hoy en {branch}', { branch: 'Centro' }) */
export function fmt(template: string, values: Record<string, string | number>) {
  return template.replace(/\{(\w+)\}/g, (_, key) => String(values[key] ?? `{${key}}`));
}

/** Localized link for an app path ('/sales' -> '/en/sales' in English). */
export function localePath(locale: Locale, path: string) {
  return getRelativeLocaleUrl(locale, path.replace(/^\//, ''));
}

/** Same page in the other language. */
export function alternatePath(locale: Locale, pathname: string) {
  const other: Locale = locale === 'es' ? 'en' : 'es';
  return localePath(other, pathname.replace(/^\/en(?=\/|$)/, ''));
}

export function money(locale: Locale, amount: number) {
  return new Intl.NumberFormat(dictionaries[locale].intl, { style: 'currency', currency: 'MXN' }).format(amount);
}

export function longDate(locale: Locale, date: Date) {
  const text = new Intl.DateTimeFormat(dictionaries[locale].intl, { dateStyle: 'full' }).format(date);
  return text.charAt(0).toUpperCase() + text.slice(1);
}
