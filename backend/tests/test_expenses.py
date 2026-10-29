# Integration test against the real DB: expenses and purchases paid from the register, another way, or owed.
# The admin's own open register (if any) is given back at the end.
import secrets
from decimal import Decimal

from tests.test_calendar import A, client
from tests.test_purchases import _seed

D = lambda v: Decimal(str(v))  # noqa: E731


def test_expenses_and_purchase_payments():
    tag = secrets.token_hex(3).upper()
    before = client.get("/cash-sessions/current", headers=A)
    mine = before.json() if before.status_code == 200 else None
    if mine:
        client.post(f"/cash-registers/{mine['cash_register_id']}/release", headers={**A, "X-Branch-Id": mine["branch_id"]})
    branch = client.post("/branches", json={"name": f"Gastos {tag}", "code": f"G{tag}"}, headers=A).json()["id"]
    H = {**A, "X-Branch-Id": branch}
    reg = client.post("/cash-registers", json={"name": f"Caja G {tag}"}, headers=H).json()["id"]
    cash = next(m["id"] for m in client.get("/payment-methods", headers=A).json() if m["description"] == "Cash")
    product = client.post("/products", json={"name": f"Tornillo {tag}", "product_type_id": _seed("/product-types", "Product"),
                                             "unit_of_measure_id": _seed("/units", "Unit")}, headers=A).json()
    drawer = lambda: D(client.get("/cash-sessions/current", headers=A).json()["cash_balance"])
    expense = lambda **kw: client.post("/expenses", json={"description": f"Luz {tag}", "amount": 300, **kw}, headers=H)
    purchase_ids = []
    try:
        # No register occupied: cash can't be taken, but paying another way or owing works
        r = expense(cash_amount=100)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "no_register"
        owed = expense(other_amount=50).json()
        assert D(owed["paid"]) == 50 and D(owed["owed"]) == 250 and D(owed["paid_cash"]) == 0

        client.post(f"/cash-registers/{reg}/occupy", headers=H)
        client.post(f"/cash-registers/{reg}/movements", json={"movement_type": "Cash In", "payment_method_id": cash, "amount": 500}, headers=H)
        assert drawer() == 500

        # Not enough cash in the drawer; more than the amount
        r = expense(amount=700, cash_amount=600)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "not_enough_cash" and D(r.json()["detail"]["available"]) == 500
        assert expense(cash_amount=200, other_amount=200).json()["detail"]["code"] == "over_owed"

        # Part from the register, part another way, the rest owed
        e = expense(cash_amount=120, other_amount=80).json()
        assert (D(e["paid_cash"]), D(e["paid"]), D(e["owed"])) == (120, 200, 100) and drawer() == 380
        assert [p["source"] for p in e["payments"]] == ["CASH", "OTHER"] and e["payments"][0]["cash_register"] == f"Caja G {tag}"
        moves = client.get(f"/cash-registers/{reg}/movements", headers=H).json()["items"]
        assert moves[0]["movement_type"] == "Expense" and D(moves[0]["amount"]) == -120

        # Pay the rest later; over-paying is refused
        assert client.post(f"/expenses/{e['id']}/payments", json={"cash_amount": 150}, headers=H).json()["detail"]["code"] == "over_owed"
        e = client.post(f"/expenses/{e['id']}/payments", json={"cash_amount": 100}, headers=H).json()
        assert D(e["owed"]) == 0 and drawer() == 280

        # Lists and summary
        listed = lambda **q: {x["id"] for x in client.get("/expenses", params=q, headers=H).json()["items"]}
        assert listed(status="owed") == {owed["id"]} and listed(status="paid") == {e["id"]}
        s = client.get("/expenses/summary", headers=H).json()
        assert D(s["total"]) == 600 and D(s["owed"]) == 250

        # Edit: description yes, amount no
        assert client.patch(f"/expenses/{e['id']}", json={"description": f"Luz bimestral {tag}"}, headers=H).json()["description"] == f"Luz bimestral {tag}"

        # Void: its cash (120 + 100) goes back to the register
        v = client.request("DELETE", f"/expenses/{e['id']}", json={"reason": "Duplicado"}, headers=H).json()
        assert D(v["cash_returned"]) == 220 and drawer() == 500
        assert client.post(f"/expenses/{e['id']}/payments", json={"other_amount": 1}, headers=H).status_code == 409
        assert listed() == {owed["id"]} and listed(include_voided=True) == {owed["id"], e["id"]}

        # Purchases: same split; the drawer check; voiding returns the cash
        buy = lambda qty=10, **kw: client.post("/purchases", json={"items": [{"product_id": product["id"], "quantity": qty, "unit_cost": 40}], **kw}, headers=H)
        assert buy(qty=20, cash_amount=600).json()["detail"]["code"] == "not_enough_cash"
        p = buy(cash_amount=250, other_amount=50).json()
        purchase_ids.append(p["id"])
        assert (D(p["paid_cash"]), D(p["owed"])) == (250, 100) and drawer() == 250
        assert {x["id"] for x in client.get("/purchases", params={"status": "owed"}, headers=H).json()["items"]} == {p["id"]}
        p = client.post(f"/purchases/{p['id']}/payments", json={"other_amount": 100}, headers=H).json()
        assert D(p["owed"]) == 0
        v = client.delete(f"/purchases/{p['id']}", headers=H).json()
        assert D(v["cash_returned"]) == 250 and drawer() == 500
        moves = client.get(f"/cash-registers/{reg}/movements", headers=H).json()["items"]
        assert moves[0]["movement_type"] == "Purchase" and D(moves[0]["amount"]) == 250

        # Without paying anything the whole purchase is owed
        p2 = buy().json()
        purchase_ids.append(p2["id"])
        assert D(p2["owed"]) == 400 and p2["payments"] == []
    finally:
        for pid in purchase_ids:
            client.delete(f"/purchases/{pid}", headers=H)
        for x in client.get("/expenses", headers=H).json().get("items", []):
            client.request("DELETE", f"/expenses/{x['id']}", json={"reason": "Limpieza test"}, headers=H)
        left = D(client.get("/cash-sessions/current", headers=A).json().get("cash_balance", 0)) if client.get("/cash-sessions/current", headers=A).status_code == 200 else 0
        if left:
            client.post(f"/cash-registers/{reg}/movements", json={"movement_type": "Cash Out", "payment_method_id": cash, "amount": str(left), "notes": "Limpieza test"}, headers=H)
        client.post(f"/cash-registers/{reg}/release", headers=H)
        client.delete(f"/cash-registers/{reg}", headers=H)
        client.delete(f"/products/{product['id']}", headers=A)
        client.delete(f"/branches/{branch}", headers=A)
        if mine:  # give the admin's register back
            client.post(f"/cash-registers/{mine['cash_register_id']}/occupy", headers={**A, "X-Branch-Id": mine["branch_id"]})
