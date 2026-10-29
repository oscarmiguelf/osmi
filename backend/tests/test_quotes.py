# Integration test against the real DB: quotes and their conversion into a sale (uses the sales fixture).
# docker compose run --rm -v ./tests:/code/tests api sh -c "pip install -q pytest httpx && python -m pytest -q tests"
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.application.quote_service import valid_until_for
from tests.test_calendar import A, client
from tests.test_sales import env  # noqa: F401  (fixture)

D = lambda v: Decimal(str(v))  # noqa: E731


def test_valid_until_is_end_of_local_day():
    now = datetime(2026, 10, 28, 5, 0, tzinfo=timezone.utc)  # still Oct 27 in Mexico City
    assert valid_until_for(1, "America/Mexico_City", now) == datetime(2026, 10, 29, 5, 59, 59, tzinfo=timezone.utc)


def test_quotes_flow(env):
    cust = env["customer"]
    H, p, m = env["H"], env["p"], env["m"]
    body = {"customer_id": cust["id"], "valid_days": 7, "discount": 10, "notes": "Entrega en obra", "items": [
        {"product_id": p["hammer"]["id"], "quantity": 20},   # more than in stock: a warning only
        {"product_id": p["install"]["id"], "quantity": 1, "discount": 20}]}

    pv = client.post("/quotes/preview", json=body, headers=H).json()
    assert (D(pv["subtotal"]), D(pv["total"])) == (2500, 2490) and pv["stock_warnings"][0]["needed"] == 20
    q = client.post("/quotes", json=body, headers=H)
    assert q.status_code == 201
    q = q.json()
    assert q["folio"].endswith("Q000001") and q["status"] == "OPEN" and q["stock_warnings"]
    assert q["tax_breakdown"][0]["tax_name"] and q["customer"] == cust["full_name"]
    assert client.post("/quotes", json={**body, "items": []}, headers=H).status_code == 422
    assert client.post("/quotes/preview", json={"items": [{"product_id": p["hammer"]["id"], "quantity": 1, "unit_price": 1}]},
                       headers=H).json()["detail"]["field"] == "items.0.unit_price"  # prices can't be changed
    assert client.post("/quotes", json={**body, "valid_until": "2020-01-01T00:00:00Z"}, headers=H).json()["detail"]["field"] == "valid_until"
    assert client.get(f"/quotes/by-folio/{q['folio'].lower()}", headers=H).json()["id"] == q["id"]
    assert [x["id"] for x in client.get("/quotes", params={"status": "OPEN", "q": cust["full_name"][:9]}, headers=H).json()["items"]] == [q["id"]]

    # A prospect without a customer record, then "edit" = duplicate + cancel
    prospect = client.post("/quotes", json={"customer_name": "Juan de la obra", "items": [{"product_id": p["nails"]["id"], "quantity": "2.5"}]}, headers=H).json()
    assert prospect["customer"] == "Juan de la obra" and prospect["customer_id"] is None
    dup = client.post(f"/quotes/{prospect['id']}/duplicate", headers=H).json()
    assert dup["customer_name"] == "Juan de la obra" and D(dup["items"][0]["quantity"]) == D("2.5")
    assert client.post(f"/quotes/{prospect['id']}/cancel", headers=H).json()["status"] == "CANCELLED"
    assert client.post(f"/quotes/{prospect['id']}/cancel", headers=H).status_code == 409
    assert client.get(f"/quotes/{prospect['id']}/convert-draft", headers=H).json()["detail"]["code"] == "quote_status"
    assert [h["to_status"] for h in client.get(f"/quotes/{prospect['id']}/history", headers=H).json() if h["action"] == "UPDATE"] == ["CANCELLED"]

    # Convert: the draft honors the quoted price and says what changed since
    client.patch(f"/products/{p['hammer']['id']}", json={"price": 120}, headers=A)
    draft = client.get(f"/quotes/{q['id']}/convert-draft", headers=H).json()
    hammer = next(i for i in draft["items"] if i["product_id"] == p["hammer"]["id"])
    assert D(hammer["unit_price"]) == 116 and D(hammer["current_price"]) == 120 and hammer["price_changed"]
    assert draft["stock_warnings"][0]["available"] == 10
    sale_body = {"customer_id": cust["id"], "discount": draft["discount"], "items": [
        {"product_id": i["product_id"], "quantity": 5 if i["product_id"] == p["hammer"]["id"] else i["quantity"],
         "unit_price": i["unit_price"], "discount": i["discount"]} for i in draft["items"]],
        "payments": [{"payment_method_id": m["Cash"], "amount": 750}]}  # 5 x 116 (quoted, not today's 120) + (200 - 20) - 10
    convert = lambda b: client.post(f"/quotes/{q['id']}/convert", json=b, headers=H)
    assert client.post("/sales/preview", json={**sale_body, "payments": []}, headers=H).json()["detail"]["field"].endswith("unit_price")
    assert D(client.post("/sales/preview", json={**sale_body, "quote_id": q["id"], "payments": []}, headers=H).json()["total"]) == 750
    assert convert(sale_body).json()["detail"]["code"] == "register"
    client.post(f"/cash-registers/{env['register']}/occupy", headers=H)
    assert convert({**sale_body, "customer_id": None}).json()["detail"]["field"] == "customer_id"  # must be the quote's customer
    r = convert(sale_body)
    assert r.status_code == 201, r.text
    r = r.json()
    assert r["quote"]["status"] == "CONVERTED" and r["quote"]["sale_folio"] == r["sale"]["folio"] and r["sale"]["quote_folio"] == q["folio"]
    assert convert(sale_body).json()["detail"]["code"] == "quote_status"  # only once
    assert client.post(f"/quotes/{q['id']}/cancel", headers=H).status_code == 409

    # Expiration is computed: an open quote past valid_until can't be converted
    short = client.post("/quotes", json={"valid_until": (datetime.now(timezone.utc) + timedelta(seconds=2)).isoformat(),
                                         "items": [{"product_id": p["install"]["id"], "quantity": 1}]}, headers=H).json()
    time.sleep(2.5)
    assert client.get(f"/quotes/{short['id']}", headers=H).json()["is_expired"]
    assert [x["id"] for x in client.get("/quotes", params={"status": "EXPIRED"}, headers=H).json()["items"]] == [short["id"]]
    assert client.post(f"/quotes/{short['id']}/convert", json={"items": [{"product_id": p["install"]["id"], "quantity": 1}],
                                                                "payments": [{"payment_method_id": m["Cash"], "amount": 200}]},
                       headers=H).json()["detail"]["code"] == "quote_expired"

    # Clean up the sale so the fixture can empty the branch: return what was sold
    sale = r["sale"]
    client.post(f"/sales/{sale['id']}/returns", json={"items": [{"sale_item_id": i["id"], "quantity": i["quantity"]} for i in sale["items"]],
                                                      "refunds": [{"payment_method_id": m["Cash"], "amount": 750}]}, headers=H)
