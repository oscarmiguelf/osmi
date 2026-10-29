import json
import re

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.infrastructure.persistence.permissions import has_permission

COLUMNS = ("full_name", "email", "company", "phone", "address", "additional_phone", "credit_limit", "price_list_id")


def _fold(expr: str) -> str:
    """Case- and accent-insensitive form, so "lopez" finds "López" (no unaccent extension in the schema)."""
    return f"TRANSLATE(LOWER({expr}), 'áéíóúüñàèìòù', 'aeiouunaeiou')"


def _like(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class SqlCustomerRepository:
    def __init__(self, session: Session):
        self.session = session

    def _one(self, sql: str, **params) -> dict | None:
        row = self.session.execute(text(sql), params).mappings().first()
        return dict(row) if row else None

    def _all(self, sql: str, **params) -> list[dict]:
        return [dict(r) for r in self.session.execute(text(sql), params).mappings()]

    def has_permission(self, user_id, module, permission):
        return has_permission(self.session, user_id, module, permission)

    def search(self, q, sort, limit, offset):
        # Phones are stored as bare digits, so "55 1234-5678" must still find 5512345678.
        digits = re.sub(r"\D", "", q)
        where = f"""
            WHERE deleted_at IS NULL
              AND (:q = '' OR {_fold('full_name')} LIKE {_fold(':p')} OR {_fold('company')} LIKE {_fold(':p')}
                   OR {_fold('email')} LIKE {_fold(':p')} OR (:digits <> '' AND phone LIKE :pd))
        """
        params = {"q": q, "p": _like(q), "digits": digits, "pd": _like(digits)}
        order = "created_at DESC, id" if sort == "recent" else "LOWER(full_name), id"
        items = self._all(f"""
            SELECT id, full_name, company, phone, email, credit_limit, created_at
            FROM customers {where} ORDER BY {order} LIMIT :limit OFFSET :offset
        """, **params, limit=limit, offset=offset)
        total = self.session.execute(text(f"SELECT COUNT(*) FROM customers {where}"), params).scalar()
        return items, total

    def get(self, customer_id):
        return self._one("""
            SELECT c.*, l.name AS price_list FROM customers c LEFT JOIN price_lists l ON l.id = c.price_list_id WHERE c.id = :id
        """, id=customer_id)

    def price_list_active(self, list_id):
        return self.session.execute(text("SELECT 1 FROM price_lists WHERE id = :id AND deleted_at IS NULL"), {"id": list_id}).first() is not None

    def count_same_phone(self, phone, exclude_id):
        return self.session.execute(text(
            "SELECT COUNT(*) FROM customers WHERE phone = :phone AND id <> :id AND deleted_at IS NULL"
        ), {"phone": phone, "id": exclude_id}).scalar()

    def create(self, user_id, data):
        return self._one("""
            INSERT INTO customers (full_name, email, company, phone, address, additional_phone, credit_limit, extra,
                                   price_list_id, created_by, updated_by)
            VALUES (:full_name, :email, :company, :phone, :address, :additional_phone, COALESCE(:credit_limit, 0),
                    CAST(:extra AS jsonb), :price_list_id, :uid, :uid)
            RETURNING *
        """, **{k: data.get(k) for k in COLUMNS}, extra=json.dumps(data.get("extra") or {}), uid=user_id)

    def update(self, user_id, customer_id, fields):
        # fields keys come from the request model, never from raw client input
        sets = "".join(f"{k} = {'CAST(:extra AS jsonb)' if k == 'extra' else ':' + k}, " for k in fields)
        params = {**fields, **({"extra": json.dumps(fields["extra"])} if "extra" in fields else {})}
        return self._one(f"""
            UPDATE customers SET {sets}updated_by = :uid
            WHERE id = :id AND deleted_at IS NULL RETURNING *
        """, **params, uid=user_id, id=customer_id)

    def delete(self, user_id, customer_id):
        self.session.execute(text("""
            UPDATE customers SET deleted_at = NOW(), deleted_by = :uid, updated_by = :uid
            WHERE id = :id AND deleted_at IS NULL
        """), {"uid": user_id, "id": customer_id})

    def restore(self, user_id, customer_id):
        return self._one("""
            UPDATE customers SET deleted_at = NULL, deleted_by = NULL, updated_by = :uid
            WHERE id = :id AND deleted_at IS NOT NULL RETURNING *
        """, uid=user_id, id=customer_id)

    def balance(self, customer_id):
        return self.session.execute(text(
            "SELECT COALESCE((SELECT balance FROM customer_credit_balances WHERE customer_id = :id), 0)"
        ), {"id": customer_id}).scalar()

    def history(self, customer_id, limit, offset):
        return self._all("""
            SELECT a.changed_at, a.action, u.email AS changed_by_email, a.changed_fields, a.old_data, a.new_data
            FROM customers_audit a LEFT JOIN users u ON u.id = a.changed_by
            WHERE a.customer_id = :id ORDER BY a.changed_at DESC, a.id DESC LIMIT :limit OFFSET :offset
        """, id=customer_id, limit=limit, offset=offset)

    def credit_summary(self, customer_id):
        return self._one("""
            SELECT c.id AS customer_id, c.full_name, c.credit_limit,
                   COALESCE(b.balance, 0) AS balance,
                   c.credit_limit - COALESCE(b.balance, 0) AS available_credit
            FROM customers c
            LEFT JOIN customer_credit_balances b ON b.customer_id = c.id
            WHERE c.id = :id AND c.deleted_at IS NULL
        """, id=customer_id)

    def credit_movements(self, customer_id, limit, offset):
        return self._all("""
            SELECT m.created_at, s.folio, m.movement_type, m.amount, m.balance_after, u.email AS registered_by
            FROM customer_credit_movements m
            JOIN sales s ON s.id = m.sale_id
            JOIN users u ON u.id = m.created_by
            WHERE m.customer_id = :id ORDER BY m.created_at DESC, m.id DESC LIMIT :limit OFFSET :offset
        """, id=customer_id, limit=limit, offset=offset)

    def pending_sales(self, customer_id, limit, offset):
        return self._all("""
            SELECT * FROM sales_credit_pending WHERE customer_id = :id
            ORDER BY sold_at, sale_id LIMIT :limit OFFSET :offset
        """, id=customer_id, limit=limit, offset=offset)

    def sales(self, customer_id, limit, offset):
        return self._all("""
            SELECT s.id, s.folio, s.sold_at, s.subtotal, s.discount, s.total, st.name AS status, b.name AS branch
            FROM sales s
            JOIN sale_statuses st ON st.id = s.status_id
            JOIN branches b ON b.id = s.branch_id
            WHERE s.customer_id = :id AND s.deleted_at IS NULL
            ORDER BY s.sold_at DESC, s.id DESC LIMIT :limit OFFSET :offset
        """, id=customer_id, limit=limit, offset=offset)

    def commit(self):
        self.session.commit()
