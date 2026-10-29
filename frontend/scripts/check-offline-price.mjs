// Checks the offline price rules against cases computed by the API's own rules (backend sale_pricing.py).
// Run: node scripts/check-offline-price.mjs
import assert from 'node:assert/strict';
import { cents, lineCents, listPrice, milli } from '../src/lib/offline/price.ts';

// [general, quantity, tiers, percent, expected unit price, expected line]
const cases = [
  ['10.00', '2', [], '-10', '9.00', '18.00'],
  ['100.00', '12', [['12', '85.00'], ['24', '80.00']], '0', '85.00', '1020.00'],
  ['100.00', '11.999', [['12', '85.00']], '-10', '90.00', '1079.91'],
  ['100.00', '30', [['12', '85.00'], ['24', '80.00']], '-10', '80.00', '2400.00'],
  ['33.33', '1', [], '-12.5', '29.16', '29.16'],  // 33.33 × 0.875 = 29.16375 -> 29.16
  ['9.99', '0.333', [], '0', '9.99', '3.33'],     // 3.32667 -> 3.33
  ['0.05', '0.5', [], '0', '0.05', '0.03'],       // 0.025 -> 0.03 (half up)
  ['19.90', '1.005', [], '15', '22.89', '23.00'], // 22.885 -> 22.89; 1.005 × 22.89 = 23.00445 -> 23.00
];
for (const [general, qty, tiers, pct, unit, line] of cases) {
  const u = listPrice(cents(general), milli(qty), tiers, pct);
  assert.equal(u, cents(unit), `unit ${general} × ${qty} ${pct}%`);
  assert.equal(lineCents(milli(qty), u), cents(line), `line ${general} × ${qty}`);
}
console.log(`offline price rules: ${cases.length} cases ok`);
