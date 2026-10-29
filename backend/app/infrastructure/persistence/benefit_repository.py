from sqlalchemy import text
from sqlalchemy.orm import Session


class SqlBenefitRepository:
    def __init__(self, session: Session):
        self.session = session

    def _all(self, sql, **params):
        return [dict(r) for r in self.session.execute(text(sql), params).mappings()]

    def product_kind(self, product_id):
        row = self.session.execute(text("""
            SELECT p.id, p.name, t.tracks_stock, t.is_kit FROM products p JOIN product_types t ON t.id = p.product_type_id
            WHERE p.id = :id AND p.deleted_at IS NULL
        """), {"id": product_id}).mappings().first()
        return dict(row) if row else None

    def price_list_active(self, list_id):
        return self.session.execute(text("SELECT 1 FROM price_lists WHERE id = :id AND deleted_at IS NULL"), {"id": list_id}).first() is not None

    def set_benefit(self, user_id, product_id, data):
        self.session.execute(text("""
            INSERT INTO product_benefits (product_id, kind, service_product_id, sessions, valid_days, price_list_id, updated_by)
            VALUES (:p, :kind, :service_product_id, :sessions, :valid_days, :price_list_id, :uid)
            ON CONFLICT (product_id) DO UPDATE SET kind = EXCLUDED.kind, service_product_id = EXCLUDED.service_product_id,
                sessions = EXCLUDED.sessions, valid_days = EXCLUDED.valid_days, price_list_id = EXCLUDED.price_list_id,
                updated_by = EXCLUDED.updated_by, updated_at = NOW()
        """), {"p": product_id, "uid": user_id, "service_product_id": None, "sessions": None, "valid_days": None, "price_list_id": None, **data})

    def clear_benefit(self, product_id):
        self.session.execute(text("DELETE FROM product_benefits WHERE product_id = :p"), {"p": product_id})

    def customer_benefits(self, customer_id):
        return self._all("""
            SELECT b.id, b.kind, b.product_id, p.name AS product, b.service_product_id, s.name AS service, b.sessions_total,
                   b.sessions_used, b.sessions_total - b.sessions_used AS sessions_left, l.name AS price_list, b.starts_at, b.ends_at,
                   sa.folio AS sale_folio, b.sale_id,
                   (b.starts_at <= NOW() AND (b.ends_at IS NULL OR b.ends_at > NOW())
                    AND (b.kind = 'membership' OR b.sessions_used < b.sessions_total)) AS active
            FROM customer_benefits b
            JOIN products p ON p.id = b.product_id
            LEFT JOIN products s ON s.id = b.service_product_id
            LEFT JOIN price_lists l ON l.id = b.price_list_id
            JOIN sales sa ON sa.id = b.sale_id
            WHERE b.customer_id = :c ORDER BY active DESC, b.ends_at DESC NULLS FIRST, b.created_at DESC
        """, c=customer_id)

    def expiring(self, days):
        """Memberships that end within `days` and weren't renewed (no later one of the same customer and product)."""
        return self._all("""
            SELECT b.id, b.customer_id, c.full_name AS customer, c.phone, p.name AS product, b.ends_at
            FROM customer_benefits b JOIN customers c ON c.id = b.customer_id AND c.deleted_at IS NULL JOIN products p ON p.id = b.product_id
            WHERE b.kind = 'membership' AND b.ends_at > NOW() AND b.ends_at <= NOW() + make_interval(days => :d)
              AND NOT EXISTS (SELECT 1 FROM customer_benefits n WHERE n.customer_id = b.customer_id AND n.product_id = b.product_id
                              AND n.kind = 'membership' AND n.ends_at > b.ends_at)
            ORDER BY b.ends_at
        """, d=days)

    def commit(self):
        self.session.commit()
