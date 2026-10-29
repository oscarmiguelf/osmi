import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

# Same rule as fn_promotion_applies: valid in [starts_at, ends_at) while enabled
STATUS = """
    CASE WHEN NOT p.is_enabled THEN 'DISABLED' WHEN NOW() < p.starts_at THEN 'SCHEDULED'
         WHEN NOW() < p.ends_at THEN 'ACTIVE' ELSE 'ENDED' END
"""
PROMOTION = f"""
    p.id, p.name, p.description, p.kind, p.percent, p.amount, p.buy_quantity, p.get_quantity, p.starts_at, p.ends_at,
    p.is_enabled, p.deleted_at, p.created_at, {STATUS} AS status,
    (SELECT COUNT(*) FROM promotion_products pp WHERE pp.promotion_id = p.id AND pp.deleted_at IS NULL) AS product_count,
    (SELECT COUNT(*) FROM promotion_branches pb WHERE pb.promotion_id = p.id AND pb.deleted_at IS NULL) AS branch_count,
    u.lines_sold, u.units_sold, u.discount_given
"""
FROM = "promotions p LEFT JOIN promotion_usage u ON u.promotion_id = p.id"
LINKS = {("promotion_products", "product_id"), ("promotion_branches", "branch_id")}  # fixed, never client input


class SqlPromotionRepository:
    def __init__(self, session: Session):
        self.session = session

    def _one(self, sql: str, **params) -> dict | None:
        row = self.session.execute(text(sql), params).mappings().first()
        return dict(row) if row else None

    def _all(self, sql: str, **params) -> list[dict]:
        return [dict(r) for r in self.session.execute(text(sql), params).mappings()]

    def search(self, filters, limit, offset):
        return self._all(f"""
            SELECT {PROMOTION} FROM {FROM}
            WHERE (p.deleted_at IS NULL OR :include_deleted)
              AND (CAST(:status AS text) IS NULL OR {STATUS} = CAST(:status AS text))
              AND (:q = '' OR p.name ILIKE :p)
              AND (CAST(:product_id AS uuid) IS NULL OR EXISTS (
                    SELECT 1 FROM promotion_products pp WHERE pp.promotion_id = p.id
                      AND pp.product_id = CAST(:product_id AS uuid) AND pp.deleted_at IS NULL))
            ORDER BY p.starts_at DESC, p.id LIMIT :limit OFFSET :offset
        """, **filters, p="%" + filters["q"].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%",
            limit=limit, offset=offset)

    def get(self, promotion_id):
        promo = self._one(f"SELECT {PROMOTION} FROM {FROM} WHERE p.id = :id", id=promotion_id)
        if promo is None:
            return None
        promo["products"] = self._all("""
            SELECT pr.id, pr.name, pr.price, pr.deleted_at IS NOT NULL AS deleted
            FROM promotion_products pp JOIN products pr ON pr.id = pp.product_id
            WHERE pp.promotion_id = :id AND pp.deleted_at IS NULL ORDER BY LOWER(pr.name)
        """, id=promotion_id)
        promo["branches"] = self._all("""
            SELECT b.id, b.name FROM promotion_branches pb JOIN branches b ON b.id = pb.branch_id
            WHERE pb.promotion_id = :id AND pb.deleted_at IS NULL ORDER BY LOWER(b.name)
        """, id=promotion_id)
        return promo

    def missing_products(self, product_ids):
        found = self.session.execute(text("SELECT id FROM products WHERE id = ANY(CAST(:ids AS uuid[])) AND deleted_at IS NULL"),
                                     {"ids": product_ids}).scalars().all()
        return [i for i in product_ids if i not in set(found)]

    def missing_branches(self, branch_ids):
        found = self.session.execute(text("SELECT id FROM branches WHERE id = ANY(CAST(:ids AS uuid[])) AND deleted_at IS NULL"),
                                     {"ids": branch_ids}).scalars().all()
        return [i for i in branch_ids if i not in set(found)]

    def create(self, user_id, data):
        promotion_id = uuid.uuid4()
        self.session.execute(text("""
            INSERT INTO promotions (id, name, description, kind, percent, amount, buy_quantity, get_quantity,
                                    starts_at, ends_at, is_enabled, created_by, updated_by)
            VALUES (:id, :name, :description, :kind, :percent, :amount, :buy_quantity, :get_quantity,
                    :starts_at, :ends_at, :is_enabled, :uid, :uid)
        """), {**data, "id": promotion_id, "uid": user_id})
        return promotion_id

    def update(self, user_id, promotion_id, fields):
        sets = "".join(f"{k} = :{k}, " for k in fields)  # keys come from the request model
        self.session.execute(text(f"UPDATE promotions SET {sets}updated_by = :uid WHERE id = :id AND deleted_at IS NULL"),
                             {**fields, "uid": user_id, "id": promotion_id})

    def set_links(self, user_id, promotion_id, table, column, ids):
        """Replace the products / branches of a promotion: drop the ones left out, add the new ones."""
        assert (table, column) in LINKS
        self.session.execute(text(f"""
            UPDATE {table} SET deleted_at = NOW(), deleted_by = :uid, updated_by = :uid
            WHERE promotion_id = :p AND deleted_at IS NULL AND NOT ({column} = ANY(CAST(:ids AS uuid[])))
        """), {"uid": user_id, "p": promotion_id, "ids": ids})
        self.session.execute(text(f"""
            INSERT INTO {table} (promotion_id, {column}, created_by, updated_by)
            SELECT :p, x, :uid, :uid FROM UNNEST(CAST(:ids AS uuid[])) AS x
            WHERE NOT EXISTS (SELECT 1 FROM {table} t WHERE t.promotion_id = :p AND t.{column} = x AND t.deleted_at IS NULL)
        """), {"uid": user_id, "p": promotion_id, "ids": ids})

    def delete(self, user_id, promotion_id):
        self.session.execute(text("""
            UPDATE promotions SET deleted_at = NOW(), deleted_by = :uid, updated_by = :uid WHERE id = :id AND deleted_at IS NULL
        """), {"uid": user_id, "id": promotion_id})

    def restore(self, user_id, promotion_id):
        self.session.execute(text("""
            UPDATE promotions SET deleted_at = NULL, deleted_by = NULL, updated_by = :uid WHERE id = :id AND deleted_at IS NOT NULL
        """), {"uid": user_id, "id": promotion_id})

    def history(self, promotion_id, limit, offset):
        return self._all("""
            SELECT a.changed_at, a.entity_type, a.action, u.email AS changed_by, a.changed_fields,
                   CASE a.entity_type WHEN 'product' THEN (SELECT name FROM products WHERE id = CAST(COALESCE(a.new_data, a.old_data) ->> 'product_id' AS uuid))
                                      WHEN 'branch' THEN (SELECT name FROM branches WHERE id = CAST(COALESCE(a.new_data, a.old_data) ->> 'branch_id' AS uuid))
                   END AS target, a.old_data, a.new_data
            FROM promotions_audit a LEFT JOIN users u ON u.id = a.changed_by
            WHERE a.promotion_id = :id ORDER BY a.changed_at DESC, a.id DESC LIMIT :limit OFFSET :offset
        """, id=promotion_id, limit=limit, offset=offset)

    def commit(self):
        self.session.commit()
