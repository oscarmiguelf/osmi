from decimal import Decimal

from app.application.errors import Conflict, Invalid
from app.application.ports.outgoing_payment_repository import Kind, OutgoingPaymentRepository


def record_payment(repo: OutgoingPaymentRepository, uid, branch, kind: Kind, parent_id, owed: Decimal,
                   cash: Decimal, other: Decimal, notes=None):
    """Pay (part of) what is owed: `cash` leaves the register the person occupies in this branch, `other` was paid
    some other way (own money, a transfer...: not tracked). What isn't paid stays owed. The caller commits."""
    if cash + other > owed:
        raise Invalid({"message": "the payment is more than what is owed", "code": "over_owed", "owed": owed})
    if cash:
        register = repo.my_register(uid, branch)
        if register is None:
            raise Conflict({"message": "occupy a register of this branch to take cash from it", "code": "no_register"})
        method, available = repo.lock_cash(register["id"])  # locked: a sale or a cut can't change it until commit
        if cash > available:
            raise Invalid({"message": "not enough cash in the register", "code": "not_enough_cash", "available": available,
                           "register": register["name"]})
        repo.add_payment(uid, kind, parent_id, "CASH", cash, register["id"], method, notes)
    if other:
        repo.add_payment(uid, kind, parent_id, "OTHER", other, None, None, notes)


def paid_totals(payments: list[dict], total: Decimal) -> dict:
    cash = sum((p["amount"] for p in payments if p["source"] == "CASH"), Decimal(0))
    paid = sum((p["amount"] for p in payments), Decimal(0))
    return {"paid": paid, "paid_cash": cash, "owed": total - paid}
