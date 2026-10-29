# Integration test: packages (sessions of a service) and memberships (validity + price list), sold and used at the POS.
import secrets
from datetime import datetime, timezone
from decimal import Decimal

from tests.test_calendar import A, B, client
from tests.test_purchases import _seed

D = lambda v: Decimal(str(v))  # noqa: E731


def test_packages_and_memberships():
    tag = secrets.token_hex(3)
    mine = client.get("/cash-sessions/current", headers=A)
    mine = mine.json() if mine.status_code == 200 else None
    if mine:
        client.post(f"/cash-registers/{mine['cash_register_id']}/release", headers={**A, "X-Branch-Id": mine["branch_id"]})
    branch = client.post("/branches", json={"name": f"Spa {tag}", "code": f"S{tag[:4]}".upper()}, headers=A).json()["id"]
    H = {**A, "X-Branch-Id": branch}
    reg = client.post("/cash-registers", json={"name": f"Caja {tag}"}, headers=H).json()["id"]
    client.post(f"/cash-registers/{reg}/occupy", headers=H)
    stype, sunit, ptype, unit = _seed("/product-types", "Service"), _seed("/units", "Service"), _seed("/product-types", "Product"), _seed("/units", "Unit")
    mk = lambda name, price, t=stype, u=sunit, **kw: client.post("/products", json={"name": f"{name} {tag}", "product_type_id": t,
                                                                                 "unit_of_measure_id": u, "price": price, **kw}, headers=H).json()
    massage, pack, member = mk("Masaje", 500), mk("Paquete 5 masajes", 2000), mk("Membresía mensual", 300)
    oil = mk("Aceite", 100, ptype, unit, initial_stock=5)
    vip = client.post("/price-lists", json={"name": f"VIP {tag}", "percent": -20}, headers=A).json()
    cust = client.post("/customers", json={"full_name": f"Socia {tag}", "phone": "55" + str(secrets.randbelow(10**8)).zfill(8)}, headers=A).json()
    other = client.post("/customers", json={"full_name": f"Otra {tag}", "phone": "55" + str(secrets.randbelow(10**8)).zfill(8)}, headers=A).json()
    cash = next(m["id"] for m in client.get("/payment-methods", headers=A).json() if m["description"] == "Cash")
    sell = lambda items, customer=cust["id"], amount=None: client.post("/sales", json={"customer_id": customer, "items": items,
        **({"payments": [{"payment_method_id": cash, "amount": amount}]} if amount is not None else {})}, headers=H)
    try:
        # Configure: a package needs a service; only service-type products; products.prices
        assert client.put(f"/products/{pack['id']}/benefit", json={"kind": "package", "service_product_id": massage["id"], "sessions": 5}, headers=B).status_code == 403
        assert client.put(f"/products/{oil['id']}/benefit", json={"kind": "membership", "valid_days": 30}, headers=A).status_code == 422
        assert client.put(f"/products/{pack['id']}/benefit", json={"kind": "package", "service_product_id": oil["id"], "sessions": 5}, headers=A).status_code == 422
        client.put(f"/products/{pack['id']}/benefit", json={"kind": "package", "service_product_id": massage["id"], "sessions": 5, "valid_days": 180}, headers=A)
        client.put(f"/products/{member['id']}/benefit", json={"kind": "membership", "valid_days": 30, "price_list_id": vip["id"]}, headers=A)
        assert client.get(f"/products/{pack['id']}", headers=A).json()["benefit"]["sessions"] == 5

        # Selling them needs a customer
        r = client.post("/sales", json={"items": [{"product_id": pack["id"], "quantity": 1}], "payments": [{"payment_method_id": cash, "amount": 2000}]}, headers=H)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "benefit_customer"
        assert sell([{"product_id": pack["id"], "quantity": 1}, {"product_id": member["id"], "quantity": 1}], amount=2300).status_code == 201
        got = {b["kind"]: b for b in client.get(f"/customers/{cust['id']}/benefits", headers=A).json()}
        package, membership = got["package"], got["membership"]
        assert package["sessions_left"] == 5 and package["active"] and membership["price_list"] == f"VIP {tag}"

        # Membership: its price list applies (-20%)
        p = client.post("/sales/preview", json={"customer_id": cust["id"], "items": [{"product_id": oil["id"], "quantity": 1}]}, headers=H).json()
        assert D(p["lines"][0]["unit_price"]) == 80
        # Using sessions: $0 lines; not another customer's; not more than left
        assert sell([{"product_id": massage["id"], "quantity": 1, "benefit_id": package["id"]}], other["id"]).status_code == 422
        r = sell([{"product_id": massage["id"], "quantity": 6, "benefit_id": package["id"]}])
        assert r.status_code == 422 and r.json()["detail"]["code"] == "benefit_sessions"
        s = sell([{"product_id": massage["id"], "quantity": 2, "benefit_id": package["id"]}]).json()
        assert D(s["total"]) == 0
        left = next(b for b in client.get(f"/customers/{cust['id']}/benefits", headers=A).json() if b["id"] == package["id"])
        assert left["sessions_left"] == 3

        # Renewal: a second membership starts when the first ends
        sell([{"product_id": member["id"], "quantity": 1}], amount=240)  # members pay VIP price for it too
        ms = sorted((b for b in client.get(f"/customers/{cust['id']}/benefits", headers=A).json() if b["kind"] == "membership"), key=lambda b: b["starts_at"])
        assert len(ms) == 2 and ms[1]["starts_at"] == ms[0]["ends_at"]
        assert all(e["customer_id"] != cust["id"] for e in client.get("/memberships/expiring", params={"days": 35}, headers=A).json())  # renewed
    finally:
        for sale in client.get("/sales", headers=H).json().get("items", []):
            d = client.get(f"/sales/{sale['id']}", headers=H).json()
            if D(d["total"]) > 0:
                client.post(f"/sales/{sale['id']}/returns", json={"items": [{"sale_item_id": i["id"], "quantity": i["quantity"]} for i in d["items"]],
                                                                 "refunds": [{"payment_method_id": cash, "amount": d["total"]}]}, headers=H)
        left = D(client.get(f"/products/{oil['id']}", headers=H).json()["current_stock"])
        if left:
            client.post("/inventory/adjustments", json={"product_id": oil["id"], "quantity": str(-left), "notes": "Limpieza test"}, headers=H)
        for p in (massage, pack, member, oil):
            client.delete(f"/products/{p['id']}/benefit", headers=A)
            client.delete(f"/products/{p['id']}", headers=A)
        for c in (cust, other):
            client.delete(f"/customers/{c['id']}", headers=A)
        client.post(f"/cash-registers/{reg}/release", headers=H)
        if mine:
            client.post(f"/cash-registers/{mine['cash_register_id']}/occupy", headers={**A, "X-Branch-Id": mine["branch_id"]})
