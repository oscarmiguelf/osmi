from app.application.errors import Conflict, Invalid, NotFound
from app.application.ports.supplier_repository import SupplierRepository


class SupplierService:
    """Suppliers: a global catalog (all branches). Their purchases are shown only for the branches the person belongs to."""

    def __init__(self, repo: SupplierRepository):
        self.repo = repo

    def search(self, q, include_deleted, page, page_size, sort):
        items, total = self.repo.search(q.strip(), include_deleted, sort, page_size, (page - 1) * page_size)
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    def options(self, include_deleted):
        return self.repo.options(include_deleted)

    def get(self, uid, sid):
        """Deleted suppliers still resolve (old purchases print their name); deleted_at tells them apart."""
        supplier = self.repo.get(sid, uid)
        if supplier is None:
            raise NotFound("supplier not found")
        return supplier

    def create(self, uid, data, force):
        self._check_name(data["name"], None, force)
        row = self.repo.create(uid, data)
        self.repo.commit()
        return row

    def update(self, uid, sid, fields, force):
        current = self._active(uid, sid)
        if "name" in fields and fields["name"].lower() != current["name"].strip().lower():
            self._check_name(fields["name"], sid, force)
        row = self.repo.update(uid, sid, fields) if fields else current
        self.repo.commit()
        return self.repo.get(sid, uid) if fields else row

    def delete(self, uid, sid):
        """Allowed even with products or purchases (they stay as history); its product links are unlinked with it."""
        self._active(uid, sid)
        self.repo.delete(uid, sid)
        self.repo.commit()

    def restore(self, uid, sid):
        supplier = self.repo.get(sid, uid)
        if supplier is None or supplier["deleted_at"] is None:
            raise NotFound("deleted supplier not found")
        self.repo.restore(uid, sid)  # also relinks the products unlinked by the delete
        self.repo.commit()
        return self.repo.get(sid, uid)

    def history(self, uid, sid, page, page_size):
        self.get(uid, sid)
        return self._page(lambda limit, offset: self.repo.history(sid, limit, offset), page, page_size)

    def products(self, uid, sid, page, page_size):
        self.get(uid, sid)
        return self._page(lambda limit, offset: self.repo.products(sid, limit, offset), page, page_size)

    def set_products(self, uid, sid, product_ids):
        self._active(uid, sid)
        ids = list(dict.fromkeys(product_ids))
        missing = self.repo.missing_products(ids)
        if missing:
            raise Invalid({"message": "some products don't exist or were deleted", "field": "product_ids",
                           "product_ids": [str(p) for p in missing]})
        self.repo.set_products(uid, sid, ids)
        self.repo.commit()
        return {"product_ids": [str(p) for p in ids]}

    def link(self, uid, sid, product_id):
        """Idempotent: linking an already linked product is not an error."""
        self._active(uid, sid)
        if self.repo.missing_products([product_id]):
            raise NotFound("product not found")
        created = self.repo.link(uid, sid, product_id)
        self.repo.commit()
        return {"linked": True, "created": created}

    def unlink(self, uid, sid, product_id):
        self.get(uid, sid)
        if not self.repo.unlink(uid, sid, product_id):
            raise NotFound("that product is not linked to this supplier")
        self.repo.commit()

    def purchases(self, uid, sid, start, end, page, page_size):
        self.get(uid, sid)
        return self._page(lambda limit, offset: self.repo.purchases(uid, sid, start, end, limit, offset), page, page_size)

    def summary(self, uid, sid, start, end):
        self.get(uid, sid)
        return self.repo.summary(uid, sid, start, end)

    def price_history(self, uid, sid, product_id, limit):
        self.get(uid, sid)
        return self.repo.price_history(uid, sid, product_id, limit)

    def _active(self, uid, sid):
        supplier = self.repo.get(sid, uid)
        if supplier is None or supplier["deleted_at"] is not None:
            raise NotFound("supplier not found")
        return supplier

    def _check_name(self, name, exclude_id, force):
        # Names aren't unique in the DB (two shops can share one): a match asks for confirmation (?force=true)
        same = [] if force else self.repo.same_name(name, exclude_id)
        if same:
            raise Conflict({"message": "another supplier already has that name", "code": "duplicate_name", "field": "name",
                            "matches": [{"id": str(s["id"]), "name": s["name"]} for s in same]})

    @staticmethod
    def _page(fetch, page, page_size):
        rows = fetch(page_size + 1, (page - 1) * page_size)  # one extra row tells whether there is a next page
        return {"items": rows[:page_size], "page": page, "page_size": page_size, "has_more": len(rows) > page_size}
