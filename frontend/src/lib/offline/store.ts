// The device's copy for selling without internet (browser only): the catalog snapshot and the queue of offline sales.
// IndexedDB, not localStorage: it holds thousands of products and it must survive the browser closing.
import { toAmount } from './price';

export interface Snapshot {
  generated_at: string;
  user_id: string;
  user: string;
  locale: 'es' | 'en';
  branch: { id: string; name: string; address: string | null; phone: string | null };
  register: { id: string; name: string };
  products: { id: string; name: string; barcode: string | null; price: string; unit: string; tax_rate: string; tracks_stock: boolean;
    is_kit: boolean; stock: string | null }[];
  price_lists: { id: string; name: string; percent: string; tiers: Record<string, [string, string][]> }[];
  customers: { id: string; full_name: string; price_list_id: string | null }[];
  payment_methods: { id: string; description: string }[];
}

export interface QueuedSale {
  id: string;
  offline_folio: string;
  sold_at: string;
  cash_register_id: string;
  customer_id: string | null;
  items: { product_id: string; quantity: string; unit_price: string }[];
  payments: { payment_method_id: string; amount: string; amount_tendered: string | null }[];
  // Not sent: who sold it, what the ticket showed, and how syncing went
  user_id: string;
  branch_id: string;
  ticket: { lines: { name: string; quantity: string; unit: string; unit_price: string; total: string }[]; total: string; change: string;
    customer: string | null; method: string; register: string };
  status: 'pending' | 'synced' | 'error';
  folio?: string;
  error?: string;
  synced_at?: string;
}

const DB = 'osmi-offline';
let opening: Promise<IDBDatabase> | null = null;
function db() {
  return (opening ??= new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => {
      req.result.createObjectStore('kv');
      req.result.createObjectStore('queue', { keyPath: 'id' });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => { opening = null; reject(req.error); };
  }));
}

async function run<T>(store: 'kv' | 'queue', mode: IDBTransactionMode, op: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const tx = (await db()).transaction(store, mode);
  const req = op(tx.objectStore(store));
  return new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve(req.result);
    tx.onerror = tx.onabort = () => reject(tx.error ?? req.error);
  });
}

export const getKv = <T>(key: string) => run<T | undefined>('kv', 'readonly', (s) => s.get(key) as IDBRequest<T | undefined>);
export const setKv = (key: string, value: unknown) => run('kv', 'readwrite', (s) => s.put(value, key));
export const deleteKv = (key: string) => run('kv', 'readwrite', (s) => s.delete(key));
export const queued = () => run<QueuedSale[]>('queue', 'readonly', (s) => s.getAll() as IDBRequest<QueuedSale[]>)
  .then((all) => all.sort((a, b) => a.sold_at.localeCompare(b.sold_at)));
export const putQueued = (sale: QueuedSale) => run('queue', 'readwrite', (s) => s.put(sale));
export const deleteQueued = (id: string) => run('queue', 'readwrite', (s) => s.delete(id));

const ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'; // no 0/O, 1/I: read aloud or typed from a ticket
/** The next temporary folio of this device: OFF-K7QX-12. The device code is made once and kept. */
export async function nextOfflineFolio() {
  let device = await getKv<string>('device');
  if (!device) {
    device = Array.from(crypto.getRandomValues(new Uint8Array(4)), (b) => ALPHABET[b % ALPHABET.length]).join('');
    await setKv('device', device);
  }
  const n = ((await getKv<number>('counter')) ?? 0) + 1;
  await setKv('counter', n);
  return `OFF-${device}-${n}`;
}

/** Removes what a signed-out device shouldn't keep (catalog, customers). Queued sales stay: they were paid and must be sent. */
export const forgetSnapshot = () => deleteKv('snapshot');

export { toAmount };
