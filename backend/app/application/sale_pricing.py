"""Sale money math, exactly as the DB computes and checks it at COMMIT (one function for preview and create).

  line_gross = round(quantity * unit_price, 2)        line_total = line_gross - line_discount
  subtotal   = sum(line_total)                         total      = subtotal - sale_discount
  tax_amount = round(line_total * rate / (1 + rate), 2)            (prices include tax)
  tax_total  = round(sum(tax_amount) * total / subtotal, 2)         (0 when subtotal = 0)
"""
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, ROUND_HALF_UP)  # = PostgreSQL ROUND(numeric, 2) for the positive amounts we handle


def promotion_discount(promo: dict, quantity: Decimal, unit_price: Decimal) -> Decimal:
    """= fn_promotion_discount: PERCENT of the line, AMOUNT per unit (capped at the line), BUY_X_GET_Y free units."""
    gross = money(quantity * unit_price)
    if promo["kind"] == "PERCENT":
        return money(gross * Decimal(promo["percent"]) / 100)
    if promo["kind"] == "AMOUNT":
        return min(money(quantity * Decimal(promo["amount"])), gross)
    sets = (quantity / (promo["buy_quantity"] + promo["get_quantity"])).to_integral_value(ROUND_FLOOR)
    return money(sets * promo["get_quantity"] * unit_price)


def list_price(general: Decimal, quantity: Decimal, tiers: list[tuple[Decimal, Decimal]], percent: Decimal) -> Decimal:
    """The price a customer's price list charges for a product. tiers: [(min_quantity, price)] of that product in
    the list: the highest step reached wins ("from 12 pieces, $85"); below them, or without its own price, the
    general price adjusted by the list's percent (-10 = 10% less)."""
    reached = [(m, p) for m, p in tiers if m <= quantity]
    if reached:
        return max(reached)[1]
    return money(general * (1 + percent / 100)) if percent else general


def price_sale(lines: list[dict], sale_discount: Decimal) -> dict:
    """lines: [{quantity, unit_price, discount, tax_rate}] (discount already resolved, promotion or manual).
    Returns the lines with gross / line_total / tax_amount and the header totals."""
    priced = []
    for line in lines:
        gross = money(line["quantity"] * line["unit_price"])
        line_total = gross - line["discount"]
        rate = Decimal(line["tax_rate"])
        priced.append({**line, "gross": gross, "line_total": line_total,
                       "tax_amount": money(line_total * rate / (1 + rate))})
    subtotal = sum((p["line_total"] for p in priced), Decimal(0))
    total = subtotal - sale_discount
    tax = sum((p["tax_amount"] for p in priced), Decimal(0))
    return {
        "lines": priced, "subtotal": subtotal, "discount": sale_discount, "total": total,
        "tax_total": money(tax * total / subtotal) if subtotal else Decimal(0),
    }
