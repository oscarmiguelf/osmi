from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

COLUMNS = """l.id, l.name, l.percent, l.deleted_at,
    (SELECT COUNT(*) FROM customers c WHERE c.price_list_id = l.id AND c.deleted_at IS NULL) AS customers,
    (SELECT COUNT(*) FROM price_list_items i WHERE i.price_list_id = l.id) AS items_count"""


class SqlPriceListRepository:
    def __init__(self, session: Session):
        self.session = session

    def _one(self, sql, **params):
        try:
            with self.session.begin_nested():
                row = self.session.execute(text(sql), params).mappings().first()
        except IntegrityError:  # uq_price_lists_name
            return None
        return dict(row) if row else None

    def all(self):
        return [dict(r) for r in self.session.execute(text(f"SELECT {COLUMNS} FROM price_lists l WHERE l.deleted_at IS NULL ORDER BY LOWER(l.name)")).mappings()]

    def get(self, list_id):
        row = self.session.execute(text(f"SELECT {COLUMNS} FROM price_lists l WHERE l.id = :id"), {"id": list_id}).mappings().first()
        if row is None:
            return None
        plist = dict(row)
        plist["items"] = [dict(r) for r in self.session.execute(text("""
            SELECT i.product_id, p.name AS product, p.price AS general_price, i.min_quantity, i.price
            FROM price_list_items i JOIN products p ON p.id = i.product_id
            WHERE i.price_list_id = :id ORDER BY LOWER(p.name), i.min_quantity
        """), {"id": list_id}).mappings()]
        return plist

    def create(self, user_id, data):
        return self._one("INSERT INTO price_lists (name, percent, created_by, updated_by) VALUES (:name, :percent, :uid, :uid) RETURNING id",
                         name=data["name"], percent=data.get("percent", 0), uid=user_id)

    def update(self, user_id, list_id, data):
        sets = "".join(f"{k} = :{k}, " for k in data)  # keys from the request model
        return self._one(f"UPDATE price_lists SET {sets}updated_by = :uid WHERE id = :id AND deleted_at IS NULL RETURNING id",
                         **data, uid=user_id, id=list_id)

    def delete(self, user_id, list_id):
        self.session.execute(text("UPDATE price_lists SET deleted_at = NOW(), deleted_by = :uid, updated_by = :uid WHERE id = :id"),
                             {"uid": user_id, "id": list_id})

    def customers_using(self, list_id):
        return self.session.execute(text("SELECT COUNT(*) FROM customers WHERE price_list_id = :id AND deleted_at IS NULL"), {"id": list_id}).scalar()

    def missing_products(self, product_ids):
        if not product_ids:
            return []
        rows = self.session.execute(text("""
            SELECT x FROM UNNEST(CAST(:ids AS uuid[])) x WHERE NOT EXISTS (SELECT 1 FROM products p WHERE p.id = x AND p.deleted_at IS NULL)
        """), {"ids": [str(p) for p in product_ids]})
        return [r.x for r in rows]

    def set_items(self, user_id, list_id, items):
        self.session.execute(text("DELETE FROM price_list_items WHERE price_list_id = :id"), {"id": list_id})
        if items:
            self.session.execute(text("""
                INSERT INTO price_list_items (price_list_id, product_id, min_quantity, price, created_by)
                VALUES (:l, :product_id, :min_quantity, :price, :uid)
            """), [{**i, "l": list_id, "uid": user_id} for i in items])

    def commit(self):
        self.session.commit()
