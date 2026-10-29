import uuid
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from app.application.errors import Conflict, Invalid, NotFound
from app.application.ports.sale_repository import SaleRepository
from app.application.sale_pricing import list_price, money, price_sale, promotion_discount
from app.application.stock_rules import INTEGER_UNITS

NO_REGISTER = {"message": "occupy a cash register of this branch first", "code": "register"}


def _whole(product, quantity, field):
    if product["unit"].lower() in INTEGER_UNITS and quantity != quantity.to_integral_value():
        raise Invalid({"message": f"{product['name']} is counted in whole units", "field": field,
                       "product_id": str(product["id"])})


def stock_shortages(repo, branch, lines) -> list[dict]:
    """What the lines would take out of the branch (products and kit components) that isn't there."""
    need: dict = {}
    names: dict = {}
    for line in lines:
        if line["tracks_stock"] and not line["is_kit"]:
            need[line["product_id"]] = need.get(line["product_id"], Decimal(0)) + line["quantity"]
            names[line["product_id"]] = line["product"]
    kits: dict = {}
    for line in lines:
        if line["is_kit"]:
            kits[line["product_id"]] = kits.get(line["product_id"], Decimal(0)) + line["quantity"]
    for c in repo.kit_components(list(kits)) if kits else []:
        q = (kits[c["kit_id"]] * c["quantity"]).quantize(Decimal("0.001"), ROUND_HALF_UP)
        need[c["product_id"]] = need.get(c["product_id"], Decimal(0)) + q
        names[c["product_id"]] = c["name"]
    if not need:
        return []
    stock = repo.branch_stock(branch, list(need))
    return [{"product_id": str(p), "product": names[p], "needed": q, "available": stock.get(p, Decimal(0))}
            for p, q in need.items() if stock.get(p, Decimal(0)) < q]


class SaleService:
    def __init__(self, repo: SaleRepository):
        self.repo = repo

    # --- composing a sale (shared by preview and create) ---
    def _price(self, uid, branch, body, quoted=None):
        """quoted: {product_id: unit_price} of the quote being converted (its prices are honored)."""
        items = body["items"]
        if not items:
            raise Invalid({"message": "add at least one product", "field": "items"})
        products = self.repo.products(list({i["product_id"] for i in items}))
        plist, tiers = _price_list(self.repo, body.get("customer_id"), list(products))
        grants = self.repo.product_benefits(list(products))
        uses = self.repo.benefits_for_use([i["benefit_id"] for i in items if i.get("benefit_id")])
        used: dict = {}
        lines = []
        for n, item in enumerate(items):
            product = products.get(item["product_id"])
            if product is None or product["deleted_at"] is not None:
                raise Invalid({"message": "the product doesn't exist or is deleted", "field": f"items.{n}.product_id"})
            _whole(product, item["quantity"], f"items.{n}.quantity")
            applies = list_price(product["price"], item["quantity"], tiers.get(product["id"], []), plist["percent"]) if plist else product["price"]
            if item.get("benefit_id"):  # sessions of a package: this line costs nothing
                _check_use(uses.get(item["benefit_id"]), body.get("customer_id"), product, item, used, n)
                applies = Decimal(0)
            if product["id"] in grants and not body.get("customer_id"):
                raise Invalid({"message": "packages and memberships are sold to a customer", "field": "customer_id", "code": "benefit_customer"})
            if product["id"] in grants and item["quantity"] != int(item["quantity"]):
                raise Invalid({"message": "packages and memberships are sold in whole units", "field": f"items.{n}.quantity"})
            price = applies if item.get("unit_price") is None else item["unit_price"]
            # Business rule: the price that applies is charged (catalog or the customer's price list; the quoted one when
            # converting a quote); nobody types a price
            if price != applies and price != (quoted or {}).get(product["id"]):
                raise Invalid({"message": "the price of a product can't be changed", "field": f"items.{n}.unit_price",
                               "price": applies})
            gross = money(item["quantity"] * price)
            discount, promo = item.get("discount") or Decimal(0), None
            if item.get("promotion_id"):
                if discount:
                    raise Invalid({"message": "a line takes a promotion or a manual discount, not both", "field": f"items.{n}.discount"})
                promo = self.repo.promotion(item["promotion_id"], product["id"], branch)
                if promo is None:
                    raise Invalid({"message": "the promotion doesn't apply to this product here and now", "field": f"items.{n}.promotion_id"})
                discount = promotion_discount(promo, item["quantity"], price)
            if discount > gross:
                raise Invalid({"message": "the discount is larger than the line", "field": f"items.{n}.discount"})
            lines.append({"product_id": product["id"], "product": product["name"], "unit": product["unit"],
                          "quantity": item["quantity"], "unit_price": price, "discount": discount,
                          "promotion_id": item.get("promotion_id"), "promotion": promo and promo["name"],
                          "tax_rate": product["tax_rate"], "fulfillment": item.get("fulfillment", "DELIVERED"),
                          "benefit_id": item.get("benefit_id"), "grant": grants.get(product["id"]),
                          "price_list_id": plist["id"] if plist and price == applies != product["price"] and not item.get("benefit_id") else None,
                          "price_list": plist["name"] if plist and price == applies != product["price"] else None,
                          "tracks_stock": product["tracks_stock"], "is_kit": product["is_kit"]})
        priced = price_sale(lines, body.get("discount") or Decimal(0))
        if priced["discount"] > priced["subtotal"]:
            raise Invalid({"message": "the sale discount is larger than the subtotal", "field": "discount"})
        short = stock_shortages(self.repo, branch, lines)  # with numbers, before the DB rejects the whole sale
        if short:
            raise Invalid({"message": "not enough stock in this branch", "field": "items", "products": short})
        return priced

    def _payments(self, body, total, customer, deposit=False):
        payments = body.get("payments") or []
        methods = self.repo.payment_methods(list({p["payment_method_id"] for p in payments}))
        credit = Decimal(0)
        for n, p in enumerate(payments):
            method = methods.get(p["payment_method_id"])
            if method is None:
                raise Invalid({"message": "the payment method is disabled or doesn't exist", "field": f"payments.{n}.payment_method_id"})
            if method["is_credit"]:
                if customer is None:
                    raise Invalid({"message": "a sale on credit needs a customer", "field": "customer_id"})
                if p.get("amount_tendered") is not None:
                    raise Invalid({"message": "cash handed over doesn't apply to credit", "field": f"payments.{n}.amount_tendered"})
                credit += p["amount"]
            elif p.get("amount_tendered") is not None and p["amount_tendered"] < p["amount"]:
                raise Invalid({"message": "the cash handed over is less than the amount", "field": f"payments.{n}.amount_tendered"})
        paid = sum((p["amount"] for p in payments), Decimal(0))
        if paid != total:
            raise Invalid({"message": f"the payments ({paid}) must add up to the total ({total})", "field": "payments",
                           "total": total, "paid": paid})
        if credit and not deposit and customer["balance"] + credit > customer["credit_limit"]:
            raise Invalid({"message": "credit limit exceeded", "field": "payments", "credit_limit": customer["credit_limit"],
                           "debt": customer["balance"], "available": customer["credit_limit"] - customer["balance"]})
        return payments, credit

    def _customer(self, body):
        if not body.get("customer_id"):
            return None
        customer = self.repo.customer_credit(body["customer_id"])
        if customer is None:
            raise Invalid({"message": "the customer doesn't exist or is deleted", "field": "customer_id"})
        return customer

    def preview(self, uid, branch, body):
        """Totals, tax and promotions as they'd be saved; payments are optional here (shows what's left and the change)."""
        quoted = self._quote(branch, body) if body.get("quote_id") else None
        priced = self._price(uid, branch, body, quoted)
        payments = body.get("payments") or []
        paid = sum((p["amount"] for p in payments), Decimal(0))
        tendered = sum((p.get("amount_tendered") or p["amount"] for p in payments), Decimal(0))
        return {**_public(priced), "paid": paid, "remaining": priced["total"] - paid, "change": max(tendered - paid, Decimal(0)),
                "register": self.repo.current_register(uid, branch)}

    def create(self, uid, branch, body):
        sale_id = body.get("id") or uuid.uuid4()
        existing = self.repo.sale_owner(sale_id)
        if existing is not None:  # a retry of a sale already saved: same answer, no second sale
            if existing["branch_id"] != branch:
                raise Conflict({"message": "that sale id is already used"})
            return self.repo.get(sale_id)
        register = self.repo.current_register(uid, branch)
        if register is None:
            raise Conflict(NO_REGISTER)
        quoted = self._quote(branch, body) if body.get("quote_id") else None
        if body.get("quote_id") and not body.get("appointment_id"):  # an event's quote: the sale charges the event
            body["appointment_id"] = self.repo.appointment_of_quote(body["quote_id"])
        priced = self._price(uid, branch, body, quoted)
        # An appointment's sale made when it's booked (on_credit: all owed, paid later) or charged before it starts:
        # the balance stays the customer's for it, without needing a credit limit, and the appointment stays open
        keep_open = bool(body.get("on_credit"))
        deposit = bool(body.get("appointment_id")) and (keep_open or self._appointment(branch, body)["starts_at"] > datetime.now(timezone.utc))
        if keep_open and body.get("appointment_id"):
            self._appointment(branch, body)
        if keep_open:
            credit_method = self.repo.credit_method()
            body["payments"] = [{"payment_method_id": credit_method["id"], "amount": priced["total"]}] if priced["total"] else []
        customer = self._customer(body)
        payments, credit = self._payments(body, priced["total"], customer, deposit)
        header = {k: priced[k] for k in ("subtotal", "discount", "total", "tax_total")}
        header.update(customer_id=customer and customer["id"], status="PENDING" if credit else "PAID",
                      quote_id=body.get("quote_id"), appointment_id=body.get("appointment_id"), keep_open=keep_open,
                      uses=[{"benefit_id": l["benefit_id"], "product_id": l["product_id"], "quantity": int(l["quantity"])}
                            for l in priced["lines"] if l.get("benefit_id")],
                      grants=[{**l["grant"], "product_id": l["product_id"], "quantity": int(l["quantity"])} for l in priced["lines"] if l.get("grant")])
        self.repo.create(uid, branch, register["id"], sale_id, header, priced["lines"],
                         [{"amount_tendered": None, "reference": None, **p} for p in payments])
        return self.repo.get(sale_id)

    def _appointment(self, branch, body):
        """Charging an appointment: of this branch, not cancelled or missed, not charged yet; the sale is its customer's."""
        appointment = self.repo.appointment_for_sale(body["appointment_id"])
        if appointment is None or appointment["branch_id"] != branch:
            raise NotFound("appointment not found")
        if appointment["sale_id"] and appointment["sale_status"] != "RETURNED":  # a returned sale can be replaced
            raise Conflict({"message": "the appointment was already charged", "code": "appointment_charged", "sale_id": appointment["sale_id"]})
        if appointment["status"] in ("CANCELLED", "NO_SHOW"):
            raise Conflict({"message": f"the appointment is {appointment['status']}", "code": "appointment_status", "status": appointment["status"]})
        body["customer_id"] = appointment["customer_id"]
        return appointment

    def _quote(self, branch, body):
        """The checks the DB makes on a conversion, as friendly errors. Returns the quoted prices."""
        quote = self.repo.quote_for_sale(body["quote_id"])
        if quote is None or quote["branch_id"] != branch:
            raise NotFound("quote not found")
        if quote["status"] != "OPEN":
            raise Conflict({"message": f"the quote is {quote['status']}", "code": "quote_status", "status": quote["status"]})
        if quote["expired"]:
            raise Conflict({"message": "the quote expired", "code": "quote_expired", "valid_until": quote["valid_until"]})
        if quote["customer_id"] and body.get("customer_id") != quote["customer_id"]:
            raise Invalid({"message": "the sale must be for the customer of the quote", "field": "customer_id",
                           "customer_id": str(quote["customer_id"])})
        return quote["prices"]

    # --- after the sale ---
    def get(self, branch, sale_id):
        sale = self.repo.get(sale_id)
        if sale is None or sale["branch_id"] != branch or sale["deleted_at"] is not None:
            raise NotFound("sale not found")
        return sale

    def by_folio(self, branch, folio):
        sale_id = self.repo.id_by_folio(branch, folio)
        if sale_id is None:
            raise NotFound("sale not found")
        return self.get(branch, sale_id)

    def search(self, branch, filters, page, page_size):
        rows = self.repo.search(branch, filters, page_size + 1, (page - 1) * page_size)
        return {"items": rows[:page_size], "page": page, "page_size": page_size, "has_more": len(rows) > page_size}

    def history(self, branch, sale_id):
        self.get(branch, sale_id)
        return self.repo.history(sale_id)

    def deliver(self, uid, branch, sale_id, item_ids):
        self._locked(branch, sale_id)
        states = {s["id"]: s for s in self.repo.item_states(sale_id, item_ids)}
        for item_id in item_ids:
            state = states.get(item_id)
            if state is None:
                raise NotFound({"message": "the item isn't part of this sale", "sale_item_id": str(item_id)})
            if state["fulfillment"] != "RESERVED":
                raise Conflict({"message": "the item was already delivered", "sale_item_id": str(item_id)})
            if state["returnable_quantity"] == 0:
                raise Conflict({"message": "the item was returned: nothing to deliver", "sale_item_id": str(item_id)})
        self.repo.deliver(uid, sale_id, item_ids)
        self.repo.commit()
        return self.repo.get(sale_id)

    def abono(self, uid, branch, sale_id, payment):
        register = self._register(uid, branch)
        sale = self._locked(branch, sale_id)
        if sale["status"] == "RETURNED":
            raise Conflict({"message": "the sale was returned: it can't receive payments"})
        self._abono_method(payment)
        if payment["amount"] > sale["credit_outstanding"]:
            raise Invalid({"message": "the payment is more than what is owed", "field": "amount",
                           "outstanding": sale["credit_outstanding"]})
        self.repo.add_abonos(uid, register["id"], [{"sale_id": sale_id, **payment}])
        return self.repo.get(sale_id)

    def abonos(self, uid, branch, sale_id, payments):
        """Several payments to one sale at once (part cash, part card...), in one transaction."""
        register = self._register(uid, branch)
        sale = self._locked(branch, sale_id)
        if sale["status"] == "RETURNED":
            raise Conflict({"message": "the sale was returned: it can't receive payments"})
        for p in payments:
            self._abono_method(p)
        total = sum((p["amount"] for p in payments), Decimal(0))
        if total > sale["credit_outstanding"]:
            raise Invalid({"message": "the payments are more than what is owed", "field": "payments", "outstanding": sale["credit_outstanding"]})
        self.repo.add_abonos(uid, register["id"], [{"sale_id": sale_id, **p} for p in payments])
        return self.repo.get(sale_id)

    def customer_abono(self, uid, branch, customer_id, payment):
        """One payment from a customer spread over their sales in this branch, oldest first."""
        register = self._register(uid, branch)
        self._abono_method(payment)
        pending = self.repo.credit_pending(branch, customer_id, lock=True)
        owed = sum((p["credit_outstanding"] for p in pending), Decimal(0))
        if not pending:
            raise Conflict({"message": "the customer owes nothing in this branch"})
        if payment["amount"] > owed:
            raise Invalid({"message": "the payment is more than what is owed", "field": "amount", "outstanding": owed})
        left, abonos = payment["amount"], []
        for p in pending:
            if left == 0:
                break
            part = min(left, p["credit_outstanding"])
            abonos.append({"sale_id": p["sale_id"], "folio": p["folio"], "payment_method_id": payment["payment_method_id"],
                           "amount": part, "amount_tendered": None, "reference": payment.get("reference")})
            left -= part
        tendered = payment.get("amount_tendered")
        if tendered is not None:  # what was handed over goes on the last row, so the change is tendered - total
            abonos[-1]["amount_tendered"] = tendered - sum((a["amount"] for a in abonos[:-1]), Decimal(0))
        self.repo.add_abonos(uid, register["id"], [{k: v for k, v in a.items() if k != "folio"} for a in abonos])
        return {"applied": [{"sale_id": a["sale_id"], "folio": a["folio"], "amount": a["amount"]} for a in abonos],
                "change": tendered - payment["amount"] if tendered is not None else None,
                "owed_after": owed - payment["amount"]}

    def credit_pending(self, branch, customer_id):
        return self.repo.credit_pending(branch, customer_id)

    def pending_deliveries(self, branch):
        return self.repo.pending_deliveries(branch)

    def active_promotions(self, branch):
        return self.repo.active_promotions(branch)

    # --- returns ---
    def returnable(self, branch, sale_id):
        self.get(branch, sale_id)
        return self.repo.returnable(sale_id)

    def _return_lines(self, sale_id, items):
        if not items:
            raise Invalid({"message": "choose at least one product to return", "field": "items"})
        merged: dict = {}
        for i in items:
            merged[i["sale_item_id"]] = merged.get(i["sale_item_id"], Decimal(0)) + i["quantity"]
        available = {r["sale_item_id"]: r for r in self.repo.returnable(sale_id)}
        products = {}
        lines = []
        for item_id, quantity in merged.items():
            row = available.get(item_id)
            if row is None:
                raise Invalid({"message": "the item isn't part of this sale", "field": "items", "sale_item_id": str(item_id)})
            if quantity > row["returnable_quantity"]:
                raise Invalid({"message": f"only {row['returnable_quantity']} of {row['product']} can still be returned",
                               "field": "items", "sale_item_id": str(item_id), "returnable": row["returnable_quantity"]})
            products[item_id] = {"id": item_id, "name": row["product"], "unit": row["unit"]}
            _whole(products[item_id], quantity, "items")
            lines.append({"sale_item_id": item_id, "product": row["product"], "quantity": quantity,
                          "refund_amount": self.repo.refund_for(item_id, quantity),
                          "completes": quantity == row["returnable_quantity"]})
        everything = all(r["returnable_quantity"] == 0 or (r["sale_item_id"] in merged and merged[r["sale_item_id"]] == r["returnable_quantity"])
                         for r in available.values())
        return lines, everything

    def preview_return(self, branch, sale_id, items):
        sale = self.get(branch, sale_id)
        if sale["status"] == "RETURNED":
            raise Conflict({"message": "the sale is already fully returned"})
        lines, everything = self._return_lines(sale_id, items)
        total = sum((l["refund_amount"] for l in lines), Decimal(0))
        credit = min(sale["credit_outstanding"], total)  # unpaid goods cancel debt first; only the rest is money back
        return {"items": lines, "refund_total": total, "credit_refund": credit, "money_refund": total - credit,
                "completes_sale": everything}

    def create_return(self, uid, branch, sale_id, body):
        register = self._register(uid, branch)
        sale = self._locked(branch, sale_id)
        if sale["status"] == "RETURNED":
            raise Conflict({"message": "the sale is already fully returned"})
        lines, _ = self._return_lines(sale_id, body["items"])
        total = sum((l["refund_amount"] for l in lines), Decimal(0))
        credit_due = min(sale["credit_outstanding"], total)
        refunds = body.get("refunds") or []
        methods = self.repo.payment_methods(list({r["payment_method_id"] for r in refunds}))
        for n, r in enumerate(refunds):
            if r["payment_method_id"] not in methods:
                raise Invalid({"message": "the payment method is disabled or doesn't exist", "field": f"refunds.{n}.payment_method_id"})
        credit = sum((r["amount"] for r in refunds if methods[r["payment_method_id"]]["is_credit"]), Decimal(0))
        if credit_due and credit == 0:
            # The credit part is not the cashier's choice: add it when they only sent the money part
            method = self.repo.credit_method()
            refunds = [{"payment_method_id": method["id"], "amount": credit_due, "reference": None}, *refunds]
            credit = credit_due
        if credit != credit_due:
            raise Invalid({"message": f"the credit refund must be {credit_due} (what is still owed on this sale, up to the refund)",
                           "field": "refunds", "credit_refund": credit_due})
        sent = sum((r["amount"] for r in refunds), Decimal(0))
        if sent != total:
            raise Invalid({"message": f"the refunds ({sent}) must add up to {total}", "field": "refunds",
                           "refund_total": total, "money_refund": total - credit_due})
        return_id = uuid.uuid4()
        self.repo.create_return(uid, register["id"], return_id, sale_id, total, body.get("reason"),
                                [{"sale_item_id": l["sale_item_id"], "quantity": l["quantity"]} for l in lines],
                                [{"reference": None, **r} for r in refunds])
        return self.repo.get_return(return_id)

    def returns(self, branch, filters, page, page_size):
        rows = self.repo.returns(branch, filters, page_size + 1, (page - 1) * page_size)
        return {"items": rows[:page_size], "page": page, "page_size": page_size, "has_more": len(rows) > page_size}

    def get_return(self, branch, return_id):
        ret = self.repo.get_return(return_id)
        if ret is None or ret["branch_id"] != branch:
            raise NotFound("return not found")
        return ret

    def report(self, branch, start, end):
        if end <= start:
            raise Invalid({"message": "'to' must be after 'from'", "field": "to"})
        return self.repo.report(branch, start, end)

    # --- helpers ---
    def _register(self, uid, branch):
        register = self.repo.current_register(uid, branch)
        if register is None:
            raise Conflict(NO_REGISTER)
        return register

    def _locked(self, branch, sale_id):
        sale = self.repo.lock_sale(sale_id)
        if sale is None or sale["branch_id"] != branch or sale["deleted_at"] is not None:
            raise NotFound("sale not found")
        return sale

    def _abono_method(self, payment):
        method = self.repo.payment_methods([payment["payment_method_id"]]).get(payment["payment_method_id"])
        if method is None:
            raise Invalid({"message": "the payment method is disabled or doesn't exist", "field": "payment_method_id"})
        if method["is_credit"]:
            raise Invalid({"message": "a payment on credit must use a real method (cash, card...), not credit", "field": "payment_method_id"})
        if payment.get("amount_tendered") is not None and payment["amount_tendered"] < payment["amount"]:
            raise Invalid({"message": "the cash handed over is less than the amount", "field": "amount_tendered"})


def _check_use(benefit, customer_id, product, item, used, n):
    """A line paid with a package: the customer's, for this service, still valid, with enough sessions left (across lines)."""
    field = f"items.{n}.benefit_id"
    if benefit is None or benefit["customer_id"] != customer_id:
        raise Invalid({"message": "that package isn't this customer's", "field": field})
    if benefit["service_product_id"] != product["id"]:
        raise Invalid({"message": "the package is for another service", "field": field})
    if benefit["expired"]:
        raise Invalid({"message": "the package expired", "field": field, "code": "benefit_expired"})
    if item["quantity"] != int(item["quantity"]) or item.get("discount") or item.get("promotion_id"):
        raise Invalid({"message": "package sessions are whole, without discounts", "field": field})
    used[benefit["id"]] = used.get(benefit["id"], 0) + int(item["quantity"])
    if used[benefit["id"]] > benefit["sessions_left"]:
        raise Invalid({"message": "not enough sessions left", "field": field, "code": "benefit_sessions", "left": benefit["sessions_left"]})


def _price_list(repo, customer_id, product_ids):
    """The customer's price list (or None) and its price steps for these products: {product_id: [(min_quantity, price)]}."""
    plist = repo.price_list_for(customer_id) if customer_id else None
    return plist, (repo.list_tiers(plist["id"], product_ids) if plist else {})


def _public(priced):
    """Preview payload: drop the internal flags used for the stock check."""
    keep = ("product_id", "product", "unit", "quantity", "unit_price", "discount", "promotion_id", "promotion",
            "tax_rate", "gross", "line_total", "tax_amount", "fulfillment", "price_list", "benefit_id")
    return {**priced, "lines": [{k: l[k] for k in keep} for l in priced["lines"]]}
