import uuid

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.infrastructure.persistence.permissions import has_permission

REGISTER = """
    r.id, r.branch_id, r.name, r.created_at, r.deleted_at,
    s.id AS session_id, s.user_id AS occupied_by, s.started_at AS occupied_since,
    u.first_name || ' ' || u.last_name AS occupied_by_name, u.email AS occupied_by_email
"""
REGISTER_FROM = """
    cash_registers r
    LEFT JOIN cash_register_sessions s ON s.cash_register_id = r.id AND s.ended_at IS NULL
    LEFT JOIN users u ON u.id = s.user_id
"""
CUT_DETAILS = """
    COALESCE((SELECT JSON_AGG(JSON_BUILD_OBJECT(
        'payment_method_id', d.payment_method_id, 'payment_method', pm.description,
        'expected_amount', d.expected_amount, 'final_amount', d.final_amount, 'difference', d.difference)
        ORDER BY pm.description)
      FROM cash_cut_details d JOIN payment_methods pm ON pm.id = d.payment_method_id
      WHERE d.cash_cut_id = c.id), '[]') AS details
"""


class SqlCashRepository:
    def __init__(self, session: Session):
        self.session = session

    def _one(self, sql: str, **params) -> dict | None:
        row = self.session.execute(text(sql), params).mappings().first()
        return dict(row) if row else None

    def _all(self, sql: str, **params) -> list[dict]:
        return [dict(r) for r in self.session.execute(text(sql), params).mappings()]

    def _guarded(self, sql: str, **params) -> dict | None:
        """Run a write that may hit a unique/exclusion constraint; None instead of an aborted transaction."""
        try:
            with self.session.begin_nested():
                return self._one(sql, **params)
        except IntegrityError:
            return None

    def has_permission(self, user_id, module, permission):
        return has_permission(self.session, user_id, module, permission)

    # --- registers ---

    def registers_status(self, branch_id):
        return self._all(f"""
            SELECT {REGISTER} FROM {REGISTER_FROM}
            WHERE r.branch_id = :b AND r.deleted_at IS NULL ORDER BY LOWER(r.name)
        """, b=branch_id)

    def get_register(self, register_id):
        return self._one(f"SELECT {REGISTER} FROM {REGISTER_FROM} WHERE r.id = :id", id=register_id)

    def create_register(self, user_id, branch_id, name):
        row = self._guarded("""
            INSERT INTO cash_registers (branch_id, name, created_by, updated_by)
            VALUES (:b, :name, :uid, :uid) RETURNING id
        """, b=branch_id, name=name, uid=user_id)
        return row and self.get_register(row["id"])

    def rename_register(self, user_id, register_id, name):
        row = self._guarded("""
            UPDATE cash_registers SET name = :name, updated_by = :uid
            WHERE id = :id AND deleted_at IS NULL RETURNING id
        """, name=name, uid=user_id, id=register_id)
        return row and self.get_register(register_id)

    def delete_register(self, user_id, register_id):
        self.session.execute(text("""
            UPDATE cash_registers SET deleted_at = NOW(), deleted_by = :uid, updated_by = :uid
            WHERE id = :id AND deleted_at IS NULL
        """), {"uid": user_id, "id": register_id})

    def restore_register(self, user_id, register_id):
        row = self._guarded("""
            UPDATE cash_registers SET deleted_at = NULL, deleted_by = NULL, updated_by = :uid
            WHERE id = :id AND deleted_at IS NOT NULL RETURNING id
        """, uid=user_id, id=register_id)
        return row and self.get_register(register_id)

    def nonzero_balances(self, register_id):
        return self.session.execute(text(
            "SELECT COUNT(*) FROM cash_register_balances WHERE cash_register_id = :id AND balance <> 0"
        ), {"id": register_id}).scalar()

    def register_history(self, register_id, limit, offset):
        return self._all("""
            SELECT a.changed_at, a.action, u.email AS changed_by_email, a.changed_fields, a.old_data, a.new_data
            FROM cash_audit a LEFT JOIN users u ON u.id = a.changed_by
            WHERE a.entity_type = 'cash_register' AND a.entity_id = :id
            ORDER BY a.changed_at DESC, a.id DESC LIMIT :limit OFFSET :offset
        """, id=register_id, limit=limit, offset=offset)

    # --- sessions (occupancy) ---

    def current_session(self, user_id):
        return self._one("""
            SELECT s.id, s.cash_register_id, s.started_at, r.name AS cash_register, r.branch_id, b.name AS branch,
                   -- cash in the drawer: what an expense or a purchase can take from it
                   COALESCE((SELECT cb.balance FROM cash_register_balances cb JOIN payment_methods pm ON pm.id = cb.payment_method_id
                              WHERE cb.cash_register_id = r.id AND pm.is_cash), 0) AS cash_balance
            FROM cash_register_sessions s
            JOIN cash_registers r ON r.id = s.cash_register_id
            JOIN branches b ON b.id = r.branch_id
            WHERE s.user_id = :uid AND s.ended_at IS NULL
        """, uid=user_id)

    def open_session(self, register_id):
        return self._one("""
            SELECT id, user_id, started_at FROM cash_register_sessions
            WHERE cash_register_id = :id AND ended_at IS NULL
        """, id=register_id)

    def occupy(self, user_id, register_id):
        # Unique indexes reject a second open session per register or per user (a race we lost)
        return self._guarded("""
            INSERT INTO cash_register_sessions (cash_register_id, user_id) VALUES (:r, :uid) RETURNING *
        """, r=register_id, uid=user_id)

    def release(self, register_id, by):
        return self._one("""
            UPDATE cash_register_sessions SET ended_at = NOW(), ended_by = :by
            WHERE cash_register_id = :id AND ended_at IS NULL RETURNING *
        """, id=register_id, by=by)

    # --- payment methods ---

    def payment_methods(self, include_disabled):
        return self._all("""
            SELECT id, description, is_enabled, is_credit, is_cash FROM payment_methods
            WHERE deleted_at IS NULL AND (is_enabled OR :all) ORDER BY description
        """, all=include_disabled)

    def payment_method(self, method_id):
        return self._one("""
            SELECT id, description, is_enabled, is_credit, is_cash FROM payment_methods
            WHERE id = :id AND deleted_at IS NULL
        """, id=method_id)

    def update_payment_method(self, user_id, method_id, fields):
        # fields keys come from the request model, never from raw client input
        sets = "".join(f"{k} = :{k}, " for k in fields)
        return self._guarded(f"""
            UPDATE payment_methods SET {sets}updated_by = :uid
            WHERE id = :id AND deleted_at IS NULL RETURNING id, description, is_enabled, is_credit
        """, **fields, uid=user_id, id=method_id)

    # --- money ---

    def balances(self, register_id):
        # Every method that can hold money here: the enabled ones (0 if never used) plus any with a balance row
        return self._all("""
            SELECT pm.id AS payment_method_id, pm.description, pm.is_enabled, pm.is_cash, COALESCE(b.balance, 0) AS balance
            FROM payment_methods pm
            LEFT JOIN cash_register_balances b ON b.payment_method_id = pm.id AND b.cash_register_id = :id
            WHERE pm.deleted_at IS NULL AND NOT pm.is_credit AND (pm.is_enabled OR b.balance IS NOT NULL)
            ORDER BY pm.description
        """, id=register_id)

    def lock_balances(self, register_id):
        # FOR UPDATE: a sale or movement can't change these balances until we commit
        rows = self.session.execute(text("""
            SELECT payment_method_id, balance FROM cash_register_balances
            WHERE cash_register_id = :id FOR UPDATE
        """), {"id": register_id})
        return {r.payment_method_id: r.balance for r in rows}

    def add_movement(self, user_id, register_id, method_id, type_name, amount, notes):
        return self._one("""
            INSERT INTO cash_register_movements (cash_register_id, payment_method_id, movement_type_id, amount, notes, created_by, created_at)
            VALUES (:r, :pm, (SELECT id FROM cash_movement_types WHERE name = :type AND deleted_at IS NULL),
                    :amount, :notes, :uid, clock_timestamp())  -- the real moment: several in one transaction (a cut) keep their order
            RETURNING *
        """, r=register_id, pm=method_id, type=type_name, amount=amount, notes=notes, uid=user_id)

    def movements(self, register_id, filters, limit, offset):
        return self._all("""
            SELECT m.id, m.created_at, t.name AS movement_type, m.payment_method_id, pm.description AS payment_method,
                   m.amount, m.balance_before, m.balance_after, u.email AS created_by_email, m.sale_id, m.notes
            FROM cash_register_movements m
            JOIN cash_movement_types t ON t.id = m.movement_type_id
            JOIN payment_methods pm    ON pm.id = m.payment_method_id
            JOIN users u               ON u.id = m.created_by
            WHERE m.cash_register_id = :r
              AND (CAST(:from AS timestamptz) IS NULL OR m.created_at >= CAST(:from AS timestamptz))
              AND (CAST(:to AS timestamptz) IS NULL OR m.created_at < CAST(:to AS timestamptz))
              AND (CAST(:type AS text) IS NULL OR t.name = CAST(:type AS text))
              AND (CAST(:pm AS uuid) IS NULL OR m.payment_method_id = CAST(:pm AS uuid))
            ORDER BY m.created_at DESC, m.id DESC LIMIT :limit OFFSET :offset
        """, r=register_id, **filters, limit=limit, offset=offset)

    def sales_totals(self, register_id, start, end):
        return self._all("""
            SELECT pm.id AS payment_method_id, pm.description, SUM(m.amount) AS total
            FROM cash_register_movements m
            JOIN cash_movement_types t ON t.id = m.movement_type_id AND t.name IN ('Sale', 'Return')
            JOIN payment_methods pm ON pm.id = m.payment_method_id
            WHERE m.cash_register_id = :r AND m.created_at >= :start AND m.created_at < :end
            GROUP BY pm.id, pm.description ORDER BY pm.description
        """, r=register_id, start=start, end=end)

    # --- cuts ---

    def cut_period_start(self, register_id):
        """End of the previous cut, else the first movement, else when the register was created."""
        return self.session.execute(text("""
            SELECT COALESCE(
              (SELECT MAX(ended_at) FROM cash_cuts WHERE cash_register_id = :id),
              (SELECT MIN(created_at) FROM cash_register_movements WHERE cash_register_id = :id),
              (SELECT created_at FROM cash_registers WHERE id = :id))
        """), {"id": register_id}).scalar()

    def create_cut(self, user_id, register_id, started_at, notes, details, withdrawn=0, withdrawal_reason=None):
        cut_id = uuid.uuid4()
        try:
            with self.session.begin_nested():  # header + details together; the DB checks there's at least one detail
                self.session.execute(text("""
                    INSERT INTO cash_cuts (id, cash_register_id, started_at, ended_at, notes, withdrawn, withdrawal_reason, created_by)
                    VALUES (:id, :r, :start, NOW(), :notes, :withdrawn, :reason, :uid)
                """), {"id": cut_id, "r": register_id, "start": started_at, "notes": notes, "withdrawn": withdrawn,
                      "reason": withdrawal_reason, "uid": user_id})
                self.session.execute(text("""
                    INSERT INTO cash_cut_details (cash_cut_id, payment_method_id, expected_amount, final_amount)
                    VALUES (:cut, :pm, :expected, :counted)
                """), [{"cut": cut_id, "pm": pm, "expected": expected, "counted": counted}
                       for pm, expected, counted in details])
        except IntegrityError:  # overlaps a previous cut of this register
            return None
        return cut_id

    def cuts(self, register_id, limit, offset):
        return self._all(f"""
            SELECT c.id, c.cash_register_id, c.started_at, c.ended_at, c.notes, c.withdrawn, c.withdrawal_reason, u.email AS performed_by, {CUT_DETAILS}
            FROM cash_cuts c JOIN users u ON u.id = c.created_by
            WHERE c.cash_register_id = :r ORDER BY c.ended_at DESC LIMIT :limit OFFSET :offset
        """, r=register_id, limit=limit, offset=offset)

    def get_cut(self, cut_id):
        return self._one(f"""
            SELECT c.id, c.cash_register_id, r.branch_id, r.name AS cash_register, c.started_at, c.ended_at, c.notes,
                   c.withdrawn, c.withdrawal_reason,
                   u.email AS performed_by, {CUT_DETAILS}
            FROM cash_cuts c JOIN users u ON u.id = c.created_by JOIN cash_registers r ON r.id = c.cash_register_id
            WHERE c.id = :id
        """, id=cut_id)

    def commit(self):
        self.session.commit()
