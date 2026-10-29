from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from app.application.errors import Conflict, Invalid, NotFound
from app.application.outgoing_payments import paid_totals, record_payment
from app.application.ports.purchase_repository import PurchaseRepository
from app.application.stock_rules import check_stock_product

CENT = Decimal("0.01")
CLOCK_SKEW = timedelta(minutes=5)  # a purchase date a little ahead of our clock is a device clock, not the future


def line_total(quantity: Decimal, unit_cost: Decimal) -> Decimal:
    """Same rounding as the DB's generated purchase_items.line_total, so total = SUM(line_total) holds at commit."""
    return (quantity * unit_cost).quantize(CENT, ROUND_HALF_UP)


def average_in(stock: Decimal, cost: Decimal, quantity: Decimal, value: Decimal) -> Decimal:
    """Weighted average cost after `quantity` units worth `value` come in. stock = units on hand in ALL branches before."""
    if stock <= 0:  # nothing on hand: the old cost weighs nothing
        return (value / quantity).quantize(CENT, ROUND_HALF_UP)
    return ((stock * cost + value) / (stock + quantity)).quantize(CENT, ROUND_HALF_UP)


def average_out(stock: Decimal, cost: Decimal, quantity: Decimal, value: Decimal) -> Decimal:
    """Undo average_in when a purchase is voided. stock = units on hand before taking them out."""
    left, worth = stock - quantity, stock * cost - value
    if left <= 0 or worth < 0:  # nothing left to value, or the cost was edited by hand since: keep it
        return cost
    return (worth / left).quantize(CENT, ROUND_HALF_UP)


def _by_product(items) -> dict:
    """{product_id: (quantity, value)} over all lines of each product."""
    totals: dict = {}
    for i in items:
        q, v = totals.get(i["product_id"], (Decimal(0), Decimal(0)))
        totals[i["product_id"]] = (q + Decimal(i["quantity"]), v + Decimal(i["line_total"]))
    return totals


class PurchaseService:
    def __init__(self, repo: PurchaseRepository):
        self.repo = repo

    def create(self, uid, branch, header, items: list[dict]):
        cash, other = header.pop("cash_amount", Decimal(0)), header.pop("other_amount", Decimal(0))
        if not items:
            raise Invalid({"message": "add at least one product", "field": "items"})
        # Same product at the same cost: one line. At a different cost: separate lines (the DB allows it)
        merged: dict = {}
        for i in items:
            key = (i["product_id"], i["unit_cost"])
            merged[key] = merged.get(key, Decimal(0)) + i["quantity"]
        items = [{"product_id": p, "unit_cost": c, "quantity": q} for (p, c), q in merged.items()]
        self._check_header(header)
        products = self.repo.stock_products(list({i["product_id"] for i in items}))
        for item in items:
            check_stock_product(products.get(item["product_id"]), item["quantity"])
            item["line_total"] = line_total(item["quantity"], item["unit_cost"])
        header["total"] = sum((i["line_total"] for i in items), Decimal(0))
        # Average cost first: it weighs the stock on hand BEFORE these units come in
        costs = self._apply_costs(uid, _by_product(items), average_in)
        purchase_id = self.repo.create(uid, branch, header, items)
        record_payment(self.repo, uid, branch, "purchase", purchase_id, header["total"], cash, other, header.get("reference"))
        self.repo.commit()
        return {**self.get(branch, purchase_id), "cost_changes": costs}

    def update(self, uid, branch, purchase_id, fields):
        purchase = self._active(branch, purchase_id)
        self._check_header(fields)
        if fields:
            self.repo.update(uid, purchase["id"], fields)
            self.repo.commit()
        return self.get(branch, purchase_id)

    def search(self, branch, filters, page, page_size):
        rows = self.repo.search(branch, filters, page_size + 1, (page - 1) * page_size)
        return {"items": rows[:page_size], "page": page, "page_size": page_size, "has_more": len(rows) > page_size}

    def get(self, branch, purchase_id):
        purchase = self.repo.get(purchase_id)
        if purchase is None or purchase["branch_id"] != branch:  # other branches' purchases are "not found"
            raise NotFound("purchase not found")
        payments = self.repo.payments("purchase", purchase_id)
        return {**purchase, **paid_totals(payments, purchase["total"]), "payments": payments}

    def pay(self, uid, branch, purchase_id, cash: Decimal, other: Decimal, notes):
        """Pay (part of) what is still owed to the supplier."""
        purchase = self._active(branch, purchase_id)
        if not cash and not other:
            raise Invalid({"message": "enter how much was paid", "field": "cash_amount"})
        record_payment(self.repo, uid, branch, "purchase", purchase_id, purchase["owed"], cash, other, notes or purchase["reference"])
        self.repo.commit()
        return self.get(branch, purchase_id)

    def void(self, uid, branch, purchase_id):
        """Void + take its stock out + undo its effect on the average cost + its cash back to the register, in one transaction."""
        self._active(branch, purchase_id)
        items = self.repo.items(purchase_id)  # exact decimals (the detail's JSON would give floats)
        totals = _by_product(items)
        names = {i["product_id"]: i["product"] for i in items}
        stock = self.repo.lock_branch_stock(branch, list(totals))
        short = [{"product_id": str(p), "product": names[p], "needed": q, "available": stock.get(p, Decimal(0))}
                 for p, (q, _) in totals.items() if stock.get(p, Decimal(0)) < q]
        if short:  # already sold or moved: the stock can't go back
            raise Conflict({"message": "some of its stock is no longer in this branch", "products": short})
        costs = self._apply_costs(uid, totals, average_out)
        returned = self.repo.return_cash(uid, "purchase", purchase_id)  # before the void: payments need an active parent
        self.repo.void(uid, branch, purchase_id, {p: q for p, (q, _) in totals.items()})
        self.repo.commit()
        return {"voided": True, "cost_changes": costs, "cash_returned": returned}

    def history(self, branch, purchase_id, page, page_size):
        self.get(branch, purchase_id)
        rows = self.repo.history(purchase_id, page_size + 1, (page - 1) * page_size)
        return {"items": rows[:page_size], "page": page, "page_size": page_size, "has_more": len(rows) > page_size}

    def last_price(self, product_id):
        return self.repo.last_price(product_id)

    def product_lines(self, branch, product_id, page, page_size):
        rows = self.repo.product_lines(branch, product_id, page_size + 1, (page - 1) * page_size)
        return {"items": rows[:page_size], "page": page, "page_size": page_size, "has_more": len(rows) > page_size}

    def summary(self, branch, start, end, tz):
        if end <= start:
            raise Invalid({"message": "'to' must be after 'from'", "field": "to"})
        return self.repo.summary(branch, start, end, tz)

    def _active(self, branch, purchase_id):
        purchase = self.get(branch, purchase_id)
        if purchase["deleted_at"] is not None:
            raise Conflict({"message": "the purchase is voided"})
        return purchase

    def _check_header(self, header):
        if header.get("supplier_id") and not self.repo.supplier_active(header["supplier_id"]):
            raise Invalid({"message": "the supplier doesn't exist or is deleted", "field": "supplier_id"})
        if header.get("purchased_at") and header["purchased_at"] > datetime.now(timezone.utc) + CLOCK_SKEW:
            raise Invalid({"message": "the purchase date can't be in the future", "field": "purchased_at"})

    def _apply_costs(self, uid, totals, rule):
        """products.cost is one number for all branches, so the average weighs the stock of every branch."""
        changes = []
        for p in self.repo.cost_basis(list(totals)):  # locks the product rows until commit
            quantity, value = totals[p["id"]]
            new = rule(Decimal(p["stock"]), Decimal(p["cost"]), quantity, value)
            if new != p["cost"]:
                self.repo.set_cost(uid, p["id"], new)
                changes.append({"product_id": str(p["id"]), "product": p["name"], "old_cost": p["cost"], "new_cost": new})
        return changes
