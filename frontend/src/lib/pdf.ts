// PDFs sent to customers (WhatsApp): the sale ticket and the prescription. Server-side only (pdf-lib, standard fonts).
import { PDFDocument, rgb, StandardFonts, type PDFFont, type PDFImage } from 'pdf-lib';
import { fmt, money, type Dict, type Locale } from '@/i18n';
import type { Prescription } from './clinical';
import { formatPhone } from './customers';
import type { Quote, Sale } from './sales';

type Align = 'left' | 'center' | 'right';
type Op = { y: number } & ({ kind: 'text'; text: string; x: number; size: number; font: PDFFont }
  | { kind: 'rule'; thick: number; x1: number; x2: number } | { kind: 'image'; img: PDFImage; x: number; w: number; h: number });

// The standard fonts only know WinAnsi (Latin-1 + a few): Intl's narrow spaces and the minus sign would throw
const WIN_ANSI = /[^\x20-\x7e\xa0-\xff€‚ƒ„…†‡ˆ‰Š‹ŒŽ‘’“”•–—˜™š›œžŸ]/g;
const clean = (s: string) => s.normalize('NFC').replace(/[   ]/g, ' ').replace(/−/g, '-').replace(/\s+/g, ' ').replace(WIN_ANSI, '?');

/** Lays content out top to bottom, then paints it on one page that fits (ticket) or on fixed-size pages (letter). */
class Flow {
  ops: Op[] = [];
  y = 0;
  constructor(public width: number, public regular: PDFFont, public bold: PDFFont) {}

  lines(text: string, size: number, font: PDFFont, width: number) {
    const out: string[] = [];
    for (const para of String(text).split('\n')) {
      let line = '';
      for (const word of clean(para).split(' ')) {
        const next = line ? `${line} ${word}` : word;
        if (line && font.widthOfTextAtSize(next, size) > width) {
          out.push(line);
          line = word;
        } else line = next;
      }
      out.push(line);
    }
    return out;
  }

  text(text: string, opts: { size?: number; bold?: boolean; align?: Align; x?: number; width?: number; gap?: number } = {}) {
    const { size = 9, bold = false, align = 'left', x = 0, gap = 1.35 } = opts;
    const width = opts.width ?? this.width - x;
    const font = bold ? this.bold : this.regular;
    for (const line of this.lines(text, size, font, width)) {
      const w = font.widthOfTextAtSize(line, size);
      const lx = align === 'left' ? x : align === 'center' ? x + (width - w) / 2 : x + width - w;
      this.ops.push({ kind: 'text', text: line, x: lx, y: this.y + size, size, font });
      this.y += size * gap;
    }
  }

  /** Label on the left, amount on the right, same line */
  row(left: string, right: string, { size = 9, bold = false } = {}) {
    const font = bold ? this.bold : this.regular;
    const rw = font.widthOfTextAtSize(clean(right), size) + 6;
    const top = this.y;
    this.text(left, { size, bold, width: this.width - rw });
    const end = this.y;
    this.y = top;
    this.text(right, { size, bold, align: 'right' });
    this.y = Math.max(end, this.y);
  }

  rule(thick = 0.6, gap = 6) {
    this.y += gap;
    this.ops.push({ kind: 'rule', y: this.y, thick, x1: 0, x2: this.width });
    this.y += gap;
  }

  image(img: PDFImage, maxW: number, maxH: number, align: Align = 'center') {
    const scale = Math.min(maxW / img.width, maxH / img.height, 1);
    const w = img.width * scale;
    const h = img.height * scale;
    const x = align === 'left' ? 0 : align === 'center' ? (this.width - w) / 2 : this.width - w;
    this.ops.push({ kind: 'image', img, x, y: this.y + h, w, h });
    this.y += h;
  }

  /** pageHeight null: one page as tall as the content (a receipt) */
  paint(pdf: PDFDocument, pageWidth: number, margin: number, pageHeight: number | null) {
    const usable = pageHeight === null ? this.y : pageHeight - 2 * margin;
    const height = pageHeight ?? this.y + 2 * margin;
    const pages: ReturnType<PDFDocument['addPage']>[] = [];
    for (const op of this.ops) {
      const n = pageHeight === null ? 0 : Math.max(0, Math.floor((op.y - 0.01) / usable));
      while (pages.length <= n) pages.push(pdf.addPage([pageWidth, height]));
      const page = pages[n];
      const y = height - margin - (op.y - n * usable);
      if (op.kind === 'text') page.drawText(op.text, { x: margin + op.x, y, size: op.size, font: op.font, color: rgb(0.07, 0.07, 0.07) });
      else if (op.kind === 'rule') page.drawLine({ start: { x: margin + op.x1, y }, end: { x: margin + op.x2, y }, thickness: op.thick, color: rgb(0.2, 0.2, 0.2) });
      else page.drawImage(op.img, { x: margin + op.x, y, width: op.w, height: op.h });
    }
    if (!pages.length) pdf.addPage([pageWidth, height]);
  }
}

async function start(title: string, logo: Uint8Array | null) {
  const pdf = await PDFDocument.create();
  pdf.setTitle(clean(title));
  pdf.setProducer('Osmi');
  pdf.setCreator('Osmi');
  const [regular, bold] = await Promise.all([pdf.embedFont(StandardFonts.Helvetica), pdf.embedFont(StandardFonts.HelveticaBold)]);
  // The API always stores the logo as PNG; a broken file just leaves it out
  const img = logo ? await pdf.embedPng(logo).catch(() => null) : null;
  return { pdf, regular, bold, img };
}

/** An 80 mm receipt, as tall as it needs to be. */
export async function ticketPdf(sale: Sale, t: Dict, locale: Locale, timeZone: string, logo: Uint8Array | null) {
  const s = t.sales;
  const title = fmt(s.detail.title, { folio: sale.folio });
  const { pdf, regular, bold, img } = await start(title, logo);
  const W = 227; // 80 mm
  const M = 14;
  const f = new Flow(W - 2 * M, regular, bold);
  const when = new Intl.DateTimeFormat(t.intl, { dateStyle: 'medium', timeStyle: 'short', timeZone });
  const m = (n: number) => money(locale, Number(n));
  if (img) {
    f.image(img, 110, 55);
    f.y += 6;
  }
  f.text(sale.branch, { size: 11, bold: true, align: 'center' });
  if (sale.branch_address) f.text(sale.branch_address, { size: 8, align: 'center' });
  if (sale.branch_phone) f.text(sale.branch_phone, { size: 8, align: 'center' });
  f.y += 4;
  f.text(`${title} · ${when.format(new Date(sale.sold_at))}`, { size: 8, align: 'center' });
  if (sale.customer) f.text(`${s.detail.customer}: ${sale.customer}`, { size: 8, align: 'center' });
  f.rule();
  for (const i of sale.items) {
    f.text(i.product, { size: 9 });
    const qty = `${Number(i.quantity)} ${t.products.unitNames[i.unit] ?? i.unit} × ${m(i.unit_price)}`
      + (Number(i.discount) > 0 ? ` · -${m(i.discount)}` : '')
      + (Number(i.returned_quantity) > 0 ? ` · ${fmt(s.detail.returnedQty, { n: Number(i.returned_quantity) })}` : '');
    f.row(qty, m(i.line_total), { size: 8 });
    f.y += 3;
  }
  f.rule();
  f.row(s.cart.subtotal, m(sale.subtotal));
  if (Number(sale.discount) > 0) f.row(s.cart.discount, `-${m(sale.discount)}`);
  f.row(s.cart.total, m(sale.total), { size: 11, bold: true });
  f.row(s.detail.taxIncluded, m(sale.tax_total), { size: 8 });
  const paid = sale.payments.filter((p) => p.kind === 'sale');
  if (paid.length) {
    f.y += 6;
    for (const p of paid) f.row(t.cash.methodNames[p.method] ?? p.method, m(p.amount), { size: 8 });
    const change = sale.payments.reduce((sum, p) => sum + Number(p.change_given ?? 0), 0);
    if (change > 0) f.row(s.cart.change, m(change), { size: 9, bold: true });
  }
  if (Number(sale.credit_outstanding) > 0) f.row(t.share.owed, m(sale.credit_outstanding), { size: 9, bold: true });
  f.y += 10;
  f.text(s.detail.thanks, { size: 9, align: 'center' });
  f.paint(pdf, W, M, null);
  return pdf.save();
}

/** A letter-size prescription: the doctor's header (Settings), patient, date, diagnosis, medicines and the signature line. */
export async function prescriptionPdf(rx: Prescription, t: Dict, timeZone: string, logo: Uint8Array | null) {
  const c = t.clinical;
  const date = new Intl.DateTimeFormat(t.intl, { dateStyle: 'long', timeZone }).format(new Date(rx.created_at));
  const { pdf, regular, bold, img } = await start(fmt(c.rxOf, { date }), logo);
  const [W, H, M] = [612, 792, 54];
  const f = new Flow(W - 2 * M, regular, bold);
  const header = rx.doctor_header || rx.author || '';
  if (img) {
    // Logo on the left, the doctor's header next to it
    const top = f.y;
    f.image(img, 120, 64, 'left');
    const below = f.y;
    f.y = top;
    f.text(header, { size: 11, bold: true, x: 136 });
    f.text([rx.branch, rx.branch_address, rx.branch_phone].filter(Boolean).join(' · '), { size: 8.5, x: 136 });
    f.y = Math.max(f.y, below);
  } else {
    f.text(header, { size: 12, bold: true });
    f.text([rx.branch, rx.branch_address, rx.branch_phone].filter(Boolean).join(' · '), { size: 8.5 });
  }
  f.rule(1.4, 8);
  const top = f.y;
  f.text(c.rxPatient.toUpperCase(), { size: 7 });
  f.text(rx.patient, { size: 11, width: f.width - 170 });
  const end = f.y;
  f.y = top;
  f.text(c.rxDate.toUpperCase(), { size: 7, align: 'right' });
  f.text(date, { size: 11, align: 'right' });
  f.y = Math.max(end, f.y) + 6;
  if (rx.diagnosis) {
    f.text(c.rxDiagnosis.toUpperCase(), { size: 7 });
    f.text(rx.diagnosis, { size: 10 });
  }
  f.y += 12;
  f.text('Rx', { size: 20, bold: true });
  f.y += 6;
  rx.items.forEach((med, n) => {
    f.text(`${n + 1}. ${med.name}${med.dose ? ` — ${med.dose}` : ''}`, { size: 11, bold: true });
    if (med.instructions) f.text(med.instructions, { size: 10, x: 16 });
    f.y += 8;
  });
  f.y += 64;
  f.ops.push({ kind: 'rule', y: f.y, thick: 0.8, x1: f.width - 220, x2: f.width });
  f.y += 4;
  f.text(c.rxSignature, { size: 8.5, x: f.width - 220, width: 220, align: 'center' });
  f.paint(pdf, W, M, H);
  return pdf.save();
}

/** A letter-size quote: the business (logo, branch), folio, dates, customer, lines, totals, notes and the fine print. */
export async function quotePdf(q: Quote, t: Dict, locale: Locale, timeZone: string, logo: Uint8Array | null) {
  const qt = t.quotes;
  const c = t.sales.cart;
  const title = fmt(qt.detailTitle, { folio: q.folio });
  const { pdf, regular, bold, img } = await start(title, logo);
  const [W, H, M] = [612, 792, 54];
  const f = new Flow(W - 2 * M, regular, bold);
  const day = new Intl.DateTimeFormat(t.intl, { dateStyle: 'long', timeZone });
  const m = (n: number) => money(locale, Number(n));
  // Head: the business on the left (with its logo), the quote on the right
  const top = f.y;
  if (img) {
    f.image(img, 110, 56, 'left');
    f.y += 4;
  }
  f.text(q.branch, { size: 12, bold: true, width: 280 });
  if (q.branch_address) f.text(q.branch_address, { size: 8.5, width: 280 });
  if (q.branch_phone) f.text(formatPhone(q.branch_phone), { size: 8.5, width: 280 });
  const left = f.y;
  f.y = top;
  f.text(title, { size: 13, bold: true, align: 'right' });
  f.text(fmt(qt.issued, { date: day.format(new Date(q.created_at)) }), { size: 9, align: 'right' });
  f.text(fmt(qt.validLong, { date: day.format(new Date(q.valid_until)) }), { size: 9, bold: true, align: 'right' });
  f.y = Math.max(left, f.y);
  f.rule(1.2, 8);
  f.text(qt.customer.toUpperCase(), { size: 7 });
  f.text(q.customer ?? qt.noCustomer, { size: 11, bold: true });
  if (q.customer_phone) f.text(formatPhone(q.customer_phone), { size: 9 });
  if (q.customer_email) f.text(q.customer_email, { size: 9 });
  f.y += 10;
  // Lines: product | quantity | price | amount
  const cols = [{ x: 0, w: 250 }, { x: 250, w: 90 }, { x: 340, w: 80 }, { x: 420, w: f.width - 420 }];
  const row = (cells: string[], opts: { size?: number; bold?: boolean } = {}) => {
    const start = f.y;
    let end = start;
    cells.forEach((text, n) => {
      f.y = start;
      f.text(text, { ...opts, x: cols[n].x, width: cols[n].w - (n === 0 ? 8 : 0), align: n === 0 ? 'left' : 'right' });
      end = Math.max(end, f.y);
    });
    f.y = end;
  };
  row([c.product, c.quantity, c.price, c.lineTotal], { size: 8, bold: true });
  f.rule(0.6, 3);
  for (const i of q.items) {
    row([i.product, `${Number(i.quantity)} ${t.products.unitNames[i.unit] ?? i.unit}`, m(i.unit_price), m(i.line_total)], { size: 9.5 });
    if (Number(i.discount) > 0) f.text(fmt(qt.lineDiscount, { amount: m(i.discount) }), { size: 8, width: 240 });
    f.y += 4;
  }
  f.rule(0.6, 4);
  const sums = { x: 300, width: f.width - 300 };
  const sum = (label: string, value: string, opts: { size?: number; bold?: boolean } = {}) => {
    const start = f.y;
    f.text(label, { ...opts, x: sums.x, width: 120 });
    f.y = start;
    f.text(value, { ...opts, x: sums.x, width: sums.width, align: 'right' });
  };
  sum(c.subtotal, m(q.subtotal), { size: 9.5 });
  if (Number(q.discount) > 0) sum(c.discount, `-${m(q.discount)}`, { size: 9.5 });
  sum(c.total, m(q.total), { size: 12, bold: true });
  sum(qt.taxNote, m(q.tax_breakdown.reduce((s, x) => s + Number(x.tax_amount), 0)), { size: 8 });
  if (q.notes) {
    f.y += 12;
    f.text(q.notes, { size: 9.5 });
  }
  f.y += 16;
  f.text(qt.fine, { size: 7.5 });
  f.paint(pdf, W, M, H);
  return pdf.save();
}
