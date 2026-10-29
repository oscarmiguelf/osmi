"""Read-only reports: every report is one query over the operational tables (there is no reports schema).

Parameters every query may use: :branches (uuid[] already validated), :from / :to (UTC instants of local
midnights, [from, to)), :tz (IANA zone of the person), :limit / :offset (detail reports), plus the extras
each report declares. Definitions are the same everywhere so numbers reconcile:
  gross sales = SUM(sales.total) by sold_at; returns = SUM(sale_returns.refund_total) by the RETURN date;
  net = gross - returns; line net revenue = line_total * total / subtotal (sale discount pro-rata);
  COGS = quantity * sale_items.unit_cost (snapshot at sale time).
"""
import json

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.infrastructure.persistence.database import SessionLocal

from app.infrastructure.persistence.permissions import has_permission

LIVE = "s.deleted_at IS NULL AND s.branch_id = ANY(CAST(:branches AS uuid[])) AND s.sold_at >= :from AND s.sold_at < :to"
NET = "CASE WHEN s.subtotal = 0 THEN 0 ELSE {x} * s.total / s.subtotal END"  # spread the sale discount over its lines

# name -> sql, columns (key, type), range (needs from/to), paged (detail list), extras (required params)
CATALOG: dict[str, dict] = {
    # ----------------------------------------------------------------- sales
    "sales/summary": {
        "columns": [("period", "date"), ("tickets", "int"), ("gross_sales", "money"), ("discount", "money"), ("tax", "money"),
                    ("returns", "money"), ("net_sales", "money"), ("avg_ticket", "money")],
        "sql": f"""
            WITH s AS (
              SELECT date_trunc(:group, s.sold_at AT TIME ZONE :tz)::date AS period, COUNT(*) AS tickets,
                     SUM(s.discount) AS discount, SUM(s.total) AS gross_sales, SUM(s.tax_total) AS tax
              FROM sales s WHERE {LIVE} GROUP BY 1),
            r AS (
              SELECT date_trunc(:group, r.created_at AT TIME ZONE :tz)::date AS period, SUM(r.refund_total) AS returns
              FROM sale_returns r WHERE r.branch_id = ANY(CAST(:branches AS uuid[])) AND r.created_at >= :from AND r.created_at < :to
              GROUP BY 1)
            SELECT COALESCE(s.period, r.period) AS period, COALESCE(s.tickets, 0) AS tickets, COALESCE(s.gross_sales, 0) AS gross_sales,
                   COALESCE(s.discount, 0) AS discount, COALESCE(s.tax, 0) AS tax, COALESCE(r.returns, 0) AS returns,
                   COALESCE(s.gross_sales, 0) - COALESCE(r.returns, 0) AS net_sales,
                   CASE WHEN COALESCE(s.tickets, 0) = 0 THEN 0 ELSE ROUND(s.gross_sales / s.tickets, 2) END AS avg_ticket
            FROM s FULL JOIN r ON r.period = s.period ORDER BY 1
        """,
        "totals": ["tickets", "gross_sales", "discount", "tax", "returns", "net_sales"],
    },
    "sales/by-payment-method": {
        "columns": [("method", "method"), ("tickets", "int"), ("amount", "money"), ("refunded", "money"), ("net", "money")],
        "sql": f"""
            WITH paid AS (
              SELECT pm.description AS method, COUNT(DISTINCT p.sale_id) AS tickets, SUM(p.amount) AS amount
              FROM sale_payments p JOIN sales s ON s.id = p.sale_id JOIN payment_methods pm ON pm.id = p.payment_method_id
              WHERE p.kind = 'sale' AND {LIVE} GROUP BY pm.description),
            ref AS (
              SELECT pm.description AS method, SUM(rf.amount) AS refunded
              FROM sale_return_refunds rf JOIN sale_returns r ON r.id = rf.sale_return_id JOIN payment_methods pm ON pm.id = rf.payment_method_id
              WHERE r.branch_id = ANY(CAST(:branches AS uuid[])) AND r.created_at >= :from AND r.created_at < :to GROUP BY pm.description)
            SELECT COALESCE(paid.method, ref.method) AS method, COALESCE(paid.tickets, 0) AS tickets, COALESCE(paid.amount, 0) AS amount,
                   COALESCE(ref.refunded, 0) AS refunded, COALESCE(paid.amount, 0) - COALESCE(ref.refunded, 0) AS net
            FROM paid FULL JOIN ref ON ref.method = paid.method ORDER BY amount DESC
        """,
        "totals": ["tickets", "amount", "refunded", "net"],
    },
    "sales/by-seller": {
        "columns": [("seller", "text"), ("tickets", "int"), ("gross_sales", "money"), ("avg_ticket", "money"), ("returns", "money")],
        "sql": f"""
            SELECT TRIM(CONCAT(u.first_name, ' ', u.last_name)) AS seller, COUNT(*) AS tickets, SUM(s.total) AS gross_sales,
                   ROUND(AVG(s.total), 2) AS avg_ticket,
                   COALESCE((SELECT SUM(r.refund_total) FROM sale_returns r JOIN sales s2 ON s2.id = r.sale_id
                             WHERE s2.created_by = u.id AND r.branch_id = ANY(CAST(:branches AS uuid[]))
                               AND r.created_at >= :from AND r.created_at < :to), 0) AS returns
            FROM sales s JOIN users u ON u.id = s.created_by WHERE {LIVE}
            GROUP BY u.id ORDER BY gross_sales DESC
        """,
        "totals": ["tickets", "gross_sales", "returns"],
    },
    "sales/by-customer": {
        "columns": [("customer", "text"), ("tickets", "int"), ("gross_sales", "money"), ("avg_ticket", "money")],
        "sql": f"""
            SELECT COALESCE(cu.full_name, '—') AS customer, COUNT(*) AS tickets, SUM(s.total) AS gross_sales, ROUND(AVG(s.total), 2) AS avg_ticket
            FROM sales s LEFT JOIN customers cu ON cu.id = s.customer_id WHERE {LIVE}
            GROUP BY cu.id, cu.full_name ORDER BY gross_sales DESC LIMIT 100
        """,
        "totals": ["tickets", "gross_sales"],
    },
    "sales/by-category": {
        "columns": [("category", "text"), ("units", "number"), ("revenue", "money"), ("cogs", "money"), ("margin", "money")],
        "sql": f"""
            SELECT COALESCE(c.name, '—') AS category, SUM(i.quantity) AS units,
                   ROUND(SUM({NET.format(x='i.line_total')}), 2) AS revenue,
                   ROUND(SUM(i.quantity * i.unit_cost), 2) AS cogs,
                   ROUND(SUM({NET.format(x='(i.line_total - i.tax_amount)')}) - SUM(i.quantity * i.unit_cost), 2) AS margin
            FROM sale_items i JOIN sales s ON s.id = i.sale_id JOIN products p ON p.id = i.product_id
            LEFT JOIN categories c ON c.id = p.category_id WHERE {LIVE}
            GROUP BY 1 ORDER BY revenue DESC
        """,
        "totals": ["revenue", "cogs", "margin"],
    },
    "sales/top-products": {
        "columns": [("product", "text"), ("category", "text"), ("units", "number"), ("revenue", "money"), ("cogs", "money"),
                    ("margin", "money"), ("no_cost", "flag")],
        "sql": f"""
            WITH sold AS (
              SELECT i.product_id, SUM(i.quantity) AS units, SUM({NET.format(x='(i.line_total - i.tax_amount)')}) AS revenue,
                     SUM(i.quantity * i.unit_cost) AS cogs
              FROM sale_items i JOIN sales s ON s.id = i.sale_id WHERE {LIVE} GROUP BY i.product_id),
            ret AS (
              SELECT i.product_id, SUM(ri.quantity) AS units,
                     SUM(ri.refund_amount - ROUND(ri.refund_amount * i.tax_rate / (1 + i.tax_rate), 2)) AS refunded,
                     SUM(ri.quantity * i.unit_cost) AS cogs
              FROM sale_return_items ri JOIN sale_returns r ON r.id = ri.sale_return_id JOIN sale_items i ON i.id = ri.sale_item_id
              WHERE r.branch_id = ANY(CAST(:branches AS uuid[])) AND r.created_at >= :from AND r.created_at < :to GROUP BY i.product_id)
            SELECT p.name AS product, COALESCE(c.name, '—') AS category,
                   COALESCE(sold.units, 0) - COALESCE(ret.units, 0) AS units,
                   ROUND(COALESCE(sold.revenue, 0) - COALESCE(ret.refunded, 0), 2) AS revenue,
                   ROUND(COALESCE(sold.cogs, 0) - COALESCE(ret.cogs, 0), 2) AS cogs,
                   ROUND(COALESCE(sold.revenue, 0) - COALESCE(ret.refunded, 0) - COALESCE(sold.cogs, 0) + COALESCE(ret.cogs, 0), 2) AS margin,
                   p.cost = 0 AS no_cost
            FROM sold FULL JOIN ret ON ret.product_id = sold.product_id
            JOIN products p ON p.id = COALESCE(sold.product_id, ret.product_id)
            LEFT JOIN categories c ON c.id = p.category_id
            ORDER BY {{order}} LIMIT 100
        """,
        "totals": ["revenue", "cogs", "margin"],
    },
    "sales/hourly": {
        "columns": [("weekday", "weekday"), ("hour", "hour"), ("tickets", "int"), ("gross_sales", "money")],
        "sql": f"""
            SELECT EXTRACT(ISODOW FROM s.sold_at AT TIME ZONE :tz)::int AS weekday, EXTRACT(HOUR FROM s.sold_at AT TIME ZONE :tz)::int AS hour,
                   COUNT(*) AS tickets, SUM(s.total) AS gross_sales
            FROM sales s WHERE {LIVE} GROUP BY 1, 2 ORDER BY 1, 2
        """,
        "totals": ["tickets", "gross_sales"],
    },
    "sales/discounts": {
        "columns": [("kind", "discount_kind"), ("name", "text"), ("count", "int"), ("amount", "money")],
        "sql": f"""
            SELECT 'sale' AS kind, NULL AS name, COUNT(*) AS count, COALESCE(SUM(s.discount), 0) AS amount
              FROM sales s WHERE {LIVE} AND s.discount > 0
            UNION ALL
            SELECT 'line', NULL, COUNT(*), COALESCE(SUM(i.discount), 0)
              FROM sale_items i JOIN sales s ON s.id = i.sale_id WHERE {LIVE} AND i.promotion_id IS NULL AND i.discount > 0
            UNION ALL
            SELECT * FROM (SELECT 'promotion', pr.name, COUNT(*), SUM(i.discount)
              FROM sale_items i JOIN sales s ON s.id = i.sale_id JOIN promotions pr ON pr.id = i.promotion_id WHERE {LIVE}
              GROUP BY pr.name ORDER BY 4 DESC) promos
        """,
        "totals": ["count", "amount"],
    },
    "sales/returns": {
        "columns": [("folio", "text"), ("created_at", "datetime"), ("sale_folio", "text"), ("customer", "text"), ("refund_total", "money"),
                    ("reason", "text"), ("processed_by", "text")],
        "paged": True,
        "sql": """
            SELECT r.folio, r.created_at, s.folio AS sale_folio, COALESCE(cu.full_name, '—') AS customer, r.refund_total,
                   COALESCE(r.reason, '') AS reason, u.email AS processed_by
            FROM sale_returns r JOIN sales s ON s.id = r.sale_id JOIN users u ON u.id = r.created_by
            LEFT JOIN customers cu ON cu.id = s.customer_id
            WHERE r.branch_id = ANY(CAST(:branches AS uuid[])) AND r.created_at >= :from AND r.created_at < :to
            ORDER BY r.created_at DESC LIMIT :limit OFFSET :offset
        """,
    },
    "sales/tax": {
        "columns": [("tax", "text"), ("rate", "percent"), ("taxable_base", "money"), ("tax_amount", "money")],
        "sql": f"""
            SELECT r.name AS tax, i.tax_rate AS rate,
                   ROUND(SUM({NET.format(x='(i.line_total - i.tax_amount)')}), 2) AS taxable_base,
                   ROUND(SUM({NET.format(x='i.tax_amount')}), 2) AS tax_amount
            FROM sale_items i JOIN sales s ON s.id = i.sale_id JOIN tax_rates r ON r.id = i.tax_rate_id WHERE {LIVE}
            GROUP BY r.name, i.tax_rate ORDER BY i.tax_rate DESC
        """,
        "totals": ["taxable_base", "tax_amount"],
        # the official figure (per-sale rounding) next to the breakdown
        "extra_totals": f"SELECT COALESCE(SUM(s.tax_total), 0) AS official_tax FROM sales s WHERE {LIVE}",
    },
    "sales/pending-deliveries": {
        "columns": [("folio", "text"), ("sold_at", "datetime"), ("customer", "text"), ("product", "text"), ("quantity", "number"),
                    ("days_waiting", "int")],
        "range": False,
        "sql": """
            SELECT s.folio, s.sold_at, COALESCE(c.full_name, '—') AS customer, p.name AS product, rt.returnable_quantity AS quantity,
                   (CURRENT_DATE - (s.sold_at AT TIME ZONE :tz)::date) AS days_waiting
            FROM sale_items i
            JOIN sales s ON s.id = i.sale_id AND s.deleted_at IS NULL AND s.branch_id = ANY(CAST(:branches AS uuid[]))
            JOIN fulfillment_statuses f ON f.id = i.fulfillment_status_id AND f.name = 'RESERVED'
            JOIN sale_items_returnable rt ON rt.sale_item_id = i.id AND rt.returnable_quantity > 0
            JOIN products p ON p.id = i.product_id LEFT JOIN customers c ON c.id = s.customer_id
            ORDER BY s.sold_at
        """,
    },
    # ------------------------------------------------------------------ cash
    "cash/movements": {
        "columns": [("register", "text"), ("movement_type", "cash_type"), ("method", "method"), ("movements", "int"), ("total", "money")],
        "sql": """
            SELECT cr.name AS register, t.name AS movement_type, pm.description AS method, COUNT(*) AS movements, SUM(m.amount) AS total
            FROM cash_register_movements m
            JOIN cash_registers cr ON cr.id = m.cash_register_id AND cr.branch_id = ANY(CAST(:branches AS uuid[]))
            JOIN cash_movement_types t ON t.id = m.movement_type_id JOIN payment_methods pm ON pm.id = m.payment_method_id
            WHERE m.created_at >= :from AND m.created_at < :to
            GROUP BY cr.name, t.name, pm.description ORDER BY cr.name, t.name, pm.description
        """,
        "totals": ["movements", "total"],
    },
    "cash/cuts": {
        "columns": [("ended_at", "datetime"), ("register", "text"), ("performed_by", "text"), ("method", "method"),
                    ("expected", "money"), ("counted", "money"), ("difference", "money")],
        "paged": True,
        "sql": """
            SELECT c.ended_at, cr.name AS register, u.email AS performed_by, pm.description AS method,
                   d.expected_amount AS expected, d.final_amount AS counted, d.difference
            FROM cash_cuts c JOIN cash_registers cr ON cr.id = c.cash_register_id AND cr.branch_id = ANY(CAST(:branches AS uuid[]))
            JOIN cash_cut_details d ON d.cash_cut_id = c.id JOIN payment_methods pm ON pm.id = d.payment_method_id
            JOIN users u ON u.id = c.created_by
            WHERE c.ended_at >= :from AND c.ended_at < :to
            ORDER BY c.ended_at DESC, pm.description LIMIT :limit OFFSET :offset
        """,
    },
    "cash/balances": {
        "columns": [("branch", "text"), ("register", "text"), ("method", "method"), ("balance", "money")],
        "range": False,
        "sql": """
            SELECT b.name AS branch, cr.name AS register, pm.description AS method, cb.balance
            FROM cash_register_balances cb
            JOIN cash_registers cr ON cr.id = cb.cash_register_id AND cr.deleted_at IS NULL AND cr.branch_id = ANY(CAST(:branches AS uuid[]))
            JOIN branches b ON b.id = cr.branch_id JOIN payment_methods pm ON pm.id = cb.payment_method_id
            ORDER BY b.name, cr.name, pm.description
        """,
        "totals": ["balance"],
    },
    "cash/collections": {
        "columns": [("day", "date"), ("method", "method"), ("received_by", "text"), ("payments", "int"), ("amount", "money")],
        "sql": """
            SELECT (p.created_at AT TIME ZONE :tz)::date AS day, pm.description AS method, u.email AS received_by,
                   COUNT(*) AS payments, SUM(p.amount) AS amount
            FROM sale_payments p
            JOIN cash_registers cr ON cr.id = p.cash_register_id AND cr.branch_id = ANY(CAST(:branches AS uuid[]))
            JOIN payment_methods pm ON pm.id = p.payment_method_id JOIN users u ON u.id = p.created_by
            WHERE p.kind = 'credit_payment' AND p.created_at >= :from AND p.created_at < :to
            GROUP BY 1, 2, 3 ORDER BY 1, 2
        """,
        "totals": ["payments", "amount"],
    },
    # ---------------------------------------------------------------- credit
    "credit/receivables": {
        "columns": [("customer", "text"), ("credit_limit", "money"), ("owed", "money"), ("d0_30", "money"), ("d31_60", "money"),
                    ("d61_90", "money"), ("d90_plus", "money")],
        "range": False,
        "sql": """
            SELECT cu.full_name AS customer, cu.credit_limit, SUM(v.credit_outstanding) AS owed,
                   COALESCE(SUM(v.credit_outstanding) FILTER (WHERE NOW() - v.sold_at <= INTERVAL '30 days'), 0) AS d0_30,
                   COALESCE(SUM(v.credit_outstanding) FILTER (WHERE NOW() - v.sold_at > INTERVAL '30 days' AND NOW() - v.sold_at <= INTERVAL '60 days'), 0) AS d31_60,
                   COALESCE(SUM(v.credit_outstanding) FILTER (WHERE NOW() - v.sold_at > INTERVAL '60 days' AND NOW() - v.sold_at <= INTERVAL '90 days'), 0) AS d61_90,
                   COALESCE(SUM(v.credit_outstanding) FILTER (WHERE NOW() - v.sold_at > INTERVAL '90 days'), 0) AS d90_plus
            FROM sales_credit_pending v JOIN customers cu ON cu.id = v.customer_id
            WHERE v.branch_id = ANY(CAST(:branches AS uuid[])) AND v.credit_outstanding > 0
            GROUP BY cu.id ORDER BY owed DESC
        """,
        "totals": ["owed", "d0_30", "d31_60", "d61_90", "d90_plus"],
    },
    "credit/statement": {
        "columns": [("created_at", "datetime"), ("movement", "credit_type"), ("sale_folio", "text"), ("amount", "money"),
                    ("balance_after", "money")],
        "extras": ["customer_id"],
        "sql": """
            SELECT m.created_at, m.movement_type AS movement, s.folio AS sale_folio, m.amount, m.balance_after
            FROM customer_credit_movements m JOIN sales s ON s.id = m.sale_id AND s.branch_id = ANY(CAST(:branches AS uuid[]))
            WHERE m.customer_id = :customer_id AND m.created_at >= :from AND m.created_at < :to
            ORDER BY m.created_at, m.id
        """,
        "totals": ["amount"],
    },
    # ------------------------------------------------------------- inventory
    "inventory/valuation": {
        "columns": [("branch", "text"), ("category", "text"), ("units", "number"), ("value_at_cost", "money"), ("value_at_price", "money")],
        "range": False,
        "sql": """
            SELECT b.name AS branch, COALESCE(c.name, '—') AS category, SUM(s.current_stock) AS units,
                   ROUND(SUM(s.current_stock * p.cost), 2) AS value_at_cost, ROUND(SUM(s.current_stock * p.price), 2) AS value_at_price
            FROM product_stock s JOIN products p ON p.id = s.product_id AND p.deleted_at IS NULL
            JOIN branches b ON b.id = s.branch_id LEFT JOIN categories c ON c.id = p.category_id
            WHERE s.deleted_at IS NULL AND s.branch_id = ANY(CAST(:branches AS uuid[])) AND s.current_stock <> 0
            GROUP BY b.name, c.name ORDER BY b.name, value_at_cost DESC
        """,
        "totals": ["value_at_cost", "value_at_price"],
    },
    "inventory/low-stock": {
        "columns": [("branch", "text"), ("product", "text"), ("current_stock", "number"), ("min_stock", "number")],
        "range": False,
        "sql": """
            SELECT branch_name AS branch, name AS product, current_stock, min_stock FROM products_with_stock
            WHERE branch_id = ANY(CAST(:branches AS uuid[])) AND is_low_stock ORDER BY branch_name, name
        """,
    },
    "inventory/slow-movers": {
        "columns": [("product", "text"), ("branch", "text"), ("current_stock", "number"), ("value_at_cost", "money"), ("last_sale", "datetime")],
        "range": False,
        "paged": True,
        "extras": ["days"],
        "sql": """
            SELECT p.name AS product, b.name AS branch, s.current_stock, ROUND(s.current_stock * p.cost, 2) AS value_at_cost,
                   (SELECT MAX(m.created_at) FROM inventory_movements m JOIN inventory_movement_types t ON t.id = m.movement_type_id AND t.name = 'Sale'
                     WHERE m.product_id = p.id AND m.branch_id = s.branch_id) AS last_sale
            FROM product_stock s JOIN products p ON p.id = s.product_id AND p.deleted_at IS NULL JOIN branches b ON b.id = s.branch_id
            WHERE s.deleted_at IS NULL AND s.branch_id = ANY(CAST(:branches AS uuid[])) AND s.current_stock > 0
              AND NOT EXISTS (SELECT 1 FROM inventory_movements m JOIN inventory_movement_types t ON t.id = m.movement_type_id AND t.name = 'Sale'
                              WHERE m.product_id = p.id AND m.branch_id = s.branch_id AND m.created_at >= NOW() - make_interval(days => :days))
            ORDER BY s.current_stock * p.cost DESC LIMIT :limit OFFSET :offset
        """,
    },
    "inventory/movements": {
        "columns": [("movement_type", "inventory_type"), ("movements", "int"), ("net_units", "number"), ("net_value_at_cost", "money")],
        "sql": """
            SELECT t.name AS movement_type, COUNT(*) AS movements, SUM(m.quantity) AS net_units, ROUND(SUM(m.quantity * p.cost), 2) AS net_value_at_cost
            FROM inventory_movements m JOIN inventory_movement_types t ON t.id = m.movement_type_id JOIN products p ON p.id = m.product_id
            WHERE m.branch_id = ANY(CAST(:branches AS uuid[])) AND m.created_at >= :from AND m.created_at < :to
            GROUP BY t.name ORDER BY t.name
        """,
        "totals": ["movements", "net_value_at_cost"],
    },
    "inventory/shrinkage": {
        "columns": [("product", "text"), ("units_lost", "number"), ("cost_lost", "money")],
        "sql": """
            SELECT p.name AS product, SUM(-m.quantity) AS units_lost, ROUND(SUM(-m.quantity * p.cost), 2) AS cost_lost
            FROM inventory_movements m JOIN products p ON p.id = m.product_id
            JOIN inventory_movement_types t ON t.id = m.movement_type_id AND t.name = 'Adjustment'
            WHERE m.branch_id = ANY(CAST(:branches AS uuid[])) AND m.created_at >= :from AND m.created_at < :to AND m.quantity < 0
            GROUP BY p.name ORDER BY cost_lost DESC LIMIT 100
        """,
        "totals": ["cost_lost"],
    },
    "inventory/kardex": {
        "columns": [("created_at", "datetime"), ("branch", "text"), ("movement_type", "inventory_type"), ("quantity", "signed"),
                    ("stock_after", "number"), ("user", "text"), ("reference", "text")],
        "paged": True,
        "extras": ["product_id"],
        "sql": """
            SELECT m.created_at, b.name AS branch, t.name AS movement_type, m.quantity, m.stock_after, u.email AS user,
                   COALESCE(m.reference, m.notes, '') AS reference
            FROM inventory_movements m JOIN inventory_movement_types t ON t.id = m.movement_type_id
            JOIN branches b ON b.id = m.branch_id JOIN users u ON u.id = m.created_by
            WHERE m.product_id = :product_id AND m.branch_id = ANY(CAST(:branches AS uuid[])) AND m.created_at >= :from AND m.created_at < :to
            ORDER BY m.created_at DESC, m.id DESC LIMIT :limit OFFSET :offset
        """,
    },
    "inventory/stocktakes": {
        "columns": [("folio", "text"), ("closed_at", "datetime"), ("counted", "int"), ("with_difference", "int"),
                    ("surplus_value", "money"), ("shortage_value", "money"), ("net_value", "money")],
        "sql": """
            SELECT s.folio, s.closed_at, COUNT(i.id) AS counted, COUNT(i.id) FILTER (WHERE i.applied_adjustment <> 0) AS with_difference,
                   COALESCE(ROUND(SUM(i.applied_adjustment * p.cost) FILTER (WHERE i.applied_adjustment > 0), 2), 0) AS surplus_value,
                   COALESCE(ROUND(SUM(-i.applied_adjustment * p.cost) FILTER (WHERE i.applied_adjustment < 0), 2), 0) AS shortage_value,
                   COALESCE(ROUND(SUM(i.applied_adjustment * p.cost), 2), 0) AS net_value
            FROM stocktakes s LEFT JOIN stocktake_items i ON i.stocktake_id = s.id AND i.deleted_at IS NULL
            LEFT JOIN products p ON p.id = i.product_id
            WHERE s.status = 'COMPLETED' AND s.branch_id = ANY(CAST(:branches AS uuid[])) AND s.closed_at >= :from AND s.closed_at < :to
            GROUP BY s.id ORDER BY s.closed_at DESC
        """,
        "totals": ["surplus_value", "shortage_value", "net_value"],
    },
    "inventory/transfers": {
        "columns": [("from_branch", "text"), ("to_branch", "text"), ("status", "transfer_status"), ("transfers", "int")],
        "sql": """
            SELECT fb.name AS from_branch, tb.name AS to_branch, st.name AS status, COUNT(*) AS transfers
            FROM transfers t JOIN transfer_statuses st ON st.id = t.status_id
            JOIN branches fb ON fb.id = t.from_branch_id JOIN branches tb ON tb.id = t.to_branch_id
            WHERE (t.from_branch_id = ANY(CAST(:branches AS uuid[])) OR t.to_branch_id = ANY(CAST(:branches AS uuid[])))
              AND t.created_at >= :from AND t.created_at < :to
            GROUP BY fb.name, tb.name, st.name ORDER BY fb.name, tb.name, st.name
        """,
        "totals": ["transfers"],
    },
    # ------------------------------------------------------------- purchases
    "purchases/by-supplier": {
        "columns": [("supplier", "text"), ("purchases", "int"), ("total", "money")],
        "sql": """
            SELECT COALESCE(s.name, '—') AS supplier, COUNT(*) AS purchases, SUM(pu.total) AS total
            FROM purchases pu LEFT JOIN suppliers s ON s.id = pu.supplier_id
            WHERE pu.deleted_at IS NULL AND pu.branch_id = ANY(CAST(:branches AS uuid[])) AND pu.purchased_at >= :from AND pu.purchased_at < :to
            GROUP BY s.name ORDER BY total DESC
        """,
        "totals": ["purchases", "total"],
    },
    "purchases/by-product": {
        "columns": [("product", "text"), ("units", "number"), ("total", "money"), ("avg_cost", "money"), ("last_cost", "money"),
                    ("current_cost", "money")],
        "sql": """
            SELECT p.name AS product, SUM(i.quantity) AS units, SUM(i.line_total) AS total,
                   ROUND(SUM(i.line_total) / NULLIF(SUM(i.quantity), 0), 2) AS avg_cost,
                   (ARRAY_AGG(i.unit_cost ORDER BY pu.purchased_at DESC))[1] AS last_cost, p.cost AS current_cost
            FROM purchase_items i JOIN purchases pu ON pu.id = i.purchase_id AND pu.deleted_at IS NULL JOIN products p ON p.id = i.product_id
            WHERE pu.branch_id = ANY(CAST(:branches AS uuid[])) AND pu.purchased_at >= :from AND pu.purchased_at < :to
            GROUP BY p.id ORDER BY total DESC LIMIT 200
        """,
        "totals": ["total"],
    },
    "purchases/cost-history": {
        "columns": [("day", "date"), ("supplier", "text"), ("quantity", "number"), ("unit_cost", "money")],
        "extras": ["product_id"],
        "sql": """
            SELECT (pu.purchased_at AT TIME ZONE :tz)::date AS day, COALESCE(s.name, '—') AS supplier, i.quantity, i.unit_cost
            FROM purchase_items i JOIN purchases pu ON pu.id = i.purchase_id AND pu.deleted_at IS NULL LEFT JOIN suppliers s ON s.id = pu.supplier_id
            WHERE i.product_id = :product_id AND pu.branch_id = ANY(CAST(:branches AS uuid[])) AND pu.purchased_at >= :from AND pu.purchased_at < :to
            ORDER BY pu.purchased_at
        """,
    },
    # ----------------------------------------------------------------- admin
    "admin/login-events": {
        "columns": [("event", "login_event"), ("count", "int")],
        "admin": True,
        "sql": "SELECT event_type AS event, COUNT(*) AS count FROM login_audit WHERE created_at >= :from AND created_at < :to GROUP BY 1 ORDER BY 2 DESC",
        "totals": ["count"],
    },
    "admin/exports": {
        "columns": [("created_at", "datetime"), ("user", "text"), ("report", "report_name"), ("format", "text"), ("row_count", "int"),
                    ("branches", "text")],
        "admin": True,
        "paged": True,
        "sql": """
            SELECT e.created_at, u.email AS user, e.report, UPPER(e.format) AS format, e.row_count,
                   (SELECT STRING_AGG(b.name, ', ' ORDER BY b.name) FROM branches b
                     WHERE b.id::text IN (SELECT JSONB_ARRAY_ELEMENTS_TEXT(e.parameters -> 'branch_ids'))) AS branches
            FROM report_exports e JOIN users u ON u.id = e.user_id
            WHERE e.created_at >= :from AND e.created_at < :to
            ORDER BY e.created_at DESC LIMIT :limit OFFSET :offset
        """,
    },
    "admin/failed-logins": {
        "columns": [("created_at", "datetime"), ("email", "text"), ("event", "login_event"), ("ip", "text")],
        "admin": True,
        "paged": True,
        "sql": """
            SELECT created_at, email_attempted AS email, event_type AS event, HOST(ip_address) AS ip FROM login_audit
            WHERE event_type IN ('login_failed', 'account_locked', 'token_reuse_detected') AND created_at >= :from AND created_at < :to
            ORDER BY created_at DESC LIMIT :limit OFFSET :offset
        """,
    },
}

TOP_ORDER = {"revenue": "revenue", "units": "units", "margin": "margin"}  # whitelisted ORDER BY for top products


class SqlReportRepository:
    def __init__(self, session: Session):
        self.session = session
        self.session.execute(text("SET TRANSACTION READ ONLY"))  # reports never write

    def spec(self, name):
        """What a report needs and returns (everything but its SQL), or None when there's no such report."""
        spec = CATALOG.get(name)
        return None if spec is None else {k: v for k, v in spec.items() if k not in ("sql", "extra_totals")}

    def names(self):
        return list(CATALOG)

    def has_permission(self, user_id, module, permission):
        return has_permission(self.session, user_id, module, permission)

    def timezone(self, user_id):
        return self.session.execute(text("SELECT timezone FROM users WHERE id = :id"), {"id": user_id}).scalar() or "UTC"

    def user_branches(self, user_id, branch_ids):
        """The requested branches the person belongs to (the rest are refused by the caller)."""
        rows = self.session.execute(text("""
            SELECT id FROM branches WHERE id = ANY(CAST(:ids AS uuid[])) AND deleted_at IS NULL AND fn_user_in_branch(:uid, id)
        """), {"ids": branch_ids, "uid": user_id})
        return {r.id for r in rows}

    def run(self, name, params, order=None):
        spec = CATALOG[name]
        sql = spec["sql"]
        if "{order}" in sql:
            column, direction = order
            sql = sql.replace("{order}", f"{TOP_ORDER[column]} {'ASC' if direction == 'asc' else 'DESC'}, product")
        rows = [dict(r) for r in self.session.execute(text(sql), params).mappings()]
        extra = dict(self.session.execute(text(spec["extra_totals"]), params).mappings().first()) if spec.get("extra_totals") else {}
        return rows, extra

    def record_export(self, user_id, report, fmt, parameters, row_count):
        """Its own short write transaction: the report itself runs read-only."""
        with SessionLocal() as w:
            w.execute(text("""
                INSERT INTO report_exports (user_id, report, format, parameters, row_count)
                VALUES (:u, :r, :f, CAST(:p AS jsonb), :n)
            """), {"u": user_id, "r": report, "f": fmt, "p": json.dumps(parameters, default=str), "n": row_count})
            w.commit()

    def security_events(self, hours):
        """Locked accounts, stolen refresh tokens caught (reuse) and failed sign-ins in the last `hours`."""
        return dict(self.session.execute(text("""
            SELECT COUNT(*) FILTER (WHERE event_type = 'account_locked') AS locked,
                   COUNT(*) FILTER (WHERE event_type = 'token_reuse_detected') AS token_reuse,
                   COUNT(*) FILTER (WHERE event_type = 'login_failed') AS failed
            FROM login_audit WHERE created_at > NOW() - make_interval(hours => :h)
        """), {"h": hours}).mappings().one())

    def dashboard(self, branches, days, tz):
        """Tickets / net sales / average for each [start, end) in days, plus a few counters of right now."""
        out = {"periods": []}
        for start, end in days:
            p = {"branches": branches, "from": start, "to": end}
            sold = self.session.execute(text(f"""
                SELECT COUNT(*) AS tickets, COALESCE(SUM(s.total), 0) AS gross FROM sales s WHERE {LIVE}
            """), p).mappings().first()
            returns = self.session.execute(text("""
                SELECT COALESCE(SUM(refund_total), 0) FROM sale_returns
                WHERE branch_id = ANY(CAST(:branches AS uuid[])) AND created_at >= :from AND created_at < :to
            """), p).scalar()
            out["periods"].append({"tickets": sold["tickets"], "gross_sales": sold["gross"], "returns": returns,
                                   "net_sales": sold["gross"] - returns,
                                   "avg_ticket": round(sold["gross"] / sold["tickets"], 2) if sold["tickets"] else 0})
        p = {"branches": branches, "from": days[0][0], "to": days[0][1], "tz": tz}
        out["top_products"] = [dict(r) for r in self.session.execute(text(f"""
            SELECT p.name AS product, SUM(i.quantity) AS units, ROUND(SUM({NET.format(x='i.line_total')}), 2) AS revenue
            FROM sale_items i JOIN sales s ON s.id = i.sale_id JOIN products p ON p.id = i.product_id WHERE {LIVE}
            GROUP BY p.name ORDER BY revenue DESC LIMIT 5
        """), p).mappings()]
        out["cash"] = [dict(r) for r in self.session.execute(text("""
            SELECT pm.description AS method, SUM(cb.balance) AS balance FROM cash_register_balances cb
            JOIN cash_registers cr ON cr.id = cb.cash_register_id AND cr.deleted_at IS NULL AND cr.branch_id = ANY(CAST(:branches AS uuid[]))
            JOIN payment_methods pm ON pm.id = cb.payment_method_id GROUP BY pm.description ORDER BY pm.description
        """), p).mappings()]
        out["low_stock"] = self.session.execute(text(
            "SELECT COUNT(*) FROM products_with_stock WHERE branch_id = ANY(CAST(:branches AS uuid[])) AND is_low_stock"), p).scalar()
        out["credit_pending"] = self.session.execute(text("""
            SELECT COALESCE(SUM(credit_outstanding), 0) FROM sales_credit_pending WHERE branch_id = ANY(CAST(:branches AS uuid[]))
        """), p).scalar()
        return out
