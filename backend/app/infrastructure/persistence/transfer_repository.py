import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.infrastructure.persistence.inventory_repository import STOCK_PRODUCT

STATUS = "(SELECT id FROM transfer_statuses WHERE name = :status AND deleted_at IS NULL)"


def _like(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class SqlTransferRepository:
    def __init__(self, session: Session):
        self.session = session

    def _one(self, sql: str, **params) -> dict | None:
        row = self.session.execute(text(sql), params).mappings().first()
        return dict(row) if row else None

    def _all(self, sql: str, **params) -> list[dict]:
        return [dict(r) for r in self.session.execute(text(sql), params).mappings()]

    def branch_active(self, branch_id):
        return self.session.execute(text(
            "SELECT EXISTS (SELECT 1 FROM branches WHERE id = :id AND deleted_at IS NULL)"), {"id": branch_id}).scalar()

    def stock_products(self, product_ids):
        return {r["id"]: r for r in self._all(f"{STOCK_PRODUCT} WHERE p.id = ANY(CAST(:ids AS uuid[]))", ids=product_ids)}

    def lock_stock(self, branch_id, product_ids):
        # FOR UPDATE: a sale can't take these units between our check and the transfer insert
        rows = self.session.execute(text("""
            SELECT product_id, current_stock FROM product_stock
            WHERE branch_id = :b AND product_id = ANY(CAST(:ids AS uuid[])) AND deleted_at IS NULL FOR UPDATE
        """), {"b": branch_id, "ids": product_ids})
        return {r.product_id: r.current_stock for r in rows}

    def create(self, user_id, from_branch, to_branch, notes, items):
        """Header and items in one transaction: the DB takes the stock out of the origin here and checks >= 1 item at commit."""
        transfer_id = uuid.uuid4()
        self.session.execute(text(f"""
            INSERT INTO transfers (id, from_branch_id, to_branch_id, status_id, notes, created_by, updated_by)
            VALUES (:id, :from, :to, {STATUS}, :notes, :uid, :uid)
        """), {"id": transfer_id, "from": from_branch, "to": to_branch, "status": "IN_TRANSIT", "notes": notes, "uid": user_id})
        self.session.execute(text("""
            INSERT INTO transfer_items (transfer_id, product_id, quantity, created_by) VALUES (:id, :product_id, :quantity, :uid)
        """), [{"id": transfer_id, "uid": user_id, **item} for item in items])
        return transfer_id

    def search(self, branch_id, filters, limit, offset):
        return self._all("""
            SELECT t.id, t.folio, t.created_at, t.updated_at, st.name AS status,
                   t.from_branch_id, fb.name AS from_branch, t.to_branch_id, tb.name AS to_branch,
                   CASE WHEN t.from_branch_id = :b THEN 'outgoing' ELSE 'incoming' END AS direction,
                   uc.email AS sent_by, uu.email AS last_updated_by,
                   (SELECT COUNT(*) FROM transfer_items i WHERE i.transfer_id = t.id) AS item_count
            FROM transfers t
            JOIN transfer_statuses st ON st.id = t.status_id
            JOIN branches fb ON fb.id = t.from_branch_id
            JOIN branches tb ON tb.id = t.to_branch_id
            JOIN users uc ON uc.id = t.created_by
            JOIN users uu ON uu.id = t.updated_by
            WHERE (t.from_branch_id = :b OR t.to_branch_id = :b)
              AND (CAST(:direction AS text) IS NULL
                   OR (CAST(:direction AS text) = 'outgoing' AND t.from_branch_id = :b)
                   OR (CAST(:direction AS text) = 'incoming' AND t.to_branch_id = :b))
              AND (CAST(:status AS text) IS NULL OR st.name = CAST(:status AS text))
              AND (CAST(:from AS timestamptz) IS NULL OR t.created_at >= CAST(:from AS timestamptz))
              AND (CAST(:to AS timestamptz) IS NULL OR t.created_at < CAST(:to AS timestamptz))
            ORDER BY t.created_at DESC, t.id DESC LIMIT :limit OFFSET :offset
        """, b=branch_id, **filters, limit=limit, offset=offset)

    def in_transit(self, branch_id):
        return self._all("""
            SELECT t.id, t.folio, t.from_branch_id, b.name AS from_branch, t.created_at
            FROM transfers_in_transit t JOIN branches b ON b.id = t.from_branch_id
            WHERE t.to_branch_id = :b ORDER BY t.created_at
        """, b=branch_id)

    def get(self, transfer_id):
        return self._one("""
            SELECT t.id, t.folio, st.name AS status, t.notes, t.created_at, t.updated_at,
                   t.from_branch_id, fb.name AS from_branch, t.to_branch_id, tb.name AS to_branch,
                   uc.email AS sent_by, uu.email AS last_updated_by,
                   COALESCE((SELECT JSON_AGG(JSON_BUILD_OBJECT('product_id', p.id, 'product', p.name, 'quantity', i.quantity) ORDER BY p.name)
                     FROM transfer_items i JOIN products p ON p.id = i.product_id WHERE i.transfer_id = t.id), '[]') AS items,
                   COALESCE((SELECT JSON_AGG(JSON_BUILD_OBJECT('changed_at', h.changed_at, 'from_status', fs.name,
                               'to_status', ts.name, 'changed_by', u.email) ORDER BY h.changed_at)
                     FROM transfer_status_history h
                     LEFT JOIN transfer_statuses fs ON fs.id = h.from_status_id
                     JOIN transfer_statuses ts ON ts.id = h.to_status_id
                     JOIN users u ON u.id = h.changed_by
                     WHERE h.transfer_id = t.id), '[]') AS history,
                   COALESCE((SELECT JSON_AGG(JSON_BUILD_OBJECT('created_at', m.created_at, 'branch', b.name, 'product', p.name,
                               'quantity', m.quantity, 'stock_before', m.stock_before, 'stock_after', m.stock_after, 'type', mt.name)
                               ORDER BY m.created_at, p.name)
                     FROM inventory_movements m
                     JOIN branches b ON b.id = m.branch_id
                     JOIN products p ON p.id = m.product_id
                     JOIN inventory_movement_types mt ON mt.id = m.movement_type_id
                     WHERE m.transfer_id = t.id), '[]') AS movements
            FROM transfers t
            JOIN transfer_statuses st ON st.id = t.status_id
            JOIN branches fb ON fb.id = t.from_branch_id
            JOIN branches tb ON tb.id = t.to_branch_id
            JOIN users uc ON uc.id = t.created_by
            JOIN users uu ON uu.id = t.updated_by
            WHERE t.id = :id
        """, id=transfer_id)

    def set_status(self, transfer_id, user_id, status):
        # Only from IN_TRANSIT: of two simultaneous receive/cancel, one updates and the other gets 0 rows
        return self.session.execute(text(f"""
            UPDATE transfers SET status_id = {STATUS}, updated_by = :uid
            WHERE id = :id AND status_id = (SELECT id FROM transfer_statuses WHERE name = 'IN_TRANSIT')
        """), {"id": transfer_id, "uid": user_id, "status": status}).rowcount == 1

    def available_products(self, branch_id, q, limit):
        return self._all("""
            SELECT p.id, p.name, p.barcode, u.name AS unit, ps.current_stock
            FROM product_stock ps
            JOIN products p ON p.id = ps.product_id AND p.deleted_at IS NULL
            JOIN product_types t ON t.id = p.product_type_id AND t.tracks_stock AND NOT t.is_kit
            JOIN units_of_measure u ON u.id = p.unit_of_measure_id
            WHERE ps.branch_id = :b AND ps.deleted_at IS NULL AND ps.current_stock > 0
              AND (:q = '' OR LOWER(p.name) LIKE LOWER(:p) OR p.barcode = :q)
            ORDER BY LOWER(p.name) LIMIT :limit
        """, b=branch_id, q=q, p=_like(q), limit=limit)

    def commit(self):
        self.session.commit()
