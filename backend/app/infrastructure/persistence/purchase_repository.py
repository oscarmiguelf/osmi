import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.infrastructure.persistence.inventory_repository import STOCK_PRODUCT
from app.infrastructure.persistence.outgoing_payments import OutgoingPaymentsSql
from app.infrastructure.persistence.product_repository import _like


PAID = "(SELECT COALESCE(SUM(op.amount), 0) FROM outgoing_payments op WHERE op.purchase_id = pu.id)"


class SqlPurchaseRepository(OutgoingPaymentsSql):
    def __init__(self, session: Session):
        self.session = session

    def _one(self, sql: str, **params) -> dict | None:
        row = self.session.execute(text(sql), params).mappings().first()
        return dict(row) if row else None

    def _all(self, sql: str, **params) -> list[dict]:
        return [dict(r) for r in self.session.execute(text(sql), params).mappings()]

    def supplier_active(self, supplier_id):
        return self.session.execute(text(
            "SELECT EXISTS (SELECT 1 FROM suppliers WHERE id = :id AND deleted_at IS NULL)"), {"id": supplier_id}).scalar()

    def stock_products(self, product_ids):
        rows = self._all(f"{STOCK_PRODUCT} WHERE p.id = ANY(CAST(:ids AS uuid[]))", ids=product_ids)
        return {r["id"]: r for r in rows}

    def cost_basis(self, product_ids):
        """Cost and units on hand in every branch; FOR UPDATE so two purchases don't average from the same base."""
        return self._all("""
            SELECT p.id, p.name, p.cost,
                   COALESCE((SELECT SUM(s.current_stock) FROM product_stock s
                             WHERE s.product_id = p.id AND s.deleted_at IS NULL), 0) AS stock
            FROM products p WHERE p.id = ANY(CAST(:ids AS uuid[])) ORDER BY p.id FOR UPDATE OF p
        """, ids=product_ids)

    def set_cost(self, user_id, product_id, cost):
        self.session.execute(text("UPDATE products SET cost = :cost, updated_by = :uid WHERE id = :id"),
                             {"cost": cost, "uid": user_id, "id": product_id})

    def create(self, user_id, branch_id, header, items):
        """Header, items and one Purchase stock movement per item: one transaction (the DB checks total and items at commit)."""
        purchase_id = uuid.uuid4()
        params = {"id": purchase_id, "branch": branch_id, "uid": user_id}
        self.session.execute(text("""
            INSERT INTO purchases (id, branch_id, supplier_id, purchased_at, total, reference, notes, created_by, updated_by)
            VALUES (:id, :branch, :supplier_id, COALESCE(CAST(:purchased_at AS timestamptz), NOW()), :total, :reference, :notes, :uid, :uid)
        """), {**params, **header})
        self.session.execute(text("""
            INSERT INTO purchase_items (purchase_id, product_id, quantity, unit_cost, created_by)
            VALUES (:id, :product_id, :quantity, :unit_cost, :uid)
        """), [{**params, **item} for item in items])
        self.session.execute(text("""
            INSERT INTO inventory_movements (branch_id, product_id, movement_type_id, quantity, purchase_id, reference, created_by)
            SELECT :branch, i.product_id, (SELECT id FROM inventory_movement_types WHERE name = 'Purchase' AND deleted_at IS NULL),
                   i.quantity, :id, :reference, :uid
            FROM purchase_items i WHERE i.purchase_id = :id
        """), {**params, "reference": header["reference"]})
        return purchase_id

    def update(self, user_id, purchase_id, fields):
        sets = "".join(f"{k} = :{k}, " for k in fields)  # keys come from the request model
        self.session.execute(text(f"UPDATE purchases SET {sets}updated_by = :uid WHERE id = :id AND deleted_at IS NULL"),
                             {**fields, "uid": user_id, "id": purchase_id})

    def search(self, branch_id, filters, limit, offset):
        status = {"owed": f"AND {PAID} < pu.total", "paid": f"AND {PAID} >= pu.total"}.get(filters.get("status"), "")
        return self._all(f"""
            SELECT pu.id, pu.purchased_at, pu.total, pu.reference, pu.supplier_id, s.name AS supplier, u.email AS created_by_email,
                   pu.deleted_at, pu.total - {PAID} AS owed,
                   (SELECT COUNT(*) FROM purchase_items i WHERE i.purchase_id = pu.id) AS item_count
            FROM purchases pu
            LEFT JOIN suppliers s ON s.id = pu.supplier_id
            JOIN users u ON u.id = pu.created_by
            WHERE pu.branch_id = :branch AND (pu.deleted_at IS NULL OR :include_voided)
              AND (:q = '' OR LOWER(pu.reference) LIKE LOWER(:p))
              AND (CAST(:from AS timestamptz) IS NULL OR pu.purchased_at >= CAST(:from AS timestamptz))
              AND (CAST(:to AS timestamptz) IS NULL OR pu.purchased_at < CAST(:to AS timestamptz))
              AND (CAST(:supplier_id AS uuid) IS NULL OR pu.supplier_id = CAST(:supplier_id AS uuid)) {status}
            ORDER BY pu.purchased_at DESC, pu.id DESC LIMIT :limit OFFSET :offset
        """, branch=branch_id, **filters, p=_like(filters["q"]), limit=limit, offset=offset)

    def get(self, purchase_id):
        return self._one("""
            SELECT pu.id, pu.branch_id, pu.purchased_at, pu.total, pu.reference, pu.notes, pu.supplier_id, s.name AS supplier,
                   u.email AS created_by_email, pu.created_at, pu.deleted_at,
                   COALESCE((SELECT JSON_AGG(JSON_BUILD_OBJECT('product_id', i.product_id, 'product', p.name,
                               'quantity', i.quantity, 'unit_cost', i.unit_cost, 'line_total', i.line_total) ORDER BY p.name)
                     FROM purchase_items i JOIN products p ON p.id = i.product_id WHERE i.purchase_id = pu.id), '[]') AS items,
                   COALESCE((SELECT JSON_AGG(JSON_BUILD_OBJECT('product', p.name, 'quantity', m.quantity,
                               'stock_before', m.stock_before, 'stock_after', m.stock_after) ORDER BY p.name)
                     FROM inventory_movements m JOIN products p ON p.id = m.product_id WHERE m.purchase_id = pu.id), '[]') AS movements
            FROM purchases pu
            LEFT JOIN suppliers s ON s.id = pu.supplier_id
            JOIN users u ON u.id = pu.created_by
            WHERE pu.id = :id
        """, id=purchase_id)

    def items(self, purchase_id):
        return self._all("""
            SELECT i.product_id, p.name AS product, i.quantity, i.line_total
            FROM purchase_items i JOIN products p ON p.id = i.product_id WHERE i.purchase_id = :id
        """, id=purchase_id)

    def lock_branch_stock(self, branch_id, product_ids):
        # FOR UPDATE: a sale can't take the same units between this check and the voiding movement
        rows = self.session.execute(text("""
            SELECT product_id, current_stock FROM product_stock
            WHERE branch_id = :b AND product_id = ANY(CAST(:ids AS uuid[])) AND deleted_at IS NULL FOR UPDATE
        """), {"b": branch_id, "ids": product_ids})
        return {r.product_id: r.current_stock for r in rows}

    def void(self, user_id, branch_id, purchase_id, quantities):
        """Soft delete + one negative Adjustment per product, linked to the purchase."""
        self.session.execute(text("""
            UPDATE purchases SET deleted_at = NOW(), deleted_by = :uid, updated_by = :uid WHERE id = :id AND deleted_at IS NULL
        """), {"uid": user_id, "id": purchase_id})
        self.session.execute(text("""
            INSERT INTO inventory_movements (branch_id, product_id, movement_type_id, quantity, purchase_id, notes, created_by)
            VALUES (:b, :p, (SELECT id FROM inventory_movement_types WHERE name = 'Adjustment' AND deleted_at IS NULL),
                    :q, :id, 'Compra anulada', :uid)
        """), [{"b": branch_id, "p": p, "q": -q, "id": purchase_id, "uid": user_id} for p, q in quantities.items()])

    def history(self, purchase_id, limit, offset):
        return self._all("""
            SELECT a.changed_at, a.entity_type, a.action, u.email AS changed_by_email, a.changed_fields
            FROM purchases_audit a LEFT JOIN users u ON u.id = a.changed_by
            WHERE a.purchase_id = :id ORDER BY a.changed_at DESC, a.id DESC LIMIT :limit OFFSET :offset
        """, id=purchase_id, limit=limit, offset=offset)

    def last_price(self, product_id):
        """Last price paid in any branch (the cost is shared by all branches too)."""
        return self._one("""
            SELECT i.unit_cost, pu.purchased_at, s.name AS supplier, b.name AS branch, pu.id AS purchase_id
            FROM purchase_items i
            JOIN purchases pu ON pu.id = i.purchase_id AND pu.deleted_at IS NULL
            JOIN branches b ON b.id = pu.branch_id
            LEFT JOIN suppliers s ON s.id = pu.supplier_id
            WHERE i.product_id = :id ORDER BY pu.purchased_at DESC, pu.created_at DESC LIMIT 1
        """, id=product_id)

    def product_lines(self, branch_id, product_id, limit, offset):
        return self._all("""
            SELECT pu.id AS purchase_id, pu.purchased_at, pu.reference, s.name AS supplier, i.quantity, i.unit_cost, i.line_total
            FROM purchase_items i
            JOIN purchases pu ON pu.id = i.purchase_id AND pu.deleted_at IS NULL
            LEFT JOIN suppliers s ON s.id = pu.supplier_id
            WHERE i.product_id = :p AND pu.branch_id = :b
            ORDER BY pu.purchased_at DESC, i.id LIMIT :limit OFFSET :offset
        """, p=product_id, b=branch_id, limit=limit, offset=offset)

    def summary(self, branch_id, start, end, tz):
        params = {"b": branch_id, "start": start, "end": end, "tz": tz}
        where = "pu.branch_id = :b AND pu.deleted_at IS NULL AND pu.purchased_at >= :start AND pu.purchased_at < :end"
        return {
            "by_supplier": self._all(f"""
                SELECT pu.supplier_id, s.name AS supplier, COUNT(*) AS purchases, SUM(pu.total) AS total
                FROM purchases pu LEFT JOIN suppliers s ON s.id = pu.supplier_id
                WHERE {where} GROUP BY pu.supplier_id, s.name ORDER BY total DESC
            """, **params),
            "by_day": self._all(f"""
                SELECT (pu.purchased_at AT TIME ZONE :tz)::date AS day, COUNT(*) AS purchases, SUM(pu.total) AS total
                FROM purchases pu WHERE {where} GROUP BY 1 ORDER BY 1
            """, **params),
            "total": self.session.execute(text(f"SELECT COALESCE(SUM(pu.total), 0) FROM purchases pu WHERE {where}"), params).scalar(),
        }

    def commit(self):
        self.session.commit()
