from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

COLUMNS = "s.id, s.name, s.phone, s.email, s.created_at, s.updated_at, s.deleted_at"
# Purchases count only in the branches the person belongs to; voided purchases (deleted) don't count
MINE = "pu.supplier_id = :id AND pu.deleted_at IS NULL AND fn_user_in_branch(:uid, pu.branch_id)"
PERIOD = "AND (CAST(:start AS timestamptz) IS NULL OR pu.purchased_at >= :start) AND (CAST(:end AS timestamptz) IS NULL OR pu.purchased_at < :end)"


def _like(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class SqlSupplierRepository:
    def __init__(self, session: Session):
        self.session = session

    def _one(self, sql: str, **params) -> dict | None:
        row = self.session.execute(text(sql), params).mappings().first()
        return dict(row) if row else None

    def _all(self, sql: str, **params) -> list[dict]:
        return [dict(r) for r in self.session.execute(text(sql), params).mappings()]

    def search(self, q, include_deleted, sort, limit, offset):
        where = """
            WHERE (:deleted OR s.deleted_at IS NULL)
              AND (:q = '' OR LOWER(s.name) LIKE LOWER(:p) OR LOWER(s.email) LIKE LOWER(:p) OR s.phone LIKE :p)
        """
        params = {"q": q, "p": _like(q), "deleted": include_deleted}
        order = "s.created_at DESC, s.id" if sort == "recent" else "LOWER(s.name), s.id"
        items = self._all(f"""
            SELECT {COLUMNS},
                   (SELECT COUNT(*) FROM product_suppliers ps JOIN products p ON p.id = ps.product_id AND p.deleted_at IS NULL
                     WHERE ps.supplier_id = s.id AND ps.deleted_at IS NULL) AS products,
                   (SELECT MAX(pu.purchased_at) FROM purchases pu WHERE pu.supplier_id = s.id AND pu.deleted_at IS NULL) AS last_purchase_at
            FROM suppliers s {where} ORDER BY {order} LIMIT :limit OFFSET :offset
        """, **params, limit=limit, offset=offset)
        total = self.session.execute(text(f"SELECT COUNT(*) FROM suppliers s {where}"), params).scalar()
        return items, total

    def options(self, include_deleted):
        return self._all("""
            SELECT id, name, phone, email, deleted_at FROM suppliers WHERE deleted_at IS NULL OR :deleted ORDER BY LOWER(name)
        """, deleted=include_deleted)

    def get(self, supplier_id, user_id):
        return self._one(f"""
            SELECT {COLUMNS},
                   (SELECT COUNT(*) FROM product_suppliers ps JOIN products p ON p.id = ps.product_id AND p.deleted_at IS NULL
                     WHERE ps.supplier_id = s.id AND ps.deleted_at IS NULL) AS products,
                   (SELECT COUNT(*) FROM purchases pu WHERE {MINE}) AS purchases,
                   (SELECT MAX(pu.purchased_at) FROM purchases pu WHERE {MINE}) AS last_purchase_at
            FROM suppliers s WHERE s.id = :id
        """, id=supplier_id, uid=user_id)

    def same_name(self, name, exclude_id):
        return self._all("""
            SELECT id, name FROM suppliers
            WHERE deleted_at IS NULL AND LOWER(BTRIM(name)) = LOWER(BTRIM(:name)) AND (CAST(:id AS uuid) IS NULL OR id <> :id)
        """, name=name, id=exclude_id)

    def create(self, user_id, data):
        return self._one("""
            INSERT INTO suppliers (name, phone, email, created_by, updated_by) VALUES (:name, :phone, :email, :uid, :uid)
            RETURNING id, name, phone, email, created_at, updated_at, deleted_at
        """, name=data["name"], phone=data.get("phone"), email=data.get("email"), uid=user_id)

    def update(self, user_id, supplier_id, fields):
        sets = "".join(f"{k} = :{k}, " for k in fields)  # keys come from the request model
        return self._one(f"""
            UPDATE suppliers SET {sets}updated_by = :uid WHERE id = :id AND deleted_at IS NULL RETURNING id
        """, **fields, uid=user_id, id=supplier_id)

    def delete(self, user_id, supplier_id):
        # Same transaction = same NOW(): restore finds the links removed with the supplier by that timestamp
        unlinked = self.session.execute(text("""
            UPDATE product_suppliers SET deleted_at = NOW(), deleted_by = :uid, updated_by = :uid
            WHERE supplier_id = :id AND deleted_at IS NULL
        """), {"uid": user_id, "id": supplier_id}).rowcount
        self.session.execute(text("""
            UPDATE suppliers SET deleted_at = NOW(), deleted_by = :uid, updated_by = :uid WHERE id = :id AND deleted_at IS NULL
        """), {"uid": user_id, "id": supplier_id})
        return unlinked

    def restore(self, user_id, supplier_id):
        # Relink what the delete unlinked (same timestamp), unless the product is gone or was linked again meanwhile
        relinked = self.session.execute(text("""
            UPDATE product_suppliers ps SET deleted_at = NULL, deleted_by = NULL, updated_by = :uid
            FROM suppliers s
            WHERE s.id = :id AND ps.supplier_id = s.id AND ps.deleted_at = s.deleted_at
              AND EXISTS (SELECT 1 FROM products p WHERE p.id = ps.product_id AND p.deleted_at IS NULL)
              AND NOT EXISTS (SELECT 1 FROM product_suppliers o WHERE o.supplier_id = s.id AND o.product_id = ps.product_id
                                AND o.deleted_at IS NULL)
        """), {"uid": user_id, "id": supplier_id}).rowcount
        self.session.execute(text("""
            UPDATE suppliers SET deleted_at = NULL, deleted_by = NULL, updated_by = :uid WHERE id = :id AND deleted_at IS NOT NULL
        """), {"uid": user_id, "id": supplier_id})
        return relinked

    def history(self, supplier_id, limit, offset):
        # The supplier's own changes plus its product links (whose audit rows carry supplier_id in the data)
        return self._all("""
            SELECT a.changed_at, a.entity_type, a.action, u.email AS changed_by_email, a.changed_fields, a.old_data, a.new_data,
                   p.name AS product
            FROM product_audit a
            LEFT JOIN users u ON u.id = a.changed_by
            LEFT JOIN products p ON p.id = a.product_id
            WHERE (a.entity_type = 'supplier' AND a.entity_id = :id)
               OR (a.entity_type = 'product_supplier' AND COALESCE(a.new_data, a.old_data) ->> 'supplier_id' = CAST(:id AS text))
            ORDER BY a.changed_at DESC, a.id DESC LIMIT :limit OFFSET :offset
        """, id=supplier_id, limit=limit, offset=offset)

    def products(self, supplier_id, limit, offset):
        return self._all("""
            SELECT p.id, p.name, p.barcode, p.cost, p.price, ps.created_at AS linked_at
            FROM product_suppliers ps JOIN products p ON p.id = ps.product_id AND p.deleted_at IS NULL
            WHERE ps.supplier_id = :id AND ps.deleted_at IS NULL
            ORDER BY LOWER(p.name), p.id LIMIT :limit OFFSET :offset
        """, id=supplier_id, limit=limit, offset=offset)

    def missing_products(self, product_ids):
        if not product_ids:
            return []
        rows = self.session.execute(text("""
            SELECT x FROM UNNEST(CAST(:ids AS uuid[])) x
            WHERE NOT EXISTS (SELECT 1 FROM products p WHERE p.id = x AND p.deleted_at IS NULL)
        """), {"ids": [str(p) for p in product_ids]})
        return [r.x for r in rows]

    def set_products(self, user_id, supplier_id, product_ids):
        ids = [str(p) for p in product_ids]
        self.session.execute(text("""
            UPDATE product_suppliers SET deleted_at = NOW(), deleted_by = :uid, updated_by = :uid
            WHERE supplier_id = :id AND deleted_at IS NULL AND NOT (product_id = ANY(CAST(:ids AS uuid[])))
        """), {"uid": user_id, "id": supplier_id, "ids": ids})
        self.session.execute(text("""
            INSERT INTO product_suppliers (product_id, supplier_id, created_by, updated_by)
            SELECT x, :id, :uid, :uid FROM UNNEST(CAST(:ids AS uuid[])) x
            WHERE NOT EXISTS (SELECT 1 FROM product_suppliers WHERE supplier_id = :id AND product_id = x AND deleted_at IS NULL)
        """), {"uid": user_id, "id": supplier_id, "ids": ids})

    def link(self, user_id, supplier_id, product_id):
        try:
            with self.session.begin_nested():
                self.session.execute(text("""
                    INSERT INTO product_suppliers (product_id, supplier_id, created_by, updated_by) VALUES (:pid, :id, :uid, :uid)
                """), {"pid": product_id, "id": supplier_id, "uid": user_id})
            return True
        except IntegrityError:  # uq_product_suppliers_active: already linked
            return False

    def unlink(self, user_id, supplier_id, product_id):
        return self.session.execute(text("""
            UPDATE product_suppliers SET deleted_at = NOW(), deleted_by = :uid, updated_by = :uid
            WHERE product_id = :pid AND supplier_id = :id AND deleted_at IS NULL
        """), {"pid": product_id, "id": supplier_id, "uid": user_id}).rowcount > 0

    def purchases(self, user_id, supplier_id, start, end, limit, offset):
        return self._all(f"""
            SELECT pu.id, pu.purchased_at, pu.branch_id, b.name AS branch, pu.total, pu.reference,
                   (SELECT COUNT(*) FROM purchase_items i WHERE i.purchase_id = pu.id) AS items
            FROM purchases pu JOIN branches b ON b.id = pu.branch_id
            WHERE {MINE} {PERIOD}
            ORDER BY pu.purchased_at DESC, pu.id LIMIT :limit OFFSET :offset
        """, id=supplier_id, uid=user_id, start=start, end=end, limit=limit, offset=offset)

    def summary(self, user_id, supplier_id, start, end):
        return self._one(f"""
            SELECT COUNT(*) AS purchases, COALESCE(SUM(pu.total), 0) AS total_spent,
                   CASE WHEN COUNT(*) = 0 THEN 0 ELSE ROUND(SUM(pu.total) / COUNT(*), 2) END AS avg_purchase,
                   MAX(pu.purchased_at) AS last_purchase_at
            FROM purchases pu WHERE {MINE} {PERIOD}
        """, id=supplier_id, uid=user_id, start=start, end=end)

    def price_history(self, user_id, supplier_id, product_id, limit):
        return self._all(f"""
            SELECT pu.id AS purchase_id, pu.purchased_at, i.unit_cost, i.quantity, b.name AS branch
            FROM purchase_items i JOIN purchases pu ON pu.id = i.purchase_id JOIN branches b ON b.id = pu.branch_id
            WHERE {MINE} AND i.product_id = :pid
            ORDER BY pu.purchased_at DESC, pu.id LIMIT :limit
        """, id=supplier_id, uid=user_id, pid=product_id, limit=limit)

    def commit(self):
        self.session.commit()
