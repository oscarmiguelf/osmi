# Integration test against the real DB: suppliers CRUD, duplicate names, product links, purchases by branch, history.
import secrets
from datetime import datetime, timedelta, timezone

from tests.test_calendar import A, client
from tests.test_purchases import _seed


def test_suppliers():
    tag = secrets.token_hex(3).upper()
    name = f"Truper {tag}"
    branch = client.post("/branches", json={"name": f"Prov {tag}", "code": f"V{tag}"}, headers=A).json()["id"]
    H = {**A, "X-Branch-Id": branch}
    ptype, unit = _seed("/product-types", "Product"), _seed("/units", "Unit")
    prods = [client.post("/products", json={"name": f"{n} {tag}", "product_type_id": ptype, "unit_of_measure_id": unit}, headers=A).json()
             for n in ("Martillo", "Pinza", "Llave")]
    sup = dup = None
    try:
        # Validation: phone free text (no 10-digit rule), email trimmed + lowercased, blank -> null
        assert client.post("/suppliers", json={"name": " "}, headers=A).status_code == 422
        assert client.post("/suppliers", json={"name": name, "phone": "55-abc"}, headers=A).status_code == 422
        assert client.post("/suppliers", json={"name": name, "email": "ventas@"}, headers=A).status_code == 422
        sup = client.post("/suppliers", json={"name": name, "phone": "+52 (55) 1234-5678", "email": " Ventas@Truper.MX "},
                          headers=A).json()
        assert sup["email"] == "ventas@truper.mx" and sup["phone"] == "+52 (55) 1234-5678"

        # Same name ignoring case: 409 with the matches, unless force=true
        r = client.post("/suppliers", json={"name": f"truper {tag.lower()}"}, headers=A)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "duplicate_name" and r.json()["detail"]["matches"][0]["id"] == sup["id"]
        dup = client.post("/suppliers", params={"force": "true"}, json={"name": f"truper {tag.lower()}"}, headers=A).json()
        assert client.patch(f"/suppliers/{dup['id']}", json={"name": f"Urrea {tag}"}, headers=A).status_code == 200
        assert client.patch(f"/suppliers/{dup['id']}", json={"name": name}, headers=A).status_code == 409
        assert client.patch(f"/suppliers/{sup['id']}", json={"name": f"TRUPER {tag}"}, headers=A).status_code == 200  # own casing fix
        assert client.patch(f"/suppliers/{sup['id']}", json={"email": None}, headers=A).json()["email"] is None

        # Search (paginated) and the selector list
        found = client.get("/suppliers", params={"q": tag.lower()}, headers=A).json()
        assert found["total"] == 2 and {s["id"] for s in found["items"]} == {sup["id"], dup["id"]}
        assert any(s["id"] == sup["id"] for s in client.get("/suppliers/options", headers=A).json())

        # Products: replace the set, link (idempotent), unlink
        p1, p2, p3 = (p["id"] for p in prods)
        assert client.put(f"/suppliers/{sup['id']}/products", json={"product_ids": [p1, p2, p2]}, headers=A).status_code == 200
        r = client.put(f"/suppliers/{sup['id']}/products", json={"product_ids": [p1, "00000000-0000-0000-0000-000000000000"]}, headers=A)
        assert r.status_code == 422
        assert client.post(f"/suppliers/{sup['id']}/products/{p3}", headers=A).json()["created"] is True
        assert client.post(f"/suppliers/{sup['id']}/products/{p3}", headers=A).json()["created"] is False
        assert client.delete(f"/suppliers/{sup['id']}/products/{p2}", headers=A).status_code == 204
        assert client.delete(f"/suppliers/{sup['id']}/products/{p2}", headers=A).status_code == 404
        linked = [p["id"] for p in client.get(f"/suppliers/{sup['id']}/products", headers=A).json()["items"]]
        assert sorted(linked) == sorted([p1, p3])
        assert {s["id"] for s in client.get(f"/products/{p1}", headers=A).json()["suppliers"]} == {sup["id"]}

        # Purchases, summary and cost history (branches the person belongs to)
        buy = lambda cost, qty: client.post("/purchases", json={"supplier_id": sup["id"], "items": [{"product_id": p1, "quantity": qty, "unit_cost": cost}]},
                                            headers=H).json()
        first, second = buy(100, 2), buy(120, 1)
        assert [p["id"] for p in client.get(f"/suppliers/{sup['id']}/purchases", headers=A).json()["items"]] == [second["id"], first["id"]]
        summary = client.get(f"/suppliers/{sup['id']}/summary", headers=A).json()
        assert summary["purchases"] == 2 and float(summary["total_spent"]) == 320 and float(summary["avg_purchase"]) == 160
        later = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        assert client.get(f"/suppliers/{sup['id']}/summary", params={"from": later}, headers=A).json()["purchases"] == 0
        assert [float(x["unit_cost"]) for x in client.get(f"/suppliers/{sup['id']}/price-history/{p1}", headers=A).json()] == [120, 100]
        detail = client.get(f"/suppliers/{sup['id']}", headers=A).json()
        assert detail["products"] == 2 and detail["purchases"] == 2 and detail["last_purchase_at"]

        # Delete: allowed with purchases; unlinks its products, gone from the selector, still readable; restore relinks
        assert client.delete(f"/suppliers/{sup['id']}", headers=A).status_code == 204
        assert client.get(f"/products/{p1}", headers=A).json()["suppliers"] == []
        assert all(s["id"] != sup["id"] for s in client.get("/suppliers/options", headers=A).json())
        assert client.get(f"/suppliers/{sup['id']}", headers=A).json()["deleted_at"]
        assert client.patch(f"/suppliers/{sup['id']}", json={"name": "x"}, headers=A).status_code == 404
        assert client.post("/purchases", json={"supplier_id": sup["id"], "items": [{"product_id": p1, "quantity": 1, "unit_cost": 1}]},
                           headers=H).status_code in (404, 409, 422)
        assert client.post(f"/suppliers/{sup['id']}/restore", headers=A).json()["products"] == 2
        assert client.post(f"/suppliers/{sup['id']}/restore", headers=A).status_code == 404

        # History: the supplier's changes and its product links
        hist = client.get(f"/suppliers/{sup['id']}/history", params={"page_size": 100}, headers=A).json()["items"]
        kinds = {(h["entity_type"], h["action"]) for h in hist}
        assert ("supplier", "INSERT") in kinds and ("supplier", "UPDATE") in kinds and ("product_supplier", "INSERT") in kinds
        assert any(h["product"] == f"Martillo {tag}" for h in hist if h["entity_type"] == "product_supplier")

        # Not a supplier user: no access
        assert client.get("/suppliers").status_code == 401
    finally:
        for p in client.get("/purchases", params={"supplier_id": sup["id"]} if sup else {}, headers=H).json().get("items", []):
            client.delete(f"/purchases/{p['id']}", headers=H)
        for p in prods:
            left = float(client.get(f"/products/{p['id']}", headers=H).json().get("current_stock") or 0)
            if left:
                client.post("/inventory/adjustments", json={"product_id": p["id"], "quantity": str(-left), "notes": "Limpieza test"}, headers=H)
            client.delete(f"/products/{p['id']}", headers=A)
        for s in (sup, dup):
            if s:
                client.delete(f"/suppliers/{s['id']}", headers=A)
        client.delete(f"/branches/{branch}", headers=A)
