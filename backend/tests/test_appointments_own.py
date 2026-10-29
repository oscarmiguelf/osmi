# Integration test: appointments.own — a doctor / therapist sees only the appointments assigned to them or they booked.
import secrets
from datetime import datetime, timedelta, timezone

from tests.test_calendar import OTHER, A, B, client
from tests.test_products import _grant


def test_only_their_appointments():
    tag = secrets.token_hex(3)
    branch = client.post("/branches", json={"name": f"Consultorio {tag}", "code": f"O{tag[:4]}".upper()}, headers=A).json()["id"]
    HA, HB = {**A, "X-Branch-Id": branch}, {**B, "X-Branch-Id": branch}
    client.post(f"/branches/{branch}/users", json={"user_id": str(OTHER)}, headers=A)
    cust = client.post("/customers", json={"full_name": f"Paciente {tag}", "phone": "55" + str(secrets.randbelow(10**8)).zfill(8)}, headers=A).json()
    start = (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0)
    book = lambda h, title, hours, **kw: client.post("/appointments", json={"customer_id": cust["id"], "title": title,  # noqa: E731
        "starts_at": (start + timedelta(hours=hours)).isoformat(), "ends_at": (start + timedelta(hours=hours, minutes=30)).isoformat(), **kw}, headers=h)
    ids = []
    try:
        _grant(OTHER, {"appointments": {"read", "create", "update", "own"}, "customers": {"read"}})
        assigned = book(HA, "Asignada", 0, assigned_to=str(OTHER)).json()
        others = book(HA, "De otro", 1).json()
        mine = book(HB, "La agendé yo", 2).json()
        ids = [assigned["id"], others["id"], mine["id"]]

        # Only theirs: in the calendar, by id, in the customer's history; what they can't see they can't touch
        listed = {a["title"] for a in client.get("/appointments", headers=HB).json()}
        assert listed == {"Asignada", "La agendé yo"}
        assert client.get(f"/appointments/{others['id']}", headers=HB).status_code == 404
        assert client.patch(f"/appointments/{others['id']}", json={"title": "x"}, headers=HB).status_code == 404
        assert client.post(f"/appointments/{others['id']}/confirm", headers=HB).status_code == 404
        assert client.get(f"/appointments/{assigned['id']}", headers=HB).status_code == 200
        history = {a["title"] for a in client.get(f"/customers/{cust['id']}/appointments", headers=HB).json()["items"]}
        assert history == {"Asignada", "La agendé yo"}
        # Front desk / managers (no 'own'): everything
        assert {a["title"] for a in client.get("/appointments", headers=HA).json()} == {"Asignada", "De otro", "La agendé yo"}
        _grant(OTHER, {"appointments": {"read", "create", "update"}, "customers": {"read"}})
        assert len(client.get("/appointments", headers=HB).json()) == 3
    finally:
        _grant(OTHER, {})
        for aid in ids:
            client.post(f"/appointments/{aid}/cancel", json={"reason": "Prueba"}, headers=HA)
        client.delete(f"/customers/{cust['id']}", headers=A)
        client.delete(f"/branches/{branch}/users/{OTHER}", headers=A)
