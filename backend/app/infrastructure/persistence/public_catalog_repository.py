from sqlalchemy import text
from sqlalchemy.orm import Session

# Stock of a product over active branches
STOCK = """(SELECT COALESCE(SUM(s.current_stock), 0) FROM product_stock s JOIN branches b ON b.id = s.branch_id AND b.deleted_at IS NULL
            WHERE s.product_id = p.id AND s.deleted_at IS NULL)"""
# Few left: the exact count is shown only up to here ("last pieces"); above it the catalog just says "available"
FEW = 5
# Shown: active, not a kit, and either a service (no stock) or with stock somewhere
VISIBLE = f"p.deleted_at IS NULL AND NOT t.is_kit AND (NOT t.tracks_stock OR {STOCK} > 0)"


def _like(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class SqlPublicCatalogRepository:
    def __init__(self, session: Session):
        self.session = session

    def products(self, q, category_id, kind, limit, offset):
        kind_sql = {"products": "AND t.tracks_stock", "services": "AND NOT t.tracks_stock"}.get(kind, "")
        rows = self.session.execute(text(f"""
            SELECT p.id, p.name, p.description, p.price, b.name AS brand, c.name AS category, u.name AS unit,
                   NOT t.tracks_stock AS is_service,
                   -- Never the exact stock to the public (competitors): one / few / plenty. max_order caps the order
                   -- only when few are left (that much is already said); otherwise the order is confirmed on WhatsApp
                   CASE WHEN NOT t.tracks_stock THEN NULL WHEN {STOCK} <= 1 THEN 'one' WHEN {STOCK} <= {FEW} THEN 'few' ELSE 'plenty' END AS availability,
                   CASE WHEN t.tracks_stock AND {STOCK} <= {FEW} THEN FLOOR({STOCK})::int END AS max_order,
                   COALESCE((SELECT JSON_AGG(pi.id ORDER BY pi.sort_order, pi.created_at, pi.id)
                             FROM product_images pi WHERE pi.product_id = p.id), '[]') AS image_ids
            FROM products p
            JOIN product_types t ON t.id = p.product_type_id
            JOIN units_of_measure u ON u.id = p.unit_of_measure_id
            LEFT JOIN brands b ON b.id = p.brand_id
            LEFT JOIN categories c ON c.id = p.category_id
            WHERE {VISIBLE} {kind_sql}
              AND (:q = '' OR LOWER(p.name) LIKE LOWER(:p) OR LOWER(b.name) LIKE LOWER(:p) OR LOWER(c.name) LIKE LOWER(:p))
              AND (CAST(:cat AS uuid) IS NULL OR p.category_id = CAST(:cat AS uuid))
            ORDER BY LOWER(p.name), p.id LIMIT :limit OFFSET :offset
        """), {"q": q, "p": _like(q), "cat": category_id, "limit": limit, "offset": offset}).mappings()
        return [dict(r) for r in rows]

    def categories(self):
        """Only categories that have something to show."""
        return [dict(r) for r in self.session.execute(text(f"""
            SELECT DISTINCT c.id, c.name FROM products p JOIN product_types t ON t.id = p.product_type_id
            JOIN categories c ON c.id = p.category_id AND c.deleted_at IS NULL
            WHERE {VISIBLE} ORDER BY c.name
        """)).mappings()]

    def whatsapp_number(self):
        return self.session.execute(text("SELECT value FROM settings WHERE key = 'whatsapp_number'")).scalar() or ""

    def image(self, product_id, image_id):
        row = self.session.execute(text(f"""
            SELECT pi.file_name, pi.content_type FROM product_images pi
            JOIN products p ON p.id = pi.product_id JOIN product_types t ON t.id = p.product_type_id
            WHERE pi.id = :img AND pi.product_id = :pid AND {VISIBLE}
        """), {"img": image_id, "pid": product_id}).mappings().first()
        return dict(row) if row else None
