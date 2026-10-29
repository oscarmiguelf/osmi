from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.application.errors import Conflict, Invalid, NotFound
from app.application.ports.offline_repository import OfflineRepository
from app.application.ports.sale_repository import SaleRepository
from app.application.sale_pricing import list_price, price_sale
from app.application.sale_service import NO_REGISTER, stock_shortages


class OfflineSaleService:
    """Sales made while the register had no internet, sent when it comes back.

    The customer already paid and took the goods, so a sale that arrives is recorded even if the world changed meanwhile:
    a price that changed or stock that wasn't there is saved as an issue to review, never as a rejection. What can't be
    recorded (another register, a deleted product) is refused with a reason and stays queued on the device."""

    def __init__(self, sales: SaleRepository, repo: OfflineRepository):
        self.sales = sales
        self.repo = repo

    def snapshot(self, uid, branch):
        register = self.sales.current_register(uid, branch)
        if register is None:
            raise Conflict(NO_REGISTER)
        return {**self.repo.snapshot(branch), "register": register, "generated_at": datetime.now(timezone.utc)}

    def create(self, uid, branch, body):
        existing = self.sales.sale_owner(body["id"])
        if existing is not None:  # sent before (the answer got lost): same sale, nothing new
            if existing["branch_id"] != branch:
                raise Conflict({"message": "that sale id is already used"})
            return {"sale": self.sales.get(body["id"]), "issues": []}
        if self.repo.folio_owner(body["offline_folio"]) is not None:
            raise Conflict({"message": "that offline folio is already used", "code": "offline_folio"})
        if body["sold_at"] > datetime.now(timezone.utc) + timedelta(minutes=10):
            raise Invalid({"message": "the sale date is in the future", "field": "sold_at"})
        register = self.sales.current_register(uid, branch)
        if register is None or register["id"] != body["cash_register_id"]:
            # The DB only takes a sale from whoever occupies its register: it waits on the device until they do
            raise Conflict({**NO_REGISTER, "message": "occupy the register the sale was made at to send it", "code": "offline_register"})

        items = body["items"]
        products = self.sales.products(list({i["product_id"] for i in items}))
        gone = [str(i["product_id"]) for i in items if products.get(i["product_id"]) is None or products[i["product_id"]]["deleted_at"]]
        if gone:
            raise Invalid({"message": "a product of the sale was deleted; restore it to send the sale", "code": "product_gone", "products": gone})
        if self.sales.product_benefits(list(products)):
            raise Invalid({"message": "packages and memberships aren't sold offline", "code": "benefit"})
        customer = body.get("customer_id")
        if customer and not self.sales.customer_exists(customer):
            customer = None  # deleted meanwhile: the sale stays, without the customer
        plist = self.sales.price_list_for(customer) if customer else None
        tiers = self.sales.list_tiers(plist["id"], list(products)) if plist else {}

        issues, lines = [], []
        for item in items:
            product = products[item["product_id"]]
            applies = list_price(product["price"], item["quantity"], tiers.get(product["id"], []), plist["percent"]) if plist else product["price"]
            if item["unit_price"] != applies:  # charged with the prices the device had: kept, and flagged
                issues.append({"kind": "price", "detail": {"product_id": product["id"], "product": product["name"],
                                                           "charged": item["unit_price"], "current": applies}})
            lines.append({"product_id": product["id"], "product": product["name"], "unit": product["unit"], "quantity": item["quantity"],
                          "unit_price": item["unit_price"], "discount": Decimal(0), "promotion_id": None, "tax_rate": product["tax_rate"],
                          "fulfillment": "DELIVERED",
                          "price_list_id": plist["id"] if plist and item["unit_price"] == applies != product["price"] else None,
                          "tracks_stock": product["tracks_stock"], "is_kit": product["is_kit"]})
        priced = price_sale(lines, Decimal(0))

        payments = body["payments"]
        methods = self.sales.payment_methods(list({p["payment_method_id"] for p in payments}))
        for n, p in enumerate(payments):
            method = methods.get(p["payment_method_id"])
            if method is None or method["is_credit"]:
                raise Invalid({"message": "offline sales are paid in full (no credit)", "field": f"payments.{n}.payment_method_id"})
            if p.get("amount_tendered") is not None and p["amount_tendered"] < p["amount"]:
                raise Invalid({"message": "the cash handed over is less than the amount", "field": f"payments.{n}.amount_tendered"})
        if sum((p["amount"] for p in payments), Decimal(0)) != priced["total"]:
            raise Invalid({"message": "the payments don't add up to the total", "field": "payments", "total": priced["total"]})

        for short in stock_shortages(self.sales, branch, priced["lines"]):
            issues.append({"kind": "stock", "detail": short})
        header = {k: priced[k] for k in ("subtotal", "discount", "total", "tax_total")}
        header.update(customer_id=customer, status="PAID", quote_id=None, appointment_id=None, uses=[], grants=[],
                      sold_at=body["sold_at"], offline_folio=body["offline_folio"], offline_issues=issues)
        self.sales.create(uid, branch, register["id"], body["id"], header, priced["lines"],
                          [{"amount_tendered": None, "reference": None, **p} for p in payments])
        return {"sale": self.sales.get(body["id"]), "issues": issues}

    def issues(self, branch, resolved=False):
        return self.repo.issues(branch, resolved)

    def resolve(self, uid, branch, issue_id, note):
        issue = self.repo.issue(issue_id)
        if issue is None or issue["branch_id"] != branch:
            raise NotFound("issue not found")
        if issue["resolved_at"]:
            raise Conflict({"message": "already reviewed", "code": "resolved"})
        self.repo.resolve(uid, issue_id, note)
        self.repo.commit()
