from decimal import Decimal

from app.application.errors import Conflict, Forbidden, Invalid, NotFound
from app.application.ports.cash_repository import CashRepository

MODULE = "cash"
CUT_WITHDRAWAL = "Retiro de corte"
MANUAL_TYPES = ("Cash In", "Cash Out")  # Sale / Return come from DB triggers; no manual adjustments: corrections are an in or an out


class CashService:
    def __init__(self, repo: CashRepository):
        self.repo = repo

    # --- registers ---

    def list_registers(self, branch):
        return self.repo.registers_status(branch)

    def get_register(self, branch, rid, include_deleted=False):
        register = self.repo.get_register(rid)
        # A register of another branch is "not found": its existence isn't leaked
        if register is None or register["branch_id"] != branch or (register["deleted_at"] and not include_deleted):
            raise NotFound("cash register not found")
        return register

    def create_register(self, uid, branch, name):
        row = self.repo.create_register(uid, branch, name)
        if row is None:
            raise Conflict({"message": "a register with that name already exists in this branch", "field": "name"})
        self.repo.commit()
        return row

    def rename_register(self, uid, branch, rid, name):
        self.get_register(branch, rid)
        row = self.repo.rename_register(uid, rid, name)
        if row is None:
            raise Conflict({"message": "a register with that name already exists in this branch", "field": "name"})
        self.repo.commit()
        return row

    def delete_register(self, uid, branch, rid):
        register = self.get_register(branch, rid)
        blockers = {}
        if register["session_id"]:
            blockers["occupied_by"] = register["occupied_by_email"]
        if self.repo.nonzero_balances(rid):
            blockers["nonzero_balances"] = self.repo.nonzero_balances(rid)
        if blockers:
            raise Conflict({"message": "the register is in use", "blockers": blockers})
        self.repo.delete_register(uid, rid)
        self.repo.commit()

    def restore_register(self, uid, branch, rid):
        register = self.get_register(branch, rid, include_deleted=True)
        if register["deleted_at"] is None:
            raise NotFound("deleted cash register not found")
        row = self.repo.restore_register(uid, rid)
        if row is None:
            raise Conflict({"message": "another active register in this branch has that name", "field": "name"})
        self.repo.commit()
        return row

    def register_history(self, branch, rid, page, page_size):
        self.get_register(branch, rid, include_deleted=True)
        return self._page(self.repo.register_history, rid, page, page_size)

    # --- occupancy ---

    def current_session(self, uid):
        return self.repo.current_session(uid)

    def occupy(self, uid, branch, rid):
        self.get_register(branch, rid)
        mine = self.repo.current_session(uid)
        if mine and mine["cash_register_id"] == rid:
            return mine  # already mine: continue with it
        if mine:
            raise Conflict({"message": "you already occupy another register; release it first", "session": mine})
        taken = self.repo.open_session(rid)
        if taken:
            raise Conflict({"message": "the register is occupied", "occupied_by": self.repo.get_register(rid)["occupied_by_email"]})
        if self.repo.occupy(uid, rid) is None:  # lost a race for the register or for the user's single session
            raise Conflict({"message": "the register was just taken, or you just took another one"})
        self.repo.commit()
        return self.repo.current_session(uid)

    def release(self, uid, branch, rid, force):
        self.get_register(branch, rid)
        session = self.repo.open_session(rid)
        if session is None:
            raise Conflict({"message": "the register is not occupied"})
        if session["user_id"] != uid:
            # Supervisors (cash.update) release a register someone else forgot to close
            if not force or not self.repo.has_permission(uid, MODULE, "update"):
                raise Forbidden("this register is occupied by someone else")
        row = self.repo.release(rid, uid)
        self.repo.commit()
        return row

    # --- payment methods ---

    def payment_methods(self, include_disabled):
        return self.repo.payment_methods(include_disabled)

    def update_payment_method(self, uid, mid, fields):
        if self.repo.payment_method(mid) is None:
            raise NotFound("payment method not found")
        row = self.repo.update_payment_method(uid, mid, fields)
        if row is None:
            raise Conflict({"message": "another payment method has that description", "field": "description"})
        self.repo.commit()
        return row

    # --- money ---

    def balances(self, branch, rid):
        self.get_register(branch, rid)
        return self.repo.balances(rid)

    def movements(self, branch, rid, filters, page, page_size):
        self.get_register(branch, rid)
        rows = self.repo.movements(rid, filters, page_size + 1, (page - 1) * page_size)
        return {"items": rows[:page_size], "page": page, "page_size": page_size, "has_more": len(rows) > page_size}

    def add_movement(self, uid, branch, rid, type_name, method_id, amount: Decimal, notes):
        self._operate(uid, branch, rid)
        if type_name not in MANUAL_TYPES:
            raise Invalid("only Cash In and Cash Out can be registered manually")
        if amount == 0:
            raise Invalid("amount can't be zero")
        if type_name != "Cash In" and not notes:
            raise Invalid("a note is required for cash out and adjustments")
        method = self.repo.payment_method(method_id)
        if method is None or not method["is_enabled"] or method["is_credit"]:
            raise Invalid("the payment method doesn't exist, is disabled, or doesn't move money (credit)")
        # The sign comes from the type, never from the client (adjustments keep theirs)
        signed = abs(amount) if type_name == "Cash In" else -abs(amount) if type_name == "Cash Out" else amount
        if type_name == "Cash Out":
            balance = self.repo.lock_balances(rid).get(method_id, Decimal(0))
            if abs(amount) > balance:  # business rule: no withdrawing more than the drawer holds
                raise Invalid({"message": "not enough money of that payment method in the register", "balance": balance})
        row = self.repo.add_movement(uid, rid, method_id, type_name, signed, notes)
        self.repo.commit()
        return row

    def sales_totals(self, branch, rid, start, end):
        self.get_register(branch, rid)
        if end <= start:
            raise Invalid("'to' must be after 'from'")
        return self.repo.sales_totals(rid, start, end)

    # --- cuts ---

    def create_cut(self, uid, branch, rid, counts: list[tuple], notes, withdrawal: Decimal = Decimal(0), reason: str | None = None):
        """Closes the turn: counts every method, leaves the cash at what was counted (minus the cut withdrawal), puts
        what isn't cash back to 0 (it was counted and handed in) and releases the register. One transaction."""
        self._operate(uid, branch, rid)
        if not counts:
            raise Invalid("count at least one payment method")
        ids = [mid for mid, _ in counts]
        if len(set(ids)) != len(ids):
            raise Invalid("a payment method is counted more than once")
        methods = {}
        for mid in ids:
            method = self.repo.payment_method(mid)
            if method is None or method["is_credit"]:
                raise Invalid(f"payment method {mid} doesn't exist or doesn't move money (credit)")
            methods[mid] = method
        if withdrawal < 0:
            raise Invalid({"message": "the withdrawal can't be negative", "field": "withdrawal"})
        expected = self.repo.lock_balances(rid)  # locked until commit: sales can't move the expected amounts mid-cut
        # A cut is the whole drawer: every method holding money must be counted, or its difference would go unseen
        missing = [str(mid) for mid, balance in expected.items() if balance != 0 and mid not in ids]
        if missing:
            raise Invalid({"message": "count every payment method that has money in the register", "missing": missing})
        counted = dict(counts)
        cash = next((mid for mid, m in methods.items() if m["is_cash"]), None)  # stays in the drawer; the others are handed in
        if withdrawal > (counted.get(cash, Decimal(0)) if cash else Decimal(0)):
            raise Invalid({"message": "the withdrawal is more than the cash counted", "field": "withdrawal",
                           "cash": counted.get(cash, Decimal(0)) if cash else Decimal(0)})
        details = [(mid, expected.get(mid, Decimal(0)), c) for mid, c in counts]
        cut_id = self.repo.create_cut(uid, rid, self.repo.cut_period_start(rid), notes, details, withdrawal,
                                      (reason or "").strip() or (CUT_WITHDRAWAL if withdrawal else None))
        if cut_id is None:
            raise Conflict({"message": "the cut overlaps a previous cut of this register"})
        for mid, was in expected.items():
            # cash: to what was counted; everything else: back to 0 (counted and handed in)
            delta = (counted[mid] - was) if mid == cash else -was
            if mid in counted and delta:
                self.repo.add_movement(uid, rid, mid, "Cut", delta, "Diferencia del corte" if mid == cash else "Corte: se reinicia (ya se contó)")
        if withdrawal:
            self.repo.add_movement(uid, rid, cash, "Cash Out", -withdrawal, (reason or "").strip() or CUT_WITHDRAWAL)
        if self.repo.open_session(rid):
            self.repo.release(rid, uid)
        self.repo.commit()
        return self.repo.get_cut(cut_id)

    def cuts(self, branch, rid, page, page_size):
        self.get_register(branch, rid, include_deleted=True)
        return self._page(self.repo.cuts, rid, page, page_size)

    def get_cut(self, branch, cut_id):
        cut = self.repo.get_cut(cut_id)
        if cut is None or cut["branch_id"] != branch:
            raise NotFound("cash cut not found")
        return cut

    def _operate(self, uid, branch, rid):
        """Operations at a register: it must be in the working branch and occupied by the user (or a supervisor)."""
        self.get_register(branch, rid)
        session = self.repo.open_session(rid)
        if (session is None or session["user_id"] != uid) and not self.repo.has_permission(uid, MODULE, "update"):
            raise Forbidden("occupy this register first")

    @staticmethod
    def _page(fetch, rid, page, page_size):
        rows = fetch(rid, page_size + 1, (page - 1) * page_size)
        return {"items": rows[:page_size], "page": page, "page_size": page_size, "has_more": len(rows) > page_size}
