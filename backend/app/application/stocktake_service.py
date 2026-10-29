from app.application.errors import Conflict, Invalid, NotFound
from app.application.ports.stocktake_repository import StocktakeRepository
from app.application.stock_rules import INTEGER_UNITS

# Blind count: whoever only counts doesn't see what the system says (they'd count "to the screen")
HIDDEN = ("system_quantity", "difference", "applied_adjustment")


class StocktakeService:
    def __init__(self, repo: StocktakeRepository):
        self.repo = repo

    def _supervisor(self, uid):
        return self.repo.has_permission(uid, "stocktakes", "update")

    def search(self, branch, filters, page, page_size):
        rows = self.repo.search(branch, filters, page_size + 1, (page - 1) * page_size)
        return {"items": rows[:page_size], "page": page, "page_size": page_size, "has_more": len(rows) > page_size}

    def current(self, branch):
        return self.repo.open_in_branch(branch)

    def open(self, uid, branch, notes):
        stocktake_id = self.repo.create(uid, branch, notes)
        if stocktake_id is None:  # one open stocktake per branch (unique index)
            existing = self.repo.open_in_branch(branch)
            raise Conflict({"message": "this branch already has an open stocktake", "code": "already_open", "stocktake": existing})
        self.repo.commit()
        return self.get(uid, branch, stocktake_id)

    def get(self, uid, branch, stocktake_id):
        st = self._in_branch(branch, stocktake_id)
        supervisor = self._supervisor(uid)
        totals = self.repo.totals(stocktake_id)
        if not supervisor:
            totals = {"counted_items": totals["counted_items"]}
        return {**st, "totals": totals, "can_see_system": supervisor,
                "uncounted": self.repo.uncounted_count(stocktake_id, branch) if st["status"] == "OPEN" else None}

    def items(self, uid, branch, stocktake_id, filters, page, page_size):
        self._in_branch(branch, stocktake_id)
        supervisor = self._supervisor(uid)
        if not supervisor:
            filters = {**filters, "only_differences": False}
        rows = self.repo.items(stocktake_id, filters, page_size + 1, (page - 1) * page_size)
        if not supervisor:
            rows = [{k: v for k, v in r.items() if k not in HIDDEN} for r in rows]
        return {"items": rows[:page_size], "page": page, "page_size": page_size, "has_more": len(rows) > page_size}

    def products(self, branch, stocktake_id, q):
        """Search for the counting screen: counters may not have access to the products module."""
        self._in_branch(branch, stocktake_id)
        return self.repo.search_countable(q, 10) if len(q) >= 2 else []

    def count(self, uid, branch, stocktake_id, product_id, counted, notes):
        """Record or correct the count of one product (one row per product: a recount overwrites it)."""
        self._open(branch, stocktake_id)
        product = self._countable(product_id, None, counted)
        item = self.repo.upsert_item(uid, stocktake_id, product["id"], counted, notes)
        self.repo.commit()
        return item if self._supervisor(uid) else {k: v for k, v in item.items() if k not in HIDDEN}

    def bulk(self, uid, branch, stocktake_id, lines):
        """Scanner / import: every line gets its own result; a bad line doesn't stop the others."""
        self._open(branch, stocktake_id)
        results = []
        for n, line in enumerate(lines):
            try:
                product = self._countable(line.get("product_id"), line.get("barcode"), line["counted_quantity"])
                self.repo.upsert_item(uid, stocktake_id, product["id"], line["counted_quantity"], line.get("notes"))
                results.append({"line": n, "ok": True, "product_id": str(product["id"]), "product": product["name"]})
            except Invalid as e:
                results.append({"line": n, "ok": False, **e.detail})
        self.repo.commit()
        return {"saved": sum(r["ok"] for r in results), "failed": sum(not r["ok"] for r in results), "results": results}

    def remove(self, uid, branch, stocktake_id, product_id):
        self._open(branch, stocktake_id)
        if not self.repo.delete_item(uid, stocktake_id, product_id):
            raise NotFound("that product wasn't counted in this stocktake")
        self.repo.commit()

    def uncounted(self, branch, stocktake_id, filters, page, page_size):
        self._in_branch(branch, stocktake_id)
        rows = self.repo.uncounted(stocktake_id, branch, filters, page_size + 1, (page - 1) * page_size)
        return {"items": rows[:page_size], "page": page, "page_size": page_size, "has_more": len(rows) > page_size}

    def differences(self, uid, branch, stocktake_id, page, page_size):
        self._in_branch(branch, stocktake_id)
        page_rows = self.items(uid, branch, stocktake_id, {"only_differences": True, "q": ""}, page, page_size)
        return {**page_rows, "totals": self.repo.totals(stocktake_id)}

    def complete(self, uid, branch, stocktake_id):
        """OPEN -> COMPLETED: the DB adjusts each counted product to exactly what was counted, at this moment."""
        self._open(branch, stocktake_id)
        if self.repo.totals(stocktake_id)["counted_items"] == 0:
            raise Invalid({"message": "count at least one product before completing", "code": "nothing_counted"})
        if not self.repo.set_status(uid, stocktake_id, "COMPLETED"):
            raise Conflict({"message": "the stocktake is no longer open", "code": "not_open"})
        self.repo.commit()
        return self.result(branch, stocktake_id)

    def cancel(self, uid, branch, stocktake_id):
        self._open(branch, stocktake_id)
        if not self.repo.set_status(uid, stocktake_id, "CANCELLED"):
            raise Conflict({"message": "the stocktake is no longer open", "code": "not_open"})
        self.repo.commit()
        return self.repo.get(stocktake_id)

    def result(self, branch, stocktake_id):
        st = self._in_branch(branch, stocktake_id)
        items = self.repo.items(stocktake_id, {"only_differences": False, "q": ""}, 10_000, 0)
        return {**st, "totals": self.repo.totals(stocktake_id), "items": items, "movements": self.repo.movements(stocktake_id)}

    def history(self, branch, stocktake_id, page, page_size):
        self._in_branch(branch, stocktake_id)
        rows = self.repo.history(stocktake_id, page_size + 1, (page - 1) * page_size)
        return {"items": rows[:page_size], "page": page, "page_size": page_size, "has_more": len(rows) > page_size}

    def sheet(self, uid, branch, stocktake_id):
        """Count sheet: products with stock in the branch, counted or not (system quantity only for supervisors)."""
        st = self._in_branch(branch, stocktake_id)
        return st, self.repo.sheet(stocktake_id, branch), self._supervisor(uid)

    # --- helpers ---
    def _in_branch(self, branch, stocktake_id):
        st = self.repo.get(stocktake_id)
        if st is None or st["branch_id"] != branch:
            raise NotFound("stocktake not found")
        return st

    def _open(self, branch, stocktake_id):
        st = self._in_branch(branch, stocktake_id)
        if st["status"] != "OPEN":
            raise Conflict({"message": f"the stocktake is {st['status']}", "code": "not_open", "status": st["status"]})
        return st

    def _countable(self, product_id, barcode, counted):
        product = self.repo.countable_product(product_id, barcode)
        if product is None or product["deleted_at"] is not None:
            raise Invalid({"message": "the product doesn't exist", "field": "product_id", "code": "not_found",
                           **({"barcode": barcode} if barcode else {})})
        if not product["tracks_stock"] or product["is_kit"]:
            raise Invalid({"message": f"{product['name']} has no stock of its own (service or kit)", "field": "product_id",
                           "code": "not_countable", "product": product["name"]})
        if product["unit"].lower() in INTEGER_UNITS and counted != counted.to_integral_value():
            raise Invalid({"message": f"{product['name']} is counted in whole units", "field": "counted_quantity",
                           "code": "whole_units", "product": product["name"]})
        return product
