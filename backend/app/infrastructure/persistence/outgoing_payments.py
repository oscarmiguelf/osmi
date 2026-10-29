from sqlalchemy import text

# Fixed by kind (never client input): the parent column and the cash movement type
KINDS = {"expense": ("expense_id", "Expense"), "purchase": ("purchase_id", "Purchase")}


class OutgoingPaymentsSql:
    """Mixed into the expense and purchase repositories (they share the session)."""

    def my_register(self, user_id, branch_id):
        row = self.session.execute(text("""
            SELECT r.id, r.name FROM cash_register_sessions s JOIN cash_registers r ON r.id = s.cash_register_id
            WHERE s.user_id = :uid AND s.ended_at IS NULL AND r.branch_id = :b AND r.deleted_at IS NULL
        """), {"uid": user_id, "b": branch_id}).mappings().first()
        return dict(row) if row else None

    def lock_cash(self, register_id):
        method = self.session.execute(text(
            "SELECT id FROM payment_methods WHERE description = 'Cash' AND NOT is_credit AND deleted_at IS NULL")).scalar_one()
        balance = self.session.execute(text("""
            SELECT balance FROM cash_register_balances WHERE cash_register_id = :r AND payment_method_id = :m FOR UPDATE
        """), {"r": register_id, "m": method}).scalar()
        return method, balance or 0

    def add_payment(self, user_id, kind, parent_id, source, amount, register_id, method_id, notes):
        column, movement_type = KINDS[kind]
        movement = None
        if source == "CASH":
            movement = self.session.execute(text("""
                INSERT INTO cash_register_movements (cash_register_id, payment_method_id, movement_type_id, amount, notes, created_by)
                VALUES (:r, :m, (SELECT id FROM cash_movement_types WHERE name = :type AND deleted_at IS NULL), :amount, :notes, :uid)
                RETURNING id
            """), {"r": register_id, "m": method_id, "type": movement_type, "amount": -amount, "notes": notes, "uid": user_id}).scalar()
        self.session.execute(text(f"""
            INSERT INTO outgoing_payments ({column}, source, amount, cash_register_id, cash_movement_id, notes, created_by)
            VALUES (:parent, :source, :amount, :r, :mv, :notes, :uid)
        """), {"parent": parent_id, "source": source, "amount": amount, "r": register_id, "mv": movement, "notes": notes, "uid": user_id})

    def payments(self, kind, parent_id):
        column, _ = KINDS[kind]
        return [dict(r) for r in self.session.execute(text(f"""
            SELECT p.id, p.created_at, p.source, p.amount, p.notes, r.name AS cash_register, u.email AS created_by_email
            FROM outgoing_payments p
            LEFT JOIN cash_registers r ON r.id = p.cash_register_id
            LEFT JOIN users u ON u.id = p.created_by
            WHERE p.{column} = :id ORDER BY p.created_at, p.source, p.id
        """), {"id": parent_id}).mappings()]

    def return_cash(self, user_id, kind, parent_id):
        """On void: each cash payment goes back into the register it came from (a positive movement of the same type)."""
        column, _ = KINDS[kind]
        return self.session.execute(text(f"""
            WITH back AS (
                INSERT INTO cash_register_movements (cash_register_id, payment_method_id, movement_type_id, amount, notes, created_by)
                SELECT m.cash_register_id, m.payment_method_id, m.movement_type_id, -m.amount, 'Anulación', :uid
                FROM outgoing_payments p JOIN cash_register_movements m ON m.id = p.cash_movement_id
                WHERE p.{column} = :id AND p.source = 'CASH'
                RETURNING amount
            )
            SELECT COALESCE(SUM(amount), 0) FROM back
        """), {"id": parent_id, "uid": user_id}).scalar()
