from sqlalchemy import text
from sqlalchemy.orm import Session


class SqlOfflineRepository:
    def __init__(self, session: Session):
        self.session = session

    def _all(self, sql, **params):
        return [dict(r) for r in self.session.execute(text(sql), params).mappings()]

    def snapshot(self, branch_id):
        """Everything the register needs to sell without internet, as of now. Packages and memberships are left out
        (they grant benefits, which needs the server)."""
        branch = self._all("SELECT id, name, address, phone FROM branches WHERE id = :b", b=branch_id)[0]
        products = self._all("""
            SELECT p.id, p.name, p.barcode, p.price, u.name AS unit, tr.rate AS tax_rate, t.tracks_stock, t.is_kit,
                   CASE WHEN t.tracks_stock AND NOT t.is_kit THEN COALESCE(ps.current_stock, 0) END AS stock
            FROM products p
            JOIN product_types t ON t.id = p.product_type_id
            JOIN units_of_measure u ON u.id = p.unit_of_measure_id
            JOIN tax_rates tr ON tr.id = p.tax_rate_id
            LEFT JOIN product_stock ps ON ps.product_id = p.id AND ps.branch_id = :b AND ps.deleted_at IS NULL
            WHERE p.deleted_at IS NULL AND NOT EXISTS (SELECT 1 FROM product_benefits pb WHERE pb.product_id = p.id)
            ORDER BY p.name
        """, b=branch_id)
        lists = self._all("SELECT id, name, percent FROM price_lists WHERE deleted_at IS NULL ORDER BY name")
        tiers = self._all("""
            SELECT i.price_list_id, i.product_id, i.min_quantity, i.price FROM price_list_items i
            JOIN price_lists l ON l.id = i.price_list_id AND l.deleted_at IS NULL ORDER BY i.min_quantity
        """)
        for pl in lists:
            pl["tiers"] = {}
            for t in tiers:
                if t["price_list_id"] == pl["id"]:
                    pl["tiers"].setdefault(str(t["product_id"]), []).append([t["min_quantity"], t["price"]])
        # Only what's needed to pick a customer and apply their prices (an active membership's list wins, as at the register)
        customers = self._all("""
            SELECT c.id, c.full_name, COALESCE(
                (SELECT b.price_list_id FROM customer_benefits b
                  WHERE b.customer_id = c.id AND b.kind = 'membership' AND b.price_list_id IS NOT NULL
                    AND b.starts_at <= NOW() AND (b.ends_at IS NULL OR b.ends_at > NOW())
                  ORDER BY b.ends_at DESC NULLS FIRST LIMIT 1), c.price_list_id) AS price_list_id
            FROM customers c WHERE c.deleted_at IS NULL ORDER BY c.full_name
        """)
        methods = self._all("""
            SELECT id, description, is_cash FROM payment_methods WHERE deleted_at IS NULL AND is_enabled AND NOT is_credit ORDER BY description
        """)
        return {"branch": branch, "products": products, "price_lists": lists, "customers": customers, "payment_methods": methods}

    def folio_owner(self, offline_folio):
        return self.session.execute(text("SELECT id FROM sales WHERE offline_folio = :f"), {"f": offline_folio}).scalar()

    ISSUE = """i.id, i.sale_id, s.folio, s.offline_folio, s.sold_at, s.branch_id, i.kind, i.detail, i.created_at, i.resolved_at,
               i.note, u.email AS resolved_by"""

    def issues(self, branch_id, resolved):
        return self._all(f"""
            SELECT {self.ISSUE} FROM sale_offline_issues i JOIN sales s ON s.id = i.sale_id LEFT JOIN users u ON u.id = i.resolved_by
            WHERE s.branch_id = :b AND (i.resolved_at IS NOT NULL) = :resolved ORDER BY i.created_at DESC LIMIT 200
        """, b=branch_id, resolved=resolved)

    def issue(self, issue_id):
        rows = self._all(f"""
            SELECT {self.ISSUE} FROM sale_offline_issues i JOIN sales s ON s.id = i.sale_id LEFT JOIN users u ON u.id = i.resolved_by
            WHERE i.id = :id
        """, id=issue_id)
        return rows[0] if rows else None

    def resolve(self, user_id, issue_id, note):
        self.session.execute(text("UPDATE sale_offline_issues SET resolved_at = NOW(), resolved_by = :u, note = :n WHERE id = :id"),
                             {"u": user_id, "n": note, "id": issue_id})

    def commit(self):
        self.session.commit()
