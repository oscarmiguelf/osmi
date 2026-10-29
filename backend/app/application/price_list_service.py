from app.application.errors import Conflict, Invalid, NotFound
from app.application.ports.price_list_repository import PriceListRepository


class PriceListService:
    """Price lists (mayoreo, frecuente...): read with products.read, changed with products.prices."""

    def __init__(self, repo: PriceListRepository):
        self.repo = repo

    def all(self):
        return self.repo.all()

    def get(self, list_id):
        plist = self.repo.get(list_id)
        if plist is None or plist["deleted_at"] is not None:
            raise NotFound("price list not found")
        return plist

    def create(self, uid, data):
        row = self.repo.create(uid, data)
        if row is None:
            raise Conflict({"message": "another price list has that name", "field": "name"})
        self.repo.commit()
        return self.get(row["id"])

    def update(self, uid, list_id, data):
        self.get(list_id)
        if data and self.repo.update(uid, list_id, data) is None:
            raise Conflict({"message": "another price list has that name", "field": "name"})
        self.repo.commit()
        return self.get(list_id)

    def delete(self, uid, list_id):
        self.get(list_id)
        used = self.repo.customers_using(list_id)
        if used:  # their prices would change without anybody noticing
            raise Conflict({"message": "customers use this price list", "code": "in_use", "customers": used})
        self.repo.delete(uid, list_id)
        self.repo.commit()

    def set_items(self, uid, list_id, items):
        """Replaces the list's prices: [{product_id, min_quantity, price}], each product and quantity once."""
        self.get(list_id)
        keys = [(i["product_id"], i["min_quantity"]) for i in items]
        if len(set(keys)) != len(keys):
            raise Invalid({"message": "a product is listed twice from the same quantity", "field": "items"})
        missing = self.repo.missing_products(list({i["product_id"] for i in items}))
        if missing:
            raise Invalid({"message": "some products don't exist or were deleted", "field": "items", "product_ids": [str(m) for m in missing]})
        self.repo.set_items(uid, list_id, items)
        self.repo.commit()
        return self.get(list_id)
