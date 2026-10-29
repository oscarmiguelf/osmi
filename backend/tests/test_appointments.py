# Integration test against the real DB: appointments on a throwaway branch.
# docker compose run --rm -v ./tests:/code/tests api sh -c "pip install -q pytest httpx && python -m pytest -q tests"
import secrets
from datetime import datetime, timedelta, timezone

import pytest

from tests.test_calendar import ADMIN, OTHER, A, client
from tests.test_customers import _phone


@pytest.fixture
def env():
    tag = secrets.token_hex(3).upper()
    branch = client.post("/branches", json={"name": f"Citas {tag}", "code": f"T{tag}"}, headers=A).json()["id"]
    client.post(f"/branches/{branch}/users", json={"user_id": str(OTHER)}, headers=A)
    customer = client.post("/customers", json={"full_name": f"Paciente {tag}", "phone": _phone()}, headers=A).json()
    yield {"tag": tag, "H": {**A, "X-Branch-Id": branch}, "customer": customer}
    client.delete(f"/customers/{customer['id']}", headers=A)
    client.delete(f"/branches/{branch}/users/{OTHER}", headers=A)
    client.delete(f"/branches/{branch}", headers=A)


def test_appointments_flow(env):
    H, cust = env["H"], env["customer"]
    day = (datetime.now(timezone.utc) + timedelta(days=3)).replace(hour=16, minute=0, second=0, microsecond=0)
    at = lambda h, m=0: (day + timedelta(hours=h, minutes=m)).isoformat()
    new = lambda **kw: client.post("/appointments", json={"customer_id": cust["id"], "title": "Consulta", "starts_at": at(0),
                                                          "ends_at": at(1), **kw}, headers=H)

    assert {s["id"] for s in client.get("/appointments/staff", headers=H).json()} >= {str(ADMIN), str(OTHER)}
    assert new(ends_at=at(-1)).json()["detail"]["field"] == "ends_at"
    assert new(assigned_to="00000000-0000-0000-0000-000000000000").json()["detail"]["field"] == "assigned_to"

    # Schedule; the same person can't have two appointments at once (others can)
    a = new(assigned_to=str(OTHER), notes="Primera vez")
    assert a.status_code == 201, a.text
    a = a.json()
    assert a["status"] == "SCHEDULED" and a["customer"] == cust["full_name"] and a["history"][0]["action"] == "CREATED"
    r = new(assigned_to=str(OTHER), starts_at=at(0, 30), ends_at=at(1, 30))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "clash"
    b = new(starts_at=at(0, 30), ends_at=at(1, 30), status="CONFIRMED").json()
    assert b["status"] == "CONFIRMED"
    base = f"/appointments/{a['id']}"

    # Confirm, then reschedule: counted, recorded with old/new times and reason, back to SCHEDULED
    assert client.post(f"{base}/confirm", headers=H).json()["status"] == "CONFIRMED"
    assert client.post(f"{base}/confirm", headers=H).status_code == 409
    r = client.post(f"{base}/reschedule", json={"starts_at": at(2), "ends_at": at(3), "reason": "El paciente pidió más tarde"}, headers=H).json()
    assert r["status"] == "SCHEDULED" and r["reschedule_count"] == 1
    moved = r["history"][0]
    assert moved["action"] == "RESCHEDULED" and moved["reason"] == "El paciente pidió más tarde"
    assert datetime.fromisoformat(moved["from_starts_at"]) == day and datetime.fromisoformat(moved["to_starts_at"]) == day + timedelta(hours=2)
    assert client.post(f"{base}/reschedule", json={"starts_at": at(2), "ends_at": at(3)}, headers=H).status_code == 422  # same time

    # Edit and follow-up notes
    r = client.patch(base, json={"title": "Revisión", "assigned_to": None}, headers=H).json()
    assert r["title"] == "Revisión" and r["assigned_to"] is None and r["history"][0]["action"] == "UPDATED"
    r = client.post(f"{base}/notes", json={"note": "Llamar 1 día antes"}, headers=H).json()
    assert [n["note"] for n in r["follow_up"]] == ["Llamar 1 día antes"]

    # Calendar range
    listed = lambda **q: [x["id"] for x in client.get("/appointments", params={"from": at(-1), "to": at(5), **q}, headers=H).json()]
    assert set(listed()) == {a["id"], b["id"]}
    assert listed(status="CONFIRMED") == [b["id"]]

    # Cancel (with a reason), then it's final; notes still allowed
    assert client.post(f"{base}/cancel", json={"reason": ""}, headers=H).status_code == 422
    r = client.post(f"{base}/cancel", json={"reason": "Se enfermó"}, headers=H).json()
    assert r["status"] == "CANCELLED" and r["cancel_reason"] == "Se enfermó" and r["history"][0]["reason"] == "Se enfermó"
    assert client.post(f"{base}/reschedule", json={"starts_at": at(4), "ends_at": at(5)}, headers=H).json()["detail"]["code"] == "closed"
    assert client.post(f"{base}/notes", json={"note": "Reagendar la próxima semana"}, headers=H).status_code == 201
    assert set(listed(hide_cancelled=True)) == {b["id"]}

    # Attended / no-show
    assert client.post(f"/appointments/{b['id']}/complete", headers=H).json()["status"] == "COMPLETED"
    c = new(starts_at=at(6), ends_at=at(7)).json()
    assert client.post(f"/appointments/{c['id']}/no-show", headers=H).json()["status"] == "NO_SHOW"

    # The customer's follow-up
    history = client.get(f"/customers/{cust['id']}/appointments", headers=A).json()["items"]
    assert [x["status"] for x in history] == ["NO_SHOW", "CANCELLED", "COMPLETED"] and history[1]["note_count"] == 2
