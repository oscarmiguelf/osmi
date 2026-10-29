from app.application.custom_fields import clean_extra
from app.application.errors import Conflict, Forbidden, Invalid, NotFound
from app.application.ports.custom_field_repository import CustomFieldRepository
from app.application.ports.customer_repository import CustomerRepository

MODULE = "customers"


class CustomerService:
    def __init__(self, repo: CustomerRepository, fields: CustomFieldRepository):
        self.repo = repo
        self.fields = fields

    def search(self, q, page, page_size, sort):
        items, total = self.repo.search(q.strip(), sort, page_size, (page - 1) * page_size)
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    def get(self, cid):
        """Deleted customers are still returned (with deleted_at), so old sales can show who they were."""
        customer = self.repo.get(cid)
        if customer is None:
            raise NotFound("customer not found")
        return customer

    def create(self, uid, data):
        if data.get("credit_limit"):
            self._require_credit(uid)
        data["extra"] = clean_extra(self.fields.active("customer"), data.get("extra") or {})
        self._check_list(data.get("price_list_id"))
        row = self.repo.create(uid, data)
        warnings = self._phone_warning(row)
        self.repo.commit()
        return {**row, "warnings": warnings}

    def update(self, uid, cid, fields):
        current = self._active(cid)
        # Only a real change of the limit needs customers.credit; forms often resend the unchanged value.
        if "credit_limit" in fields and fields["credit_limit"] != current["credit_limit"]:
            self._require_credit(uid)
        if fields.get("price_list_id"):
            self._check_list(fields["price_list_id"])
        if "extra" in fields:
            fields["extra"] = clean_extra(self.fields.active("customer"), fields["extra"] or {}, current["extra"])
        row = self.repo.update(uid, cid, fields)
        warnings = self._phone_warning(row) if fields.get("phone", current["phone"]) != current["phone"] else []
        if "credit_limit" in fields:
            balance = self.repo.balance(cid)
            if row["credit_limit"] < balance:  # allowed by the DB: it only blocks new credit charges
                warnings.append({"code": "credit_limit_below_balance", "balance": balance})
        self.repo.commit()
        return {**row, "warnings": warnings}

    def delete(self, uid, cid):
        self._active(cid)
        balance = self.repo.balance(cid)
        if balance > 0:
            raise Conflict({"message": "customer still owes money", "balance": balance})
        self.repo.delete(uid, cid)
        self.repo.commit()

    def restore(self, uid, cid):
        row = self.repo.restore(uid, cid)
        if row is None:
            raise NotFound("deleted customer not found")
        self.repo.commit()
        return row

    def history(self, cid, page, page_size):
        self.get(cid)
        return self._page(self.repo.history, cid, page, page_size)

    def credit(self, cid):
        summary = self.repo.credit_summary(cid)
        if summary is None:
            raise NotFound("customer not found")
        return summary

    def credit_movements(self, cid, page, page_size):
        self.get(cid)
        return self._page(self.repo.credit_movements, cid, page, page_size)

    def pending_sales(self, cid, page, page_size):
        self.get(cid)
        return self._page(self.repo.pending_sales, cid, page, page_size)

    def sales(self, cid, page, page_size):
        self.get(cid)
        return self._page(self.repo.sales, cid, page, page_size)

    def _active(self, cid):
        customer = self.repo.get(cid)
        if customer is None or customer["deleted_at"] is not None:
            raise NotFound("customer not found")
        return customer

    def _check_list(self, list_id):
        if list_id and not self.repo.price_list_active(list_id):
            raise Invalid({"message": "the price list doesn't exist or was deleted", "field": "price_list_id"})

    def _require_credit(self, uid):
        if not self.repo.has_permission(uid, MODULE, "credit"):
            raise Forbidden(f"missing permission {MODULE}.credit")

    def _phone_warning(self, row):
        # Phones aren't unique (a company shares one), so a match is a heads-up, not an error.
        same = self.repo.count_same_phone(row["phone"], row["id"])
        return [{"code": "duplicate_phone", "count": same}] if same else []

    @staticmethod
    def _page(fetch, cid, page, page_size):
        rows = fetch(cid, page_size + 1, (page - 1) * page_size)  # one extra row tells whether there is a next page
        return {"items": rows[:page_size], "page": page, "page_size": page_size, "has_more": len(rows) > page_size}
