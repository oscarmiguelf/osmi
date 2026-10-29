# Integration test against the real DB (seed admin + the helper user from test_calendar), plus a unit test with a
# fake repository for the rules that need customer debt, which only credit sales can create.
# docker compose run --rm -v ./tests:/code/tests api sh -c "pip install -q pytest httpx && python -m pytest -q tests"
import secrets
import uuid
from decimal import Decimal

import pytest

from app.application.customer_service import CustomerService
from app.application.errors import Conflict
from tests.test_calendar import OTHER, A, B, client


def _phone():
    return "55" + "".join(secrets.choice("0123456789") for _ in range(8))


def _set_access(user_id, perms):
    """Give user_id the customers module with these permission codes (admin is the super admin)."""
    module = next(m for m in client.get("/modules", headers=A).json() if m["code"] == "customers")
    ids = [p["id"] for p in module["permissions"] if p["code"] in perms]
    mods = [{"module_id": module["id"], "permission_ids": ids}] if perms else []
    assert client.put(f"/users/{user_id}/modules", json={"modules": mods}, headers=A).status_code == 200


def test_customer_crud_search_history():
    assert client.get("/customers", headers=B).status_code == 403

    phone = _phone()
    pretty = f"({phone[:2]}) {phone[2:6]}-{phone[6:]}"
    r = client.post("/customers", json={
        "full_name": "  Ferretería López  ", "phone": pretty, "email": "compras@lopez.mx",
        "company": "Ferretería López SA", "credit_limit": 1500.5,
    }, headers=A)
    assert r.status_code == 201, r.text
    c = r.json()
    cid = c["id"]
    assert c["phone"] == phone and c["full_name"] == "Ferretería López" and c["warnings"] == []
    assert float(c["credit_limit"]) == 1500.5

    # Same phone is allowed, with a warning
    twin = client.post("/customers", json={"full_name": "Sucursal López", "phone": phone}, headers=A).json()
    assert twin["warnings"] == [{"code": "duplicate_phone", "count": 1}]

    for bad, field in [({"phone": "55123"}, "phone"), ({"email": "nope@"}, "email"), ({"full_name": "  "}, "full_name"),
                       ({"credit_limit": -1}, "credit_limit"), ({"credit_limit": 1.234}, "credit_limit"),
                       ({"additional_phone": "+52 5512345678"}, "additional_phone")]:
        r = client.post("/customers", json={"full_name": "X", "phone": _phone(), **bad}, headers=A)
        assert r.status_code == 422 and r.json()["detail"][0]["loc"][-1] == field, (bad, r.text)

    # Search: name (any case), phone typed with spaces, company; paginated with total
    for q in ["ferretería lóp", f"{phone[:2]} {phone[2:6]}", "lopez sa"]:
        found = client.get("/customers", params={"q": q}, headers=A).json()
        assert cid in [i["id"] for i in found["items"]], q
    page = client.get("/customers", params={"q": phone, "page_size": 1}, headers=A).json()
    assert page["total"] == 2 and len(page["items"]) == 1
    assert client.get("/customers", params={"page_size": 101}, headers=A).status_code == 422

    # PATCH is partial; null clears optional fields but not required ones
    r = client.patch(f"/customers/{cid}", json={"company": "Ferretería López y Asociados", "email": None}, headers=A)
    assert r.status_code == 200 and r.json()["email"] is None and r.json()["phone"] == phone
    assert client.patch(f"/customers/{cid}", json={"full_name": None}, headers=A).status_code == 422

    credit = client.get(f"/customers/{cid}/credit", headers=A).json()
    assert float(credit["credit_limit"]) == 1500.5 and float(credit["balance"]) == 0
    assert float(credit["available_credit"]) == 1500.5
    for path in ["credit/movements", "credit/pending-sales", "sales"]:
        r = client.get(f"/customers/{cid}/{path}", headers=A)
        assert r.status_code == 200 and r.json()["items"] == [] and r.json()["has_more"] is False, path

    # Soft delete, still readable by id, hidden from search, restorable once
    assert client.delete(f"/customers/{cid}", headers=A).status_code == 204
    assert client.get(f"/customers/{cid}", headers=A).json()["deleted_at"] is not None
    assert cid not in [i["id"] for i in client.get("/customers", params={"q": phone}, headers=A).json()["items"]]
    assert client.patch(f"/customers/{cid}", json={"company": "x"}, headers=A).status_code == 404
    assert client.post(f"/customers/{cid}/restore", headers=A).status_code == 200
    assert client.post(f"/customers/{cid}/restore", headers=A).status_code == 404

    history = client.get(f"/customers/{cid}/history", headers=A).json()["items"]
    assert [h["action"] for h in history] == ["RESTORE", "DELETE", "UPDATE", "INSERT"]
    assert "company" in history[2]["changed_fields"] and history[0]["changed_by_email"] == "admin"

    assert client.get(f"/customers/{uuid.uuid4()}", headers=A).status_code == 404
    for c_id in (cid, twin["id"]):
        client.delete(f"/customers/{c_id}", headers=A)


def test_credit_limit_needs_its_own_permission():
    _set_access(OTHER, {"read", "create", "update"})
    try:
        assert client.post("/customers", json={"full_name": "Sin crédito", "phone": _phone(), "credit_limit": 100},
                           headers=B).status_code == 403
        r = client.post("/customers", json={"full_name": "Sin crédito", "phone": _phone()}, headers=B)
        assert r.status_code == 201
        cid = r.json()["id"]
        # Resending the unchanged limit (a full form) is fine; changing it is not
        assert client.patch(f"/customers/{cid}", json={"company": "Acme", "credit_limit": 0}, headers=B).status_code == 200
        assert client.patch(f"/customers/{cid}", json={"credit_limit": 50}, headers=B).status_code == 403
        assert client.delete(f"/customers/{cid}", headers=B).status_code == 403  # no customers.delete
        assert client.patch(f"/customers/{cid}", json={"credit_limit": 50}, headers=A).status_code == 200
        client.delete(f"/customers/{cid}", headers=A)
    finally:
        _set_access(OTHER, set())


class FakeRepo:
    def __init__(self, balance):
        self.row = {"id": "c1", "phone": "5512345678", "credit_limit": Decimal("500"), "deleted_at": None}
        self._balance = Decimal(balance)
        self.deleted = False

    def get(self, cid): return self.row
    def balance(self, cid): return self._balance
    def has_permission(self, *args): return True
    def update(self, uid, cid, fields): return {**self.row, **fields}
    def count_same_phone(self, *args): return 0
    def delete(self, uid, cid): self.deleted = True
    def commit(self): pass


def test_customer_with_debt_cannot_be_deleted():
    repo = FakeRepo("120.50")
    with pytest.raises(Conflict) as err:
        CustomerService(repo, None).delete("u1", "c1")
    assert err.value.detail["balance"] == Decimal("120.50") and not repo.deleted
    CustomerService(FakeRepo("0"), None).delete("u1", "c1")


def test_limit_below_debt_is_saved_with_a_warning():
    row = CustomerService(FakeRepo("300"), None).update("u1", "c1", {"credit_limit": Decimal("100")})
    assert row["credit_limit"] == Decimal("100")
    assert row["warnings"] == [{"code": "credit_limit_below_balance", "balance": Decimal("300")}]


def test_event_linked_to_customer():
    cust = client.post("/customers", json={"full_name": "Cliente Evento", "phone": _phone()}, headers=A).json()
    gone = client.post("/customers", json={"full_name": "Cliente Borrado", "phone": _phone()}, headers=A).json()
    client.delete(f"/customers/{gone['id']}", headers=A)
    cal = client.post("/calendars", json={"name": "Visitas"}, headers=A).json()
    ev = {"title": "Visita", "start_at": "2026-12-01T16:00:00Z", "end_at": "2026-12-01T17:00:00Z"}

    r = client.post(f"/calendars/{cal['id']}/events", json={**ev, "customer_id": cust["id"]}, headers=A)
    assert r.status_code == 201 and r.json()["customer_id"] == cust["id"]
    eid = r.json()["id"]
    got = client.get(f"/events/{eid}", headers=A).json()
    assert got["customer_name"] == "Cliente Evento" and got["customer_deleted"] is False

    assert client.post(f"/calendars/{cal['id']}/events", json={**ev, "customer_id": gone["id"]},
                       headers=A).status_code == 422
    assert client.patch(f"/events/{eid}", json={"customer_id": str(uuid.uuid4())}, headers=A).status_code == 422

    # Deleting the customer later keeps the link visible and the event editable
    client.delete(f"/customers/{cust['id']}", headers=A)
    assert client.patch(f"/events/{eid}", json={"title": "Visita (reagendar)"}, headers=A).status_code == 200
    got = client.get(f"/events/{eid}", headers=A).json()
    assert got["customer_deleted"] is True and got["customer_id"] == cust["id"]
    assert client.patch(f"/events/{eid}", json={"customer_id": None}, headers=A).json()["customer_id"] is None

    client.delete(f"/calendars/{cal['id']}", headers=A)
