// Keeps the device ready to sell without internet (browser only): refreshes the catalog copy and sends queued sales.
import { deleteQueued, getKv, putQueued, queued, setKv, type QueuedSale, type Snapshot } from './store';

const FRESH_MS = 10 * 60_000; // a copy younger than this isn't fetched again on every page
const KEEP_SYNCED_MS = 7 * 24 * 3600_000; // sent sales stay visible a week (their real folio), then go

export async function refreshSnapshot(user: { id: string; name: string }, locale: 'es' | 'en', force = false) {
  const current = await getKv<Snapshot>('snapshot');
  if (!force && current && current.user_id === user.id && Date.now() - Date.parse(current.generated_at) < FRESH_MS) return current;
  const res = await fetch('/api/offline/snapshot', { credentials: 'same-origin' });
  if (!res.ok) return current; // no register occupied, no permission, or offline: keep what there is
  const snap: Snapshot = { ...(await res.json()), user_id: user.id, user: user.name, locale };
  await setKv('snapshot', snap);
  return snap;
}

/** Sends this user's pending sales, oldest first. Stops at the first network failure (still offline). */
export async function syncQueue(userId: string) {
  let sent = 0;
  for (const sale of await queued()) {
    if (sale.status === 'synced') {
      if (sale.synced_at && Date.now() - Date.parse(sale.synced_at) > KEEP_SYNCED_MS) await deleteQueued(sale.id);
      continue;
    }
    if (sale.user_id !== userId) continue; // only whoever made it occupies its register
    const { user_id, branch_id, ticket, status, folio, error, synced_at, ...body } = sale;
    let res: Response;
    try {
      res = await fetch('/api/offline/sales', { method: 'POST', credentials: 'same-origin', headers: { 'content-type': 'application/json',
        'x-branch-id': branch_id }, body: JSON.stringify(body) });
    } catch {
      break;
    }
    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      await putQueued({ ...sale, status: 'synced', folio: data.sale?.folio, error: undefined, synced_at: new Date().toISOString() });
      sent++;
    } else if (res.status === 401) {
      break; // signed out: sent after the next sign-in
    } else {
      // Kept on the device with the reason (register not occupied, deleted product...); retried next time
      await putQueued({ ...sale, status: 'error', error: data?.detail?.code ?? String(res.status) } as QueuedSale);
    }
  }
  return sent;
}

export const pendingCount = async () => (await queued()).filter((s) => s.status !== 'synced').length;
