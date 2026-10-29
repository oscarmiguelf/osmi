import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.infrastructure.persistence.outgoing_payments import OutgoingPaymentsSql

PAID = "(SELECT COALESCE(SUM(p.amount), 0) FROM outgoing_payments p WHERE p.expense_id = e.id)"
PERIOD = """AND (CAST(:start AS timestamptz) IS NULL OR e.spent_at >= :start)
            AND (CAST(:end AS timestamptz) IS NULL OR e.spent_at < :end)"""


def _like(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class SqlExpenseRepository(OutgoingPaymentsSql):
    def __init__(self, session: Session):
        self.session = session

    def _one(self, sql: str, **params) -> dict | None:
        row = self.session.execute(text(sql), params).mappings().first()
        return dict(row) if row else None

    def _all(self, sql: str, **params) -> list[dict]:
        return [dict(r) for r in self.session.execute(text(sql), params).mappings()]

    def supplier_active(self, supplier_id):
        return self.session.execute(text("SELECT 1 FROM suppliers WHERE id = :id AND deleted_at IS NULL"), {"id": supplier_id}).first() is not None

    def create(self, user_id, branch_id, data):
        expense_id = uuid.uuid4()
        self.session.execute(text("""
            INSERT INTO expenses (id, branch_id, description, supplier_id, amount, spent_at, reference, notes, created_by, updated_by)
            VALUES (:id, :b, :description, :supplier_id, :amount, COALESCE(CAST(:spent_at AS timestamptz), NOW()), :reference, :notes, :uid, :uid)
        """), {"supplier_id": None, "spent_at": None, "reference": None, "notes": None, **data, "id": expense_id, "b": branch_id, "uid": user_id})
        return expense_id

    def update(self, user_id, expense_id, fields):
        sets = "".join(f"{k} = :{k}, " for k in fields)  # keys come from the request model
        self.session.execute(text(f"UPDATE expenses SET {sets}updated_by = :uid WHERE id = :id AND deleted_at IS NULL"),
                             {**fields, "uid": user_id, "id": expense_id})

    def get(self, expense_id):
        return self._one("""
            SELECT e.id, e.branch_id, e.description, e.supplier_id, s.name AS supplier, e.amount, e.spent_at, e.reference, e.notes,
                   e.created_at, u.email AS created_by_email, e.deleted_at, d.email AS deleted_by_email, e.void_reason
            FROM expenses e
            LEFT JOIN suppliers s ON s.id = e.supplier_id
            LEFT JOIN users u ON u.id = e.created_by
            LEFT JOIN users d ON d.id = e.deleted_by
            WHERE e.id = :id
        """, id=expense_id)

    def search(self, branch_id, filters, limit, offset):
        status = {"owed": f"AND {PAID} < e.amount", "paid": f"AND {PAID} >= e.amount"}.get(filters["status"], "")
        return self._all(f"""
            SELECT e.id, e.description, e.supplier_id, s.name AS supplier, e.amount, e.spent_at, e.reference, e.deleted_at,
                   {PAID} AS paid, e.amount - {PAID} AS owed,
                   (SELECT COALESCE(SUM(p.amount), 0) FROM outgoing_payments p WHERE p.expense_id = e.id AND p.source = 'CASH') AS paid_cash
            FROM expenses e LEFT JOIN suppliers s ON s.id = e.supplier_id
            WHERE e.branch_id = :b AND (:voided OR e.deleted_at IS NULL) {PERIOD} {status}
              AND (:q = '' OR LOWER(e.description) LIKE LOWER(:p) OR LOWER(e.reference) LIKE LOWER(:p) OR LOWER(s.name) LIKE LOWER(:p))
            ORDER BY e.spent_at DESC, e.id LIMIT :limit OFFSET :offset
        """, b=branch_id, voided=filters["include_voided"], start=filters["from"], end=filters["to"], q=filters["q"],
            p=_like(filters["q"]), limit=limit, offset=offset)

    def summary(self, branch_id, start, end):
        return self._one(f"""
            SELECT COUNT(*) AS expenses, COALESCE(SUM(e.amount), 0) AS total,
                   COALESCE(SUM({PAID}), 0) AS paid, COALESCE(SUM(e.amount - {PAID}), 0) AS owed
            FROM expenses e WHERE e.branch_id = :b AND e.deleted_at IS NULL {PERIOD}
        """, b=branch_id, start=start, end=end)

    def void(self, user_id, expense_id, reason):
        self.session.execute(text("""
            UPDATE expenses SET deleted_at = NOW(), deleted_by = :uid, updated_by = :uid, void_reason = :reason
            WHERE id = :id AND deleted_at IS NULL
        """), {"uid": user_id, "id": expense_id, "reason": reason})

    def commit(self):
        self.session.commit()
