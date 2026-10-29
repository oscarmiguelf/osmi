// Server-side client for the users administration API.
import { request } from './api';

export interface User {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  is_active: boolean;
  is_locked: boolean;
  timezone: string;
  must_change_password: boolean;
  last_login_at: string | null;
  created_at: string;
  deleted_at: string | null;
  created_by_email: string | null;
}

export interface AccessModule {
  module_id: string;
  module_code: string;
  module_name: string;
  has_module: boolean;
  permissions: { id: string; code: string; name: string; granted: boolean }[];
}

const json = (method: string, body: unknown = {}) => ({ method, body: JSON.stringify(body) });

export function listUsers(t: string, p: { q: string; status?: string; page: number }) {
  const query = new URLSearchParams({ q: p.q, page: String(p.page), page_size: '25', ...(p.status && { status: p.status }) });
  return request<{ items: User[]; total: number }>(t, `/users?${query}`);
}
export const getUser = (t: string, id: string) => request<User>(t, `/users/${id}`);
export const createUser = (t: string, data: Record<string, string | null>) =>
  request<User & { temporary_password?: string }>(t, '/users', json('POST', data));
export const updateUser = (t: string, id: string, data: Record<string, string>) => request<User>(t, `/users/${id}`, json('PATCH', data));
export const userAction = (t: string, id: string, action: 'activate' | 'deactivate' | 'unlock' | 'logout-all' | 'restore') =>
  request<unknown>(t, `/users/${id}/${action}`, json('POST'));
export const resetPassword = (t: string, id: string) =>
  request<{ temporary_password?: string }>(t, `/users/${id}/reset-password`, json('POST'));
export const deleteUser = (t: string, id: string) => request<void>(t, `/users/${id}`, { method: 'DELETE' });
export const userSessions = (t: string, id: string) =>
  request<{ family_id: string; user_agent: string | null; ip_address: string | null; session_started_at: string; last_used_at: string }[]>(t, `/users/${id}/sessions`);
export const loginHistory = (t: string, id: string) =>
  request<{ items: { created_at: string; event_type: string; ip_address: string | null }[] }>(t, `/users/${id}/login-history?page_size=15`);
export const userHistory = (t: string, id: string) =>
  request<{ items: { changed_at: string; action: string; changed_by_email: string | null; changed_fields: string[] | null; old_data: Record<string, unknown> | null; new_data: Record<string, unknown> | null }[] }>(t, `/users/${id}/history?page_size=15`);
export const userBranches = (t: string, id: string) => request<{ id: string; name: string }[]>(t, `/users/${id}/branches`);
export const setUserBranches = (t: string, id: string, branchIds: string[]) =>
  request<unknown>(t, `/users/${id}/branches`, json('PUT', { branch_ids: branchIds }));
export const userAccess = (t: string, id: string) => request<AccessModule[]>(t, `/users/${id}/access`);
export const setUserAccess = (t: string, id: string, modules: { module_id: string; permission_ids: string[] }[]) =>
  request<unknown>(t, `/users/${id}/modules`, json('PUT', { modules }));
export const updateMe = (t: string, data: Record<string, string>) =>
  request<User>(t, '/me', json('PATCH', data));
export const changeMyPassword = (t: string, current: string, next: string) =>
  request<void>(t, '/me/change-password', json('POST', { current_password: current, new_password: next }));
