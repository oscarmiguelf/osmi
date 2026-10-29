# Integration test against the real DB: two throwaway branches; the opening stock comes from a real purchase.
# docker compose run --rm -v ./tests:/code/tests api sh -c "pip install -q pytest httpx && python -m pytest -q tests"
import secrets
from decimal import Decimal

import pytest

from tests.test_calendar import ADMIN, A, client

D = lambda v: Decimal(str(v))  # noqa: E731


def _seed(path, name):
    return next(i for i in client.get(path, headers=A).json() if i["name"] == name)["id"]


def _stock(H, product_id):
    return D(client.get(f"/products/{product_id}", headers=H).json()["current_stock"])


@pytest.fixture
def env():
    tag = secrets.token_hex(3).upper()
    branches = [client.post("/branches", json={"name": f"{name} {tag}", "code": f"{code}{tag}"}, headers=A).json()["id"]
                for name, code in (("Origen", "O"), ("Destino", "D"))]
    unit = _seed("/units", "Unit")
    make = lambda name, ptype: client.post("/products", json={"name": f"{name} {tag}", "product_type_id": _seed("/product-types", ptype),
                                                              "unit_of_measure_id": unit, "price": 100}, headers=A).json()
    product, service = make("Pintura", "Product"), make("Asesoría", "Service")
    HO, HD = ({**A, "X-Branch-Id": b} for b in branches)
    client.post("/purchases", json={"items": [{"product_id": product["id"], "quantity": 10, "unit_cost": 50}]}, headers=HO)
    yield {"origin": branches[0], "dest": branches[1], "HO": HO, "HD": HD, "product": product, "service": service}
    for H in (HO, HD):  # empty both branches so they can be deleted, even after a failure
        left = _stock(H, product["id"])
        if left:
            client.post("/inventory/adjustments", json={"product_id": product["id"], "quantity": str(-left), "notes": "Limpieza test"}, headers=H)
    for pid in (product["id"], service["id"]):
        client.delete(f"/products/{pid}", headers=A)
    for b in branches:
        client.delete(f"/branches/{b}", headers=A)


def test_send_receive_cancel(env):
    HO, HD, pid = env["HO"], env["HD"], env["product"]["id"]
    send = lambda items, to=env["dest"]: client.post("/transfers", json={"to_branch_id": to, "notes": "Reabasto", "items": items}, headers=HO)

    assert send([{"product_id": pid, "quantity": 4}], to=env["origin"]).status_code == 422  # same branch
    r = send([{"product_id": pid, "quantity": 11}])
    assert r.status_code == 422 and D(r.json()["detail"]["available"]) == 10
    assert send([{"product_id": env["service"]["id"], "quantity": 1}]).status_code == 422
    assert send([{"product_id": pid, "quantity": 1.5}]).status_code == 422  # whole units
    assert send([{"product_id": pid, "quantity": 1}] * 2).status_code == 422
    assert send([]).status_code == 422
    assert [p["id"] for p in client.get("/transfers/available-products", headers=HO).json()] == [pid]

    # Send: stock leaves the origin at once; folio uses the origin's counter
    t = send([{"product_id": pid, "quantity": 4}]).json()
    assert t["status"] == "IN_TRANSIT" and "-T" in t["folio"] and _stock(HO, pid) == 6 and _stock(HD, pid) == 0
    assert [m["type"] for m in t["movements"]] == ["Transfer Out"]
    assert [x["id"] for x in client.get("/transfers", params={"direction": "outgoing"}, headers=HO).json()["items"]] == [t["id"]]
    assert [x["id"] for x in client.get("/transfers/in-transit", headers=HD).json()] == [t["id"]]
    assert client.get("/transfers", params={"direction": "outgoing"}, headers=HD).json()["items"] == []

    # Branch rules: destination receives, origin cancels; other branches don't see it
    assert client.post(f"/transfers/{t['id']}/receive", headers=HO).status_code == 403
    assert client.post(f"/transfers/{t['id']}/cancel", headers=HD).status_code == 403
    seed = next(b["id"] for b in client.get(f"/users/{ADMIN}/branches", headers=A).json() if b["id"] not in (env["origin"], env["dest"]))
    assert client.get(f"/transfers/{t['id']}", headers={**A, "X-Branch-Id": seed}).status_code == 404
    received = client.post(f"/transfers/{t['id']}/receive", headers=HD).json()
    assert received["status"] == "RECEIVED" and _stock(HD, pid) == 4
    assert [h["to_status"] for h in received["history"]] == ["IN_TRANSIT", "RECEIVED"]
    assert client.post(f"/transfers/{t['id']}/receive", headers=HD).status_code == 409
    assert client.post(f"/transfers/{t['id']}/cancel", headers=HO).status_code == 409

    # Cancel: the stock goes back to the origin
    t2 = send([{"product_id": pid, "quantity": 2}]).json()
    assert _stock(HO, pid) == 4
    cancelled = client.post(f"/transfers/{t2['id']}/cancel", headers=HO).json()
    assert cancelled["status"] == "CANCELLED" and _stock(HO, pid) == 6
    assert client.get("/transfers/in-transit", headers=HD).json() == []
    assert [x["status"] for x in client.get("/transfers", headers=HD).json()["items"]] == ["CANCELLED", "RECEIVED"]
