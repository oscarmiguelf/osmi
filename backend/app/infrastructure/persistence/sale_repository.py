import functools
import json
import logging

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.application.errors import Conflict, Invalid
from app.infrastructure.persistence.permissions import has_permission

log = logging.getLogger(__name__)

SALE = """
    s.id, s.folio, s.sold_at, s.subtotal, s.discount, s.total, s.tax_total, st.name AS status,
    s.branch_id, s.cash_register_id, r.name AS cash_register, s.customer_id, c.full_name AS customer, c.phone AS customer_phone,
    s.created_by AS seller_id, u.email AS seller, s.quote_id, s.deleted_at, s.offline_folio
"""
SALE_FROM = """
    sales s
    JOIN sale_statuses st ON st.id = s.status_id
    JOIN cash_registers r ON r.id = s.cash_register_id
    JOIN users u ON u.id = s.created_by
    LEFT JOIN customers c ON c.id = s.customer_id
"""


def db_rules(method):
    """Business rules the triggers enforce, as 4xx. Totals that don't match are our bug: logged and re-raised (500)."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except DBAPIError as e:
            self.session.rollback()
            diag = getattr(e.orig, "diag", None)
            message = getattr(diag, "message_primary", None) or str(e.orig)
            state = getattr(e.orig, "sqlstate", None)
            if state == "23505" and "uq_sales_quote" in message:  # converted by someone else in the meantime
                message, state = "uq_sales_quote", "P0001"
            if state != "P0001" or "does not match" in message or "do not add up" in message:
                log.error("sale write rejected by the database: %s", message)
                raise
            if "uq_sales_quote" in message or "cannot be converted" in message or "expired on" in message:
                raise Conflict({"message": "the quote can't be converted any more (converted, cancelled or expired)",
                                "code": "quote_status"}) from None
            if "not occupying" in message:
                raise Conflict({"message": "occupy a cash register of this branch first", "code": "register"}) from None
            raise Invalid({"message": message}) from None
    return wrapper


class SqlSaleRepository:
    def __init__(self, session: Session):
        self.session = session

    def _one(self, sql: str, **params) -> dict | None:
        row = self.session.execute(text(sql), params).mappings().first()
        return dict(row) if row else None

    def _all(self, sql: str, **params) -> list[dict]:
        return [dict(r) for r in self.session.execute(text(sql), params).mappings()]

    def has_permission(self, user_id, module, permission):
        return has_permission(self.session, user_id, module, permission)

    # --- what a sale needs to know before writing ---
    def current_register(self, user_id, branch_id):
        return self._one("""
            SELECT r.id, r.name FROM cash_register_sessions cs JOIN cash_registers r ON r.id = cs.cash_register_id
            WHERE cs.user_id = :uid AND cs.ended_at IS NULL AND r.branch_id = :b AND r.deleted_at IS NULL
        """, uid=user_id, b=branch_id)

    def products(self, product_ids):
        rows = self._all("""
            SELECT p.id, p.name, p.price, u.name AS unit, t.tracks_stock, t.is_kit, tr.rate AS tax_rate, p.deleted_at
            FROM products p
            JOIN product_types t ON t.id = p.product_type_id
            JOIN units_of_measure u ON u.id = p.unit_of_measure_id
            JOIN tax_rates tr ON tr.id = p.tax_rate_id
            WHERE p.id = ANY(CAST(:ids AS uuid[]))
        """, ids=product_ids)
        return {r["id"]: r for r in rows}

    def kit_components(self, kit_ids):
        """Only the components that move stock (what the sale trigger takes out)."""
        return self._all("""
            SELECT kc.kit_product_id AS kit_id, kc.component_product_id AS product_id, cp.name, kc.quantity
            FROM kit_components kc
            JOIN products cp ON cp.id = kc.component_product_id AND cp.deleted_at IS NULL
            JOIN product_types ct ON ct.id = cp.product_type_id AND ct.tracks_stock
            WHERE kc.kit_product_id = ANY(CAST(:ids AS uuid[])) AND kc.deleted_at IS NULL
        """, ids=kit_ids)

    def branch_stock(self, branch_id, product_ids):
        rows = self.session.execute(text("""
            SELECT product_id, current_stock FROM product_stock
            WHERE branch_id = :b AND product_id = ANY(CAST(:ids AS uuid[])) AND deleted_at IS NULL
        """), {"b": branch_id, "ids": product_ids})
        return {r.product_id: r.current_stock for r in rows}

    def promotion(self, promotion_id, product_id, branch_id):
        """The promotion, if it applies to this product in this branch right now."""
        return self._one("""
            SELECT id, name, kind, percent, amount, buy_quantity, get_quantity FROM promotions
            WHERE id = :id AND fn_promotion_applies(:id, :p, :b, NOW())
        """, id=promotion_id, p=product_id, b=branch_id)

    def active_promotions(self, branch_id):
        return self._all("""
            SELECT a.promotion_id, a.product_id, p.name AS product, a.name, a.kind, a.percent, a.amount,
                   a.buy_quantity, a.get_quantity, a.ends_at
            FROM fn_active_promotions(:b, NOW()) a JOIN products p ON p.id = a.product_id AND p.deleted_at IS NULL
            ORDER BY p.name, a.name
        """, b=branch_id)

    def payment_methods(self, method_ids):
        rows = self._all("""
            SELECT id, description, is_credit FROM payment_methods
            WHERE id = ANY(CAST(:ids AS uuid[])) AND deleted_at IS NULL AND is_enabled
        """, ids=method_ids)
        return {r["id"]: r for r in rows}

    def credit_method(self):
        return self._one("SELECT id, description FROM payment_methods WHERE is_credit AND deleted_at IS NULL LIMIT 1")

    def customer_credit(self, customer_id):
        return self._one("""
            SELECT c.id, c.full_name, c.credit_limit, COALESCE(b.balance, 0) AS balance
            FROM customers c LEFT JOIN customer_credit_balances b ON b.customer_id = c.id
            WHERE c.id = :id AND c.deleted_at IS NULL
        """, id=customer_id)

    def quote_for_sale(self, quote_id):
        quote = self._one("""
            SELECT q.id, q.branch_id, q.customer_id, q.valid_until, st.name AS status, q.valid_until < NOW() AS expired
            FROM quotes q JOIN quote_statuses st ON st.id = q.status_id WHERE q.id = :id
        """, id=quote_id)
        if quote:
            rows = self.session.execute(text("SELECT product_id, unit_price FROM quote_items WHERE quote_id = :id"), {"id": quote_id})
            quote["prices"] = {r.product_id: r.unit_price for r in rows}
        return quote

    def sale_owner(self, sale_id):
        return self._one("SELECT id, branch_id FROM sales WHERE id = :id", id=sale_id)

    # --- writes ---
    @db_rules
    def create(self, user_id, branch_id, register_id, sale_id, header, lines, payments):
        """Header, items and payments in one transaction; stock, cash and credit move through the triggers."""
        if header.get("offline_folio"):  # sold without internet: its stock may go below zero (flagged in sale_offline_issues)
            self.session.execute(text("SELECT set_config('app.offline_sale', 'on', TRUE)"))
        self.session.execute(text("""
            INSERT INTO sales (id, subtotal, discount, total, tax_total, branch_id, cash_register_id, customer_id,
                               status_id, quote_id, sold_at, offline_folio, created_by, updated_by)
            VALUES (:id, :subtotal, :discount, :total, :tax_total, :b, :r, :customer_id,
                    (SELECT id FROM sale_statuses WHERE name = :status AND deleted_at IS NULL), :quote_id,
                    COALESCE(CAST(:sold_at AS timestamptz), NOW()), :offline_folio, :uid, :uid)
        """), {"sold_at": None, "offline_folio": None, **header, "id": sale_id, "b": branch_id, "r": register_id, "uid": user_id})
        self.session.execute(text("""
            INSERT INTO sale_items (sale_id, product_id, quantity, unit_price, discount, promotion_id,
                                    fulfillment_status_id, price_list_id, created_by)
            VALUES (:sale, :product_id, :quantity, :unit_price, :discount, :promotion_id,
                    (SELECT id FROM fulfillment_statuses WHERE name = :fulfillment AND deleted_at IS NULL), :price_list_id, :uid)
        """), [{"price_list_id": None, **line, "sale": sale_id, "uid": user_id} for line in lines])
        if header.get("appointment_id"):  # linked before the payments: an event's deposit balance skips the credit limit (DB)
            self.session.execute(text("""
                UPDATE appointments SET sale_id = :sale, updated_by = :uid,
                       -- charged at or after its start: attended; before it (a deposit for an event): it stays open
                       -- (never when the sale is made at booking: keep_open)
                       status = CASE WHEN status IN ('SCHEDULED', 'CONFIRMED') AND starts_at <= NOW() AND NOT :keep_open
                                     THEN 'COMPLETED' ELSE status END
                WHERE id = :a
            """), {"sale": sale_id, "uid": user_id, "a": header["appointment_id"], "keep_open": bool(header.get("keep_open"))})
        if payments:
            self.session.execute(text("""
                INSERT INTO sale_payments (sale_id, payment_method_id, amount, amount_tendered, reference, created_by)
                VALUES (:sale, :payment_method_id, :amount, :amount_tendered, :reference, :uid)
            """), [{**p, "sale": sale_id, "uid": user_id} for p in payments])
        for use in header.get("uses") or []:  # sessions of a package (the trigger checks customer, service, sessions left)
            self.session.execute(text("""
                INSERT INTO customer_benefit_uses (benefit_id, sale_id, product_id, quantity, created_by)
                VALUES (:benefit_id, :sale, :product_id, :quantity, :uid)
            """), {**use, "sale": sale_id, "uid": user_id})
        for g in header.get("grants") or []:  # a package / membership sold: the customer gets it (a renewal starts when the last one ends)
            self.session.execute(text("""
                WITH start AS (
                    SELECT GREATEST(NOW(), COALESCE((SELECT MAX(ends_at) FROM customer_benefits
                                                     WHERE customer_id = :c AND product_id = :p AND kind = 'membership'), NOW())) AS at
                )
                INSERT INTO customer_benefits (customer_id, product_id, sale_id, kind, service_product_id, sessions_total, price_list_id,
                                               starts_at, ends_at, created_by)
                SELECT :c, :p, :sale, CAST(:kind AS varchar), :service_product_id, :sessions_total, :price_list_id,
                       CASE WHEN CAST(:kind AS varchar) = 'membership' THEN start.at ELSE NOW() END,
                       CASE WHEN CAST(:days AS integer) IS NULL THEN NULL
                            ELSE (CASE WHEN CAST(:kind AS varchar) = 'membership' THEN start.at ELSE NOW() END)
                                 + make_interval(days => CAST(:days AS integer)) END,
                       :uid
                FROM start
            """), {"c": header["customer_id"], "p": g["product_id"], "sale": sale_id, "kind": g["kind"], "service_product_id": g["service_product_id"],
                  "sessions_total": g["sessions"] * g["quantity"] if g["sessions"] else None, "price_list_id": g["price_list_id"],
                  "days": g["valid_days"] * (g["quantity"] if g["kind"] == "membership" else 1) if g["valid_days"] else None, "uid": user_id})
        if header.get("offline_issues"):
            self.session.execute(text(
                "INSERT INTO sale_offline_issues (sale_id, kind, detail) VALUES (:sale, :kind, CAST(:detail AS jsonb))"),
                [{"sale": sale_id, "kind": i["kind"], "detail": json.dumps(i["detail"], default=str)} for i in header["offline_issues"]])
        self.session.commit()  # the deferred checks (totals, tax, payments) run here

    @db_rules
    def deliver(self, user_id, sale_id, item_ids):
        return self.session.execute(text("""
            UPDATE sale_items SET fulfillment_status_id = (SELECT id FROM fulfillment_statuses WHERE name = 'DELIVERED'),
                                  updated_by = :uid
            WHERE sale_id = :sale AND id = ANY(CAST(:ids AS uuid[]))
              AND fulfillment_status_id = (SELECT id FROM fulfillment_statuses WHERE name = 'RESERVED')
        """), {"uid": user_id, "sale": sale_id, "ids": item_ids}).rowcount

    @db_rules
    def add_abonos(self, user_id, register_id, abonos):
        """abonos: [{sale_id, payment_method_id, amount, amount_tendered, reference}] (one per sale, same transaction)."""
        self.session.execute(text("""
            INSERT INTO sale_payments (sale_id, kind, payment_method_id, cash_register_id, amount, amount_tendered, reference, created_by)
            VALUES (:sale_id, 'credit_payment', :payment_method_id, :r, :amount, :amount_tendered, :reference, :uid)
        """), [{**a, "r": register_id, "uid": user_id} for a in abonos])
        self.session.commit()

    @db_rules
    def create_return(self, user_id, register_id, return_id, sale_id, refund_total, reason, items, refunds):
        self.session.execute(text("""
            INSERT INTO sale_returns (id, sale_id, cash_register_id, refund_total, reason, created_by)
            VALUES (:id, :sale, :r, :total, :reason, :uid)
        """), {"id": return_id, "sale": sale_id, "r": register_id, "total": refund_total, "reason": reason, "uid": user_id})
        self.session.execute(text("""
            INSERT INTO sale_return_items (sale_return_id, sale_item_id, quantity, created_by)
            VALUES (:ret, :sale_item_id, :quantity, :uid)
        """), [{**i, "ret": return_id, "uid": user_id} for i in items])
        self.session.execute(text("""
            INSERT INTO sale_return_refunds (sale_return_id, payment_method_id, amount, reference, created_by)
            VALUES (:ret, :payment_method_id, :amount, :reference, :uid)
        """), [{**r, "ret": return_id, "uid": user_id} for r in refunds])
        self.session.commit()

    # --- reads ---
    def price_list_for(self, customer_id):
        """An active membership's price list first, else the customer's own list."""
        return self._one("""
            SELECT l.id, l.name, l.percent FROM price_lists l
            WHERE l.deleted_at IS NULL AND l.id = COALESCE(
                (SELECT b.price_list_id FROM customer_benefits b
                  WHERE b.customer_id = :id AND b.kind = 'membership' AND b.price_list_id IS NOT NULL
                    AND b.starts_at <= NOW() AND (b.ends_at IS NULL OR b.ends_at > NOW())
                  ORDER BY b.ends_at DESC NULLS FIRST LIMIT 1),
                (SELECT price_list_id FROM customers WHERE id = :id))
        """, id=customer_id)

    def customer_exists(self, customer_id):
        return self._one("SELECT 1 AS ok FROM customers WHERE id = :id AND deleted_at IS NULL", id=customer_id) is not None

    def product_benefits(self, product_ids):
        return {r["product_id"]: {k: r[k] for k in ("kind", "service_product_id", "sessions", "valid_days", "price_list_id")}
                for r in self._all("SELECT * FROM product_benefits WHERE product_id = ANY(CAST(:ids AS uuid[]))", ids=[str(p) for p in product_ids])}

    def benefits_for_use(self, benefit_ids):
        if not benefit_ids:
            return {}
        return {r["id"]: r for r in self._all("""
            SELECT id, customer_id, service_product_id, sessions_total - sessions_used AS sessions_left,
                   (ends_at IS NOT NULL AND ends_at <= NOW()) AS expired
            FROM customer_benefits WHERE id = ANY(CAST(:ids AS uuid[])) AND kind = 'package'
        """, ids=[str(b) for b in benefit_ids])}

    def list_tiers(self, list_id, product_ids):
        tiers: dict = {}
        for r in self._all("""
            SELECT product_id, min_quantity, price FROM price_list_items
            WHERE price_list_id = :l AND product_id = ANY(CAST(:ids AS uuid[]))
        """, l=list_id, ids=[str(p) for p in product_ids]):
            tiers.setdefault(r["product_id"], []).append((r["min_quantity"], r["price"]))
        return tiers

    def appointment_of_quote(self, quote_id):
        return self.session.execute(text("SELECT id FROM appointments WHERE quote_id = :q"), {"q": quote_id}).scalar()

    def appointment_for_sale(self, appointment_id):
        row = self.session.execute(text(
            """SELECT a.id, a.branch_id, a.customer_id, a.status, a.sale_id, a.starts_at, st.name AS sale_status
               FROM appointments a LEFT JOIN sales s ON s.id = a.sale_id LEFT JOIN sale_statuses st ON st.id = s.status_id
               WHERE a.id = :id"""), {"id": appointment_id}).mappings().first()
        return dict(row) if row else None

    def lock_sale(self, sale_id):
        """Status and credit owed, with the sale row locked until commit (abonos and returns on the same sale queue up)."""
        return self._one("""
            SELECT s.id, s.branch_id, s.customer_id, s.folio, st.name AS status, s.deleted_at,
                   fn_sale_credit_outstanding(s.id) AS credit_outstanding
            FROM sales s JOIN sale_statuses st ON st.id = s.status_id WHERE s.id = :id FOR UPDATE OF s
        """, id=sale_id)

    def search(self, branch_id, filters, limit, offset):
        return self._all(f"""
            SELECT {SALE},
                   (SELECT COUNT(*) FROM sale_items i JOIN fulfillment_statuses f ON f.id = i.fulfillment_status_id
                     WHERE i.sale_id = s.id AND f.name = 'RESERVED') AS reserved_items
            FROM {SALE_FROM}
            WHERE s.branch_id = :b AND s.deleted_at IS NULL
              AND (CAST(:from AS timestamptz) IS NULL OR s.sold_at >= CAST(:from AS timestamptz))
              AND (CAST(:to AS timestamptz) IS NULL OR s.sold_at < CAST(:to AS timestamptz))
              AND (CAST(:status AS text) IS NULL OR st.name = CAST(:status AS text))
              AND (CAST(:customer_id AS uuid) IS NULL OR s.customer_id = CAST(:customer_id AS uuid))
              AND (CAST(:seller_id AS uuid) IS NULL OR s.created_by = CAST(:seller_id AS uuid))
              AND (CAST(:register_id AS uuid) IS NULL OR s.cash_register_id = CAST(:register_id AS uuid))
              AND (:q = '' OR s.folio ILIKE :p OR s.offline_folio ILIKE :p)
            ORDER BY s.sold_at DESC, s.id DESC LIMIT :limit OFFSET :offset
        """, b=branch_id, **filters, p=f"%{filters['q']}%", limit=limit, offset=offset)

    def get(self, sale_id):
        sale = self._one(f"""
            SELECT {SALE}, b.name AS branch, b.address AS branch_address, b.phone AS branch_phone,
                   fn_sale_credit_outstanding(s.id) AS credit_outstanding, q.folio AS quote_folio,
                   (SELECT ap.id FROM appointments ap WHERE ap.sale_id = s.id) AS appointment_id,
                   (SELECT ap.starts_at FROM appointments ap WHERE ap.sale_id = s.id) AS appointment_at
            FROM {SALE_FROM} JOIN branches b ON b.id = s.branch_id LEFT JOIN quotes q ON q.id = s.quote_id WHERE s.id = :id
        """, id=sale_id)
        if sale is None:
            return None
        sale["items"] = self._all("""
            SELECT i.id, i.product_id, p.name AS product, u.name AS unit, i.quantity, i.unit_price, i.discount, i.line_total,
                   i.tax_rate, i.tax_amount, f.name AS fulfillment, i.promotion_id, pr.name AS promotion,
                   rt.returned_quantity, rt.returnable_quantity
            FROM sale_items i
            JOIN products p ON p.id = i.product_id
            JOIN units_of_measure u ON u.id = p.unit_of_measure_id
            JOIN fulfillment_statuses f ON f.id = i.fulfillment_status_id
            JOIN sale_items_returnable rt ON rt.sale_item_id = i.id
            LEFT JOIN promotions pr ON pr.id = i.promotion_id
            WHERE i.sale_id = :id ORDER BY i.created_at, p.name, i.id  -- items of one sale share created_at
        """, id=sale_id)
        sale["payments"] = self._all("""
            SELECT pay.id, pay.created_at, pay.kind, pm.description AS method, pm.is_credit, pay.amount,
                   pay.amount_tendered, pay.change_given, pay.reference, u.email AS created_by
            FROM sale_payments pay JOIN payment_methods pm ON pm.id = pay.payment_method_id JOIN users u ON u.id = pay.created_by
            WHERE pay.sale_id = :id ORDER BY pay.created_at, pay.id
        """, id=sale_id)
        sale["returns"] = self._all("""
            SELECT r.id, r.folio, r.created_at, r.refund_total, r.reason, u.email AS processed_by
            FROM sale_returns r JOIN users u ON u.id = r.created_by WHERE r.sale_id = :id ORDER BY r.created_at
        """, id=sale_id)
        sale["tax_breakdown"] = self._all("""
            SELECT tax_name, tax_rate, taxable_base, tax_amount, gross_amount FROM sale_tax_breakdown
            WHERE sale_id = :id ORDER BY tax_rate DESC
        """, id=sale_id)
        return sale

    def id_by_folio(self, branch_id, folio):
        return self.session.execute(text("SELECT id FROM sales WHERE branch_id = :b AND (UPPER(folio) = UPPER(:f) OR UPPER(offline_folio) = UPPER(:f))"),
                                    {"b": branch_id, "f": folio}).scalar()

    def returnable(self, sale_id):
        return self._all("""
            SELECT rt.sale_item_id, p.name AS product, i.quantity AS sold_quantity, rt.returned_quantity,
                   rt.returnable_quantity, i.line_total, u.name AS unit
            FROM sale_items_returnable rt
            JOIN sale_items i ON i.id = rt.sale_item_id
            JOIN products p ON p.id = i.product_id
            JOIN units_of_measure u ON u.id = p.unit_of_measure_id
            WHERE rt.sale_id = :id ORDER BY i.created_at, i.id
        """, id=sale_id)

    def refund_for(self, sale_item_id, quantity):
        return self.session.execute(text("SELECT fn_calc_return_refund(:i, :q)"), {"i": sale_item_id, "q": quantity}).scalar()

    def credit_pending(self, branch_id, customer_id=None, lock=False):
        return self._all(f"""
            SELECT v.sale_id, v.folio, v.sold_at, v.total, v.credit_outstanding, v.customer_id, c.full_name AS customer
            FROM sales_credit_pending v JOIN customers c ON c.id = v.customer_id
            {"JOIN sales s ON s.id = v.sale_id" if lock else ""}
            WHERE v.branch_id = :b AND (CAST(:c AS uuid) IS NULL OR v.customer_id = CAST(:c AS uuid))
            ORDER BY v.sold_at, v.sale_id {"FOR UPDATE OF s" if lock else ""}
        """, b=branch_id, c=customer_id)

    def pending_deliveries(self, branch_id):
        return self._all("""
            SELECT s.id AS sale_id, s.folio, s.sold_at, c.full_name AS customer, i.id AS sale_item_id, p.name AS product,
                   i.quantity, rt.returnable_quantity
            FROM sale_items i
            JOIN sales s ON s.id = i.sale_id AND s.deleted_at IS NULL AND s.branch_id = :b
            JOIN sale_statuses st ON st.id = s.status_id AND st.name <> 'RETURNED'
            JOIN fulfillment_statuses f ON f.id = i.fulfillment_status_id AND f.name = 'RESERVED'
            JOIN sale_items_returnable rt ON rt.sale_item_id = i.id AND rt.returnable_quantity > 0
            JOIN products p ON p.id = i.product_id
            LEFT JOIN customers c ON c.id = s.customer_id
            ORDER BY s.sold_at, i.created_at
        """, b=branch_id)

    def item_states(self, sale_id, item_ids):
        return self._all("""
            SELECT i.id, f.name AS fulfillment, rt.returnable_quantity FROM sale_items i
            JOIN fulfillment_statuses f ON f.id = i.fulfillment_status_id
            JOIN sale_items_returnable rt ON rt.sale_item_id = i.id
            WHERE i.sale_id = :sale AND i.id = ANY(CAST(:ids AS uuid[])) FOR UPDATE OF i
        """, sale=sale_id, ids=item_ids)

    def returns(self, branch_id, filters, limit, offset):
        return self._all("""
            SELECT r.id, r.folio, r.created_at, r.refund_total, r.reason, r.sale_id, s.folio AS sale_folio,
                   u.email AS processed_by, c.full_name AS customer
            FROM sale_returns r JOIN sales s ON s.id = r.sale_id JOIN users u ON u.id = r.created_by
            LEFT JOIN customers c ON c.id = s.customer_id
            WHERE r.branch_id = :b
              AND (CAST(:from AS timestamptz) IS NULL OR r.created_at >= CAST(:from AS timestamptz))
              AND (CAST(:to AS timestamptz) IS NULL OR r.created_at < CAST(:to AS timestamptz))
            ORDER BY r.created_at DESC, r.id DESC LIMIT :limit OFFSET :offset
        """, b=branch_id, **filters, limit=limit, offset=offset)

    def get_return(self, return_id):
        ret = self._one("""
            SELECT r.id, r.folio, r.created_at, r.refund_total, r.reason, r.sale_id, s.folio AS sale_folio, r.branch_id,
                   cr.name AS cash_register, u.email AS processed_by
            FROM sale_returns r JOIN sales s ON s.id = r.sale_id JOIN users u ON u.id = r.created_by
            JOIN cash_registers cr ON cr.id = r.cash_register_id
            WHERE r.id = :id
        """, id=return_id)
        if ret is None:
            return None
        ret["items"] = self._all("""
            SELECT ri.sale_item_id, p.name AS product, ri.quantity, ri.refund_amount
            FROM sale_return_items ri JOIN sale_items i ON i.id = ri.sale_item_id JOIN products p ON p.id = i.product_id
            WHERE ri.sale_return_id = :id ORDER BY p.name
        """, id=return_id)
        ret["refunds"] = self._all("""
            SELECT pm.description AS method, pm.is_credit, rf.amount, rf.reference
            FROM sale_return_refunds rf JOIN payment_methods pm ON pm.id = rf.payment_method_id
            WHERE rf.sale_return_id = :id ORDER BY rf.created_at, rf.id
        """, id=return_id)
        return ret

    def history(self, sale_id):
        return {
            "status": self._all("""
                SELECT h.changed_at, fs.name AS from_status, ts.name AS to_status, u.email AS changed_by
                FROM sale_status_history h JOIN sale_statuses ts ON ts.id = h.to_status_id
                LEFT JOIN sale_statuses fs ON fs.id = h.from_status_id JOIN users u ON u.id = h.changed_by
                WHERE h.sale_id = :id ORDER BY h.changed_at, h.id
            """, id=sale_id),
            "fulfillment": self._all("""
                SELECT h.changed_at, h.sale_item_id, p.name AS product, ff.name AS from_status, tf.name AS to_status,
                       u.email AS changed_by
                FROM sale_item_fulfillment_history h JOIN sale_items i ON i.id = h.sale_item_id
                JOIN products p ON p.id = i.product_id JOIN fulfillment_statuses tf ON tf.id = h.to_status_id
                LEFT JOIN fulfillment_statuses ff ON ff.id = h.from_status_id JOIN users u ON u.id = h.changed_by
                WHERE h.sale_id = :id ORDER BY h.changed_at, h.id
            """, id=sale_id),
            "audit": self._all("""
                SELECT a.changed_at, a.entity_type, a.action, u.email AS changed_by, a.changed_fields
                FROM sales_audit a LEFT JOIN users u ON u.id = a.changed_by
                WHERE a.sale_id = :id ORDER BY a.changed_at, a.id
            """, id=sale_id),
        }

    def report(self, branch_id, start, end):
        p = {"b": branch_id, "start": start, "end": end}
        live = "s.branch_id = :b AND s.deleted_at IS NULL AND s.sold_at >= :start AND s.sold_at < :end"
        totals = self._one(f"""
            SELECT COUNT(*) AS sales, COALESCE(SUM(s.total), 0) AS total, COALESCE(SUM(s.tax_total), 0) AS tax,
                   COALESCE(SUM(s.discount), 0) AS sale_discounts
            FROM sales s WHERE {live}
        """, **p)
        totals["returns"] = self.session.execute(text("""
            SELECT COALESCE(SUM(refund_total), 0) FROM sale_returns WHERE branch_id = :b AND created_at >= :start AND created_at < :end
        """), p).scalar()
        totals["net"] = totals["total"] - totals["returns"]  # returns count on the day they happen
        return {
            "totals": totals,
            "by_method": self._all(f"""
                SELECT pm.description AS method, pm.is_credit, COUNT(*) AS payments, SUM(pay.amount) AS amount
                FROM sale_payments pay JOIN sales s ON s.id = pay.sale_id JOIN payment_methods pm ON pm.id = pay.payment_method_id
                WHERE pay.kind = 'sale' AND {live} GROUP BY pm.description, pm.is_credit ORDER BY amount DESC
            """, **p),
            "by_seller": self._all(f"""
                SELECT u.email AS seller, COUNT(*) AS sales, SUM(s.total) AS total
                FROM sales s JOIN users u ON u.id = s.created_by WHERE {live} GROUP BY u.email ORDER BY total DESC
            """, **p),
            # Margin of what was sold (returns not subtracted per product)
            "top_products": self._all(f"""
                SELECT p.id AS product_id, p.name AS product, SUM(i.quantity) AS quantity, SUM(i.line_total) AS total,
                       SUM(i.line_total - ROUND(i.quantity * i.unit_cost, 2)) AS margin
                FROM sale_items i JOIN sales s ON s.id = i.sale_id JOIN products p ON p.id = i.product_id
                WHERE {live} GROUP BY p.id, p.name ORDER BY total DESC LIMIT 10
            """, **p),
            "promotions": self._all(f"""
                SELECT pr.name, COUNT(*) AS lines, SUM(i.discount) AS discount_given
                FROM sale_items i JOIN sales s ON s.id = i.sale_id JOIN promotions pr ON pr.id = i.promotion_id
                WHERE {live} GROUP BY pr.name ORDER BY discount_given DESC
            """, **p),
        }

    def commit(self):
        self.session.commit()
