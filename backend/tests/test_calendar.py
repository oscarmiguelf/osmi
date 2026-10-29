# Integration test against the real DB. Uses the seed admin plus a non-loginable helper user it creates once.
# docker compose run --rm -v ./tests:/code/tests api sh -c "pip install -q pytest httpx && python -m pytest -q tests"
import secrets

from sqlalchemy import text

from fastapi.testclient import TestClient

from app.application.security import create_access_token
from app.infrastructure.persistence.database import SessionLocal
from app.main import app

# A private address per run: the per-IP sign-in cap (failures in the last 15 minutes) never carries over between runs
TEST_IP = f"10.{secrets.randbelow(250) + 1}.{secrets.randbelow(250) + 1}.{secrets.randbelow(250) + 1}"
client = TestClient(app, base_url="https://testserver", client=(TEST_IP, 50000))


def _bearer(user_id):
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


with SessionLocal() as s:
    ADMIN = s.execute(text("SELECT id FROM users WHERE email = 'admin' AND deleted_at IS NULL")).scalar()
    # password_hash '!' is not a valid hash, so this user can never log in
    s.execute(text("""
        INSERT INTO users (email, password_hash, first_name, last_name)
        SELECT 'calendar-test@example.com', '!', 'Calendar', 'Test'
        WHERE NOT EXISTS (SELECT 1 FROM users WHERE email = 'calendar-test@example.com' AND deleted_at IS NULL)
    """))
    OTHER = s.execute(text("SELECT id FROM users WHERE email = 'calendar-test@example.com' AND deleted_at IS NULL")).scalar()
    s.commit()

A, B = _bearer(ADMIN), _bearer(OTHER)


def test_calendar_flow():
    assert client.get("/calendars").status_code == 401

    cal = client.post("/calendars", json={"name": " Team ", "color": "#AABBCC"}, headers=A)
    assert cal.status_code == 201 and cal.json()["name"] == "Team"
    cid = cal.json()["id"]
    assert client.post("/calendars", json={"name": "x", "color": "red"}, headers=A).status_code == 422
    assert client.patch(f"/calendars/{cid}", json={"name": None}, headers=A).status_code == 422

    # Not shared yet: other user gets 404, not 403
    assert client.get(f"/calendars/{cid}/members", headers=B).status_code == 404

    assert client.post(f"/calendars/{cid}/members", json={"user_id": str(ADMIN), "access_level": "view"},
                       headers=A).status_code == 422
    share = {"user_id": str(OTHER), "access_level": "view"}
    assert client.post(f"/calendars/{cid}/members", json=share, headers=A).status_code == 201
    assert client.post(f"/calendars/{cid}/members", json=share, headers=A).status_code == 409

    ev = {"title": "Standup", "start_at": "2026-11-03T15:00:00Z", "end_at": "2026-11-03T15:30:00Z"}
    r = client.post(f"/calendars/{cid}/events", json=ev, headers=A)
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    assert client.post(f"/calendars/{cid}/events", json={**ev, "end_at": ev["start_at"]}, headers=A).status_code == 422

    # View member: can read, cannot write
    assert client.get(f"/events/{eid}", headers=B).status_code == 200
    assert client.patch(f"/events/{eid}", json={"title": "x"}, headers=B).status_code == 403
    assert client.patch(f"/calendars/{cid}/members/{OTHER}", json={"access_level": "edit"}, headers=A).status_code == 200
    assert client.patch(f"/events/{eid}", json={"location": "Room 1"}, headers=B).status_code == 200
    # end_at alone checked against stored start_at
    assert client.patch(f"/events/{eid}", json={"end_at": "2026-11-03T14:00:00Z"}, headers=B).status_code == 422

    rng = {"from": "2026-11-01T00:00:00Z", "to": "2026-11-30T00:00:00Z"}
    listed = client.get("/events", params={**rng, "calendar_ids": cid}, headers=B).json()
    assert [e["id"] for e in listed] == [eid]
    assert client.get("/events", params={"from": rng["from"], "to": "2028-01-01T00:00:00Z"}, headers=A).status_code == 422

    assert client.delete(f"/events/{eid}", headers=B).status_code == 204
    assert client.get(f"/events/{eid}", headers=A).status_code == 404

    audit = client.get(f"/calendars/{cid}/audit", headers=A).json()
    assert {"calendar", "member", "event"} <= {a["entity_type"] for a in audit}
    assert client.get(f"/calendars/{cid}/audit", headers=B).status_code == 403

    assert client.delete(f"/calendars/{cid}/members/{OTHER}", headers=A).status_code == 204
    assert client.get(f"/events/{eid}", headers=B).status_code == 404
    assert client.delete(f"/calendars/{cid}", headers=A).status_code == 204
    assert all(c["id"] != cid for c in client.get("/calendars", headers=A).json())


def test_search_users():
    found = client.get("/users/search", params={"q": "CALENDAR-test"}, headers=A).json()
    assert [u["id"] for u in found] == [str(OTHER)] and set(found[0]) == {"id", "name", "email"}
    assert client.get("/users/search", params={"q": "calendar-test"}, headers=B).json() == []  # never yourself
    assert client.get("/users/search", params={"q": "%%"}, headers=A).json() == []  # wildcards are literal
    assert client.get("/users/search", params={"q": "a"}, headers=A).status_code == 422
    assert client.get("/users/search", params={"q": "admin"}).status_code == 401


def test_timezone():
    assert client.patch("/me/timezone", json={"timezone": "Mars/Base"}, headers=B).status_code == 422
    assert client.patch("/me/timezone", json={"timezone": "America/Mexico_City"}, headers=B).status_code == 200
