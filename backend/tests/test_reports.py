# Integration test against the real DB: reports over a real sale and return (uses the sales fixture).
# docker compose run --rm -v ./tests:/code/tests api sh -c "pip install -q pytest httpx && python -m pytest -q tests"
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.application.report_service import local_range
from tests.test_calendar import OTHER, A, B, client
from tests.test_products import _grant
from tests.test_sales import env  # noqa: F401  (fixture)

D = lambda v: Decimal(str(v))  # noqa: E731


def test_local_range():
    start, end = local_range(date(2026, 10, 1), date(2026, 10, 31), "America/Mexico_City")
    assert start.isoformat() == "2026-10-01T06:00:00+00:00" and end.isoformat() == "2026-11-01T06:00:00+00:00"


def test_reports(env):
    H, p, m = env["H"], env["p"], env["m"]
    branch = H["X-Branch-Id"]
    client.post(f"/cash-registers/{env['register']}/occupy", headers=H)
    sale = client.post("/sales", json={"items": [{"product_id": p["hammer"]["id"], "quantity": 2}, {"product_id": p["install"]["id"], "quantity": 1}],
                                       "payments": [{"payment_method_id": m["Cash"], "amount": 300}, {"payment_method_id": m["Card"], "amount": 132}]},
                       headers=H).json()  # 2 x 116 + 200 = 432
    hammer_item = next(i["id"] for i in sale["items"] if i["product_id"] == p["hammer"]["id"])
    client.post(f"/sales/{sale['id']}/returns", json={"items": [{"sale_item_id": hammer_item, "quantity": 1}],
                                                      "refunds": [{"payment_method_id": m["Cash"], "amount": 116}], "reason": "Defecto"}, headers=H)
    tz = client.get("/auth/me", headers=A).json()["user"]["timezone"]
    today = datetime.now(ZoneInfo(tz)).date().isoformat()
    rep = lambda name, h=H, **q: client.get(f"/reports/{name}", params={"from": today, "to": today, **q}, headers=h)

    # Every report of the catalog runs (with the extras some need)
    for spec in client.get("/reports", headers=A).json():
        extras = {"product_id": p["hammer"]["id"], "customer_id": env["customer"]["id"]}
        r = rep(spec["name"], **{k: v for k, v in extras.items() if k in spec.get("extras", [])})
        assert r.status_code == 200, (spec["name"], r.text)
        assert [c["key"] for c in r.json()["columns"]] == [k for k, _ in spec["columns"]]

    # Numbers that reconcile: gross 432, returns 116 (by return date), net 316
    s = rep("sales/summary").json()
    assert s["timezone"] == tz and len(s["rows"]) == 1
    row = s["rows"][0]
    assert (row["tickets"], D(row["gross_sales"]), D(row["returns"]), D(row["net_sales"])) == (1, 432, 116, 316)
    methods = {r["method"]: r for r in rep("sales/by-payment-method").json()["rows"]}
    assert D(methods["Cash"]["amount"]) == 300 and D(methods["Cash"]["refunded"]) == 116 and D(methods["Card"]["net"]) == 132
    top = {r["product"]: r for r in rep("sales/top-products").json()["rows"]}
    hammer = top[p["hammer"]["name"]]
    assert D(hammer["units"]) == 1 and D(hammer["cogs"]) == 60  # 2 sold - 1 returned, cost 60 each (from the purchase)
    assert D(hammer["revenue"]) == 100 and D(hammer["margin"]) == 40  # 116 without 16% tax = 100
    assert top[p["install"]["name"]]["no_cost"] is True  # a service with cost 0: flagged
    tax = rep("sales/tax").json()
    assert D(tax["totals"]["official_tax"]) == D(tax["totals"]["tax_amount"])
    returns = rep("sales/returns").json()
    assert returns["rows"][0]["reason"] == "Defecto" and returns["has_more"] is False
    assert rep("sales/summary", group="month").json()["rows"][0]["period"].endswith("-01")
    cash = rep("cash/movements").json()["rows"]
    assert {(r["movement_type"], r["method"]) for r in cash} >= {("Sale", "Cash"), ("Return", "Cash"), ("Sale", "Card")}
    assert any(r["category"] for r in rep("inventory/valuation").json()["rows"])
    kardex = rep("inventory/kardex", product_id=p["hammer"]["id"]).json()["rows"]
    assert [k["movement_type"] for k in kardex][:2] == ["Return", "Sale"]

    # Rules: period required and capped, extras required, only your branches
    assert client.get("/reports/sales/summary", headers=H).json()["detail"]["field"] == "from"
    assert rep("sales/summary", **{"from": "2024-01-01"}).json()["detail"]["field"] == "to"  # more than 366 days
    assert rep("inventory/kardex").json()["detail"]["field"] == "product_id"
    assert client.get("/reports/inventory/valuation", headers=H).status_code == 200  # "as of now": no period
    assert client.get("/reports/nope/nope", params={"from": today, "to": today}, headers=H).status_code == 404
    assert rep("sales/summary", branch_ids="00000000-0000-0000-0000-000000000000").status_code == 403

    # Export needs reports.export; security reports need users.read
    _grant(OTHER, {"reports": {"read"}})
    try:
        client.post(f"/branches/{branch}/users", json={"user_id": str(OTHER)}, headers=A)
        HO = {**B, "X-Branch-Id": branch}
        assert rep("sales/summary", HO).status_code == 200
        assert rep("sales/summary", HO, export="csv").status_code == 403
        assert rep("admin/login-events", HO).status_code == 403
        assert "admin/login-events" not in [r["name"] for r in client.get("/reports", headers=HO).json()]
        assert len(rep("sales/returns", A | {"X-Branch-Id": branch}, export="xlsx", page_size=1).json()["rows"]) == 1
        log = rep("admin/exports", A | {"X-Branch-Id": branch}).json()["rows"][0]  # the export was recorded
        assert (log["report"], log["format"], log["row_count"]) == ("sales/returns", "XLSX", 1) and log["branches"]
        assert rep("sales/summary", HO, export="pdf").status_code == 422
    finally:
        client.delete(f"/branches/{branch}/users/{OTHER}", headers=A)
        _grant(OTHER, {})

    # Dashboard: today vs yesterday vs last week
    d = client.get("/reports/dashboard", headers=H).json()
    assert d["day"]["tickets"] == 1 and D(d["day"]["net_sales"]) == 316 and d["previous_day"]["tickets"] == 0
    assert d["top_products"][0]["product"] in (p["hammer"]["name"], p["install"]["name"]) and "low_stock" in d

    # Clean up: return the rest so the fixture can empty the branch
    rest = [{"sale_item_id": i["id"], "quantity": i["returnable_quantity"]} for i in client.get(f"/sales/{sale['id']}", headers=H).json()["items"]
            if float(i["returnable_quantity"]) > 0]
    client.post(f"/sales/{sale['id']}/returns", json={"items": rest, "refunds": [{"payment_method_id": m["Cash"], "amount": 316}]}, headers=H)
