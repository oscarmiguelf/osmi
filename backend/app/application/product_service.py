from app.application.errors import Conflict, Forbidden, Invalid, NotFound
from app.application.ports.product_repository import ProductRepository
from app.application.stock_rules import check_stock_product

PRICE_FIELDS = ("price", "cost", "tax_rate_id")
REFS = {  # request field -> referenced table (must exist and not be deleted)
    "product_type_id": "product_types",
    "unit_of_measure_id": "units_of_measure",
    "category_id": "categories",
    "tax_rate_id": "tax_rates",
    "brand_id": "brands",
}


class ProductService:
    def __init__(self, repo: ProductRepository):
        self.repo = repo

    def search(self, branch, filters, page, page_size):
        items, total = self.repo.search(branch, filters, page_size, (page - 1) * page_size)
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    def get(self, product_id, branch):
        product = self.repo.get(product_id, branch)
        if product is None:
            raise NotFound("product not found")
        return product

    def by_barcode(self, barcode, branch):
        product = self.repo.by_barcode(barcode, branch)
        if product is None:
            raise NotFound("no active product has that barcode")
        return product

    def create(self, uid, data, branch):
        initial_stock = data.pop("initial_stock", 0)
        self._check_refs(data)
        self._duration_for_services(data, data["product_type_id"])
        if initial_stock:
            self._check_initial_stock(uid, data, initial_stock, branch)
        # Setting a price, cost or a non-default tax rate needs products.prices (like a later change would)
        if (data["price"] or data["cost"] or data.get("tax_rate_id")) and not self._can_price(uid):
            raise Forbidden("missing permission products.prices")
        product_id = self.repo.create(uid, data)
        if product_id is None:
            raise Conflict({"message": "an active product already has that barcode", "field": "barcode"})
        if initial_stock:  # same transaction: no product without the stock it was created with
            self.repo.add_initial_stock(uid, branch, product_id, initial_stock)
        self.repo.commit()
        return self.get(product_id, branch)

    def update(self, uid, product_id, fields, branch):
        current = self._active(product_id)
        self._check_refs(fields)
        if "duration_minutes" in fields or "product_type_id" in fields:
            fields.setdefault("duration_minutes", current.get("duration_minutes"))
            self._duration_for_services(fields, fields.get("product_type_id", current["product_type_id"]))
        if any(f in fields and fields[f] != current[f] for f in PRICE_FIELDS) and not self._can_price(uid):
            raise Forbidden("missing permission products.prices")
        if "product_type_id" in fields and fields["product_type_id"] != current["product_type_id"] and self.repo.has_history(product_id):
            # A product with movements, sales or kit links can't silently become a service or a kit
            raise Conflict({"message": "the type can't change once the product has movements, sales or kit links", "field": "product_type_id"})
        if fields and self.repo.update(uid, product_id, fields) is None:
            raise Conflict({"message": "an active product already has that barcode", "field": "barcode"})
        self.repo.commit()
        return self.get(product_id, branch)

    def delete(self, uid, product_id):
        self._active(product_id)
        blockers = {k: v for k, v in self.repo.delete_blockers(product_id).items() if v}
        if blockers:
            raise Conflict({"message": "the product is still in use", "blockers": blockers})
        self.repo.delete(uid, product_id)
        self.repo.commit()

    def restore(self, uid, product_id, branch):
        product = self.get(product_id, branch)
        if product["deleted_at"] is None:
            raise NotFound("deleted product not found")
        if not self.repo.restore(uid, product_id):
            raise Conflict({"message": "another active product took its barcode", "field": "barcode"})
        self.repo.commit()
        return self.get(product_id, branch)

    def history(self, product_id, page, page_size):
        self.get(product_id, None)
        rows = self.repo.history(product_id, page_size + 1, (page - 1) * page_size)
        return {"items": rows[:page_size], "page": page, "page_size": page_size, "has_more": len(rows) > page_size}

    def set_suppliers(self, uid, product_id, supplier_ids, branch):
        self._active(product_id)
        ids = list(dict.fromkeys(supplier_ids))
        for sid in ids:
            if self.repo.ref_active("suppliers", sid) is None:
                raise Invalid({"message": f"supplier {sid} doesn't exist or is deleted", "field": "supplier_ids"})
        self.repo.replace_suppliers(uid, product_id, ids)
        self.repo.commit()
        return self.get(product_id, branch)["suppliers"]

    def set_components(self, uid, kit_id, components: list[tuple], branch):
        kit = self._active(kit_id)
        if not kit["is_kit"]:
            raise Invalid("only kit products have components")
        ids = [cid for cid, _ in components]
        if len(set(ids)) != len(ids):
            raise Invalid("a component is listed more than once")
        for cid in ids:
            if cid == kit_id:
                raise Invalid("a kit can't contain itself")
            component = self.repo.get(cid, None)
            if component is None or component["deleted_at"] is not None:
                raise Invalid({"message": f"component {cid} doesn't exist or is deleted", "field": "components"})
            if component["is_kit"] or not component["tracks_stock"]:
                raise Invalid({"message": f"{component['name']} can't be a component: only stock products (no kits or services)",
                               "field": "components"})
        self.repo.replace_components(uid, kit_id, dict(components))
        self.repo.commit()
        return self.get(kit_id, branch)["components"]

    def _duration_for_services(self, data, type_id):
        """Only a service has a duration (it proposes an appointment's length); anything with stock or a kit has none."""
        ptype = self.repo.ref_active("product_types", type_id)
        if ptype and (ptype["tracks_stock"] or ptype["is_kit"]):
            data["duration_minutes"] = None

    def _active(self, product_id):
        product = self.repo.get(product_id, None)
        if product is None or product["deleted_at"] is not None:
            raise NotFound("product not found")
        return product

    def _check_initial_stock(self, uid, data, quantity, branch):
        if branch is None:
            raise Invalid({"message": "choose a branch (X-Branch-Id) to load the initial stock into", "field": "initial_stock"})
        if not self.repo.has_permission(uid, "inventory", "create"):
            raise Forbidden("missing permission inventory.create")
        ptype = self.repo.ref_active("product_types", data["product_type_id"])
        unit = self.repo.ref_active("units_of_measure", data["unit_of_measure_id"])
        check_stock_product({"id": "", "name": data["name"], "tracks_stock": ptype["tracks_stock"], "is_kit": ptype["is_kit"],
                             "unit": unit["name"], "deleted_at": None}, quantity, field="initial_stock", quantity_field="initial_stock")

    def _check_refs(self, fields):
        for field, table in REFS.items():
            if fields.get(field) is not None and self.repo.ref_active(table, fields[field]) is None:
                raise Invalid({"message": f"{field} doesn't exist or is deleted", "field": field})

    def _can_price(self, uid):
        return self.repo.has_permission(uid, "products", "prices")
