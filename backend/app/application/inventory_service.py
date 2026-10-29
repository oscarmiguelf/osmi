from decimal import Decimal

from app.application.errors import Invalid, NotFound
from app.application.ports.inventory_repository import InventoryRepository
from app.application.stock_rules import check_stock_product


class InventoryService:
    def __init__(self, repo: InventoryRepository):
        self.repo = repo

    def stock(self, branch, filters, page, page_size):
        items, total = self.repo.stock(branch, filters, page_size, (page - 1) * page_size)
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    def stock_in_my_branches(self, uid, product_id):
        self._product(product_id)
        return self.repo.stock_in_my_branches(product_id, uid)

    def kardex(self, branch, product_id, filters, page, page_size):
        self._product(product_id)
        rows = self.repo.kardex(product_id, branch, filters, page_size + 1, (page - 1) * page_size)
        return self._page(rows, page, page_size)

    def movements(self, branch, filters, page, page_size):
        rows = self.repo.movements(branch, filters, page_size + 1, (page - 1) * page_size)
        return self._page(rows, page, page_size)

    def adjust(self, uid, branch, product_id, quantity: Decimal, notes, reference):
        if quantity == 0:
            raise Invalid({"message": "the quantity can't be zero", "field": "quantity"})
        if not notes:
            raise Invalid({"message": "say why the stock is adjusted", "field": "notes"})
        product = self.repo.stock_product(product_id)
        check_stock_product(product, quantity)
        if quantity < 0:
            available = self.repo.lock_stock(branch, product_id)
            if -quantity > available:  # the DB would reject it too; answer with the number people need
                raise Invalid({"message": f"not enough {product['name']} in stock", "field": "quantity", "available": available})
        row = self.repo.add_adjustment(uid, branch, product_id, quantity, notes, reference)
        self.repo.commit()
        return row

    def low_stock(self, branch):
        return self.repo.low_stock(branch)

    def _product(self, product_id):
        product = self.repo.stock_product(product_id)
        if product is None:
            raise NotFound("product not found")
        return product

    @staticmethod
    def _page(rows, page, page_size):
        return {"items": rows[:page_size], "page": page, "page_size": page_size, "has_more": len(rows) > page_size}
