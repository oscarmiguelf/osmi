import uuid
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.application.errors import Conflict, Invalid, NotFound
from app.application.ports.quote_repository import QuoteRepository
from app.application.sale_pricing import list_price, money, price_sale
from app.application.sale_service import _price_list, _whole, stock_shortages

DEFAULT_VALID_DAYS = 15  # shortcut: a business setting hard-coded here; move to a settings table when someone asks to change it


def valid_until_for(days: int, tz: str, now: datetime | None = None) -> datetime:
    """End of the N-th day from today, in the person's time zone, as UTC."""
    zone = ZoneInfo(tz)
    today = (now or datetime.now(timezone.utc)).astimezone(zone).date()
    end = datetime.combine(today + timedelta(days=days), time(23, 59, 59), zone)
    return end.astimezone(timezone.utc)


class QuoteService:
    def __init__(self, repo: QuoteRepository):
        self.repo = repo

    def _compose(self, uid, branch, body):
        """Same money rules as a sale (no promotions on quotes); tax is informational."""
        items = body["items"]
        if not items:
            raise Invalid({"message": "add at least one product", "field": "items"})
        products = self.repo.products(list({i["product_id"] for i in items}))
        plist, tiers = _price_list(self.repo, body.get("customer_id"), list(products))
        lines = []
        for n, item in enumerate(items):
            product = products.get(item["product_id"])
            if product is None or product["deleted_at"] is not None:
                raise Invalid({"message": "the product doesn't exist or is deleted", "field": f"items.{n}.product_id"})
            _whole(product, item["quantity"], f"items.{n}.quantity")
            applies = list_price(product["price"], item["quantity"], tiers.get(product["id"], []), plist["percent"]) if plist else product["price"]
            price = applies if item.get("unit_price") is None else item["unit_price"]
            if price != applies:  # business rule: quotes use the price that applies too (catalog or the customer's list)
                raise Invalid({"message": "the price of a product can't be changed", "field": f"items.{n}.unit_price",
                               "price": applies})
            discount = item.get("discount") or Decimal(0)
            if discount > money(item["quantity"] * price):
                raise Invalid({"message": "the discount is larger than the line", "field": f"items.{n}.discount"})
            lines.append({"product_id": product["id"], "product": product["name"], "unit": product["unit"],
                          "quantity": item["quantity"], "unit_price": price, "catalog_price": product["price"],
                          "discount": discount, "tax_rate": product["tax_rate"],
                          "tracks_stock": product["tracks_stock"], "is_kit": product["is_kit"]})
        priced = price_sale(lines, body.get("discount") or Decimal(0))
        if priced["discount"] > priced["subtotal"]:
            raise Invalid({"message": "the discount is larger than the subtotal", "field": "discount"})
        if body.get("customer_id") and self.repo.customer_credit(body["customer_id"]) is None:
            raise Invalid({"message": "the customer doesn't exist or is deleted", "field": "customer_id"})
        # A quote reserves nothing: missing stock is a warning, not an error
        return priced, stock_shortages(self.repo, branch, lines)

    def _valid_until(self, uid, body):
        if body.get("valid_until"):
            if body["valid_until"] <= datetime.now(timezone.utc):
                raise Invalid({"message": "the validity must be in the future", "field": "valid_until"})
            return body["valid_until"]
        return valid_until_for(body.get("valid_days") or DEFAULT_VALID_DAYS, self.repo.user_timezone(uid))

    def preview(self, uid, branch, body):
        priced, short = self._compose(uid, branch, body)
        return {**_public(priced), "valid_until": self._valid_until(uid, body), "stock_warnings": short}

    def create(self, uid, branch, body):
        priced, short = self._compose(uid, branch, body)
        quote_id = uuid.uuid4()
        header = {"customer_id": body.get("customer_id"), "customer_name": body.get("customer_name"),
                  "valid_until": self._valid_until(uid, body), "notes": body.get("notes"),
                  **{k: priced[k] for k in ("subtotal", "discount", "total")}}
        self.repo.create(uid, branch, quote_id, header, priced["lines"])
        return {**self.get(branch, quote_id), "stock_warnings": short}

    def search(self, branch, filters, page, page_size):
        rows = self.repo.search(branch, filters, page_size + 1, (page - 1) * page_size)
        return {"items": rows[:page_size], "page": page, "page_size": page_size, "has_more": len(rows) > page_size}

    def get(self, branch, quote_id):
        quote = self.repo.get(quote_id)
        if quote is None or quote["branch_id"] != branch:
            raise NotFound("quote not found")
        # Informational tax, with the same formula a sale would use (quotes store no tax)
        taxes: dict = {}
        for i in quote["items"]:
            rate = Decimal(i["tax_rate"])
            key = (i["tax_name"], rate)
            taxes[key] = taxes.get(key, Decimal(0)) + money(Decimal(i["line_total"]) * rate / (1 + rate))
        quote["tax_breakdown"] = [{"tax_name": name, "tax_rate": rate, "tax_amount": amount} for (name, rate), amount in taxes.items()]
        return quote

    def by_folio(self, branch, folio):
        quote_id = self.repo.id_by_folio(branch, folio)
        if quote_id is None:
            raise NotFound("quote not found")
        return self.get(branch, quote_id)

    def cancel(self, uid, branch, quote_id):
        quote = self.get(branch, quote_id)
        if quote["status"] != "OPEN" or not self.repo.cancel(uid, quote_id):
            raise Conflict({"message": f"the quote is {quote['status']}, only an open quote can be cancelled", "code": "quote_status"})
        self.repo.commit()
        return self.get(branch, quote_id)

    def history(self, branch, quote_id):
        self.get(branch, quote_id)
        return self.repo.history(quote_id)

    def duplicate(self, branch, quote_id):
        """The way to 'edit' a quote: a payload for a new one, with today's catalog prices noted."""
        quote = self.get(branch, quote_id)
        return {"customer_id": quote["customer_id"], "customer_name": quote["customer_name"] if not quote["customer_id"] else None,
                "customer": quote["customer"], "discount": quote["discount"], "notes": quote["notes"],
                "valid_days": DEFAULT_VALID_DAYS,
                "items": [{"product_id": i["product_id"], "product": i["product"], "unit": i["unit"], "quantity": i["quantity"],
                           "unit_price": i["unit_price"], "discount": i["discount"], "current_price": i["current_price"]}
                          for i in quote["items"] if i["product_active"]]}

    def convert_draft(self, branch, quote_id):
        """The sale payload prefilled from the quote (quoted prices honored), plus what changed since."""
        quote = self.get(branch, quote_id)
        self._convertible(quote)
        lines = [{"product_id": i["product_id"], "product": i["product"], "quantity": Decimal(i["quantity"]),
                  "tracks_stock": i["tracks_stock"], "is_kit": i["is_kit"]} for i in quote["items"] if i["product_active"]]
        short = {s["product_id"]: s for s in stock_shortages(self.repo, branch, lines)}
        promos: dict = {}
        for p in self.repo.active_promotions(branch):
            promos.setdefault(str(p["product_id"]), []).append({"promotion_id": p["promotion_id"], "name": p["name"]})
        return {
            "quote_id": quote["id"], "folio": quote["folio"], "customer_id": quote["customer_id"], "customer": quote["customer"],
            "discount": quote["discount"], "valid_until": quote["valid_until"],
            "appointment_id": quote["appointment_id"], "appointment_at": quote["appointment_at"],  # an event's quote: its deposit
            "items": [{"product_id": i["product_id"], "product": i["product"], "unit": i["unit"], "quantity": i["quantity"],
                       "unit_price": i["unit_price"], "discount": i["discount"], "current_price": i["current_price"],
                       "price_changed": i["current_price"] != i["unit_price"], "available": i["product_active"],
                       "promotions": promos.get(str(i["product_id"]), [])}
                      for i in quote["items"]],
            "stock_warnings": list(short.values()),
            "removed_products": [i["product"] for i in quote["items"] if not i["product_active"]],
        }

    def _convertible(self, quote):
        if quote["status"] != "OPEN":
            raise Conflict({"message": f"the quote is {quote['status']}", "code": "quote_status", "status": quote["status"]})
        if quote["is_expired"]:
            raise Conflict({"message": "the quote expired", "code": "quote_expired", "valid_until": quote["valid_until"]})


def _public(priced):
    keep = ("product_id", "product", "unit", "quantity", "unit_price", "catalog_price", "discount", "tax_rate",
            "gross", "line_total", "tax_amount")
    return {**priced, "lines": [{k: l[k] for k in keep} for l in priced["lines"]]}
