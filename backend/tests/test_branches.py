# Integration test against the real DB. Open cash sessions and issued folios have no API yet, so they're set up
# with SQL. Creates soft-deleted test branches with unique codes per run.
# docker compose run --rm -v ./tests:/code/tests api sh -c "pip install -q pytest httpx && python -m pytest -q tests"
import secrets
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.infrastructure.api.permissions import CurrentBranch
from app.infrastructure.persistence.database import SessionLocal
from app.main import app_error
from app.application.errors import AppError
from tests.test_calendar import ADMIN, OTHER, A, B, client


def _sql(query, **params):
    with SessionLocal() as s:
        result = s.execute(text(query), params)
        row = result.first() if result.returns_rows else None
        s.commit()
        return row[0] if row else None


def _code():
    return "T" + secrets.token_hex(3).upper()


def _set_branch_perms(user_id, perms):
    module = next(m for m in client.get("/modules", headers=A).json() if m["code"] == "branches")
    ids = [p["id"] for p in module["permissions"] if p["code"] in perms]
    mods = [{"module_id": module["id"], "permission_ids": ids}] if perms else []
    assert client.put(f"/users/{user_id}/modules", json={"modules": mods}, headers=A).status_code == 200


def test_branch_crud_and_rules():
    code = _code()
    r = client.post("/branches", json={"name": f"Sucursal Prueba {code}", "code": f" {code.lower()} ",
                                       "phone": "(55) 1234-5678"}, headers=A)
    assert r.status_code == 201, r.text
    br = r.json()
    bid = br["id"]
    assert br["code"] == code and br["phone"] == "5512345678" and br["code_editable"] is True
    # The creator joins the branch automatically
    assert br["user_count"] == 1 and [m["id"] for m in client.get(f"/branches/{bid}/users", headers=A).json()] == [str(ADMIN)]

    assert client.post("/branches", json={"name": "Otra", "code": code}, headers=A).json()["detail"]["fields"] == ["code"]
    assert client.post("/branches", json={"name": f"sucursal prueba {code.lower()}", "code": _code()},
                       headers=A).status_code == 409
    for bad in [{"code": "AB-1"}, {"code": "ABCDEFGHIJK"}, {"phone": "123"}, {"name": " "}]:
        assert client.post("/branches", json={"name": "X", "code": _code(), **bad}, headers=A).status_code == 422, bad

    # Code editable until the first folio is issued
    new_code = _code()
    assert client.patch(f"/branches/{bid}", json={"code": new_code}, headers=A).json()["code"] == new_code
    _sql("SELECT fn_next_folio(:b, 'sale')", b=bid)
    r = client.patch(f"/branches/{bid}", json={"code": _code()}, headers=A)
    assert r.status_code == 409 and r.json()["detail"]["field"] == "code"
    assert client.patch(f"/branches/{bid}", json={"name": f"Sucursal Prueba {code} Centro"}, headers=A).status_code == 200
    assert client.patch(f"/branches/{bid}", json={"name": None}, headers=A).status_code == 422

    # Members, and an open cash session blocking both removing the user and deleting the branch
    assert client.post(f"/branches/{bid}/users", json={"user_id": str(OTHER)}, headers=A).status_code == 204
    assert client.post(f"/branches/{bid}/users", json={"user_id": str(OTHER)}, headers=A).status_code == 409
    assert {m["id"] for m in client.get(f"/branches/{bid}/users", headers=A).json()} == {str(ADMIN), str(OTHER)}
    register = _sql("""INSERT INTO cash_registers (branch_id, name, created_by, updated_by)
                       VALUES (:b, 'Caja prueba', :a, :a) RETURNING id""", b=bid, a=ADMIN)
    session = _sql("INSERT INTO cash_register_sessions (cash_register_id, user_id) VALUES (:r, :u) RETURNING id",
                   r=register, u=OTHER)
    r = client.delete(f"/branches/{bid}/users/{OTHER}", headers=A)
    assert r.status_code == 409 and r.json()["detail"]["open"] == {"open_cash_sessions": 1}
    r = client.delete(f"/branches/{bid}", headers=A)
    assert r.status_code == 409 and r.json()["detail"]["blockers"] == {"open_cash_sessions": 1}
    _sql("UPDATE cash_register_sessions SET ended_at = NOW(), ended_by = :u WHERE id = :s", u=OTHER, s=session)

    # Replace the full set for a user
    assert str(bid) in [b["id"] for b in client.get(f"/users/{OTHER}/branches", headers=A).json()]
    assert client.put(f"/users/{OTHER}/branches", json={"branch_ids": []}, headers=A).json() == []
    assert client.put(f"/users/{OTHER}/branches", json={"branch_ids": [str(uuid.uuid4())]}, headers=A).status_code == 422

    # Delete, restore, and a restore blocked by a new branch that took the code
    assert client.delete(f"/branches/{bid}", headers=A).status_code == 204
    assert client.get(f"/branches/{bid}", headers=A).json()["deleted_at"] is not None
    assert bid not in [b["id"] for b in client.get("/branches", headers=A).json()]
    assert bid in [b["id"] for b in client.get("/branches", params={"include_deleted": True}, headers=A).json()]
    assert client.post(f"/branches/{bid}/restore", headers=A).status_code == 200
    assert client.delete(f"/branches/{bid}", headers=A).status_code == 204
    taker = client.post("/branches", json={"name": "Toma el código", "code": new_code}, headers=A).json()
    assert client.post(f"/branches/{bid}/restore", headers=A).status_code == 409
    client.delete(f"/branches/{taker['id']}", headers=A)

    items = client.get(f"/branches/{bid}/history", headers=A).json()["items"]
    actions = [(h["entity_type"], h["action"]) for h in items]
    memberships = [(h["action"], h["member_email"]) for h in items if h["entity_type"] == "user_branch"]
    assert ("INSERT", "admin") in memberships and ("DELETE", "calendar-test@example.com") in memberships
    assert ("branch", "INSERT") in actions and ("user_branch", "DELETE") in actions and ("branch", "RESTORE") in actions


def test_visibility_and_escalation():
    br = client.post("/branches", json={"name": f"Sucursal Escalada {_code()}", "code": _code()}, headers=A).json()
    try:
        # Without branches.read you only see your own branches
        client.put(f"/users/{OTHER}/branches", json={"branch_ids": [br["id"]]}, headers=A)
        assert [b["id"] for b in client.get("/branches", headers=B).json()] == [br["id"]]
        assert client.get(f"/branches/{br['id']}/users", headers=B).status_code == 403

        # With branches.update B can manage its own branch, but not hand out one it isn't in
        _set_branch_perms(OTHER, {"read", "update"})
        seed = next(b for b in client.get(f"/users/{ADMIN}/branches", headers=A).json() if b["id"] != br["id"])
        assert client.put(f"/users/{OTHER}/branches", json={"branch_ids": [br["id"], seed["id"]]},
                          headers=B).status_code == 403
        assert client.delete(f"/branches/{br['id']}/users/{ADMIN}", headers=B).status_code == 204
        assert client.post(f"/branches/{br['id']}/users", json={"user_id": str(ADMIN)}, headers=B).status_code == 204
    finally:
        _set_branch_perms(OTHER, set())
        client.put(f"/users/{OTHER}/branches", json={"branch_ids": []}, headers=A)
        client.delete(f"/branches/{br['id']}", headers=A)


def test_current_branch_header():
    """The dependency every branch-scoped endpoint will use (no such endpoint exists yet)."""
    probe = FastAPI()
    probe.add_exception_handler(AppError, app_error)

    @probe.get("/probe")
    def endpoint(branch: CurrentBranch):
        return {"branch": str(branch)}

    c = TestClient(probe)
    mine = client.get(f"/users/{ADMIN}/branches", headers=A).json()[0]["id"]
    assert c.get("/probe", headers={**A, "X-Branch-Id": mine}).json() == {"branch": mine}
    assert c.get("/probe", headers=A).status_code == 422  # header missing
    assert c.get("/probe", headers={**A, "X-Branch-Id": str(uuid.uuid4())}).status_code == 403
    assert c.get("/probe", headers={**B, "X-Branch-Id": mine}).status_code == 403  # B isn't in it
