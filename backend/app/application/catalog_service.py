from app.application.errors import Conflict, Invalid, NotFound
from app.application.ports.catalog_repository import CatalogRepository


class CatalogService:
    """Categories, units, product types, tax rates and brands: one set of rules for all of them."""

    def __init__(self, repo: CatalogRepository):
        self.repo = repo

    def list(self, catalog, include_deleted):
        return self.repo.list(catalog, include_deleted)

    def create(self, catalog, uid, data):
        make_default = data.pop("is_default", False)
        row = self.repo.create(catalog, uid, data)
        if row is None:
            raise Conflict({"message": "that name is already in use", "field": "name"})
        if make_default:
            self.repo.set_default_tax_rate(uid, row["id"])
            row = self.repo.get(catalog, row["id"])
        self.repo.commit()
        return row

    def update(self, catalog, uid, item_id, fields):
        item = self._active(catalog, item_id)
        default = fields.pop("is_default", None)
        if default is False and item.get("is_default"):
            raise Conflict({"message": "choose another default tax rate instead of unsetting this one"})
        row = self.repo.update(catalog, uid, item_id, fields) if fields else item
        if row is None:
            raise Conflict({"message": "that name is already in use", "field": "name"})
        if default:
            self.repo.set_default_tax_rate(uid, item_id)
        self.repo.commit()
        return self.repo.get(catalog, item_id)

    def delete(self, catalog, uid, item_id):
        item = self._active(catalog, item_id)
        if item.get("is_default"):
            raise Conflict({"message": "the default tax rate can't be deleted; choose another default first"})
        used = self.repo.usage(catalog, item_id)
        if used:
            raise Conflict({"message": "it is used by active products", "products": used})
        self.repo.delete(catalog, uid, item_id)
        self.repo.commit()

    def restore(self, catalog, uid, item_id):
        item = self.repo.get(catalog, item_id)
        if item is None or item["deleted_at"] is None:
            raise NotFound("deleted item not found")
        row = self.repo.restore(catalog, uid, item_id)
        if row is None:
            raise Conflict({"message": "another active item has that name", "field": "name"})
        self.repo.commit()
        return row

    def merge_brands(self, uid, from_ids, to_id):
        """Unify spellings: every product of `from_ids` moves to `to_id` and those brands are removed (one transaction).
        Renaming needs no special step: products point to the brand by id."""
        from_ids = list(dict.fromkeys(f for f in from_ids if f != to_id))
        if not from_ids:
            raise Invalid({"message": "choose at least one brand to merge into another", "field": "from_ids"})
        found = self.repo.existing_brands([*from_ids, to_id])
        missing = [str(i) for i in [*from_ids, to_id] if i not in found]
        if missing:
            raise NotFound({"message": "some brands don't exist", "ids": missing})
        moved = self.repo.merge_brands(uid, from_ids, to_id)
        self.repo.commit()
        return {"products_moved": moved, "brands_removed": len(from_ids), "brand": self.repo.get("brands", to_id)}

    def _active(self, catalog, item_id):
        item = self.repo.get(catalog, item_id)
        if item is None or item["deleted_at"] is not None:
            raise NotFound("not found")
        return item
