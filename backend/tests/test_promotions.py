# Integration test against the real DB: promotions CRUD and how they reach the point of sale (uses the sales fixture).
# docker compose run --rm -v ./tests:/code/tests api sh -c "pip install -q pytest httpx && python -m pytest -q tests"
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from tests.test_calendar import A, client
from tests.test_sales import env  # noqa: F401  (fixture)

D = lambda v: Decimal(str(v))  # noqa: E731


def test_promotions_flow(env):
    H, p, tag = env["H"], env["p"], env["tag"]
    now = datetime.now(timezone.utc)
    window = {"starts_at": (now - timedelta(hours=1)).isoformat(), "ends_at": (now + timedelta(days=7)).isoformat()}
    new = lambda **kw: client.post("/promotions", json={"name": f"Promo {tag}", **window, **kw}, headers=A)

    # Validation: the kind decides which numbers are needed; at least one product; the window must make sense
    assert new(kind="PERCENT", product_ids=[p["nails"]["id"]]).json()["detail"]["field"] == "percent"
    assert new(kind="PERCENT", percent=150, product_ids=[p["nails"]["id"]]).status_code == 422
    assert new(kind="BUY_X_GET_Y", buy_quantity=2, product_ids=[p["nails"]["id"]]).json()["detail"]["field"] == "get_quantity"
    assert new(kind="AMOUNT", amount=5, product_ids=[]).json()["detail"]["field"] == "product_ids"
    assert new(kind="AMOUNT", amount=5, product_ids=[p["nails"]["id"]], ends_at=window["starts_at"]).json()["detail"]["field"] == "ends_at"

    # 3x2 on nails, only in this branch; numbers of other kinds are dropped
    promo = new(kind="BUY_X_GET_Y", buy_quantity=2, get_quantity=1, percent=10, product_ids=[p["nails"]["id"]], branch_ids=[env["H"]["X-Branch-Id"]])
    assert promo.status_code == 201, promo.text
    promo = promo.json()
    assert promo["status"] == "ACTIVE" and promo["percent"] is None and [b["id"] for b in promo["branches"]] == [env["H"]["X-Branch-Id"]]
    pid = promo["id"]
    active = [x["promotion_id"] for x in client.get("/promotions/active", headers=H).json()]
    assert pid in active and env["promo"] in active  # the fixture's 10% hammer too

    # Edit: switch kind (old numbers go away), change products; disable / schedule show in the status
    r = client.patch(f"/promotions/{pid}", json={"kind": "PERCENT", "percent": 15, "product_ids": [p["nails"]["id"], p["install"]["id"]]}, headers=A).json()
    assert r["kind"] == "PERCENT" and r["buy_quantity"] is None and r["product_count"] == 2
    assert client.patch(f"/promotions/{pid}", json={"kind": "AMOUNT"}, headers=A).json()["detail"]["field"] == "amount"
    assert client.patch(f"/promotions/{pid}", json={"is_enabled": False}, headers=A).json()["status"] == "DISABLED"
    assert pid not in [x["promotion_id"] for x in client.get("/promotions/active", headers=H).json()]
    later = {"starts_at": (now + timedelta(days=1)).isoformat(), "ends_at": (now + timedelta(days=2)).isoformat(), "is_enabled": True}
    assert client.patch(f"/promotions/{pid}", json=later, headers=A).json()["status"] == "SCHEDULED"
    assert client.patch(f"/promotions/{pid}", json={"ends_at": (now + timedelta(hours=1)).isoformat()}, headers=A).status_code == 422  # before start
    client.patch(f"/promotions/{pid}", json=window, headers=A)

    # Lists
    listed = lambda **q: [x["id"] for x in client.get("/promotions", params=q, headers=A).json()["items"]]
    assert pid in listed(status="ACTIVE", q=f"promo {tag.lower()}") and pid in listed(product_id=p["install"]["id"])
    assert pid not in listed(status="ENDED")

    # Used at a sale: the usage shows on the promotion
    client.post(f"/cash-registers/{env['register']}/occupy", headers=H)
    sale = client.post("/sales", json={"items": [{"product_id": p["install"]["id"], "quantity": 1, "promotion_id": pid}],
                                       "payments": [{"payment_method_id": env["m"]["Cash"], "amount": 170}]}, headers=H)
    assert sale.status_code == 201, sale.text
    used = client.get(f"/promotions/{pid}", headers=A).json()
    assert used["lines_sold"] == 1 and D(used["discount_given"]) == 30

    # History, delete, restore
    history = client.get(f"/promotions/{pid}/history", headers=A).json()["items"]
    assert {h["entity_type"] for h in history} == {"promotion", "product", "branch"}
    assert client.delete(f"/promotions/{pid}", headers=A).status_code == 204
    assert pid not in listed() and pid in listed(include_deleted=True)
    assert client.patch(f"/promotions/{pid}", json={"name": "x"}, headers=A).status_code == 404
    assert client.post(f"/promotions/{pid}/restore", headers=A).json()["deleted_at"] is None
    client.delete(f"/promotions/{pid}", headers=A)

    # Return the sale so the fixture can clean the branch
    s = sale.json()
    client.post(f"/sales/{s['id']}/returns", json={"items": [{"sale_item_id": s["items"][0]["id"], "quantity": 1}],
                                                   "refunds": [{"payment_method_id": env["m"]["Cash"], "amount": 170}]}, headers=H)
