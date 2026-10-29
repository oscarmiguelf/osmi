from app.application.errors import Conflict, Invalid, NotFound
from app.application.ports.promotion_repository import PromotionRepository

# What each kind needs; the other kind fields must be empty (same rule as chk_promotions_kind)
KIND_FIELDS = {"PERCENT": ("percent",), "AMOUNT": ("amount",), "BUY_X_GET_Y": ("buy_quantity", "get_quantity")}
ALL_KIND_FIELDS = ("percent", "amount", "buy_quantity", "get_quantity")


class PromotionService:
    def __init__(self, repo: PromotionRepository):
        self.repo = repo

    def search(self, filters, page, page_size):
        rows = self.repo.search(filters, page_size + 1, (page - 1) * page_size)
        return {"items": rows[:page_size], "page": page, "page_size": page_size, "has_more": len(rows) > page_size}

    def get(self, promotion_id):
        promo = self.repo.get(promotion_id)
        if promo is None:
            raise NotFound("promotion not found")
        return promo

    def create(self, uid, data):
        product_ids, branch_ids = data.pop("product_ids"), data.pop("branch_ids")
        self._check_kind(data)
        self._check_window(data["starts_at"], data["ends_at"])
        self._check_links(product_ids, branch_ids)
        promotion_id = self.repo.create(uid, data)
        self.repo.set_links(uid, promotion_id, "promotion_products", "product_id", product_ids)
        self.repo.set_links(uid, promotion_id, "promotion_branches", "branch_id", branch_ids)
        self.repo.commit()
        return self.get(promotion_id)

    def update(self, uid, promotion_id, fields):
        """Editing never touches past sales: each sale line stores the discount it got."""
        current = self._active(promotion_id)
        product_ids, branch_ids = fields.pop("product_ids", None), fields.pop("branch_ids", None)
        if any(k in fields for k in ("kind", *ALL_KIND_FIELDS)):
            merged = {k: fields.get(k, current[k]) for k in ("kind", *ALL_KIND_FIELDS)}
            if "kind" in fields:  # switching kind: the old kind's numbers go away unless sent again
                merged.update({k: fields.get(k) for k in ALL_KIND_FIELDS})
            self._check_kind(merged)
            fields.update(merged)
        self._check_window(fields.get("starts_at", current["starts_at"]), fields.get("ends_at", current["ends_at"]))
        self._check_links(product_ids, branch_ids)
        if fields:
            self.repo.update(uid, promotion_id, fields)
        if product_ids is not None:
            self.repo.set_links(uid, promotion_id, "promotion_products", "product_id", product_ids)
        if branch_ids is not None:
            self.repo.set_links(uid, promotion_id, "promotion_branches", "branch_id", branch_ids)
        self.repo.commit()
        return self.get(promotion_id)

    def delete(self, uid, promotion_id):
        self._active(promotion_id)
        self.repo.delete(uid, promotion_id)
        self.repo.commit()

    def restore(self, uid, promotion_id):
        promo = self.get(promotion_id)
        if promo["deleted_at"] is None:
            raise Conflict({"message": "the promotion isn't deleted"})
        self.repo.restore(uid, promotion_id)
        self.repo.commit()
        return self.get(promotion_id)

    def history(self, promotion_id, page, page_size):
        self.get(promotion_id)
        rows = self.repo.history(promotion_id, page_size + 1, (page - 1) * page_size)
        return {"items": rows[:page_size], "page": page, "page_size": page_size, "has_more": len(rows) > page_size}

    def _active(self, promotion_id):
        promo = self.get(promotion_id)
        if promo["deleted_at"] is not None:
            raise NotFound("promotion not found")
        return promo

    @staticmethod
    def _check_kind(data):
        needed = KIND_FIELDS[data["kind"]]
        for field in needed:
            if data.get(field) is None:
                raise Invalid({"message": f"{data['kind']} needs {field}", "field": field})
        for field in ALL_KIND_FIELDS:
            if field not in needed:
                data[field] = None
        if data["kind"] == "PERCENT" and data["percent"] > 100:
            raise Invalid({"message": "a percent can't be more than 100", "field": "percent"})

    @staticmethod
    def _check_window(starts_at, ends_at):
        if ends_at <= starts_at:
            raise Invalid({"message": "the end must be after the start", "field": "ends_at"})

    def _check_links(self, product_ids, branch_ids):
        if product_ids is not None:
            if not product_ids:
                raise Invalid({"message": "choose at least one product", "field": "product_ids"})
            if self.repo.missing_products(product_ids):
                raise Invalid({"message": "a product doesn't exist or is deleted", "field": "product_ids"})
        if branch_ids and self.repo.missing_branches(branch_ids):
            raise Invalid({"message": "a branch doesn't exist or is deleted", "field": "branch_ids"})

