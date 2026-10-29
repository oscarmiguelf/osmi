from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

STOCK_PRODUCT = """
    SELECT p.id, p.name, t.tracks_stock, t.is_kit, u.name AS unit, p.deleted_at
    FROM products p JOIN product_types t ON t.id = p.product_type_id JOIN units_of_measure u ON u.id = p.unit_of_measure_id
"""
MOVEMENT = """
    m.id, m.created_at, t.name AS movement_type, m.product_id, p.name AS product, m.quantity, m.stock_before, m.stock_after,
    u.email AS created_by_email, m.reference, m.notes, m.sale_id, m.purchase_id, m.transfer_id, m.stocktake_id
"""
MOVEMENT_FROM = """
    inventory_movements m
    JOIN inventory_movement_types t ON t.id = m.movement_type_id
    JOIN products p ON p.id = m.product_id
    JOIN users u ON u.id = m.created_by
"""
MOVEMENT_FILTERS = """
    AND (CAST(:from AS timestamptz) IS NULL OR m.created_at >= CAST(:from AS timestamptz))
    AND (CAST(:to AS timestamptz) IS NULL OR m.created_at < CAST(:to AS timestamptz))
    AND (CAST(:type AS text) IS NULL OR t.name = CAST(:type AS text))
"""


def _like(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class SqlInventoryRepository:
    def __init__(self, session: Session):
        self.session = session

    def _one(self, sql: str, **params) -> dict | None:
        row = self.session.execute(text(sql), params).mappings().first()
        return dict(row) if row else None

    def _all(self, sql: str, **params) -> list[dict]:
        return [dict(r) for r in self.session.execute(text(sql), params).mappings()]

    def stock_product(self, product_id):
        return self._one(f"{STOCK_PRODUCT} WHERE p.id = :id", id=product_id)

    def stock(self, branch_id, filters, limit, offset):
        where = """
            WHERE p.deleted_at IS NULL AND t.tracks_stock AND NOT t.is_kit
              AND (:q = '' OR LOWER(p.name) LIKE LOWER(:p) OR p.barcode = :q)
              AND (CAST(:category_id AS uuid) IS NULL OR p.category_id = CAST(:category_id AS uuid))
              AND (NOT :low_stock OR (p.min_stock > 0 AND COALESCE(s.current_stock, 0) <= p.min_stock))
        """
        base = """
            FROM products p
            JOIN product_types t ON t.id = p.product_type_id
            JOIN units_of_measure u ON u.id = p.unit_of_measure_id
            LEFT JOIN categories c ON c.id = p.category_id
            LEFT JOIN product_stock s ON s.product_id = p.id AND s.branch_id = :branch AND s.deleted_at IS NULL
        """
        params = {**filters, "p": _like(filters["q"]), "branch": branch_id}
        items = self._all(f"""
            SELECT p.id, p.name, p.barcode, u.name AS unit, c.name AS category, p.min_stock,
                   COALESCE(s.current_stock, 0) AS current_stock,
                   (p.min_stock > 0 AND COALESCE(s.current_stock, 0) <= p.min_stock) AS is_low_stock
            {base} {where} ORDER BY LOWER(p.name), p.id LIMIT :limit OFFSET :offset
        """, **params, limit=limit, offset=offset)
        total = self.session.execute(text(f"SELECT COUNT(*) {base} {where}"), params).scalar()
        return items, total

    def stock_in_my_branches(self, product_id, user_id):
        return self._all("""
            SELECT b.id AS branch_id, b.name AS branch, COALESCE(s.current_stock, 0) AS current_stock
            FROM user_branches ub
            JOIN branches b ON b.id = ub.branch_id AND b.deleted_at IS NULL
            LEFT JOIN product_stock s ON s.branch_id = b.id AND s.product_id = :pid AND s.deleted_at IS NULL
            WHERE ub.user_id = :uid AND ub.deleted_at IS NULL ORDER BY b.name
        """, pid=product_id, uid=user_id)

    def kardex(self, product_id, branch_id, filters, limit, offset):
        return self._all(f"""
            SELECT {MOVEMENT} FROM {MOVEMENT_FROM}
            WHERE m.product_id = :pid AND m.branch_id = :branch {MOVEMENT_FILTERS}
            ORDER BY m.created_at DESC, m.id DESC LIMIT :limit OFFSET :offset
        """, pid=product_id, branch=branch_id, **filters, limit=limit, offset=offset)

    def movements(self, branch_id, filters, limit, offset):
        return self._all(f"""
            SELECT {MOVEMENT} FROM {MOVEMENT_FROM}
            WHERE m.branch_id = :branch {MOVEMENT_FILTERS}
              AND (CAST(:user_id AS uuid) IS NULL OR m.created_by = CAST(:user_id AS uuid))
            ORDER BY m.created_at DESC, m.id DESC LIMIT :limit OFFSET :offset
        """, branch=branch_id, **filters, limit=limit, offset=offset)

    def lock_stock(self, branch_id, product_id):
        # FOR UPDATE: a sale can't take the same units between this check and our movement
        value = self.session.execute(text("""
            SELECT current_stock FROM product_stock
            WHERE branch_id = :b AND product_id = :p AND deleted_at IS NULL FOR UPDATE
        """), {"b": branch_id, "p": product_id}).scalar()
        return value if value is not None else Decimal(0)

    def add_adjustment(self, user_id, branch_id, product_id, quantity, notes, reference):
        return self._one("""
            INSERT INTO inventory_movements (branch_id, product_id, movement_type_id, quantity, notes, reference, created_by)
            VALUES (:b, :p, (SELECT id FROM inventory_movement_types WHERE name = 'Adjustment' AND deleted_at IS NULL),
                    :q, :notes, :ref, :uid)
            RETURNING id, created_at, quantity, stock_before, stock_after, notes, reference
        """, b=branch_id, p=product_id, q=quantity, notes=notes, ref=reference, uid=user_id)

    def low_stock(self, branch_id):
        return self._all("""
            SELECT id, name, barcode, current_stock, min_stock FROM products_with_stock
            WHERE branch_id = :b AND is_low_stock ORDER BY LOWER(name)
        """, b=branch_id)

    def commit(self):
        self.session.commit()
