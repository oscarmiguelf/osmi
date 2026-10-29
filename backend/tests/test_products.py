# Integration test against the real DB: catalogs, products, kits, stock, adjustments and purchases on a throwaway
# branch. Everything is soft-deleted at the end (names are unique per run).
# docker compose run --rm -v ./tests:/code/tests api sh -c "pip install -q pytest httpx && python -m pytest -q tests"
import secrets
from decimal import Decimal

import pytest

from tests.test_calendar import ADMIN, OTHER, A, B, client

D = lambda v: Decimal(str(v))  # noqa: E731


def _grant(user_id, grants):
    modules = {m["code"]: m for m in client.get("/modules", headers=A).json()}
    body = [{"module_id": modules[c]["id"], "permission_ids": [p["id"] for p in modules[c]["permissions"] if p["code"] in perms]}
            for c, perms in grants.items()]
    assert client.put(f"/users/{user_id}/modules", json={"modules": body}, headers=A).status_code == 200


def _seed(path, name):
    return next(i for i in client.get(path, headers=A).json() if i["name"] == name)["id"]


@pytest.fixture
def env():
    tag = secrets.token_hex(3).upper()
    branch = client.post("/branches", json={"name": f"Inventario {tag}", "code": f"I{tag}"}, headers=A).json()["id"]
    H = {**A, "X-Branch-Id": branch}
    yield {"tag": tag, "branch": branch, "H": H}
    # Even if the test failed half-way: empty the branch's stock so it can be deleted
    for item in client.get("/stock", params={"page_size": 100}, headers=H).json()["items"]:
        if D(item["current_stock"]) > 0:
            client.post("/inventory/adjustments", json={"product_id": item["id"], "quantity": str(-D(item["current_stock"])),
                                                        "notes": "Limpieza test"}, headers=H)
    client.delete(f"/branches/{branch}", headers=A)


def test_catalogs():
    tag = secrets.token_hex(3)
    cat = client.post("/categories", json={"name": f"Ferretería {tag}"}, headers=A).json()
    assert client.post("/categories", json={"name": f"FERRETERÍA {tag}"}, headers=A).status_code == 409
    assert client.patch(f"/categories/{cat['id']}", json={"name": f"Ferretería y más {tag}"}, headers=A).status_code == 200
    assert client.post("/suppliers", json={"name": "Truper", "email": "ventas@"}, headers=A).status_code == 422
    sup = client.post("/suppliers", json={"name": f"Truper {tag}", "phone": "55 1234 5678", "email": "ventas@truper.mx"},
                      headers=A).json()
    assert sup["phone"] == "55 1234 5678"  # free text, kept as typed

    # Tax rates: exactly one default, and the default can't be deleted
    old_default = next(t for t in client.get("/tax-rates", headers=A).json() if t["is_default"])
    assert client.post("/tax-rates", json={"name": "x", "rate": 1.5}, headers=A).status_code == 422
    rate = client.post("/tax-rates", json={"name": f"IVA 8% {tag}", "rate": 0.08, "is_default": True}, headers=A).json()
    assert rate["is_default"] is True
    defaults = [t["id"] for t in client.get("/tax-rates", headers=A).json() if t["is_default"]]
    assert defaults == [rate["id"]]
    assert client.delete(f"/tax-rates/{rate['id']}", headers=A).status_code == 409
    assert client.patch(f"/tax-rates/{old_default['id']}", json={"is_default": True}, headers=A).json()["is_default"] is True
    assert client.delete(f"/tax-rates/{rate['id']}", headers=A).status_code == 204

    # Delete / restore, blocked while in use
    unit = _seed("/units", "Unit")
    ptype = _seed("/product-types", "Product")
    prod = client.post("/products", json={"name": f"Martillo {tag}", "product_type_id": ptype, "unit_of_measure_id": unit,
                                          "category_id": cat["id"]}, headers=A).json()
    r = client.delete(f"/categories/{cat['id']}", headers=A)
    assert r.status_code == 409 and r.json()["detail"]["products"] == 1
    client.delete(f"/products/{prod['id']}", headers=A)
    assert client.delete(f"/categories/{cat['id']}", headers=A).status_code == 204
    assert client.post(f"/categories/{cat['id']}/restore", headers=A).status_code == 200
    for path, item in (("categories", cat), ("suppliers", sup)):
        client.delete(f"/{path}/{item['id']}", headers=A)

    # Brands: id + name, hard delete; a product with no brand keeps working
    brand = client.post("/brands", json={"name": f"Truper {tag}"}, headers=A).json()
    assert client.post("/brands", json={"name": f"Otra {tag}"}, headers=B).status_code == 403  # products.create needed
    assert client.post("/brands", json={"name": f"truper {tag.lower()}"}, headers=A).status_code == 409
    assert client.patch(f"/brands/{brand['id']}", json={"name": f"Truper MX {tag}"}, headers=A).json()["name"] == f"Truper MX {tag}"
    prod = client.post("/products", json={"name": f"Pinza {tag}", "product_type_id": ptype, "unit_of_measure_id": unit,
                                          "brand_id": brand["id"]}, headers=A).json()
    assert prod["brand"] == f"Truper MX {tag}"
    assert [p["id"] for p in client.get("/products", params={"q": f"truper mx {tag.lower()}"}, headers=A).json()["items"]] == [prod["id"]]
    assert client.delete(f"/brands/{brand['id']}", headers=A).status_code == 409
    client.delete(f"/products/{prod['id']}", headers=A)
    assert client.delete(f"/brands/{brand['id']}", headers=A).status_code == 204
    assert all(b["id"] != brand["id"] for b in client.get("/brands", headers=A).json())
    assert client.get(f"/products/{prod['id']}", headers=A).json()["brand_id"] is None
    assert client.post("/products", json={"name": "x", "product_type_id": ptype, "unit_of_measure_id": unit,
                                          "brand_id": brand["id"]}, headers=A).status_code == 422

    # Merge spellings: products (deleted ones too) move to the target, the other brands are removed
    keep, dup1, dup2 = (client.post("/brands", json={"name": f"{n} {tag}"}, headers=A).json() for n in ("Stanley", "Stanly", "Stanley Tools"))
    mk = lambda name, b: client.post("/products", json={"name": f"{name} {tag}", "product_type_id": ptype, "unit_of_measure_id": unit,
                                                        "brand_id": b["id"]}, headers=A).json()
    p1, p2, p3 = mk("Flexómetro", dup1), mk("Nivel", dup2), mk("Escuadra", dup2)
    client.delete(f"/products/{p3['id']}", headers=A)
    assert next(b for b in client.get("/brands", headers=A).json() if b["id"] == dup2["id"])["products"] == 1  # active only
    assert client.post("/brands/merge", json={"from_ids": [keep["id"]], "to_id": keep["id"]}, headers=A).status_code == 422
    assert client.post("/brands/merge", json={"from_ids": ["00000000-0000-0000-0000-000000000000"], "to_id": keep["id"]}, headers=A).status_code == 404
    r = client.post("/brands/merge", json={"from_ids": [dup1["id"], dup2["id"]], "to_id": keep["id"]}, headers=A).json()
    assert r["products_moved"] == 3 and r["brands_removed"] == 2 and r["brand"]["products"] == 2
    assert {b["id"] for b in client.get("/brands", headers=A).json()} & {dup1["id"], dup2["id"]} == set()
    assert all(client.get(f"/products/{p['id']}", headers=A).json()["brand"] == f"Stanley {tag}" for p in (p1, p2, p3))
    for p in (p1, p2):
        client.delete(f"/products/{p['id']}", headers=A)
    client.delete(f"/brands/{keep['id']}", headers=A)


def test_products_kits_stock_and_purchases(env):
    tag, H = env["tag"], env["H"]
    unit, kg = _seed("/units", "Unit"), _seed("/units", "kg")
    product_t, service_t, kit_t = _seed("/product-types", "Product"), _seed("/product-types", "Service"), _seed("/product-types", "Kit")
    new = lambda **kw: client.post("/products", json={"product_type_id": product_t, "unit_of_measure_id": unit, **kw}, headers=H)

    drill = new(name=f"Taladro {tag}", barcode=f"750{tag}", price=1299.9, cost=800, min_stock=5).json()
    nails = new(name=f"Clavo a granel {tag}", unit_of_measure_id=kg, price=45).json()
    service = new(name=f"Instalación {tag}", product_type_id=service_t, price=300).json()
    assert drill["tax_rate_name"] == "IVA 16%" and drill["current_stock"] == 0
    assert new(name="Otro", barcode=f"750{tag}").status_code == 409
    assert new(name="Otro", category_id=drill["id"]).status_code == 422  # not a category

    # Initial stock: loaded into the working branch with the product, as an adjustment
    tape = new(name=f"Cinta {tag}", initial_stock=3).json()
    assert D(tape["current_stock"]) == 3
    kardex = client.get(f"/products/{tape['id']}/kardex", headers=H).json()["items"]
    assert [(k["movement_type"], k["notes"]) for k in kardex] == [("Adjustment", "Inventario inicial")]
    assert new(name="x", product_type_id=service_t, initial_stock=1).status_code == 422  # services carry no stock
    assert new(name="x", initial_stock=1.5).json()["detail"]["field"] == "initial_stock"  # pieces are whole
    assert client.post("/products", json={"name": "x", "product_type_id": product_t, "unit_of_measure_id": unit,
                                          "initial_stock": 1}, headers=A).status_code == 422  # no branch
    client.post("/inventory/adjustments", json={"product_id": tape["id"], "quantity": -3, "notes": "Limpieza test"}, headers=H)
    assert client.delete(f"/products/{tape['id']}", headers=H).status_code == 204

    # products.prices: without it, no price on create and no price change
    _grant(OTHER, {"products": {"read", "create", "update"}})
    try:
        HB = {**B, "X-Branch-Id": env["branch"]}
        assert client.post("/products", json={"name": "Sin precio", "product_type_id": product_t, "unit_of_measure_id": unit,
                                              "price": 10}, headers=B).status_code == 403
        mine = [x["id"] for x in client.get(f"/users/{OTHER}/branches", headers=A).json()]
        client.put(f"/users/{OTHER}/branches", json={"branch_ids": mine + [env["branch"]]}, headers=A)
        r = client.post("/products", json={"name": "Sin permiso", "product_type_id": product_t, "unit_of_measure_id": unit,
                                           "initial_stock": 1}, headers=HB)
        client.put(f"/users/{OTHER}/branches", json={"branch_ids": mine}, headers=A)
        assert r.status_code == 403 and "inventory" in r.json()["detail"]  # initial stock needs inventory.create
        assert client.patch(f"/products/{drill['id']}", json={"price": 1}, headers=B).status_code == 403
        assert client.patch(f"/products/{drill['id']}", json={"price": 1299.9, "barcode": f"750{tag}"}, headers=B).status_code == 200
    finally:
        _grant(OTHER, {})

    found = client.get("/products", params={"q": f"taladro {tag.lower()}"}, headers=H).json()
    assert [p["id"] for p in found["items"]] == [drill["id"]]
    assert client.get(f"/products/by-barcode/750{tag}", headers=H).json()["id"] == drill["id"]

    # Kits: only for kit products, components are stock products
    kit = new(name=f"Kit taladro {tag}", product_type_id=kit_t, price=1500).json()
    comps = lambda items, pid=kit["id"]: client.put(f"/products/{pid}/kit-components", json={"components": items}, headers=H)
    assert [c["name"] for c in comps([{"product_id": drill["id"], "quantity": 1}, {"product_id": nails["id"], "quantity": 0.5}]).json()] \
        == [f"Clavo a granel {tag}", f"Taladro {tag}"]
    assert comps([{"product_id": service["id"], "quantity": 1}]).status_code == 422
    assert comps([{"product_id": kit["id"], "quantity": 1}]).status_code == 422
    assert comps([{"product_id": nails["id"], "quantity": 1}], pid=drill["id"]).status_code == 422
    sup = client.post("/suppliers", json={"name": f"Bosch {tag}"}, headers=A).json()
    assert [s["name"] for s in client.put(f"/products/{drill['id']}/suppliers", json={"supplier_ids": [sup["id"]]}, headers=H).json()] == [f"Bosch {tag}"]

    # Adjustments: note required, whole units, no services, no going below zero
    adj = lambda pid, q, notes="Inventario inicial": client.post("/inventory/adjustments", json={"product_id": pid, "quantity": q, "notes": notes}, headers=H)
    assert adj(drill["id"], 3).status_code == 201
    assert adj(drill["id"], 2.5).status_code == 422
    assert adj(nails["id"], 2.5).status_code == 201  # kg allows decimals
    assert adj(service["id"], 1).status_code == 422
    assert adj(drill["id"], 1, notes="").status_code == 422
    r = adj(drill["id"], -10, notes="Merma")
    assert r.status_code == 422 and D(r.json()["detail"]["available"]) == 3
    assert drill["id"] in [p["id"] for p in client.get("/inventory/low-stock", headers=H).json()]  # 3 <= min 5

    # Purchase: total from items, stock goes up, movements linked
    p = client.post("/purchases", json={"reference": "FAC-001", "supplier_id": sup["id"], "items": [
        {"product_id": drill["id"], "quantity": 4, "unit_cost": 812.333},
    ]}, headers=H)
    assert p.status_code == 422  # unit_cost has 2 decimals at most
    p = client.post("/purchases", json={"reference": "FAC-001", "supplier_id": sup["id"], "items": [
        {"product_id": drill["id"], "quantity": 4, "unit_cost": 812.33},
        {"product_id": nails["id"], "quantity": 10.25, "unit_cost": 30.5},
    ]}, headers=H).json()
    assert D(p["total"]) == D("3249.32") + D("312.63") and len(p["movements"]) == 2
    assert client.post("/purchases", json={"items": [{"product_id": kit["id"], "quantity": 1, "unit_cost": 1}]}, headers=H).status_code == 422
    stock = {s["id"]: D(s["current_stock"]) for s in client.get("/stock", params={"q": tag}, headers=H).json()["items"]}
    assert stock[drill["id"]] == 7 and stock[nails["id"]] == D("12.75") and service["id"] not in stock
    kardex = client.get(f"/products/{drill['id']}/kardex", headers=H).json()["items"]
    assert [k["movement_type"] for k in kardex] == ["Purchase", "Adjustment"] and D(kardex[0]["stock_after"]) == 7
    other = next(b["id"] for b in client.get(f"/users/{ADMIN}/branches", headers=A).json() if b["id"] != env["branch"])
    assert client.get(f"/purchases/{p['id']}", headers={**A, "X-Branch-Id": other}).status_code == 404  # other branch
    assert client.get(f"/purchases/{p['id']}", headers=H).json()["reference"] == "FAC-001"

    # The type can't change once there are movements; delete is blocked while there's stock
    r = client.patch(f"/products/{drill['id']}", json={"product_type_id": service_t}, headers=H)
    assert r.status_code == 409 and r.json()["detail"]["field"] == "product_type_id"
    r = client.delete(f"/products/{drill['id']}", headers=H)
    assert r.status_code == 409 and r.json()["detail"]["blockers"] == {"in_kits": 1, "branches_with_stock": 1}
    history = client.get(f"/products/{drill['id']}/history", headers=H).json()["items"]
    assert {h["entity_type"] for h in history} >= {"product", "product_supplier", "stock"}
    kit_history = client.get(f"/products/{kit['id']}/history", headers=H).json()["items"]
    assert "kit_component" in {h["entity_type"] for h in kit_history}  # component links live in the kit's history

    # Clean up: empty the stock so the branch can be deleted, then delete everything
    adj(drill["id"], -7, notes="Limpieza test")
    adj(nails["id"], -12.75, notes="Limpieza test")
    for pid in (kit["id"], drill["id"], nails["id"], service["id"]):
        assert client.delete(f"/products/{pid}", headers=H).status_code == 204
    client.delete(f"/suppliers/{sup['id']}", headers=A)
