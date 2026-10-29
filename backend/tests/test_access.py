# Integration test against the real DB. Creates one soft-deleted test module per run (codes can't be reused).
# docker compose run --rm -v ./tests:/code/tests api sh -c "pip install -q pytest httpx && python -m pytest -q tests"
import secrets

from sqlalchemy import text

from app.infrastructure.persistence.database import SessionLocal

from tests.test_calendar import ADMIN, OTHER, A, B, client


def _module(code):
    return next(m for m in client.get("/modules", params={"include_inactive": True}, headers=A).json()
                if m["code"] == code)


def test_modules_permissions_and_access():
    assert client.get("/modules", headers=B).status_code == 403  # no users.read

    code = "t_" + secrets.token_hex(4)
    r = client.post("/modules", json={"code": code, "name": "Test", "with_crud_permissions": True}, headers=A)
    assert r.status_code == 201, r.text
    mod = r.json()
    mid = mod["id"]
    perms = {p["code"]: p["id"] for p in mod["permissions"]}
    assert set(perms) == {"read", "create", "update", "delete"}
    assert client.post("/modules", json={"code": code, "name": "Again"}, headers=A).status_code == 409
    assert client.post("/modules", json={"code": "Bad-Code", "name": "x"}, headers=A).status_code == 422

    assert client.patch(f"/modules/{mid}", json={"is_active": False}, headers=A).json()["is_active"] is False
    assert all(m["id"] != mid for m in client.get("/modules", headers=A).json())
    assert client.patch(f"/modules/{mid}", json={"is_active": True, "name": None}, headers=A).status_code == 422
    client.patch(f"/modules/{mid}", json={"is_active": True}, headers=A)

    # Permission lifecycle: create, conflict, delete, conflict points to restore, restore
    exp = client.post(f"/modules/{mid}/permissions", json={"code": "export", "name": "Export"}, headers=A)
    assert exp.status_code == 201
    pexp = exp.json()["id"]
    assert client.delete(f"/permissions/{pexp}", headers=A).status_code == 204
    again = client.post(f"/modules/{mid}/permissions", json={"code": "export", "name": "Export"}, headers=A)
    assert again.status_code == 409 and f"/permissions/{pexp}/restore" in again.json()["detail"]
    assert client.post(f"/permissions/{pexp}/restore", headers=A).status_code == 200

    users = _module("users")
    assert client.delete(f"/modules/{users['id']}", headers=A).status_code == 422
    assert client.patch(f"/modules/{users['id']}", json={"is_active": False}, headers=A).status_code == 422

    # Access: admin (super admin) grants a module nobody holds yet
    upd = {p["code"]: p["id"] for p in users["permissions"]}
    put = lambda uid, mods, h=A: client.put(f"/users/{uid}/modules", json={"modules": mods}, headers=h)
    grant_b = [{"module_id": mid, "permission_ids": [perms["read"]]},
               {"module_id": users["id"], "permission_ids": [upd["read"], upd["update"]]}]
    assert put(OTHER, grant_b).status_code == 200
    access = {m["module_id"]: m for m in client.get(f"/users/{OTHER}/access", headers=A).json()}
    assert access[mid]["has_module"]
    assert {p["code"] for p in access[mid]["permissions"] if p["granted"]} == {"read"}

    assert put(OTHER, [{"module_id": mid, "permission_ids": [upd["read"]]}]).status_code == 422  # wrong module
    assert put(OTHER, grant_b + grant_b[:1]).status_code == 422  # module twice

    # Escalation: B holds only test.read, so it can't give itself test.create
    assert put(OTHER, grant_b, B).status_code == 200  # no change is fine
    escalate = [{**grant_b[0], "permission_ids": [perms["read"], perms["create"]]}, grant_b[1]]
    assert put(OTHER, escalate, B).status_code == 403

    # Lockout: once B loses users access, admin can't drop its own users module
    assert put(OTHER, []).status_code == 200
    mine = [{"module_id": m["module_id"], "permission_ids": [p["id"] for p in m["permissions"] if p["granted"]]}
            for m in client.get(f"/users/{ADMIN}/access", headers=A).json() if m["has_module"]]
    # Only provable while admin is the only one who can manage access: when a real user can too, the change would
    # go through and leave admin without the users module, so it isn't tried
    with SessionLocal() as s:
        others = s.execute(text("""
            SELECT 1 FROM user_module_permissions ump
            JOIN permissions p ON p.id = ump.permission_id AND p.deleted_at IS NULL AND p.code = 'update'
            JOIN modules m ON m.id = ump.module_id AND m.deleted_at IS NULL AND m.is_active AND m.code = 'users'
            JOIN users u ON u.id = ump.user_id AND u.is_active AND u.deleted_at IS NULL
            WHERE u.id <> :admin LIMIT 1
        """), {"admin": ADMIN}).first()
    if others is None:
        assert put(ADMIN, [m for m in mine if m["module_id"] != users["id"]]).status_code == 422
    assert client.get("/modules", headers=A).status_code == 200  # still has access

    assert client.delete(f"/modules/{mid}", headers=A).status_code == 204
    assert client.get(f"/modules/{mid}", headers=A).json()["deleted_at"] is not None
