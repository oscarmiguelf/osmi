# Integration test against the real DB: physical counts on a throwaway branch.
# docker compose run --rm -v ./tests:/code/tests api sh -c "pip install -q pytest httpx && python -m pytest -q tests"
import secrets
from decimal import Decimal

import pytest

from tests.test_calendar import ADMIN, OTHER, A, B, client
from tests.test_products import _grant

D = lambda v: Decimal(str(v))  # noqa: E731


def _seed(path, name):
    return next(i for i in client.get(path, headers=A).json() if i["name"] == name)["id"]


@pytest.fixture
def env():
    tag = secrets.token_hex(3).upper()
    branch = client.post("/branches", json={"name": f"Conteo {tag}", "code": f"N{tag}"}, headers=A).json()["id"]
    client.post(f"/branches/{branch}/users", json={"user_id": str(OTHER)}, headers=A)
    H, HO = {**A, "X-Branch-Id": branch}, {**B, "X-Branch-Id": branch}
    unit, kg = _seed("/units", "Unit"), _seed("/units", "kg")
    types = {n: _seed("/product-types", n) for n in ("Product", "Service", "Kit")}
    new = lambda name, t, u=unit: client.post("/products", json={"name": f"{name} {tag}", "product_type_id": types[t],
                                                                 "unit_of_measure_id": u, "barcode": f"6{tag}{name[:2]}"}, headers=A).json()
    p = {"hammer": new("Martillo", "Product"), "nails": new("Clavo", "Product", kg), "saw": new("Serrucho", "Product"),
         "install": new("Instalación", "Service"), "kit": new("Kit", "Kit")}
    client.post("/purchases", json={"items": [{"product_id": p["hammer"]["id"], "quantity": 10, "unit_cost": 50},
                                              {"product_id": p["nails"]["id"], "quantity": "5.5", "unit_cost": 20},
                                              {"product_id": p["saw"]["id"], "quantity": 3, "unit_cost": 100}]}, headers=H)
    yield {"tag": tag, "branch": branch, "H": H, "HO": HO, "p": p}
    _grant(OTHER, {})
    for x in (p["hammer"], p["nails"], p["saw"]):
        left = D(client.get(f"/products/{x['id']}", headers=H).json()["current_stock"])
        if left:
            client.post("/inventory/adjustments", json={"product_id": x["id"], "quantity": str(-left), "notes": "Limpieza test"}, headers=H)
    for x in p.values():
        client.delete(f"/products/{x['id']}", headers=A)
    client.delete(f"/branches/{branch}/users/{OTHER}", headers=A)
    client.delete(f"/branches/{branch}", headers=A)


def test_stocktake_flow(env):
    H, HO, p, tag = env["H"], env["HO"], env["p"], env["tag"]
    stock = lambda k: D(client.get(f"/products/{p[k]['id']}", headers=H).json()["current_stock"])
    assert client.get("/stocktakes/current", headers=H).status_code == 204

    # One open stocktake per branch
    st = client.post("/stocktakes", json={"notes": "Conteo mensual"}, headers=H)
    assert st.status_code == 201
    st = st.json()
    sid, base = st["id"], f"/stocktakes/{st['id']}"
    assert st["folio"].endswith("C000001") and st["status"] == "OPEN" and st["uncounted"] == 3
    again = client.post("/stocktakes", json={}, headers=H)
    assert again.status_code == 409 and again.json()["detail"]["stocktake"]["folio"] == st["folio"]
    assert client.get("/stocktakes/current", headers=H).json()["id"] == sid

    # Count, validate, recount (one row per product)
    count = lambda k, q, h=H: client.put(f"{base}/items/{p[k]['id']}", json={"counted_quantity": q}, headers=h)
    item = count("hammer", 8).json()
    assert D(item["system_quantity"]) == 10 and D(item["difference"]) == -2
    assert count("install", 1).json()["detail"]["code"] == "not_countable"
    assert count("kit", 1).json()["detail"]["code"] == "not_countable"
    assert count("hammer", "7.5").json()["detail"]["code"] == "whole_units"
    assert count("hammer", -1).status_code == 422
    assert D(count("hammer", 9).json()["counted_quantity"]) == 9
    items = client.get(f"{base}/items", headers=H).json()["items"]
    assert len(items) == 1 and D(items[0]["difference"]) == -1

    # Scanner / import: per-line results, bad lines don't stop the rest
    r = client.post(f"{base}/items/bulk", json={"items": [
        {"barcode": p["nails"]["barcode"], "counted_quantity": "6.25"},
        {"barcode": "NO-EXISTE", "counted_quantity": 1},
        {"product_id": p["install"]["id"], "counted_quantity": 1}]}, headers=H).json()
    assert (r["saved"], r["failed"]) == (1, 2) and [x["code"] for x in r["results"] if not x["ok"]] == ["not_found", "not_countable"]

    # Blind count: a counter doesn't see what the system says, and can't complete
    _grant(OTHER, {"stocktakes": {"read", "create"}})
    found = client.get(f"{base}/products", params={"q": p["saw"]["barcode"]}, headers=HO).json()  # no products.read needed
    assert [f["id"] for f in found] == [p["saw"]["id"]] and "current_stock" not in found[0]
    assert [f["name"] for f in client.get(f"{base}/products", params={"q": f"kit {tag.lower()}"}, headers=HO).json()] == []  # not countable
    seen = count("nails", "6.25", HO).json()
    assert "system_quantity" not in seen and "difference" not in seen
    assert all("difference" not in i for i in client.get(f"{base}/items", headers=HO).json()["items"])
    assert set(client.get(base, headers=HO).json()["totals"]) == {"counted_items"}
    assert client.post(f"{base}/complete", headers=HO).status_code == 403
    assert client.get(f"{base}/differences", headers=HO).status_code == 403
    sheet = client.get(f"{base}/export", headers=HO).text
    assert "Sistema" not in sheet.splitlines()[0] and f"Serrucho {tag}" in sheet

    # What's left to count, differences at cost
    assert [u["name"] for u in client.get(f"{base}/uncounted", headers=H).json()["items"]] == [f"Serrucho {tag}"]
    diff = client.get(f"{base}/differences", headers=H).json()
    assert diff["totals"]["items_with_difference"] == 2 and D(diff["totals"]["shortage_units"]) == 1
    assert D(diff["totals"]["difference_value_at_cost"]) == D("-50") + D("0.75") * 20
    assert "Sistema" in client.get(f"{base}/export", headers=H).text.splitlines()[0]

    # Stock moves after the count: completing adjusts against the stock AT THAT MOMENT (the count wins)
    client.post("/inventory/adjustments", json={"product_id": p["hammer"]["id"], "quantity": -1, "notes": "Venta simulada"}, headers=H)
    res = client.post(f"{base}/complete", headers=H)
    assert res.status_code == 200, res.text
    res = res.json()
    assert res["status"] == "COMPLETED" and res["closed_by"]
    applied = {i["product"]: D(i["applied_adjustment"]) for i in res["items"]}
    assert applied == {f"Martillo {tag}": 0, f"Clavo {tag}": D("0.75")}  # hammer: 9 counted, 9 in stock -> no movement
    assert [m["product"] for m in res["movements"]] == [f"Clavo {tag}"]
    assert (stock("hammer"), stock("nails"), stock("saw")) == (9, D("6.25"), 3)  # the saw wasn't counted: untouched
    assert count("hammer", 1).status_code == 409 and client.post(f"{base}/cancel", headers=H).status_code == 409
    assert client.delete(f"{base}/items/{p['hammer']['id']}", headers=H).status_code == 409
    kardex = client.get(f"/products/{p['nails']['id']}/kardex", headers=H).json()["items"]
    assert kardex[0]["movement_type"] == "Adjustment" and kardex[0]["reference"] == st["folio"]

    # A second count: remove a mistaken line, can't complete empty, cancel changes nothing
    st2 = client.post("/stocktakes", json={}, headers=H).json()
    base2 = f"/stocktakes/{st2['id']}"
    client.put(f"{base2}/items/{p['saw']['id']}", json={"counted_quantity": 0}, headers=H)
    assert client.delete(f"{base2}/items/{p['saw']['id']}", headers=HO).status_code == 403  # removing is for supervisors
    assert client.delete(f"{base2}/items/{p['saw']['id']}", headers=H).status_code == 204
    assert client.post(f"{base2}/complete", headers=H).json()["detail"]["code"] == "nothing_counted"
    client.put(f"{base2}/items/{p['saw']['id']}", json={"counted_quantity": 0}, headers=H)
    assert client.post(f"{base2}/cancel", headers=H).json()["status"] == "CANCELLED"
    assert stock("saw") == 3

    # Lists and history
    assert [s["status"] for s in client.get("/stocktakes", headers=H).json()["items"]] == ["CANCELLED", "COMPLETED"]
    assert [s["folio"] for s in client.get("/stocktakes", params={"status": "COMPLETED"}, headers=H).json()["items"]] == [st["folio"]]
    history = client.get(f"{base}/history", headers=H).json()["items"]
    recount = next(h for h in history if h["product"] == f"Martillo {tag}" and "counted_quantity" in (h["changed_fields"] or []))
    assert recount["old_counted"] == "8.000"
    assert any(h["status"] == "COMPLETED" for h in history)
