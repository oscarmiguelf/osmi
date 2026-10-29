# Integration test against the real DB: purchases on two throwaway branches, the moving average cost, voiding.
# docker compose run --rm -v ./tests:/code/tests api sh -c "pip install -q pytest httpx && python -m pytest -q tests"
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.application.purchase_service import average_in, average_out
from tests.test_calendar import A, client

D = lambda v: Decimal(str(v))  # noqa: E731


def test_average_cost_rules():
    assert average_in(D(0), D(99), D(10), D(500)) == 50  # nothing on hand: the new price
    assert average_in(D(10), D(50), D(10), D(700)) == 60
    assert average_in(D(7), D(50), D(6), D(245)) == D("45.77")
    assert average_out(D(20), D(60), D(10), D(700)) == 50  # exactly undoes the purchase above
    assert average_out(D(10), D(60), D(10), D(700)) == 60  # nothing left: keep the cost
    assert average_out(D(20), D(10), D(10), D(700)) == 10  # cost edited by hand since: keep it


def _seed(path, name):
    return next(i for i in client.get(path, headers=A).json() if i["name"] == name)["id"]


@pytest.fixture
def env():
    tag = secrets.token_hex(3).upper()
    branches = [client.post("/branches", json={"name": f"Compras {n} {tag}", "code": f"C{n}{tag}"}, headers=A).json()["id"]
                for n in (1, 2)]
    product = client.post("/products", json={"name": f"Cemento {tag}", "product_type_id": _seed("/product-types", "Product"),
                                             "unit_of_measure_id": _seed("/units", "Unit")}, headers=A).json()
    sup = client.post("/suppliers", json={"name": f"Cemex {tag}"}, headers=A).json()
    H1, H2 = ({**A, "X-Branch-Id": b} for b in branches)
    yield {"tag": tag, "H1": H1, "H2": H2, "product": product, "sup": sup}
    for H in (H1, H2):  # empty both branches so they can be deleted, even after a failure
        left = D(client.get(f"/products/{product['id']}", headers=H).json()["current_stock"])
        if left:
            client.post("/inventory/adjustments", json={"product_id": product["id"], "quantity": str(-left), "notes": "Limpieza test"}, headers=H)
    client.delete(f"/products/{product['id']}", headers=A)
    client.delete(f"/suppliers/{sup['id']}", headers=A)
    for b in branches:
        client.delete(f"/branches/{b}", headers=A)


def test_purchases(env):
    tag, H1, H2, pid, sup = env["tag"], env["H1"], env["H2"], env["product"]["id"], env["sup"]
    buy = lambda H, items, **kw: client.post("/purchases", json={"items": items, **kw}, headers=H)
    cost = lambda: D(client.get(f"/products/{pid}", headers=A).json()["cost"])
    stock = lambda H: D(client.get(f"/products/{pid}", headers=H).json()["current_stock"])

    # Moving average over the stock of every branch
    p1 = buy(H1, [{"product_id": pid, "quantity": 10, "unit_cost": 50}], supplier_id=sup["id"], reference=f"F-{tag}-1").json()
    assert cost() == 50 and D(p1["cost_changes"][0]["new_cost"]) == 50
    p2 = buy(H2, [{"product_id": pid, "quantity": 10, "unit_cost": 70}], reference=f"F-{tag}-2").json()
    assert cost() == 60 and stock(H2) == 10

    # Validation: future date, repeated lines merge at the same cost and stay apart at a different one
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    assert buy(H1, [{"product_id": pid, "quantity": 1, "unit_cost": 1}], purchased_at=future).json()["detail"]["field"] == "purchased_at"

    # Edit the header; a supplier can be removed
    r = client.patch(f"/purchases/{p2['id']}", json={"supplier_id": sup["id"], "notes": "Llegó tarde"}, headers=H2).json()
    assert r["supplier"] == sup["name"] and r["notes"] == "Llegó tarde"
    assert client.patch(f"/purchases/{p2['id']}", json={"supplier_id": None}, headers=H2).json()["supplier"] is None
    assert client.patch(f"/purchases/{p2['id']}", json={"purchased_at": future}, headers=H2).status_code == 422
    assert client.patch(f"/purchases/{p2['id']}", json={"total": 1}, headers=H2).json()["total"] == 700  # not editable
    assert client.patch(f"/purchases/{p2['id']}", json={"notes": "x"}, headers=H1).status_code == 404  # other branch

    # Void: stock goes out and the average forgets the purchase
    r = client.delete(f"/purchases/{p2['id']}", headers=H2).json()
    assert r["voided"] and stock(H2) == 0 and cost() == 50
    kardex = client.get(f"/products/{pid}/kardex", headers=H2).json()["items"]
    assert (kardex[0]["movement_type"], D(kardex[0]["quantity"]), kardex[0]["notes"]) == ("Adjustment", -10, "Compra anulada")
    assert client.delete(f"/purchases/{p2['id']}", headers=H2).status_code == 409  # already voided
    assert client.patch(f"/purchases/{p2['id']}", json={"notes": "x"}, headers=H2).status_code == 409

    # Can't void once part of the stock is gone (sold, moved...): nothing changes
    client.post("/inventory/adjustments", json={"product_id": pid, "quantity": -3, "notes": "Venta simulada"}, headers=H1)
    r = client.delete(f"/purchases/{p1['id']}", headers=H1)
    assert r.status_code == 409 and D(r.json()["detail"]["products"][0]["available"]) == 7
    assert stock(H1) == 7 and client.get(f"/purchases/{p1['id']}", headers=H1).json()["deleted_at"] is None

    p3 = buy(H1, [{"product_id": pid, "quantity": 2, "unit_cost": 40}, {"product_id": pid, "quantity": 3, "unit_cost": 40},
                  {"product_id": pid, "quantity": 1, "unit_cost": 45}]).json()
    assert sorted((D(i["quantity"]), D(i["unit_cost"])) for i in p3["items"]) == [(1, 45), (5, 40)]
    assert D(p3["total"]) == 245 and cost() == D("45.77") and stock(H1) == 13

    # Lists and queries
    listed = lambda H, **q: [p["id"] for p in client.get("/purchases", params=q, headers=H).json()["items"]]
    assert listed(H1, q=f"f-{tag.lower()}-1") == [p1["id"]]
    assert listed(H2) == [] and listed(H2, include_voided=True) == [p2["id"]]
    assert [p["id"] for p in client.get(f"/suppliers/{sup['id']}/purchases", headers=H1).json()["items"]] == [p1["id"]]
    last = client.get(f"/products/{pid}/purchase-price", headers=A).json()
    assert D(last["unit_cost"]) in (40, 45) and last["purchase_id"] == p3["id"]
    assert len(client.get(f"/products/{pid}/purchases", headers=H1).json()["items"]) == 3  # p1 + two lines of p3
    day = datetime.now(timezone.utc)
    s = client.get("/purchases/summary", params={"from": (day - timedelta(days=1)).isoformat(), "to": (day + timedelta(days=1)).isoformat(),
                                                 "tz": "America/Mexico_City"}, headers=H1).json()
    assert D(s["total"]) == 745 and {r["supplier"] for r in s["by_supplier"]} == {sup["name"], None}
    assert client.get("/purchases/summary", params={"from": day.isoformat(), "to": day.isoformat(), "tz": "Mars/Base"},
                      headers=H1).status_code == 422
    history = client.get(f"/purchases/{p2['id']}/history", headers=H2).json()["items"]
    assert {h["entity_type"] for h in history} == {"purchase", "purchase_item"}
