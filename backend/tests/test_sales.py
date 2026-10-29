# Integration test against the real DB: sales, payments, credit, deliveries and returns on a throwaway branch.
# docker compose run --rm -v ./tests:/code/tests api sh -c "pip install -q pytest httpx && python -m pytest -q tests"
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.application.sale_pricing import price_sale, promotion_discount
from app.infrastructure.persistence.database import SessionLocal
from tests.test_calendar import ADMIN, A, client
from tests.test_cash import _release_current
from tests.test_customers import _phone

D = lambda v: Decimal(str(v))  # noqa: E731


def test_pricing_rules():
    assert promotion_discount({"kind": "PERCENT", "percent": D(10)}, D(2), D(116)) == D("23.20")
    assert promotion_discount({"kind": "AMOUNT", "amount": D(500)}, D(1), D(116)) == 116  # never more than the line
    assert promotion_discount({"kind": "BUY_X_GET_Y", "buy_quantity": 2, "get_quantity": 1}, D(7), D(10)) == 20  # 3x2: 2 free
    p = price_sale([{"quantity": D(2), "unit_price": D(116), "discount": D("23.20"), "tax_rate": D("0.16")},
                    {"quantity": D("1.5"), "unit_price": D("50.50"), "discount": D(0), "tax_rate": D("0.16")},
                    {"quantity": D(1), "unit_price": D(200), "discount": D(0), "tax_rate": D("0.16")}], D("4.55"))
    assert (p["subtotal"], p["total"], p["tax_total"]) == (D("484.55"), D("480.00"), D("66.21"))
    assert [l["tax_amount"] for l in p["lines"]] == [D("28.80"), D("10.45"), D("27.59")]


def _seed(path, name):
    return next(i for i in client.get(path, headers=A).json() if i["name"] == name)["id"]


@pytest.fixture
def env():
    mine = _release_current(A)  # the admin's own open register: back to them at the end
    tag = secrets.token_hex(3).upper()
    branch = client.post("/branches", json={"name": f"Ventas {tag}", "code": f"V{tag}"}, headers=A).json()["id"]
    H = {**A, "X-Branch-Id": branch}
    register = client.post("/cash-registers", json={"name": "Caja ventas"}, headers=H).json()["id"]
    unit, kg = _seed("/units", "Unit"), _seed("/units", "kg")
    types = {n: _seed("/product-types", n) for n in ("Product", "Service", "Kit")}
    new = lambda name, ptype, price, u=unit: client.post("/products", json={
        "name": f"{name} {tag}", "product_type_id": types[ptype], "unit_of_measure_id": u, "price": price}, headers=A).json()
    p = {"hammer": new("Martillo", "Product", 116), "nails": new("Clavo", "Product", "50.50", kg),
         "install": new("Instalación", "Service", 200), "kit": new("Kit obra", "Kit", 300)}
    client.put(f"/products/{p['kit']['id']}/kit-components", json={"components": [{"product_id": p["hammer"]["id"], "quantity": 2}]}, headers=A)
    client.post("/purchases", json={"items": [{"product_id": p["hammer"]["id"], "quantity": 10, "unit_cost": 60},
                                              {"product_id": p["nails"]["id"], "quantity": "5.5", "unit_cost": 20}]}, headers=H)
    customer = client.post("/customers", json={"full_name": f"Cliente {tag}", "phone": _phone(), "credit_limit": 1000}, headers=A).json()
    with SessionLocal() as s:
        promo = s.execute(text("""
            INSERT INTO promotions (name, kind, percent, starts_at, ends_at, created_by, updated_by)
            VALUES (:n, 'PERCENT', 10, NOW() - INTERVAL '1 hour', NOW() + INTERVAL '1 day', :u, :u) RETURNING id
        """), {"n": f"10% martillo {tag}", "u": ADMIN}).scalar()
        s.execute(text("INSERT INTO promotion_products (promotion_id, product_id, created_by, updated_by) VALUES (:pr, :p, :u, :u)"),
                  {"pr": promo, "p": p["hammer"]["id"], "u": ADMIN})
        s.commit()
    methods = {m["description"]: m["id"] for m in client.get("/payment-methods", headers=A).json()}
    yield {"tag": tag, "H": H, "register": register, "p": p, "customer": customer, "promo": str(promo), "m": methods}
    _release_current(A)
    if mine:
        client.post(f"/cash-registers/{mine['cash_register_id']}/occupy", headers={**A, "X-Branch-Id": mine["branch_id"]})
    for prod in (p["hammer"], p["nails"]):  # empty the branch so it can be deleted, even after a failure
        left = D(client.get(f"/products/{prod['id']}", headers=H).json()["current_stock"])
        if left:
            client.post("/inventory/adjustments", json={"product_id": prod["id"], "quantity": str(-left), "notes": "Limpieza test"}, headers=H)
    with SessionLocal() as s:
        s.execute(text("UPDATE promotions SET deleted_at = NOW(), deleted_by = :u, updated_by = :u WHERE id = :id"), {"u": ADMIN, "id": promo})
        s.commit()
    for prod in p.values():
        client.delete(f"/products/{prod['id']}", headers=A)
    client.delete(f"/customers/{customer['id']}", headers=A)
    client.delete(f"/cash-registers/{register}", headers=H)
    client.delete(f"/branches/{branch}", headers=A)


def test_sales_flow(env):
    H, p, m, cust = env["H"], env["p"], env["m"], env["customer"]
    stock = lambda key: D(client.get(f"/products/{p[key]['id']}", headers=H).json()["current_stock"])
    owed = lambda: D(client.get(f"/customers/{cust['id']}/credit", headers=A).json()["balance"])
    cart = {"discount": "4.55", "items": [
        {"product_id": p["hammer"]["id"], "quantity": 2, "promotion_id": env["promo"]},
        {"product_id": p["nails"]["id"], "quantity": "1.5"},
        {"product_id": p["install"]["id"], "quantity": 1},
    ]}
    pay = [{"payment_method_id": m["Cash"], "amount": 300, "amount_tendered": 500},
           {"payment_method_id": m["Card"], "amount": 180, "reference": "AUTH-889123"}]

    # A register first
    r = client.post("/sales", json={**cart, "payments": pay}, headers=H)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "register"
    client.post(f"/cash-registers/{env['register']}/occupy", headers=H)

    # Preview = what will be saved (the DB re-checks the same math at commit)
    pv = client.post("/sales/preview", json={**cart, "payments": pay[:1]}, headers=H).json()
    assert (D(pv["total"]), D(pv["tax_total"]), D(pv["remaining"]), D(pv["change"])) == (480, D("66.21"), 180, 200)
    assert D(pv["lines"][0]["discount"]) == D("23.20") and pv["lines"][0]["promotion"].startswith("10%")
    assert any(a["product_id"] == p["hammer"]["id"] for a in client.get("/promotions/active", headers=H).json())

    # Validation before the DB
    bad = lambda body: client.post("/sales", json=body, headers=H)
    assert bad({**cart, "payments": pay[:1]}).json()["detail"]["field"] == "payments"  # don't add up
    assert bad({"items": [{"product_id": p["hammer"]["id"], "quantity": "1.5"}]}).json()["detail"]["field"] == "items.0.quantity"
    r = bad({"items": [{"product_id": p["hammer"]["id"], "quantity": 100}], "payments": [{"payment_method_id": m["Cash"], "amount": 11600}]})
    assert r.status_code == 422 and D(r.json()["detail"]["products"][0]["available"]) == 10
    one = {"items": [{"product_id": p["install"]["id"], "quantity": 1}]}
    assert bad({"items": [{"product_id": p["install"]["id"], "quantity": 1, "unit_price": 150}]}).json()["detail"]["field"] == "items.0.unit_price"
    assert bad({**one, "payments": [{"payment_method_id": m["Credit"], "amount": 200}]}).json()["detail"]["field"] == "customer_id"
    assert bad({"items": [{"product_id": p["hammer"]["id"], "quantity": 1, "promotion_id": env["promo"], "discount": 1}]}).status_code == 422
    assert bad({"customer_id": cust["id"], "items": [{"product_id": p["install"]["id"], "quantity": 6}],
                "payments": [{"payment_method_id": m["Credit"], "amount": 200}]}).json()["detail"]["field"] == "payments"  # 1200 total

    # Mixed payment sale
    sale_id = str(uuid.uuid4())
    sale = client.post("/sales", json={"id": sale_id, **cart, "payments": pay}, headers=H)
    assert sale.status_code == 201
    sale = sale.json()
    assert sale["status"] == "PAID" and sale["folio"].endswith("000001") and D(sale["tax_total"]) == D("66.21")
    assert D(next(x for x in sale["payments"] if x["method"] == "Cash")["change_given"]) == 200
    assert (stock("hammer"), stock("nails")) == (8, 4)
    assert client.post("/sales", json={"id": sale_id, **cart, "payments": pay}, headers=H).json()["folio"] == sale["folio"]  # retry
    assert (stock("hammer"), stock("nails")) == (8, 4)  # and no second sale
    assert client.get(f"/sales/by-folio/{sale['folio'].lower()}", headers=H).json()["id"] == sale_id
    assert client.get(f"/sales/{sale_id}/ticket", headers=H).json()["tax_breakdown"][0]["tax_name"]

    # Credit sale with a reserved kit (takes 2 hammers out now)
    def kit_sale(credit):  # kit price 300: the rest in cash
        payments = [{"payment_method_id": m["Credit"], "amount": credit}]
        if credit < 300:
            payments.append({"payment_method_id": m["Cash"], "amount": 300 - credit})
        return client.post("/sales", json={"customer_id": cust["id"], "payments": payments,
                                           "items": [{"product_id": p["kit"]["id"], "quantity": 1, "fulfillment": "RESERVED"}]}, headers=H)
    r = client.post("/sales", json={"customer_id": cust["id"], "items": [{"product_id": p["install"]["id"], "quantity": 6}],
                                    "payments": [{"payment_method_id": m["Credit"], "amount": 1200}]}, headers=H)
    assert r.status_code == 422 and D(r.json()["detail"]["available"]) == 1000  # over the limit
    credit_sale = kit_sale(200).json()
    assert credit_sale["status"] == "PENDING" and D(credit_sale["credit_outstanding"]) == 200 and owed() == 200
    assert stock("hammer") == 6

    # Delivery
    item = credit_sale["items"][0]["id"]
    assert [d["sale_item_id"] for d in client.get("/sales/pending-deliveries", headers=H).json()] == [item]
    assert client.post(f"/sales/{credit_sale['id']}/deliver", json={"sale_item_ids": [item]}, headers=H).json()["items"][0]["fulfillment"] == "DELIVERED"
    assert client.post(f"/sales/{credit_sale['id']}/deliver", json={"sale_item_ids": [item]}, headers=H).status_code == 409

    # Abonos: one sale, then a customer payment spread oldest first
    abono = lambda amount, **kw: client.post(f"/sales/{credit_sale['id']}/payments", json={"payment_method_id": m["Cash"], "amount": amount, **kw}, headers=H)
    assert abono(50).json()["credit_outstanding"] == 150
    assert abono(500).json()["detail"]["outstanding"] == 150
    assert client.post(f"/sales/{credit_sale['id']}/payments", json={"payment_method_id": m["Credit"], "amount": 1}, headers=H).status_code == 422
    assert [s["sale_id"] for s in client.get("/sales/pending-credit", headers=H).json()] == [credit_sale["id"]]
    r = client.post("/sales/credit-payments", json={"customer_id": cust["id"], "payment_method_id": m["Cash"], "amount": 150,
                                                    "amount_tendered": 200}, headers=H).json()
    assert D(r["change"]) == 50 and D(r["owed_after"]) == 0 and owed() == 0
    assert client.get(f"/sales/{credit_sale['id']}", headers=H).json()["status"] == "PAID"

    # Partial return, then the rest
    hammer_item = next(i["id"] for i in sale["items"] if i["product_id"] == p["hammer"]["id"])
    pv = client.post(f"/sales/{sale_id}/returns/preview", json={"items": [{"sale_item_id": hammer_item, "quantity": 1}]}, headers=H).json()
    assert D(pv["refund_total"]) == D("103.42") and D(pv["credit_refund"]) == 0 and not pv["completes_sale"]
    ret = client.post(f"/sales/{sale_id}/returns", json={"items": [{"sale_item_id": hammer_item, "quantity": 1}], "reason": "No sirvió",
                                                         "refunds": [{"payment_method_id": m["Cash"], "amount": "103.42"}]}, headers=H)
    assert ret.status_code == 201 and ret.json()["folio"].endswith("R000001") and stock("hammer") == 7
    assert client.post(f"/sales/{sale_id}/returns", json={"items": [{"sale_item_id": hammer_item, "quantity": 2}]}, headers=H).json()["detail"]["returnable"] == 1
    rest = [{"sale_item_id": i["id"], "quantity": i["returnable_quantity"]} for i in client.get(f"/sales/{sale_id}", headers=H).json()["items"]]
    r = client.post(f"/sales/{sale_id}/returns", json={"items": rest, "refunds": [{"payment_method_id": m["Cash"], "amount": 1}]}, headers=H)
    assert D(r.json()["detail"]["refund_total"]) == D("376.58")  # 480 - 103.42
    r = client.post(f"/sales/{sale_id}/returns", json={"items": rest, "refunds": [{"payment_method_id": m["Cash"], "amount": "376.58"}]}, headers=H)
    assert r.status_code == 201
    done = client.get(f"/sales/{sale_id}", headers=H).json()
    assert done["status"] == "RETURNED" and (stock("hammer"), stock("nails")) == (8, D("5.5"))
    assert client.post(f"/sales/{sale_id}/returns", json={"items": rest}, headers=H).status_code == 409

    # Returning an unpaid credit sale cancels the debt (the Credit refund is added for you)
    c2 = kit_sale(300).json()
    assert owed() == 300
    r = client.post(f"/sales/{c2['id']}/returns", json={"items": [{"sale_item_id": c2["items"][0]["id"], "quantity": 1}]}, headers=H)
    assert r.status_code == 201 and r.json()["refunds"][0]["is_credit"] and owed() == 0
    assert client.get(f"/sales/{c2['id']}", headers=H).json()["status"] == "RETURNED" and stock("hammer") == 8

    # Lists, history, report
    assert len(client.get("/sales", params={"status": "RETURNED"}, headers=H).json()["items"]) == 2
    assert len(client.get("/returns", headers=H).json()["items"]) == 3
    h = client.get(f"/sales/{credit_sale['id']}/history", headers=H).json()
    assert [x["to_status"] for x in h["status"]] == ["PENDING", "PAID"] and h["fulfillment"][-1]["to_status"] == "DELIVERED"
    now = datetime.now(timezone.utc)
    rep = client.get("/sales/report", params={"from": (now - timedelta(hours=1)).isoformat(), "to": (now + timedelta(hours=1)).isoformat()}, headers=H).json()
    assert rep["totals"]["sales"] == 3 and D(rep["totals"]["total"]) == 1080 and D(rep["totals"]["returns"]) == 780
    assert D(rep["totals"]["net"]) == 300 and rep["promotions"][0]["lines"] == 1
