from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.application.errors import Conflict, Invalid, NotFound
from app.application.outgoing_payments import paid_totals, record_payment
from app.application.ports.expense_repository import ExpenseRepository

CLOCK_SKEW = timedelta(minutes=5)


class ExpenseService:
    """Expenses of the working branch: paid from the register the person occupies, another way, or owed."""

    def __init__(self, repo: ExpenseRepository):
        self.repo = repo

    def create(self, uid, branch, data):
        cash, other = data.pop("cash_amount"), data.pop("other_amount")
        self._check(data)
        expense_id = self.repo.create(uid, branch, data)
        record_payment(self.repo, uid, branch, "expense", expense_id, data["amount"], cash, other, data["description"][:200])
        self.repo.commit()
        return self.get(branch, expense_id)

    def update(self, uid, branch, expense_id, fields):
        self._active(branch, expense_id)
        self._check(fields)
        if fields:
            self.repo.update(uid, expense_id, fields)
            self.repo.commit()
        return self.get(branch, expense_id)

    def pay(self, uid, branch, expense_id, cash: Decimal, other: Decimal, notes):
        expense = self._active(branch, expense_id)
        if not cash and not other:
            raise Invalid({"message": "enter how much was paid", "field": "cash_amount"})
        record_payment(self.repo, uid, branch, "expense", expense_id, expense["owed"], cash, other, notes or expense["description"][:200])
        self.repo.commit()
        return self.get(branch, expense_id)

    def void(self, uid, branch, expense_id, reason):
        """Void it; the cash it took goes back to its register."""
        self._active(branch, expense_id)
        returned = self.repo.return_cash(uid, "expense", expense_id)
        self.repo.void(uid, expense_id, reason)
        self.repo.commit()
        return {"voided": True, "cash_returned": returned}

    def get(self, branch, expense_id):
        expense = self.repo.get(expense_id)
        if expense is None or expense["branch_id"] != branch:  # other branches' expenses are "not found"
            raise NotFound("expense not found")
        payments = self.repo.payments("expense", expense_id)
        return {**expense, **paid_totals(payments, expense["amount"]), "payments": payments}

    def search(self, branch, filters, page, page_size):
        rows = self.repo.search(branch, filters, page_size + 1, (page - 1) * page_size)
        return {"items": rows[:page_size], "page": page, "page_size": page_size, "has_more": len(rows) > page_size}

    def summary(self, branch, start, end):
        return self.repo.summary(branch, start, end)

    def _active(self, branch, expense_id):
        expense = self.get(branch, expense_id)
        if expense["deleted_at"] is not None:
            raise Conflict({"message": "the expense is voided"})
        return expense

    def _check(self, data):
        if data.get("supplier_id") and not self.repo.supplier_active(data["supplier_id"]):
            raise Invalid({"message": "the supplier doesn't exist or is deleted", "field": "supplier_id"})
        if data.get("spent_at") and data["spent_at"] > datetime.now(timezone.utc) + CLOCK_SKEW:
            raise Invalid({"message": "the date can't be in the future", "field": "spent_at"})
