from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# Fixed configuration (never client input): table, columns returned, and what counts as "in use"
CATALOGS = {
    "categories": {
        "table": "categories", "columns": "id, name, deleted_at",
        "usage": "SELECT COUNT(*) FROM products WHERE category_id = :id AND deleted_at IS NULL",
    },
    "units": {
        "table": "units_of_measure", "columns": "id, name, deleted_at",
        "usage": "SELECT COUNT(*) FROM products WHERE unit_of_measure_id = :id AND deleted_at IS NULL",
    },
    "product_types": {
        "table": "product_types", "columns": "id, name, tracks_stock, is_kit, deleted_at",
        "usage": "SELECT COUNT(*) FROM products WHERE product_type_id = :id AND deleted_at IS NULL",
    },
    # Brands are just id + name: no audit columns, hard delete (products keep working with no brand)
    "brands": {
        "table": "brands", "plain": True,
        "columns": "id, name, NULL::timestamptz AS deleted_at, "
                   "(SELECT COUNT(*) FROM products p WHERE p.brand_id = brands.id AND p.deleted_at IS NULL) AS products",
        "usage": "SELECT COUNT(*) FROM products WHERE brand_id = :id AND deleted_at IS NULL",
    },
    "tax_rates": {
        "table": "tax_rates", "columns": "id, name, rate, is_default, deleted_at",
        "usage": "SELECT COUNT(*) FROM products WHERE tax_rate_id = :id AND deleted_at IS NULL",
    },
}


class SqlCatalogRepository:
    def __init__(self, session: Session):
        self.session = session

    def _one(self, sql: str, **params) -> dict | None:
        row = self.session.execute(text(sql), params).mappings().first()
        return dict(row) if row else None

    def _guarded(self, sql: str, **params) -> dict | None:
        """A write that may hit a unique name index: None instead of an aborted transaction."""
        try:
            with self.session.begin_nested():
                return self._one(sql, **params)
        except IntegrityError:
            return None

    def list(self, catalog, include_deleted):
        c = CATALOGS[catalog]
        where = "" if c.get("plain") else "WHERE deleted_at IS NULL OR :deleted"
        rows = self.session.execute(text(f"""
            SELECT {c['columns']} FROM {c['table']} {where} ORDER BY LOWER(name)
        """), {"deleted": include_deleted}).mappings()
        return [dict(r) for r in rows]

    def get(self, catalog, item_id):
        c = CATALOGS[catalog]
        return self._one(f"SELECT {c['columns']} FROM {c['table']} WHERE id = :id", id=item_id)

    def create(self, catalog, user_id, data):
        c = CATALOGS[catalog]
        cols = ", ".join(data)  # keys come from the request model
        if c.get("plain"):
            return self._guarded(f"""
                INSERT INTO {c['table']} ({cols}) VALUES ({', '.join(f':{k}' for k in data)}) RETURNING {c['columns']}
            """, **data)
        return self._guarded(f"""
            INSERT INTO {c['table']} ({cols}, created_by, updated_by)
            VALUES ({', '.join(f':{k}' for k in data)}, :uid, :uid) RETURNING {c['columns']}
        """, **data, uid=user_id)

    def update(self, catalog, user_id, item_id, fields):
        c = CATALOGS[catalog]
        sets = "".join(f"{k} = :{k}, " for k in fields)  # keys come from the request model
        if c.get("plain"):
            return self._guarded(f"""
                UPDATE {c['table']} SET {sets.rstrip(', ')} WHERE id = :id RETURNING {c['columns']}
            """, **fields, id=item_id)
        return self._guarded(f"""
            UPDATE {c['table']} SET {sets}updated_by = :uid WHERE id = :id AND deleted_at IS NULL RETURNING {c['columns']}
        """, **fields, uid=user_id, id=item_id)

    def delete(self, catalog, user_id, item_id):
        c = CATALOGS[catalog]
        if c.get("plain"):
            self.session.execute(text(f"DELETE FROM {c['table']} WHERE id = :id"), {"id": item_id})
            return
        self.session.execute(text(f"""
            UPDATE {c['table']} SET deleted_at = NOW(), deleted_by = :uid, updated_by = :uid
            WHERE id = :id AND deleted_at IS NULL
        """), {"uid": user_id, "id": item_id})

    def restore(self, catalog, user_id, item_id):
        c = CATALOGS[catalog]
        return self._guarded(f"""
            UPDATE {c['table']} SET deleted_at = NULL, deleted_by = NULL, updated_by = :uid
            WHERE id = :id AND deleted_at IS NOT NULL RETURNING {c['columns']}
        """, uid=user_id, id=item_id)

    def usage(self, catalog, item_id):
        return self.session.execute(text(CATALOGS[catalog]["usage"]), {"id": item_id}).scalar()

    def set_default_tax_rate(self, user_id, item_id):
        # One active default (unique index): unset the old one first, in the same transaction
        self.session.execute(text("""
            UPDATE tax_rates SET is_default = FALSE, updated_by = :uid WHERE is_default AND deleted_at IS NULL AND id <> :id
        """), {"uid": user_id, "id": item_id})
        self.session.execute(text("""
            UPDATE tax_rates SET is_default = TRUE, updated_by = :uid WHERE id = :id AND deleted_at IS NULL
        """), {"uid": user_id, "id": item_id})

    def existing_brands(self, ids):
        rows = self.session.execute(text("SELECT id FROM brands WHERE id = ANY(CAST(:ids AS uuid[]))"), {"ids": [str(i) for i in ids]})
        return {r.id for r in rows}

    def merge_brands(self, user_id, from_ids, to_id):
        # Deleted products move too: otherwise ON DELETE SET NULL would leave them without a brand
        moved = self.session.execute(text("""
            UPDATE products SET brand_id = :to, updated_by = :uid WHERE brand_id = ANY(CAST(:from AS uuid[]))
        """), {"to": to_id, "uid": user_id, "from": [str(i) for i in from_ids]}).rowcount
        self.session.execute(text("DELETE FROM brands WHERE id = ANY(CAST(:from AS uuid[]))"), {"from": [str(i) for i in from_ids]})
        return moved

    def commit(self):
        self.session.commit()
