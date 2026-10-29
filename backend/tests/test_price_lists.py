# Integration test: price lists (steps by quantity, percent), a customer's list in sales and quotes.
import secrets
from decimal import Decimal

from app.application.sale_pricing import list_price
from tests.test_calendar import A, B, client
from tests.test_purchases import _seed

D = lambda v: Decimal(str(v))  # noqa: E731


def test_list_price_rule():
    tiers = [(D(12), D(85)), (D(50), D(80))]
    assert list_price(D(100), D(5), tiers, D(0)) == 100      # below the first step: general price
    assert list_price(D(100), D(12), tiers, D(0)) == 85      # step reached
    assert list_price(D(100), D(60), tiers, D(0)) == 80      # the highest step reached
    assert list_price(D(100), D(5), tiers, D(-10)) == 90     # no step: the list's percent
    assert list_price(D(99.99), D(1), [], D(-15)) == D("84.99")


def test_price_lists_in_sales_and_quotes():
    tag = secrets.token_hex(3)
    mine = client.get("/cash-sessions/current", headers=A)
    mine = mine.json() if mine.status_code == 200 else None
    if mine:
        client.post(f"/cash-registers/{mine['cash_register_id']}/release", headers={**A, "X-Branch-Id": mine["branch_id"]})
    branch = client.post("/branches", json={"name": f"Listas {tag}", "code": f"L{tag[:4]}".upper()}, headers=A).json()["id"]
    H = {**A, "X-Branch-Id": branch}
    reg = client.post("/cash-registers", json={"name": f"Caja {tag}"}, headers=H).json()["id"]
    client.post(f"/cash-registers/{reg}/occupy", headers=H)
    ptype, unit = _seed("/product-types", "Product"), _seed("/units", "Unit")
    nail = client.post("/products", json={"name": f"Clavo {tag}", "product_type_id": ptype, "unit_of_measure_id": unit, "price": 10,
                                          "initial_stock": 100}, headers=H).json()
    glue = client.post("/products", json={"name": f"Pegamento {tag}", "product_type_id": ptype, "unit_of_measure_id": unit, "price": 50,
                                          "initial_stock": 10}, headers=H).json()
    cash = next(m["id"] for m in client.get("/payment-methods", headers=A).json() if m["description"] == "Cash")
    wholesale = cust = None
    try:
        assert client.post("/price-lists", json={"name": f"Mayoreo {tag}"}, headers=B).status_code == 403  # products.prices
        wholesale = client.post("/price-lists", json={"name": f"Mayoreo {tag}", "percent": -10}, headers=A).json()
        assert client.post("/price-lists", json={"name": f"mayoreo {tag}"}, headers=A).status_code == 409
        assert client.put(f"/price-lists/{wholesale['id']}/items", json={"items": [
            {"product_id": nail["id"], "min_quantity": 12, "price": 8}, {"product_id": nail["id"], "min_quantity": 12, "price": 7}]}, headers=A).status_code == 422
        wholesale = client.put(f"/price-lists/{wholesale['id']}/items", json={"items": [
            {"product_id": nail["id"], "min_quantity": 12, "price": 8}, {"product_id": nail["id"], "min_quantity": 50, "price": 7}]}, headers=A).json()
        assert len(wholesale["items"]) == 2
        cust = client.post("/customers", json={"full_name": f"Ferretería {tag}", "phone": "55" + str(secrets.randbelow(10**8)).zfill(8),
                                               "price_list_id": wholesale["id"]}, headers=A).json()
        assert client.get(f"/customers/{cust['id']}", headers=A).json()["price_list"] == f"Mayoreo {tag}"

        preview = lambda items, customer=cust["id"]: client.post("/sales/preview", json={"customer_id": customer, "items": items}, headers=H)
        lines = preview([{"product_id": nail["id"], "quantity": 20}, {"product_id": glue["id"], "quantity": 1}]).json()["lines"]
        assert (D(lines[0]["unit_price"]), D(lines[1]["unit_price"])) == (8, 45) and lines[0]["price_list"] == f"Mayoreo {tag}"
        assert D(preview([{"product_id": nail["id"], "quantity": 5}]).json()["lines"][0]["unit_price"]) == 9  # below 12: -10%
        assert D(preview([{"product_id": nail["id"], "quantity": 5}], None).json()["lines"][0]["unit_price"]) == 10  # no customer
        # Typing a price (even the general one) is refused while a list applies
        r = preview([{"product_id": nail["id"], "quantity": 20, "unit_price": 10}])
        assert r.status_code == 422 and D(r.json()["detail"]["price"]) == 8

        sale = client.post("/sales", json={"customer_id": cust["id"], "items": [{"product_id": nail["id"], "quantity": 60}],
                                           "payments": [{"payment_method_id": cash, "amount": 420}]}, headers=H).json()
        assert D(sale["total"]) == 420
        quote = client.post("/quotes", json={"customer_id": cust["id"], "items": [{"product_id": nail["id"], "quantity": 12}]}, headers=H).json()
        assert D(quote["items"][0]["unit_price"]) == 8

        assert client.delete(f"/price-lists/{wholesale['id']}", headers=A).json()["detail"]["code"] == "in_use"
        client.patch(f"/customers/{cust['id']}", json={"price_list_id": None}, headers=A)
        assert D(preview([{"product_id": nail["id"], "quantity": 20}]).json()["lines"][0]["unit_price"]) == 10
    finally:
        for s in client.get("/sales", headers=H).json().get("items", []):
            d = client.get(f"/sales/{s['id']}", headers=H).json()
            client.post(f"/sales/{s['id']}/returns", json={"items": [{"sale_item_id": i["id"], "quantity": i["quantity"]} for i in d["items"]],
                                                          "refunds": [{"payment_method_id": cash, "amount": d["total"]}]}, headers=H)
        for p in (nail, glue):
            left = D(client.get(f"/products/{p['id']}", headers=H).json()["current_stock"])
            if left:
                client.post("/inventory/adjustments", json={"product_id": p["id"], "quantity": str(-left), "notes": "Limpieza test"}, headers=H)
            client.delete(f"/products/{p['id']}", headers=A)
        if cust:
            client.patch(f"/customers/{cust['id']}", json={"price_list_id": None}, headers=A)
            client.delete(f"/customers/{cust['id']}", headers=A)
        if wholesale:
            client.delete(f"/price-lists/{wholesale['id']}", headers=A)
        client.post(f"/cash-registers/{reg}/release", headers=H)
        if mine:
            client.post(f"/cash-registers/{mine['cash_register_id']}/occupy", headers={**A, "X-Branch-Id": mine["branch_id"]})
