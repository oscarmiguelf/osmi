import uuid

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.infrastructure.persistence.permissions import has_permission

# Fixed references a product can point to (never client input)
REF_TABLES = {"product_types", "units_of_measure", "categories", "tax_rates", "suppliers", "products", "brands"}

PRODUCT = """
    p.id, p.name, p.description, p.barcode, p.brand_id, b.name AS brand, p.cost, p.price, p.min_stock, p.duration_minutes,
    p.product_type_id, t.name AS type, t.tracks_stock, t.is_kit,
    p.unit_of_measure_id, u.name AS unit, p.category_id, c.name AS category,
    p.tax_rate_id, r.name AS tax_rate_name, r.rate AS tax_rate,
    COALESCE(s.current_stock, 0) AS current_stock,
    (p.min_stock > 0 AND COALESCE(s.current_stock, 0) <= p.min_stock) AS is_low_stock,
    p.created_at, p.updated_at, p.deleted_at,
    (SELECT pi.id FROM product_images pi WHERE pi.product_id = p.id ORDER BY pi.sort_order, pi.created_at, pi.id LIMIT 1) AS image_id
"""
PRODUCT_FROM = """
    products p
    JOIN product_types t ON t.id = p.product_type_id
    JOIN units_of_measure u ON u.id = p.unit_of_measure_id
    JOIN tax_rates r ON r.id = p.tax_rate_id
    LEFT JOIN categories c ON c.id = p.category_id
    LEFT JOIN brands b ON b.id = p.brand_id
    LEFT JOIN product_stock s ON s.product_id = p.id AND s.branch_id = CAST(:branch AS uuid) AND s.deleted_at IS NULL
"""
DETAIL = """,
    COALESCE((SELECT JSON_AGG(JSON_BUILD_OBJECT('id', su.id, 'name', su.name) ORDER BY su.name)
      FROM product_suppliers ps JOIN suppliers su ON su.id = ps.supplier_id AND su.deleted_at IS NULL
      WHERE ps.product_id = p.id AND ps.deleted_at IS NULL), '[]') AS suppliers,
    COALESCE((SELECT JSON_AGG(JSON_BUILD_OBJECT('product_id', cp.id, 'name', cp.name, 'quantity', k.quantity) ORDER BY cp.name)
      FROM kit_components k JOIN products cp ON cp.id = k.component_product_id
      WHERE k.kit_product_id = p.id AND k.deleted_at IS NULL), '[]') AS components,
    COALESCE((SELECT JSON_AGG(JSON_BUILD_OBJECT('id', pi.id, 'content_type', pi.content_type, 'size_bytes', pi.size_bytes)
                ORDER BY pi.sort_order, pi.created_at, pi.id)
      FROM product_images pi WHERE pi.product_id = p.id), '[]') AS images,
    (SELECT JSON_BUILD_OBJECT('kind', pb.kind, 'service_product_id', pb.service_product_id, 'service', sp.name, 'sessions', pb.sessions,
                              'valid_days', pb.valid_days, 'price_list_id', pb.price_list_id, 'price_list', pl.name)
       FROM product_benefits pb LEFT JOIN products sp ON sp.id = pb.service_product_id LEFT JOIN price_lists pl ON pl.id = pb.price_list_id
      WHERE pb.product_id = p.id) AS benefit
"""


def _like(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class SqlProductRepository:
    def __init__(self, session: Session):
        self.session = session

    def _one(self, sql: str, **params) -> dict | None:
        row = self.session.execute(text(sql), params).mappings().first()
        return dict(row) if row else None

    def _all(self, sql: str, **params) -> list[dict]:
        return [dict(r) for r in self.session.execute(text(sql), params).mappings()]

    def _scalar(self, sql: str, **params):
        return self.session.execute(text(sql), params).scalar()

    def has_permission(self, user_id, module, permission):
        return has_permission(self.session, user_id, module, permission)

    def ref_active(self, table, item_id):
        assert table in REF_TABLES
        extra = ", tracks_stock, is_kit" if table == "product_types" else ""
        active = "" if table == "brands" else " AND deleted_at IS NULL"  # brands are hard-deleted
        return self._one(f"SELECT id, name{extra} FROM {table} WHERE id = :id{active}", id=item_id)

    def search(self, branch_id, filters, limit, offset):
        where = """
            WHERE (p.deleted_at IS NULL OR :include_deleted)
              AND (:q = '' OR LOWER(p.name) LIKE LOWER(:p) OR LOWER(b.name) LIKE LOWER(:p) OR p.barcode = :q)
              AND (CAST(:type_id AS uuid) IS NULL OR p.product_type_id = CAST(:type_id AS uuid))
              AND (CAST(:category_id AS uuid) IS NULL OR p.category_id = CAST(:category_id AS uuid))
              AND (CAST(:supplier_id AS uuid) IS NULL OR EXISTS (
                    SELECT 1 FROM product_suppliers ps WHERE ps.product_id = p.id
                      AND ps.supplier_id = CAST(:supplier_id AS uuid) AND ps.deleted_at IS NULL))
              AND (NOT :low_stock OR (p.min_stock > 0 AND COALESCE(s.current_stock, 0) <= p.min_stock))
        """
        params = {**filters, "p": _like(filters["q"]), "branch": branch_id}
        items = self._all(f"SELECT {PRODUCT} FROM {PRODUCT_FROM} {where} ORDER BY LOWER(p.name), p.id LIMIT :limit OFFSET :offset",
                          **params, limit=limit, offset=offset)
        total = self._scalar(f"SELECT COUNT(*) FROM {PRODUCT_FROM} {where}", **params)
        return items, total

    def get(self, product_id, branch_id):
        return self._one(f"SELECT {PRODUCT}{DETAIL} FROM {PRODUCT_FROM} WHERE p.id = :id", id=product_id, branch=branch_id)

    def by_barcode(self, barcode, branch_id):
        return self._one(f"SELECT {PRODUCT} FROM {PRODUCT_FROM} WHERE p.barcode = :barcode AND p.deleted_at IS NULL",
                         barcode=barcode, branch=branch_id)

    def create(self, user_id, data):
        product_id = uuid.uuid4()
        try:
            with self.session.begin_nested():  # uq_products_barcode: None instead of an aborted transaction
                self.session.execute(text("""
                    INSERT INTO products (id, name, product_type_id, description, cost, price, barcode, category_id, brand_id,
                                          unit_of_measure_id, min_stock, duration_minutes, tax_rate_id, created_by, updated_by)
                    VALUES (:id, :name, :product_type_id, :description, :cost, :price, :barcode, :category_id, :brand_id,
                            :unit_of_measure_id, :min_stock, :duration_minutes,
                            COALESCE(CAST(:tax_rate_id AS uuid), (SELECT id FROM tax_rates WHERE is_default AND deleted_at IS NULL)),
                            :uid, :uid)
                """), {"duration_minutes": None, **data, "id": product_id, "uid": user_id})
        except IntegrityError:
            return None
        return product_id

    def add_initial_stock(self, user_id, branch_id, product_id, quantity):
        self.session.execute(text("""
            INSERT INTO inventory_movements (branch_id, product_id, movement_type_id, quantity, notes, created_by)
            VALUES (:b, :p, (SELECT id FROM inventory_movement_types WHERE name = 'Adjustment' AND deleted_at IS NULL),
                    :q, 'Inventario inicial', :uid)
        """), {"b": branch_id, "p": product_id, "q": quantity, "uid": user_id})

    def update(self, user_id, product_id, fields):
        sets = "".join(f"{k} = :{k}, " for k in fields)  # keys come from the request model
        try:
            with self.session.begin_nested():
                return self._one(f"""
                    UPDATE products SET {sets}updated_by = :uid WHERE id = :id AND deleted_at IS NULL RETURNING id
                """, **fields, uid=user_id, id=product_id) is not None
        except IntegrityError:
            return None

    def delete(self, user_id, product_id):
        self.session.execute(text("""
            UPDATE products SET deleted_at = NOW(), deleted_by = :uid, updated_by = :uid WHERE id = :id AND deleted_at IS NULL
        """), {"uid": user_id, "id": product_id})

    def restore(self, user_id, product_id):
        try:
            with self.session.begin_nested():
                return self._one("""
                    UPDATE products SET deleted_at = NULL, deleted_by = NULL, updated_by = :uid
                    WHERE id = :id AND deleted_at IS NOT NULL RETURNING id
                """, uid=user_id, id=product_id) is not None
        except IntegrityError:  # another active product took the barcode
            return False

    def has_history(self, product_id):
        """Movements, sales or kit links: changing the product type would make them inconsistent."""
        return self._scalar("""
            SELECT EXISTS (SELECT 1 FROM inventory_movements WHERE product_id = :id)
                OR EXISTS (SELECT 1 FROM sale_items WHERE product_id = :id)
                OR EXISTS (SELECT 1 FROM kit_components WHERE (kit_product_id = :id OR component_product_id = :id)
                           AND deleted_at IS NULL)
        """, id=product_id)

    def delete_blockers(self, product_id):
        return dict(self._one("""
            SELECT
              (SELECT COUNT(*) FROM kit_components k JOIN products kp ON kp.id = k.kit_product_id AND kp.deleted_at IS NULL
                WHERE k.component_product_id = :id AND k.deleted_at IS NULL) AS in_kits,
              (SELECT COUNT(*) FROM product_stock WHERE product_id = :id AND deleted_at IS NULL AND current_stock > 0) AS branches_with_stock,
              (SELECT COUNT(*) FROM transfer_items i JOIN transfers t ON t.id = i.transfer_id
                 JOIN transfer_statuses st ON st.id = t.status_id AND st.name = 'IN_TRANSIT'
                WHERE i.product_id = :id) AS transfers_in_transit,
              (SELECT COUNT(*) FROM stocktake_items i JOIN stocktakes s ON s.id = i.stocktake_id AND s.status = 'OPEN'
                WHERE i.product_id = :id) AS open_stocktakes
        """, id=product_id))

    def history(self, product_id, limit, offset):
        return self._all("""
            SELECT a.changed_at, a.entity_type, a.action, u.email AS changed_by_email, a.changed_fields, a.old_data, a.new_data
            FROM product_audit a LEFT JOIN users u ON u.id = a.changed_by
            WHERE a.product_id = :id ORDER BY a.changed_at DESC, a.id DESC LIMIT :limit OFFSET :offset
        """, id=product_id, limit=limit, offset=offset)

    def replace_suppliers(self, user_id, product_id, supplier_ids):
        params = {"pid": product_id, "ids": supplier_ids, "uid": user_id}
        self.session.execute(text("""
            UPDATE product_suppliers SET deleted_at = NOW(), deleted_by = :uid, updated_by = :uid
            WHERE product_id = :pid AND deleted_at IS NULL AND NOT (supplier_id = ANY(CAST(:ids AS uuid[])))
        """), params)
        self.session.execute(text("""
            INSERT INTO product_suppliers (product_id, supplier_id, created_by, updated_by)
            SELECT :pid, s, :uid, :uid FROM UNNEST(CAST(:ids AS uuid[])) s
            WHERE NOT EXISTS (SELECT 1 FROM product_suppliers WHERE product_id = :pid AND supplier_id = s AND deleted_at IS NULL)
        """), params)

    def replace_components(self, user_id, kit_id, components):
        ids = list(components)
        self.session.execute(text("""
            UPDATE kit_components SET deleted_at = NOW(), deleted_by = :uid, updated_by = :uid
            WHERE kit_product_id = :kit AND deleted_at IS NULL AND NOT (component_product_id = ANY(CAST(:ids AS uuid[])))
        """), {"kit": kit_id, "ids": ids, "uid": user_id})
        for component_id, quantity in components.items():  # the ones that stay keep their row; only the quantity changes
            updated = self.session.execute(text("""
                UPDATE kit_components SET quantity = :q, updated_by = :uid
                WHERE kit_product_id = :kit AND component_product_id = :c AND deleted_at IS NULL AND quantity <> :q
            """), {"kit": kit_id, "c": component_id, "q": quantity, "uid": user_id})
            self.session.execute(text("""
                INSERT INTO kit_components (kit_product_id, component_product_id, quantity, created_by, updated_by)
                SELECT :kit, :c, :q, :uid, :uid
                WHERE NOT EXISTS (SELECT 1 FROM kit_components WHERE kit_product_id = :kit AND component_product_id = :c AND deleted_at IS NULL)
            """), {"kit": kit_id, "c": component_id, "q": quantity, "uid": user_id})

    def commit(self):
        self.session.commit()
