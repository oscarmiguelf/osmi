# Integration test: sales made without internet, sent back later (installable app).
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from tests.test_calendar import A, client
from tests.test_purchases import _seed

D = lambda v: Decimal(str(v))  # noqa: E731


def test_offline_sales():
    tag = secrets.token_hex(3)
    mine = client.get("/cash-sessions/current", headers=A)
    mine = mine.json() if mine.status_code == 200 else None
    if mine:
        client.post(f"/cash-registers/{mine['cash_register_id']}/release", headers={**A, "X-Branch-Id": mine["branch_id"]})
    branch = client.post("/branches", json={"name": f"Offline {tag}", "code": f"O{tag[:4]}".upper()}, headers=A).json()["id"]
    H = {**A, "X-Branch-Id": branch}
    reg = client.post("/cash-registers", json={"name": f"Caja {tag}"}, headers=H).json()["id"]
    client.post(f"/cash-registers/{reg}/occupy", headers=H)
    ptype, unit = _seed("/product-types", "Product"), _seed("/units", "Unit")
    mk = lambda name, price, stock: client.post("/products", json={"name": f"{name} {tag}", "product_type_id": ptype, "unit_of_measure_id": unit,
                                                                   "price": price, "initial_stock": stock}, headers=H).json()
    pen, glue = mk("Pluma", 10, 5), mk("Pegamento", 30, 1)
    vip = client.post("/price-lists", json={"name": f"VIP {tag}", "percent": -10}, headers=A).json()
    cust = client.post("/customers", json={"full_name": f"Cliente {tag}", "phone": "55" + str(secrets.randbelow(10**8)).zfill(8),
                                           "price_list_id": vip["id"]}, headers=A).json()
    methods = {m["description"]: m for m in client.get("/payment-methods", headers=A).json()}
    cash, credit = methods["Cash"]["id"], next(m["id"] for m in methods.values() if m["is_credit"])
    device = tag[:4].upper().replace("0", "Q")
    n = [0]

    def offline(items, total, customer=None, method=cash, when=None, **extra):
        n[0] += 1
        body = {"id": str(uuid.uuid4()), "offline_folio": f"OFF-{device}-{n[0]}", "cash_register_id": reg, "customer_id": customer,
                "sold_at": (when or datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(), "items": items,
                "payments": [{"payment_method_id": method, "amount": str(total), "amount_tendered": None}], **extra}
        return body, client.post("/sales/offline", json=body, headers=H)

    sales = []
    try:
        # What the register stores: products with stock, price lists with their prices, customers with their list, no credit
        snap = client.get("/sales/offline/snapshot", headers=H).json()
        p = next(x for x in snap["products"] if x["id"] == pen["id"])
        assert D(p["price"]) == 10 and D(p["stock"]) == 5 and snap["register"]["id"] == reg
        assert next(c for c in snap["customers"] if c["id"] == cust["id"])["price_list_id"] == vip["id"]
        assert any(pl["id"] == vip["id"] for pl in snap["price_lists"]) and all(m["id"] != credit for m in snap["payment_methods"])

        # A sale made 2 hours ago with the customer's list (-10%): real folio now, the temporary one kept, its hour kept
        body, r = offline([{"product_id": pen["id"], "quantity": "2", "unit_price": "9.00"}], "18.00", customer=cust["id"])
        assert r.status_code == 201, r.text
        sale = r.json()["sale"]
        sales.append(sale["id"])
        assert r.json()["issues"] == [] and sale["offline_folio"] == body["offline_folio"] and sale["folio"] != body["offline_folio"]
        assert datetime.fromisoformat(sale["sold_at"]) < datetime.now(timezone.utc) - timedelta(hours=1)
        assert client.get(f"/sales/by-folio/{body['offline_folio']}", headers=H).json()["id"] == sale["id"]
        # Sent again (the answer got lost): the same sale, not a second one
        again = client.post("/sales/offline", json=body, headers=H)
        assert again.status_code == 201 and again.json()["sale"]["id"] == sale["id"]
        assert D(client.get(f"/products/{pen['id']}", headers=H).json()["current_stock"]) == 3

        # The price changed while offline: recorded at the price charged, flagged
        client.patch(f"/products/{pen['id']}", json={"price": 12}, headers=A)
        _, r = offline([{"product_id": pen["id"], "quantity": "1", "unit_price": "10.00"}], "10.00")
        assert r.status_code == 201 and D(r.json()["sale"]["total"]) == 10
        sales.append(r.json()["sale"]["id"])
        assert [(i["kind"], D(i["detail"]["current"])) for i in r.json()["issues"]] == [("price", 12)]

        # Not enough stock (another register sold it): recorded anyway, stock below zero, flagged
        _, r = offline([{"product_id": glue["id"], "quantity": "3", "unit_price": "30.00"}], "90.00")
        assert r.status_code == 201, r.text
        sales.append(r.json()["sale"]["id"])
        assert r.json()["issues"][0]["kind"] == "stock"
        assert D(client.get(f"/products/{glue['id']}", headers=H).json()["current_stock"]) == -2
        # A normal sale still can't take stock that isn't there; stock coming in is accepted
        normal = client.post("/sales", json={"items": [{"product_id": glue["id"], "quantity": 1}],
                                             "payments": [{"payment_method_id": cash, "amount": "30.00"}]}, headers=H)
        assert normal.status_code == 422
        assert client.post("/inventory/adjustments", json={"product_id": glue["id"], "quantity": "1", "notes": "Llegó"}, headers=H).status_code in (200, 201)
        assert D(client.get(f"/products/{glue['id']}", headers=H).json()["current_stock"]) == -1

        # Refused (stays on the device): no credit, payments must add up, a future date, a folio used twice
        assert offline([{"product_id": pen["id"], "quantity": "1", "unit_price": "12.00"}], "12.00", method=credit)[1].status_code == 422
        assert offline([{"product_id": pen["id"], "quantity": "1", "unit_price": "12.00"}], "11.00")[1].status_code == 422
        assert offline([{"product_id": pen["id"], "quantity": "1", "unit_price": "12.00"}], "12.00",
                       when=datetime.now(timezone.utc) + timedelta(days=1))[1].status_code == 422
        dup = {**body, "id": str(uuid.uuid4())}
        assert client.post("/sales/offline", json=dup, headers=H).json()["detail"]["code"] == "offline_folio"

        # To review: both issues, then one reviewed
        issues = client.get("/sales/offline/issues", headers=H).json()
        assert {i["kind"] for i in issues} == {"price", "stock"}
        assert client.post(f"/sales/offline/issues/{issues[0]['id']}/resolve", json={"note": "Ajustado"}, headers=H).status_code == 204
        assert len(client.get("/sales/offline/issues", headers=H).json()) == 1
        assert client.get("/sales/offline/issues", params={"resolved": True}, headers=H).json()[0]["note"] == "Ajustado"

        # Whoever doesn't occupy the register can't send its sales: they wait
        client.post(f"/cash-registers/{reg}/release", headers=H)
        r = offline([{"product_id": pen["id"], "quantity": "1", "unit_price": "12.00"}], "12.00")[1]
        assert r.status_code == 409 and r.json()["detail"]["code"] == "offline_register"
        client.post(f"/cash-registers/{reg}/occupy", headers=H)
    finally:
        for sid in sales:
            d = client.get(f"/sales/{sid}", headers=H).json()
            client.post(f"/sales/{sid}/returns", json={"items": [{"sale_item_id": i["id"], "quantity": i["quantity"]} for i in d["items"]],
                                                      "refunds": [{"payment_method_id": cash, "amount": d["total"]}]}, headers=H)
        for prod in (pen, glue):
            left = D(client.get(f"/products/{prod['id']}", headers=H).json()["current_stock"])
            if left:
                client.post("/inventory/adjustments", json={"product_id": prod["id"], "quantity": str(-left), "notes": "Limpieza test"}, headers=H)
            client.delete(f"/products/{prod['id']}", headers=A)
        client.delete(f"/customers/{cust['id']}", headers=A)
        client.delete(f"/price-lists/{vip['id']}", headers=A)
        client.post(f"/cash-registers/{reg}/release", headers=H)
        if mine:
            client.post(f"/cash-registers/{mine['cash_register_id']}/occupy", headers={**A, "X-Branch-Id": mine["branch_id"]})
