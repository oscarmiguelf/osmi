# Integration test against the real DB, on a throwaway branch (soft-deleted at the end).
# docker compose run --rm -v ./tests:/code/tests api sh -c "pip install -q pytest httpx && python -m pytest -q tests"
import secrets
import uuid
from decimal import Decimal

import pytest

from tests.test_calendar import ADMIN, OTHER, A, B, client


def _set_cash_perms(user_id, perms):
    module = next(m for m in client.get("/modules", headers=A).json() if m["code"] == "cash")
    ids = [p["id"] for p in module["permissions"] if p["code"] in perms]
    mods = [{"module_id": module["id"], "permission_ids": ids}] if perms else []
    assert client.put(f"/users/{user_id}/modules", json={"modules": mods}, headers=A).status_code == 200


def _release_current(headers):
    """Frees the register the user holds (their own, put back by the fixture). Returns it."""
    current = client.get("/cash-sessions/current", headers=headers)
    if current.status_code == 200:
        s = current.json()
        client.post(f"/cash-registers/{s['cash_register_id']}/release", headers={**headers, "X-Branch-Id": s["branch_id"]})
        return s
    return None


@pytest.fixture
def branch():
    mine = _release_current(A)  # the admin's own open register: back to them at the end
    code = "C" + secrets.token_hex(3).upper()
    br = client.post("/branches", json={"name": f"Caja Prueba {code}", "code": code}, headers=A).json()
    for user in (ADMIN, OTHER):
        client.post(f"/branches/{br['id']}/users", json={"user_id": str(user)}, headers=A)
    yield br["id"]
    _release_current(A)
    for user in (ADMIN, OTHER):
        client.delete(f"/branches/{br['id']}/users/{user}", headers=A)
    client.delete(f"/branches/{br['id']}", headers=A)
    if mine:
        client.post(f"/cash-registers/{mine['cash_register_id']}/occupy", headers={**A, "X-Branch-Id": mine["branch_id"]})


def test_cash_flow(branch):
    HA, HB = {**A, "X-Branch-Id": branch}, {**B, "X-Branch-Id": branch}
    methods = {m["description"]: m for m in client.get("/payment-methods", params={"include_disabled": True}, headers=A).json()}
    cash, card, credit = methods["Cash"]["id"], methods["Card"]["id"], methods["Credit"]["id"]

    assert client.get("/cash-registers", headers=A).status_code == 422  # no X-Branch-Id
    assert client.get("/cash-registers", headers={**A, "X-Branch-Id": str(uuid.uuid4())}).status_code == 403
    assert client.get("/cash-registers", headers=HB).status_code == 403  # B has no cash.read yet

    # Registers
    r1 = client.post("/cash-registers", json={"name": "Caja 1"}, headers=HA).json()
    r2 = client.post("/cash-registers", json={"name": "Caja 2"}, headers=HA).json()
    assert client.post("/cash-registers", json={"name": "caja 1"}, headers=HA).status_code == 409
    assert [r["name"] for r in client.get("/cash-registers", headers=HA).json()] == ["Caja 1", "Caja 2"]
    base = f"/cash-registers/{r1['id']}"

    # Occupy: once per register, once per user, and "continue" with the one you hold
    assert client.get("/cash-sessions/current", headers=A).status_code == 204
    s = client.post(f"{base}/occupy", headers=HA).json()
    assert s["cash_register_id"] == r1["id"]
    assert client.post(f"{base}/occupy", headers=HA).json()["id"] == s["id"]
    r = client.post(f"/cash-registers/{r2['id']}/occupy", headers=HA)
    assert r.status_code == 409 and r.json()["detail"]["session"]["cash_register_id"] == r1["id"]
    assert client.get("/cash-sessions/current", headers=A).json()["cash_register"] == "Caja 1"

    # Manual movements: sign from the type, notes, credit/disabled methods, no overdrawing
    mv = lambda body, h=HA: client.post(f"{base}/movements", json=body, headers=h)
    assert Decimal(str(mv({"movement_type": "Cash In", "payment_method_id": cash, "amount": -500}).json()["amount"])) == 500
    assert mv({"movement_type": "Cash Out", "payment_method_id": cash, "amount": 800, "notes": "Banco"}).status_code == 422
    assert mv({"movement_type": "Cash Out", "payment_method_id": cash, "amount": 200}).status_code == 422  # note required
    out = mv({"movement_type": "Cash Out", "payment_method_id": cash, "amount": 200, "notes": "Depósito banco"}).json()
    assert Decimal(str(out["amount"])) == -200 and Decimal(str(out["balance_after"])) == 300
    assert mv({"movement_type": "Adjustment", "payment_method_id": cash, "amount": -10, "notes": "Faltante"}).status_code == 422  # not manual
    assert mv({"movement_type": "Cash Out", "payment_method_id": cash, "amount": 10, "notes": "Faltante"}).status_code == 201
    assert mv({"movement_type": "Cash In", "payment_method_id": credit, "amount": 10}).status_code == 422
    assert mv({"movement_type": "Sale", "payment_method_id": cash, "amount": 10}).status_code == 422
    client.patch(f"/payment-methods/{card}", json={"is_enabled": False}, headers=A)
    try:
        assert mv({"movement_type": "Cash In", "payment_method_id": card, "amount": 10}).status_code == 422
        assert card not in [m["id"] for m in client.get("/payment-methods", headers=A).json()]
    finally:
        client.patch(f"/payment-methods/{card}", json={"is_enabled": True}, headers=A)

    balances = {b["description"]: Decimal(str(b["balance"])) for b in client.get(f"{base}/balances", headers=HA).json()}
    assert balances["Cash"] == 290 and balances["Card"] == 0 and "Credit" not in balances
    outs = client.get(f"{base}/movements", params={"type": "Cash Out"}, headers=HA).json()["items"]
    assert [o["notes"] for o in outs] == ["Faltante", "Depósito banco"]  # newest first
    assert client.get(f"{base}/sales-totals", params={"from": "2026-01-01T00:00:00Z", "to": "2027-01-01T00:00:00Z"},
                      headers=HA).json() == []

    # Another cashier: can't take, operate or release a register someone else holds
    _set_cash_perms(OTHER, {"read", "create"})
    try:
        assert client.post(f"{base}/occupy", headers=HB).status_code == 409
        assert mv({"movement_type": "Cash In", "payment_method_id": cash, "amount": 5}, HB).status_code == 403
        assert client.post(f"{base}/release", headers=HB).status_code == 403
        assert client.post(f"{base}/release", params={"force": True}, headers=HB).status_code == 403  # not a supervisor

        # Cut: expected from the locked balances, difference generated by the DB. It closes the turn: the cash stays at
        # what was counted minus the cut withdrawal, card goes back to 0 (counted and handed in), the register is released
        client.post(f"{base}/movements", json={"movement_type": "Cash In", "payment_method_id": card, "amount": 150}, headers=HA)
        counts = [{"payment_method_id": cash, "counted": 280}, {"payment_method_id": card, "counted": 140}]
        r = client.post(f"{base}/cuts", json={"counts": counts, "withdrawal": 281}, headers=HA)
        assert r.status_code == 422 and r.json()["detail"]["field"] == "withdrawal"  # more than the cash counted
        assert client.post(f"{base}/cuts", json={"counts": counts, "withdrawal": -1}, headers=HA).status_code == 422
        cut = client.post(f"{base}/cuts", json={"counts": counts, "notes": "Cierre turno", "withdrawal": 200,
                                                "withdrawal_reason": "Depósito al banco"}, headers=HA).json()
        by_method = {d["payment_method"]: d for d in cut["details"]}
        assert Decimal(str(by_method["Cash"]["expected_amount"])) == 290 and Decimal(str(by_method["Cash"]["difference"])) == -10
        assert Decimal(str(by_method["Card"]["expected_amount"])) == 150 and Decimal(str(by_method["Card"]["difference"])) == -10
        assert Decimal(str(cut["withdrawn"])) == 200 and cut["withdrawal_reason"] == "Depósito al banco"
        after = {b["description"]: Decimal(str(b["balance"])) for b in client.get(f"{base}/balances", headers=HA).json()}
        assert after["Cash"] == 80 and after["Card"] == 0
        moves = client.get(f"{base}/movements", headers=HA).json()["items"]
        assert sorted((m["movement_type"], Decimal(str(m["amount"]))) for m in moves[:3]) == [
            ("Cash Out", Decimal(-200)), ("Cut", Decimal(-150)), ("Cut", Decimal(-10))]
        assert client.get("/cash-sessions/current", headers=A).status_code == 204  # released
        client.post(f"{base}/occupy", headers=HA)
        second = client.post(f"{base}/cuts", json={"counts": [{"payment_method_id": cash, "counted": 80}]}, headers=HA)
        assert second.status_code == 201 and second.json()["started_at"] == cut["ended_at"]  # periods chain, no overlap
        assert Decimal(str(second.json()["withdrawn"])) == 0 and second.json()["withdrawal_reason"] is None
        client.post(f"{base}/occupy", headers=HA)
        assert client.post(f"{base}/cuts", json={"counts": []}, headers=HA).status_code == 422
        r = client.post(f"{base}/cuts", json={"counts": [{"payment_method_id": card, "counted": 0}]}, headers=HA)
        assert r.status_code == 422 and r.json()["detail"]["missing"] == [cash]  # cash has money and wasn't counted
        assert client.post(f"{base}/cuts", json={"counts": [{"payment_method_id": credit, "counted": 1}]},
                           headers=HA).status_code == 422
        assert [c["id"] for c in client.get(f"{base}/cuts", headers=HA).json()["items"]] == [second.json()["id"], cut["id"]]
        assert client.get(f"/cash-cuts/{cut['id']}", headers=HB).json()["id"] == cut["id"]  # same branch can view
        seed = next(b["id"] for b in client.get(f"/users/{ADMIN}/branches", headers=A).json() if b["id"] != branch)
        assert client.get(f"/cash-cuts/{cut['id']}", headers={**A, "X-Branch-Id": seed}).status_code == 404

        # Can't delete an occupied register with money in it
        r = client.delete(base, headers=HA)
        assert r.status_code == 409 and set(r.json()["detail"]["blockers"]) == {"occupied_by", "nonzero_balances"}

        # Release; B takes it; a supervisor (admin) force-releases B's session
        assert client.post(f"{base}/release", headers=HA).status_code == 200
        assert client.post(f"{base}/occupy", headers=HB).status_code == 200
        assert client.post(f"{base}/release", headers=HA).status_code == 403  # without force
        assert client.post(f"{base}/release", params={"force": True}, headers=HA).json()["ended_by"] == str(ADMIN)
    finally:
        _set_cash_perms(OTHER, set())

    # Empty the drawer, then delete and restore
    client.post(f"{base}/occupy", headers=HA)
    mv({"movement_type": "Cash Out", "payment_method_id": cash, "amount": 80, "notes": "Retiro final"})
    client.post(f"{base}/release", headers=HA)
    assert client.delete(base, headers=HA).status_code == 204
    assert client.post(f"{base}/restore", headers=HA).status_code == 200
    assert [h["action"] for h in client.get(f"{base}/history", headers=HA).json()["items"]][:2] == ["RESTORE", "DELETE"]
    for reg in (r1, r2):
        client.delete(f"/cash-registers/{reg['id']}", headers=HA)
