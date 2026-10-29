# Integration test against the real DB (users are soft-deleted at the end; emails are unique per run),
# plus a unit test with a fake repository for the "last admin" rule, which real data can't trigger.
# docker compose run --rm -v ./tests:/code/tests api sh -c "pip install -q pytest httpx && python -m pytest -q tests"
import secrets
import uuid

import pytest

from app.application.errors import Conflict, Invalid
from app.application.user_service import UserService
from tests.test_calendar import ADMIN, A, B, client


def _email(name):
    return f"{name}-{secrets.token_hex(3)}@prueba.mx"


def _login(email, password):
    return client.post("/auth/login", json={"email": email, "password": password}, headers={"x-client": "mobile"})


def _bearer(email, password):
    return {"Authorization": f"Bearer {_login(email, password).json()['access_token']}"}


def _grant(user_id, grants: dict[str, set[str]]):
    """Give user_id exactly these module permissions, e.g. {'users': {'read'}}."""
    modules = {m["code"]: m for m in client.get("/modules", headers=A).json()}
    body = [{"module_id": modules[code]["id"],
             "permission_ids": [p["id"] for p in modules[code]["permissions"] if p["code"] in perms]}
            for code, perms in grants.items()]
    assert client.put(f"/users/{user_id}/modules", json={"modules": body}, headers=A).status_code == 200


@pytest.fixture
def made():
    created = []
    yield created
    for user_id in created:
        client.delete(f"/users/{user_id}", headers=A)


def test_create_policy_and_first_login(made):
    assert client.get("/users", headers=B).status_code == 403

    email = _email("maria")
    r = client.post("/users", json={"email": f"  {email.upper()} ", "first_name": "María", "last_name": "López"}, headers=A)
    assert r.status_code == 201, r.text
    user = r.json()
    made.append(user["id"])
    temp = user["temporary_password"]
    assert user["email"] == email and user["must_change_password"] is True and user["created_by_email"] == "admin"
    assert "password_hash" not in user and user["timezone"] == "America/Mexico_City"

    # Policy, duplicates, format
    for password, rules in [("12345678", ["too_common"]), ("corta", ["min_length"]), (None, ["same_as_email"])]:
        new_email = _email("x")  # None: the password is the new user's own email
        r = client.post("/users", json={"email": new_email, "first_name": "X", "last_name": "Y",
                                        "password": password or new_email}, headers=A)
        assert r.status_code == 422 and r.json()["detail"]["rules"] == rules, r.text
    assert client.post("/users", json={"email": email, "first_name": "X", "last_name": "Y"}, headers=A).status_code == 409
    assert client.post("/users", json={"email": "no-es-correo", "first_name": "X", "last_name": "Y"}, headers=A).status_code == 422
    assert client.post("/users", json={"email": _email("x"), "first_name": "X", "last_name": "Y", "timezone": "Mars/Base"},
                       headers=A).status_code == 422

    # First login: the payload tells the front end to force a password change
    r = _login(email, temp)
    assert r.status_code == 200 and r.json()["user"]["must_change_password"] is True
    me = {"Authorization": f"Bearer {r.json()['access_token']}"}
    old_refresh = r.json()["refresh_token"]

    # /me: own profile and password, no users permission needed
    assert client.patch("/me", json={"first_name": "María José", "timezone": "America/Tijuana"}, headers=me).json()["timezone"] == "America/Tijuana"
    assert client.patch("/me", json={"timezone": "Nowhere/City"}, headers=me).status_code == 422
    r = client.post("/me/change-password", json={"current_password": "mala", "new_password": "Nueva-Clave-2026"}, headers=me)
    assert r.status_code == 422 and r.json()["detail"]["field"] == "current_password"
    r = client.post("/me/change-password", json={"current_password": temp, "new_password": "password"}, headers=me)
    assert r.status_code == 422 and "too_common" in r.json()["detail"]["rules"]
    assert client.post("/me/change-password", json={"current_password": temp, "new_password": temp}, headers=me).status_code == 422
    assert client.post("/me/change-password", json={"current_password": temp, "new_password": "Nueva-Clave-2026"},
                       headers=me).status_code == 204
    assert client.post("/auth/refresh", json={"refresh_token": old_refresh}).status_code == 401  # sessions ended
    assert _login(email, temp).status_code == 401
    r = _login(email, "Nueva-Clave-2026")
    assert r.status_code == 200 and r.json()["user"]["must_change_password"] is False


def test_admin_actions_and_audit(made):
    email = _email("pedro")
    user = client.post("/users", json={"email": email, "first_name": "Pedro", "last_name": "Ruiz",
                                       "password": "Pedro-Inicial-1"}, headers=A).json()
    uid = user["id"]
    made.append(uid)
    assert "temporary_password" not in user  # only generated passwords are echoed

    # List: search, status and branch filters
    found = client.get("/users", params={"q": "pedro ruiz"}, headers=A).json()
    assert uid in [u["id"] for u in found["items"]] and found["total"] >= 1
    branch = client.get(f"/users/{ADMIN}/branches", headers=A).json()[0]["id"]
    client.put(f"/users/{uid}/branches", json={"branch_ids": [branch]}, headers=A)
    assert uid in [u["id"] for u in client.get("/users", params={"branch_id": branch, "page_size": 100}, headers=A).json()["items"]]

    # Edit, and failed logins don't show up as admin changes in the history
    assert client.patch(f"/users/{uid}", json={"last_name": "Ruiz Gómez"}, headers=A).json()["last_name"] == "Ruiz Gómez"
    assert client.patch(f"/users/{uid}", json={"first_name": None}, headers=A).status_code == 422
    for _ in range(5):
        _login(email, "incorrecta")
    detail = client.get(f"/users/{uid}", headers=A).json()
    assert detail["is_locked"] is True
    assert client.post(f"/users/{uid}/unlock", headers=A).json()["is_locked"] is False

    # Sessions, logout-all, deactivate (ends sessions), activate
    first = _login(email, "Pedro-Inicial-1").json()
    assert len(client.get(f"/users/{uid}/sessions", headers=A).json()) == 1
    assert client.post(f"/users/{uid}/logout-all", headers=A).json()["revoked"] >= 1
    assert client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]}).status_code == 401
    second = _login(email, "Pedro-Inicial-1").json()
    assert client.post(f"/users/{uid}/deactivate", headers=A).json()["is_active"] is False
    assert client.post("/auth/refresh", json={"refresh_token": second["refresh_token"]}).status_code == 401
    assert _login(email, "Pedro-Inicial-1").status_code == 401
    assert client.post(f"/users/{uid}/activate", headers=A).json()["is_active"] is True

    # Admin reset: temporary password, must change, old one stops working
    reset = client.post(f"/users/{uid}/reset-password", json={}, headers=A).json()
    assert _login(email, "Pedro-Inicial-1").status_code == 401
    r = _login(email, reset["temporary_password"])
    assert r.status_code == 200 and r.json()["user"]["must_change_password"] is True

    events = [e["event_type"] for e in client.get(f"/users/{uid}/login-history", headers=A).json()["items"]]
    assert "account_locked" in events and "login_success" in events
    history = client.get(f"/users/{uid}/history", headers=A).json()["items"]
    fields = [f for h in history for f in (h["changed_fields"] or [])]
    assert history[-1]["action"] == "INSERT" and all(h["changed_by_email"] == "admin" for h in history)
    assert "failed_attempts" in fields  # the admin unlock is audited ...
    assert sum(1 for h in history if h["changed_fields"] == ["failed_attempts"]) == 0  # ... the 5 failed logins are not
    assert "password_hash" in fields and all("password_hash" not in (h["new_data"] or {}) for h in history)

    # Self-protection
    assert client.post(f"/users/{ADMIN}/deactivate", headers=A).status_code == 422
    assert client.delete(f"/users/{ADMIN}", headers=A).status_code == 422

    # Delete, restore, and restore blocked by a new user with the same email
    assert client.delete(f"/users/{uid}", headers=A).status_code == 204
    assert client.get("/users", params={"q": email}, headers=A).json()["total"] == 0
    assert uid in [u["id"] for u in client.get("/users", params={"q": email, "status": "deleted"}, headers=A).json()["items"]]
    assert client.post(f"/users/{uid}/restore", headers=A).status_code == 200
    client.delete(f"/users/{uid}", headers=A)
    taker = client.post("/users", json={"email": email, "first_name": "Otro", "last_name": "Pedro"}, headers=A).json()
    made.append(taker["id"])
    assert client.post(f"/users/{uid}/restore", headers=A).status_code == 409
    assert client.get(f"/users/{uuid.uuid4()}", headers=A).status_code == 404


def test_no_managing_users_with_more_access(made):
    manager_email = _email("gerente")
    manager = client.post("/users", json={"email": manager_email, "first_name": "Gerente", "last_name": "Uno",
                                          "password": "Gerente-Clave-1"}, headers=A).json()
    clerk = client.post("/users", json={"email": _email("cajero"), "first_name": "Cajero", "last_name": "Uno"}, headers=A).json()
    boss = client.post("/users", json={"email": _email("jefe"), "first_name": "Jefe", "last_name": "Uno"}, headers=A).json()
    made.extend([manager["id"], clerk["id"], boss["id"]])
    _grant(manager["id"], {"users": {"read", "update", "delete"}, "customers": {"read"}})
    _grant(clerk["id"], {"customers": {"read"}})
    _grant(boss["id"], {"customers": {"read", "delete"}})
    H = _bearer(manager_email, "Gerente-Clave-1")

    assert client.patch(f"/users/{clerk['id']}", json={"last_name": "Dos"}, headers=H).status_code == 200
    assert client.patch(f"/users/{boss['id']}", json={"last_name": "Dos"}, headers=H).status_code == 403
    assert client.post(f"/users/{ADMIN}/deactivate", headers=H).status_code == 403  # the super admin
    assert client.delete(f"/users/{boss['id']}", headers=H).status_code == 403
    assert client.post("/users", json={"email": _email("x"), "first_name": "X", "last_name": "Y"}, headers=H).status_code == 403

    # Deactivated: the access token they still hold stops working at once (not when it expires)
    assert client.get("/customers", headers=H).status_code == 200
    client.post(f"/users/{manager['id']}/deactivate", headers=A)
    assert client.get("/customers", headers=H).status_code == 403
    assert client.get("/users", headers=H).status_code == 403


class FakeRepo:
    """Target is the only users admin; the caller is the super admin acting on someone else."""
    def get(self, user_id): return {"id": user_id, "email": "t@x.mx", "deleted_at": None}
    def is_super_admin(self, user_id): return user_id == "caller"
    def has_permission(self, user_id, module, perm): return True
    def other_user_admins(self, user_id): return 0
    def revoke_sessions(self, *args): pass


def test_last_user_admin_is_protected():
    for action in (lambda s: s.set_active("caller", "target", False), lambda s: s.delete("caller", "target")):
        with pytest.raises(Conflict):
            action(UserService(FakeRepo()))
    with pytest.raises(Invalid):
        UserService(FakeRepo()).delete("caller", "caller")
