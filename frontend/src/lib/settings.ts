// Server-side client for business settings (module "settings").
import { request } from './api';

export interface Settings { whatsapp_number: string; business_type: 'retail' | 'beauty' | 'health' | 'music'; reminder_template?: string;
  doctor_header?: string; privacy_notice?: string; logo_file?: string }

export const getSettings = (t: string) => request<Settings>(t, '/settings');
export const updateSettings = (t: string, data: Partial<Settings>) =>
  request<Settings>(t, '/settings', { method: 'PATCH', body: JSON.stringify(data) });
export function uploadLogo(t: string, file: File) {
  const body = new FormData();
  body.set('file', file);
  return request<Settings>(t, '/settings/logo', { method: 'PUT', body });
}
export const deleteLogo = (t: string) => request<void>(t, '/settings/logo', { method: 'DELETE' });
