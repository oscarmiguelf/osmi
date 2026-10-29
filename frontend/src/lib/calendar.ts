// Server-side client for the calendar API, called with the signed-in user's access token.
import { request } from './api';

export { ApiError } from './api';

export type AccessLevel = 'owner' | 'edit' | 'view';

export interface Calendar {
  id: string;
  name: string;
  description: string | null;
  color: string | null;
  access_level: AccessLevel;
}

export interface CalendarEvent {
  id: string;
  calendar_id: string;
  title: string;
  description: string | null;
  location: string | null;
  start_at: string; // ISO instant, UTC
  end_at: string;
  customer_id: string | null;
  customer_name: string | null;
  customer_deleted: boolean | null;
}

export interface EventInput {
  title: string;
  description: string | null;
  location: string | null;
  start_at: string;
  end_at: string;
  customer_id?: string | null; // omitted = leave as is, null = unlink
}

/** Choices offered when creating a calendar. Stored in calendars.color, so these are data, not theme tokens. */
export const CALENDAR_COLORS = ['#284b63', '#218c74', '#e67e22', '#d93838', '#7b5ea7', '#2f80c2', '#c2477f', '#6b7f2a'];


export const listCalendars = (token: string) => request<Calendar[]>(token, '/calendars');

export const createCalendar = (token: string, data: { name: string; description: string | null; color: string }) =>
  request<Calendar>(token, '/calendars', { method: 'POST', body: JSON.stringify(data) });

export function listEvents(token: string, from: string, to: string, calendarIds?: string[]) {
  const query = new URLSearchParams({ from, to });
  calendarIds?.forEach((id) => query.append('calendar_ids', id));
  return request<CalendarEvent[]>(token, `/events?${query}`);
}

export const createEvent = (token: string, calendarId: string, data: EventInput) =>
  request<CalendarEvent>(token, `/calendars/${calendarId}/events`, { method: 'POST', body: JSON.stringify(data) });

export const updateEvent = (token: string, eventId: string, data: EventInput) =>
  request<CalendarEvent>(token, `/events/${eventId}`, { method: 'PATCH', body: JSON.stringify(data) });

export const deleteEvent = (token: string, eventId: string) =>
  request<void>(token, `/events/${eventId}`, { method: 'DELETE' });

export interface Member {
  user_id: string;
  email: string;
  name: string;
  access_level: 'edit' | 'view';
}

export interface UserResult {
  id: string;
  name: string;
  email: string;
}

export const updateCalendar = (token: string, id: string, data: { name: string; description: string | null; color: string }) =>
  request<Calendar>(token, `/calendars/${id}`, { method: 'PATCH', body: JSON.stringify(data) });

export const deleteCalendar = (token: string, id: string) =>
  request<void>(token, `/calendars/${id}`, { method: 'DELETE' });

export const listMembers = (token: string, calendarId: string) =>
  request<Member[]>(token, `/calendars/${calendarId}/members`);

export const addMember = (token: string, calendarId: string, userId: string, accessLevel: string) =>
  request<Member>(token, `/calendars/${calendarId}/members`, {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, access_level: accessLevel }),
  });

export const updateMember = (token: string, calendarId: string, userId: string, accessLevel: string) =>
  request<Member>(token, `/calendars/${calendarId}/members/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify({ access_level: accessLevel }),
  });

export const revokeMember = (token: string, calendarId: string, userId: string) =>
  request<void>(token, `/calendars/${calendarId}/members/${userId}`, { method: 'DELETE' });

export const searchUsers = (token: string, q: string) =>
  request<UserResult[]>(token, `/users/search?${new URLSearchParams({ q })}`);
