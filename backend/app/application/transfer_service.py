from decimal import Decimal

from app.application.errors import Conflict, Forbidden, Invalid, NotFound
from app.application.ports.transfer_repository import TransferRepository
from app.application.stock_rules import check_stock_product


class TransferService:
    """Sent from the working branch (origin), received by the destination, cancelled by the origin."""

    def __init__(self, repo: TransferRepository):
        self.repo = repo

    def send(self, uid, branch, to_branch, notes, items: list[dict]):
        if to_branch == branch:
            raise Invalid({"message": "the destination must be another branch", "field": "to_branch_id"})
        if not self.repo.branch_active(to_branch):
            raise Invalid({"message": "the destination branch doesn't exist or is deleted", "field": "to_branch_id"})
        if not items:
            raise Invalid({"message": "add at least one product", "field": "items"})
        ids = [i["product_id"] for i in items]
        if len(set(ids)) != len(ids):
            raise Invalid({"message": "a product is listed more than once; add up its quantity instead", "field": "items"})
        products = self.repo.stock_products(ids)
        for item in items:
            check_stock_product(products.get(item["product_id"]), item["quantity"])
        stock = self.repo.lock_stock(branch, ids)
        for item in items:  # the DB rejects it too; this names the product and the quantity available
            available = stock.get(item["product_id"], Decimal(0))
            if item["quantity"] > available:
                product = products[item["product_id"]]
                raise Invalid({"message": f"not enough {product['name']} in this branch", "field": "items",
                               "product_id": str(product["id"]), "available": available})
        transfer_id = self.repo.create(uid, branch, to_branch, notes, items)
        self.repo.commit()
        return self.repo.get(transfer_id)

    def search(self, branch, filters, page, page_size):
        rows = self.repo.search(branch, filters, page_size + 1, (page - 1) * page_size)
        return {"items": rows[:page_size], "page": page, "page_size": page_size, "has_more": len(rows) > page_size}

    def in_transit(self, branch):
        return self.repo.in_transit(branch)

    def get(self, branch, transfer_id):
        transfer = self.repo.get(transfer_id)
        # Visible only from its origin or destination
        if transfer is None or branch not in (transfer["from_branch_id"], transfer["to_branch_id"]):
            raise NotFound("transfer not found")
        return transfer

    def receive(self, uid, branch, transfer_id):
        transfer = self.get(branch, transfer_id)
        if transfer["to_branch_id"] != branch:
            raise Forbidden("only the destination branch can receive it")
        return self._change(uid, branch, transfer, "RECEIVED")

    def cancel(self, uid, branch, transfer_id):
        transfer = self.get(branch, transfer_id)
        if transfer["from_branch_id"] != branch:
            raise Forbidden("only the origin branch can cancel it")
        return self._change(uid, branch, transfer, "CANCELLED")

    def available_products(self, branch, q, limit):
        return self.repo.available_products(branch, q, limit)

    def _change(self, uid, branch, transfer, status):
        if transfer["status"] != "IN_TRANSIT" or not self.repo.set_status(transfer["id"], uid, status):
            raise Conflict({"message": "the transfer is no longer in transit", "status": self.repo.get(transfer["id"])["status"]})
        self.repo.commit()
        return self.repo.get(transfer["id"])
