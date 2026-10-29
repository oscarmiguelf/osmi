// Server-side client for the branches API.
import { ApiError, apiFieldErrors, request } from './api';

export interface Branch {
  id: string;
  name: string;
  code: string;
  phone: string | null;
  address: string | null;
  deleted_at: string | null;
  code_editable: boolean;
  user_count: number;
}

export interface BranchInput {
  name: string;
  code: string;
  phone: string | null;
  address: string | null;
}

export interface BranchMember {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
}

export interface BranchHistoryEntry {
  changed_at: string;
  entity_type: 'branch' | 'user_branch';
  action: 'INSERT' | 'UPDATE' | 'DELETE' | 'RESTORE';
  changed_by_email: string | null;
  changed_fields: string[] | null;
  old_data: Record<string, unknown> | null;
  new_data: Record<string, unknown> | null;
  member_email: string | null;
}

export const listBranches = (token: string, includeDeleted = false) =>
  request<Branch[]>(token, `/branches?include_deleted=${includeDeleted}`);
export const getBranch = (token: string, id: string) => request<Branch>(token, `/branches/${id}`);
export const createBranch = (token: string, data: BranchInput) =>
  request<Branch>(token, '/branches', { method: 'POST', body: JSON.stringify(data) });
export const updateBranch = (token: string, id: string, data: Partial<BranchInput>) =>
  request<Branch>(token, `/branches/${id}`, { method: 'PATCH', body: JSON.stringify(data) });
export const deleteBranch = (token: string, id: string) => request<void>(token, `/branches/${id}`, { method: 'DELETE' });
export const restoreBranch = (token: string, id: string) =>
  request<Branch>(token, `/branches/${id}/restore`, { method: 'POST' });
export const branchMembers = (token: string, id: string) => request<BranchMember[]>(token, `/branches/${id}/users`);
export const addBranchMember = (token: string, id: string, userId: string) =>
  request<void>(token, `/branches/${id}/users`, { method: 'POST', body: JSON.stringify({ user_id: userId }) });
export const removeBranchMember = (token: string, id: string, userId: string) =>
  request<void>(token, `/branches/${id}/users/${userId}`, { method: 'DELETE' });
export const branchHistory = (token: string, id: string, page: number, pageSize = 15) =>
  request<{ items: BranchHistoryEntry[]; has_more: boolean }>(token, `/branches/${id}/history?page=${page}&page_size=${pageSize}`);

/** API errors on the branch form -> messages per field, or one message for the whole form. */
export function branchFormErrors(
  e: ApiError,
  messages: { errors: Record<string, string>; taken: Record<string, string>; codeLocked: string; failed: string },
): { fields: Record<string, string>; form?: string } {
  if (e.status === 422) {
    const fields = apiFieldErrors(e.body, messages.errors);
    return Object.keys(fields).length ? { fields } : { fields, form: messages.failed };
  }
  const detail = e.body?.detail;
  if (e.status === 409 && detail?.field === 'code') return { fields: { code: messages.codeLocked } };
  if (e.status === 409 && Array.isArray(detail?.fields)) {
    return { fields: Object.fromEntries(detail.fields.map((f: string) => [f, messages.taken[f]])) };
  }
  return { fields: {}, form: messages.failed };
}
