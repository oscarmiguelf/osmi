# Integration test against the real DB with the seed admin (admin/admin). Writes audit/token rows.
# docker compose run --rm -v ./tests:/code/tests api sh -c "pip install -q pytest httpx && python -m pytest -q tests"
import secrets

from fastapi.testclient import TestClient

from app.main import app

# A private address per run: the per-IP sign-in cap (failures in the last 15 minutes) never carries over between runs
TEST_IP = f"10.{secrets.randbelow(250) + 1}.{secrets.randbelow(250) + 1}.{secrets.randbelow(250) + 1}"
client = TestClient(app, base_url="https://testserver", client=(TEST_IP, 50000))  # https so Secure cookies are sent back
MOBILE = {"X-Client": "mobile"}


def login(**headers):
    return client.post("/auth/login", json={"email": "ADMIN", "password": "admin"}, headers=headers)


def test_wrong_password_and_unknown_user_look_the_same():
    a = client.post("/auth/login", json={"email": "admin", "password": "nope"})
    b = client.post("/auth/login", json={"email": "ghost@x.com", "password": "nope"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json() == {"detail": "invalid credentials"}


def test_login_me_refresh_reuse_logout():
    r = login(**MOBILE)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["expires_in"] == 900 and body["user"]["email"] == "admin"
    assert body["modules"] and body["branches"]

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["user"]["id"] == body["user"]["id"]
    assert client.get("/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401

    old = body["refresh_token"]
    r2 = client.post("/auth/refresh", json={"refresh_token": old})
    assert r2.status_code == 200 and r2.json()["refresh_token"] != old
    new = r2.json()["refresh_token"]

    # Reusing the rotated token kills the whole family, including the new one.
    assert client.post("/auth/refresh", json={"refresh_token": old}).status_code == 401
    assert client.post("/auth/refresh", json={"refresh_token": new}).status_code == 401

    assert client.post("/auth/logout", json={"refresh_token": "unknown"}).status_code == 204


def test_web_cookie_flow():
    r = login()
    assert r.status_code == 200 and "refresh_token" not in r.json()
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie and "path=/auth" in cookie

    assert client.post("/auth/refresh").status_code == 200  # cookie jar sends it
    assert client.post("/auth/logout").status_code == 204
    assert client.post("/auth/refresh").status_code == 401
