from sqlalchemy import text
from sqlalchemy.orm import Session

from app.infrastructure.persistence.sale_repository import SqlSaleRepository, db_rules


class SqlQuoteRepository:
    def __init__(self, session: Session):
        self.session = session
        self.sales = SqlSaleRepository(session)  # products, customers, stock and promotions read the same as for a sale

    def _one(self, sql: str, **params) -> dict | None:
        row = self.session.execute(text(sql), params).mappings().first()
        return dict(row) if row else None

    def _all(self, sql: str, **params) -> list[dict]:
        return [dict(r) for r in self.session.execute(text(sql), params).mappings()]

    def has_permission(self, user_id, module, permission):
        return self.sales.has_permission(user_id, module, permission)

    def price_list_for(self, customer_id):
        return self.sales.price_list_for(customer_id)

    def list_tiers(self, list_id, product_ids):
        return self.sales.list_tiers(list_id, product_ids)

    def products(self, product_ids):
        return self.sales.products(product_ids)

    def kit_components(self, kit_ids):
        return self.sales.kit_components(kit_ids)

    def branch_stock(self, branch_id, product_ids):
        return self.sales.branch_stock(branch_id, product_ids)

    def active_promotions(self, branch_id):
        return self.sales.active_promotions(branch_id)

    def customer_credit(self, customer_id):
        return self.sales.customer_credit(customer_id)

    def user_timezone(self, user_id):
        return self.session.execute(text("SELECT timezone FROM users WHERE id = :id"), {"id": user_id}).scalar() or "UTC"

    @db_rules
    def create(self, user_id, branch_id, quote_id, header, lines):
        self.session.execute(text("""
            INSERT INTO quotes (id, branch_id, customer_id, customer_name, valid_until, subtotal, discount, total,
                                status_id, notes, created_by, updated_by)
            VALUES (:id, :b, :customer_id, :customer_name, :valid_until, :subtotal, :discount, :total,
                    (SELECT id FROM quote_statuses WHERE name = 'OPEN' AND deleted_at IS NULL), :notes, :uid, :uid)
        """), {**header, "id": quote_id, "b": branch_id, "uid": user_id})
        self.session.execute(text("""
            INSERT INTO quote_items (quote_id, product_id, quantity, unit_price, discount, created_by)
            VALUES (:q, :product_id, :quantity, :unit_price, :discount, :uid)
        """), [{**line, "q": quote_id, "uid": user_id} for line in lines])
        self.session.commit()  # the deferred totals check runs here

    def search(self, branch_id, filters, limit, offset):
        # status OPEN = still convertible; EXPIRED = open but past valid_until (computed, not stored)
        return self._all("""
            SELECT q.id, q.folio, q.created_at, q.valid_until, q.total, st.name AS status,
                   (st.name = 'OPEN' AND q.valid_until < NOW()) AS is_expired,
                   q.customer_id, COALESCE(c.full_name, q.customer_name) AS customer, u.email AS created_by,
                   (SELECT COUNT(*) FROM quote_items i WHERE i.quote_id = q.id) AS item_count
            FROM quotes q
            JOIN quote_statuses st ON st.id = q.status_id
            JOIN users u ON u.id = q.created_by
            LEFT JOIN customers c ON c.id = q.customer_id
            WHERE q.branch_id = :b
              AND (CAST(:from AS timestamptz) IS NULL OR q.created_at >= CAST(:from AS timestamptz))
              AND (CAST(:to AS timestamptz) IS NULL OR q.created_at < CAST(:to AS timestamptz))
              AND (CAST(:status AS text) IS NULL
                   OR (CAST(:status AS text) = 'OPEN' AND st.name = 'OPEN' AND q.valid_until >= NOW())
                   OR (CAST(:status AS text) = 'EXPIRED' AND st.name = 'OPEN' AND q.valid_until < NOW())
                   OR (CAST(:status AS text) IN ('CONVERTED', 'CANCELLED') AND st.name = CAST(:status AS text)))
              AND (CAST(:customer_id AS uuid) IS NULL OR q.customer_id = CAST(:customer_id AS uuid))
              AND (:q = '' OR q.folio ILIKE :p OR COALESCE(c.full_name, q.customer_name) ILIKE :p)
            ORDER BY q.created_at DESC, q.id DESC LIMIT :limit OFFSET :offset
        """, b=branch_id, **filters, p="%" + filters["q"].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%",
            limit=limit, offset=offset)

    def get(self, quote_id):
        quote = self._one("""
            SELECT q.id, q.folio, q.branch_id, b.name AS branch, b.address AS branch_address, b.phone AS branch_phone,
                   q.customer_id, q.customer_name, COALESCE(c.full_name, q.customer_name) AS customer,
                   c.phone AS customer_phone, c.email AS customer_email,
                   q.valid_until, q.subtotal, q.discount, q.total, st.name AS status,
                   (st.name = 'OPEN' AND q.valid_until < NOW()) AS is_expired, q.notes,
                   q.created_at, u.email AS created_by, s.id AS sale_id, s.folio AS sale_folio,
                   ap.id AS appointment_id, ap.title AS appointment_title, ap.starts_at AS appointment_at
            FROM quotes q
            JOIN quote_statuses st ON st.id = q.status_id
            JOIN branches b ON b.id = q.branch_id
            JOIN users u ON u.id = q.created_by
            LEFT JOIN customers c ON c.id = q.customer_id
            LEFT JOIN sales s ON s.quote_id = q.id AND s.deleted_at IS NULL
            LEFT JOIN appointments ap ON ap.quote_id = q.id
            WHERE q.id = :id
        """, id=quote_id)
        if quote is None:
            return None
        quote["items"] = self._all("""
            SELECT i.id, i.product_id, p.name AS product, un.name AS unit, i.quantity, i.unit_price, i.discount, i.line_total,
                   p.price AS current_price, p.deleted_at IS NULL AS product_active, t.tracks_stock, t.is_kit,
                   tr.name AS tax_name, tr.rate AS tax_rate
            FROM quote_items i
            JOIN products p ON p.id = i.product_id
            JOIN product_types t ON t.id = p.product_type_id
            JOIN units_of_measure un ON un.id = p.unit_of_measure_id
            JOIN tax_rates tr ON tr.id = p.tax_rate_id
            WHERE i.quote_id = :id ORDER BY i.created_at, p.name, i.id  -- items of one quote share created_at
        """, id=quote_id)
        return quote

    def id_by_folio(self, branch_id, folio):
        return self.session.execute(text("SELECT id FROM quotes WHERE branch_id = :b AND UPPER(folio) = UPPER(:f)"),
                                    {"b": branch_id, "f": folio}).scalar()

    @db_rules
    def cancel(self, user_id, quote_id):
        return self.session.execute(text("""
            UPDATE quotes SET status_id = (SELECT id FROM quote_statuses WHERE name = 'CANCELLED'), updated_by = :uid
            WHERE id = :id AND status_id = (SELECT id FROM quote_statuses WHERE name = 'OPEN')
        """), {"uid": user_id, "id": quote_id}).rowcount == 1

    def history(self, quote_id):
        return self._all("""
            SELECT a.changed_at, a.entity_type, a.action, u.email AS changed_by, a.changed_fields,
                   (SELECT name FROM quote_statuses WHERE id = CAST(a.new_data ->> 'status_id' AS uuid)) AS to_status
            FROM quotes_audit a LEFT JOIN users u ON u.id = a.changed_by
            WHERE a.quote_id = :id ORDER BY a.changed_at, a.id
        """, id=quote_id)

    def commit(self):
        self.session.commit()
