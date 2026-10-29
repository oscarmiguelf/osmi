import uuid

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.infrastructure.persistence.permissions import has_permission
from app.infrastructure.persistence.sale_repository import db_rules

STOCKTAKE = """
    s.id, s.folio, s.branch_id, b.name AS branch, s.status, s.notes, s.created_at, cu.email AS created_by,
    s.closed_at, xu.email AS closed_by
"""
STOCKTAKE_FROM = """
    stocktakes s JOIN branches b ON b.id = s.branch_id JOIN users cu ON cu.id = s.created_by
    LEFT JOIN users xu ON xu.id = s.closed_by
"""
ITEM = """
    i.id, p.id AS product_id, p.name AS product, p.barcode, u.name AS unit, i.system_quantity, i.counted_quantity,
    i.difference, i.applied_adjustment, i.notes, us.email AS counted_by, i.updated_at
"""


def _like(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class SqlStocktakeRepository:
    def __init__(self, session: Session):
        self.session = session

    def _one(self, sql: str, **params) -> dict | None:
        row = self.session.execute(text(sql), params).mappings().first()
        return dict(row) if row else None

    def _all(self, sql: str, **params) -> list[dict]:
        return [dict(r) for r in self.session.execute(text(sql), params).mappings()]

    def has_permission(self, user_id, module, permission):
        return has_permission(self.session, user_id, module, permission)

    def search(self, branch_id, filters, limit, offset):
        return self._all(f"""
            SELECT {STOCKTAKE},
                   (SELECT COUNT(*) FROM stocktake_items i WHERE i.stocktake_id = s.id AND i.deleted_at IS NULL) AS counted_items
            FROM {STOCKTAKE_FROM}
            WHERE s.branch_id = :b
              AND (CAST(:status AS text) IS NULL OR s.status = CAST(:status AS text))
              AND (CAST(:from AS timestamptz) IS NULL OR s.created_at >= CAST(:from AS timestamptz))
              AND (CAST(:to AS timestamptz) IS NULL OR s.created_at < CAST(:to AS timestamptz))
            ORDER BY s.created_at DESC, s.id DESC LIMIT :limit OFFSET :offset
        """, b=branch_id, **filters, limit=limit, offset=offset)

    def open_in_branch(self, branch_id):
        return self._one(f"SELECT {STOCKTAKE} FROM {STOCKTAKE_FROM} WHERE s.branch_id = :b AND s.status = 'OPEN'", b=branch_id)

    def get(self, stocktake_id):
        return self._one(f"SELECT {STOCKTAKE} FROM {STOCKTAKE_FROM} WHERE s.id = :id", id=stocktake_id)

    def totals(self, stocktake_id):
        return self._one("""
            SELECT COUNT(*) AS counted_items,
                   COUNT(*) FILTER (WHERE i.difference <> 0) AS items_with_difference,
                   COALESCE(SUM(i.difference) FILTER (WHERE i.difference > 0), 0) AS surplus_units,
                   COALESCE(SUM(-i.difference) FILTER (WHERE i.difference < 0), 0) AS shortage_units,
                   COALESCE(SUM(ROUND(i.difference * p.cost, 2)) FILTER (WHERE i.difference > 0), 0) AS surplus_value,
                   COALESCE(SUM(ROUND(-i.difference * p.cost, 2)) FILTER (WHERE i.difference < 0), 0) AS shortage_value,
                   COALESCE(SUM(ROUND(i.difference * p.cost, 2)), 0) AS difference_value_at_cost
            FROM stocktake_items i JOIN products p ON p.id = i.product_id
            WHERE i.stocktake_id = :id AND i.deleted_at IS NULL
        """, id=stocktake_id)

    def uncounted_count(self, stocktake_id, branch_id):
        return self.session.execute(text("""
            SELECT COUNT(*) FROM product_stock s
            JOIN products p ON p.id = s.product_id AND p.deleted_at IS NULL
            JOIN product_types t ON t.id = p.product_type_id AND t.tracks_stock AND NOT t.is_kit
            WHERE s.branch_id = :b AND s.deleted_at IS NULL AND s.current_stock <> 0
              AND NOT EXISTS (SELECT 1 FROM stocktake_items i WHERE i.stocktake_id = :id AND i.product_id = p.id AND i.deleted_at IS NULL)
        """), {"b": branch_id, "id": stocktake_id}).scalar()

    def create(self, user_id, branch_id, notes):
        stocktake_id = uuid.uuid4()
        try:
            with self.session.begin_nested():  # uq_stocktakes_branch_open: None instead of an aborted transaction
                self.session.execute(text("""
                    INSERT INTO stocktakes (id, branch_id, notes, created_by, updated_by) VALUES (:id, :b, :notes, :uid, :uid)
                """), {"id": stocktake_id, "b": branch_id, "notes": notes, "uid": user_id})
        except IntegrityError:
            return None
        return stocktake_id

    def countable_product(self, product_id, barcode):
        where = "p.id = :id" if product_id else "p.barcode = :barcode AND p.deleted_at IS NULL"
        return self._one(f"""
            SELECT p.id, p.name, p.deleted_at, t.tracks_stock, t.is_kit, u.name AS unit
            FROM products p JOIN product_types t ON t.id = p.product_type_id JOIN units_of_measure u ON u.id = p.unit_of_measure_id
            WHERE {where}
        """, id=product_id, barcode=barcode)

    def search_countable(self, q, limit):
        """Products a counter can count (no stock: a blind count must not show it). Exact barcode first."""
        return self._all("""
            SELECT p.id, p.name, p.barcode, u.name AS unit
            FROM products p JOIN product_types t ON t.id = p.product_type_id AND t.tracks_stock AND NOT t.is_kit
            JOIN units_of_measure u ON u.id = p.unit_of_measure_id
            WHERE p.deleted_at IS NULL AND (p.barcode = :q OR p.name ILIKE :p)
            ORDER BY (p.barcode = :q) DESC, LOWER(p.name) LIMIT :limit
        """, q=q, p=_like(q), limit=limit)

    @db_rules
    def upsert_item(self, user_id, stocktake_id, product_id, counted, notes):
        params = {"st": stocktake_id, "p": product_id, "q": counted, "notes": notes, "uid": user_id}
        update = """
            UPDATE stocktake_items SET counted_quantity = :q, notes = COALESCE(:notes, notes), updated_by = :uid
            WHERE stocktake_id = :st AND product_id = :p AND deleted_at IS NULL RETURNING id
        """
        row = self._one(update, **params)
        if row is None:
            try:
                with self.session.begin_nested():
                    row = self._one("""
                        INSERT INTO stocktake_items (stocktake_id, product_id, counted_quantity, notes, created_by)
                        VALUES (:st, :p, :q, :notes, :uid) RETURNING id
                    """, **params)
            except IntegrityError:  # another counter inserted the same product meanwhile: it's a recount
                row = self._one(update, **params)
        return self._one(f"""
            SELECT {ITEM} FROM stocktake_items i JOIN products p ON p.id = i.product_id
            JOIN units_of_measure u ON u.id = p.unit_of_measure_id JOIN users us ON us.id = i.created_by
            WHERE i.id = :id
        """, id=row["id"])

    def delete_item(self, user_id, stocktake_id, product_id):
        return self.session.execute(text("""
            UPDATE stocktake_items SET deleted_at = NOW(), deleted_by = :uid, updated_by = :uid
            WHERE stocktake_id = :st AND product_id = :p AND deleted_at IS NULL
        """), {"uid": user_id, "st": stocktake_id, "p": product_id}).rowcount == 1

    def items(self, stocktake_id, filters, limit, offset):
        return self._all(f"""
            SELECT {ITEM}
            FROM stocktake_items i
            JOIN products p ON p.id = i.product_id
            JOIN units_of_measure u ON u.id = p.unit_of_measure_id
            JOIN users us ON us.id = i.created_by
            WHERE i.stocktake_id = :st AND i.deleted_at IS NULL
              AND (NOT :only_differences OR i.difference <> 0)
              AND (:q = '' OR p.name ILIKE :p OR p.barcode = :q)
            ORDER BY LOWER(p.name), p.id LIMIT :limit OFFSET :offset
        """, st=stocktake_id, **filters, p=_like(filters["q"]), limit=limit, offset=offset)

    def uncounted(self, stocktake_id, branch_id, filters, limit, offset):
        return self._all("""
            SELECT p.id, p.name, p.barcode, u.name AS unit, s.current_stock, c.name AS category
            FROM product_stock s
            JOIN products p ON p.id = s.product_id AND p.deleted_at IS NULL
            JOIN product_types t ON t.id = p.product_type_id AND t.tracks_stock AND NOT t.is_kit
            JOIN units_of_measure u ON u.id = p.unit_of_measure_id
            LEFT JOIN categories c ON c.id = p.category_id
            WHERE s.branch_id = :b AND s.deleted_at IS NULL AND s.current_stock <> 0
              AND NOT EXISTS (SELECT 1 FROM stocktake_items i WHERE i.stocktake_id = :st AND i.product_id = p.id AND i.deleted_at IS NULL)
              AND (:q = '' OR p.name ILIKE :p OR p.barcode = :q)
              AND (CAST(:category_id AS uuid) IS NULL OR p.category_id = CAST(:category_id AS uuid))
            ORDER BY LOWER(p.name), p.id LIMIT :limit OFFSET :offset
        """, b=branch_id, st=stocktake_id, **filters, p=_like(filters["q"]), limit=limit, offset=offset)

    @db_rules
    def set_status(self, user_id, stocktake_id, status):
        """COMPLETED makes the DB adjust the stock of every counted product (same transaction)."""
        return self.session.execute(text("""
            UPDATE stocktakes SET status = :status, updated_by = :uid WHERE id = :id AND status = 'OPEN'
        """), {"status": status, "uid": user_id, "id": stocktake_id}).rowcount == 1

    def movements(self, stocktake_id):
        return self._all("""
            SELECT m.created_at, p.id AS product_id, p.name AS product, m.quantity, m.stock_before, m.stock_after
            FROM inventory_movements m JOIN products p ON p.id = m.product_id
            WHERE m.stocktake_id = :id ORDER BY LOWER(p.name)
        """, id=stocktake_id)

    def history(self, stocktake_id, limit, offset):
        return self._all("""
            SELECT a.changed_at, a.entity_type, a.action, u.email AS changed_by, a.changed_fields,
                   (SELECT name FROM products WHERE id = CAST(COALESCE(a.new_data, a.old_data) ->> 'product_id' AS uuid)) AS product,
                   a.old_data ->> 'counted_quantity' AS old_counted, a.new_data ->> 'counted_quantity' AS new_counted,
                   a.new_data ->> 'status' AS status
            FROM stocktakes_audit a LEFT JOIN users u ON u.id = a.changed_by
            WHERE a.stocktake_id = :id ORDER BY a.changed_at DESC, a.id DESC LIMIT :limit OFFSET :offset
        """, id=stocktake_id, limit=limit, offset=offset)

    def sheet(self, stocktake_id, branch_id):
        return self._all("""
            SELECT p.name, p.barcode, u.name AS unit, c.name AS category, s.current_stock AS system_quantity, i.counted_quantity
            FROM product_stock s
            JOIN products p ON p.id = s.product_id AND p.deleted_at IS NULL
            JOIN product_types t ON t.id = p.product_type_id AND t.tracks_stock AND NOT t.is_kit
            JOIN units_of_measure u ON u.id = p.unit_of_measure_id
            LEFT JOIN categories c ON c.id = p.category_id
            LEFT JOIN stocktake_items i ON i.stocktake_id = :st AND i.product_id = p.id AND i.deleted_at IS NULL
            WHERE s.branch_id = :b AND s.deleted_at IS NULL
            ORDER BY LOWER(COALESCE(c.name, '')), LOWER(p.name)
        """, st=stocktake_id, b=branch_id)

    def commit(self):
        self.session.commit()
