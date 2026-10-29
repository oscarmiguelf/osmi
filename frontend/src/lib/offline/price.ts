// Prices at the register without internet: the same rules as the API (app/application/sale_pricing.py), in whole
// cents and thousandths so the total matches the server's to the cent (the payments must add up to it).
//   line = round(quantity × price, 2)     list price = the highest quantity step reached, else general × (1 + percent/100)

/** '12.5' -> 1250 (amounts come from the API as decimal strings or numbers with at most 2 decimals) */
export const cents = (v: string | number) => Math.round(Number(v) * 100);
/** '1.25' -> 1250 thousandths (quantities have at most 3 decimals) */
export const milli = (v: string | number) => Math.round(Number(v) * 1000);
/** Round half up of a / b, for a >= 0 and b > 0 integers (= ROUND_HALF_UP of the API for our positive amounts) */
const divRound = (a: number, b: number) => Math.floor((a + b / 2) / b);

export type Tier = [string | number, string | number]; // [min_quantity, price]

/** Cents of one unit for a customer's price list. Without a list, call with tiers [] and percent 0. */
export function listPrice(generalCents: number, quantityMilli: number, tiers: Tier[], percent: string | number): number {
  const reached = tiers.map(([m, p]) => [milli(m), cents(p)] as const).filter(([m]) => m <= quantityMilli);
  if (reached.length) return reached.reduce((best, t) => (t[0] > best[0] || (t[0] === best[0] && t[1] > best[1]) ? t : best))[1];
  const pct = Math.round(Number(percent) * 100); // hundredths of a percent: -12.5% -> -1250
  return pct ? divRound(generalCents * (10000 + pct), 10000) : generalCents;
}

/** Cents of a line: round(quantity × unit price, 2) */
export const lineCents = (quantityMilli: number, unitCents: number) => divRound(quantityMilli * unitCents, 1000);

/** 1250 -> '12.50' (what the API takes) */
export const toAmount = (c: number) => (c / 100).toFixed(2);
/** 1500 -> '1.5' */
export const toQuantity = (m: number) => String(m / 1000);
