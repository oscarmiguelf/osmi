# Integration test: settings (WhatsApp number) and the public catalog (no sign-in).
import secrets

from tests.test_calendar import A, B, client
from tests.test_product_images import PNG
from tests.test_purchases import _seed


def test_settings_and_public_catalog():
    tag = secrets.token_hex(3)
    before = client.get("/settings", headers=A).json()["whatsapp_number"]
    branch = client.post("/branches", json={"name": f"Catálogo {tag}", "code": f"K{tag[:4]}".upper()}, headers=A).json()["id"]
    H = {**A, "X-Branch-Id": branch}
    ptype, stype, ktype = (_seed("/product-types", n) for n in ("Product", "Service", "Kit"))
    unit, svc_unit = _seed("/units", "Unit"), _seed("/units", "Service")
    cat = client.post("/categories", json={"name": f"Herramienta {tag}"}, headers=A).json()
    mk = lambda name, t, u, **kw: client.post("/products", json={"name": f"{name} {tag}", "product_type_id": t, "unit_of_measure_id": u,
                                                                 "price": 100, **kw}, headers=H).json()
    with_stock = mk("Martillo", ptype, unit, category_id=cat["id"], initial_stock=3)
    no_stock = mk("Pinza", ptype, unit)
    service = mk("Afilado", stype, svc_unit)
    kit = mk("Juego", ktype, unit)
    try:
        # Settings: only with the settings module; number normalized and validated
        assert client.get("/settings", headers=B).status_code == 403
        assert client.patch("/settings", json={"whatsapp_number": "55-12"}, headers=A).status_code == 422
        assert client.patch("/settings", json={"whatsapp_number": "+52 1 (55) 1234-5678"}, headers=A).json()["whatsapp_number"] == "5215512345678"

        # Public: no token needed
        info = client.get("/public/catalog").json()
        assert info["ordering"] is True and info["whatsapp_number"] == "5215512345678"
        assert any(c["id"] == cat["id"] for c in info["categories"])
        shown = {p["id"]: p for p in client.get("/public/catalog/products", params={"q": tag, "page_size": 60}).json()["items"]}
        assert set(shown) == {with_stock["id"], service["id"]}  # no stock and kits are not shown
        hammer = shown[with_stock["id"]]
        assert hammer["availability"] == "few" and hammer["max_order"] == 3 and "available" not in hammer  # no exact stock
        assert shown[service["id"]]["is_service"] is True and shown[service["id"]]["availability"] is None
        assert "cost" not in hammer
        client.post("/inventory/adjustments", json={"product_id": with_stock["id"], "quantity": "-2", "notes": "Prueba"}, headers=H)
        one = client.get("/public/catalog/products", params={"q": f"martillo {tag}"}).json()["items"][0]
        assert one["availability"] == "one" and one["max_order"] == 1
        client.post("/inventory/adjustments", json={"product_id": with_stock["id"], "quantity": "11", "notes": "Prueba"}, headers=H)
        plenty = client.get("/public/catalog/products", params={"q": f"martillo {tag}"}).json()["items"][0]
        assert plenty["availability"] == "plenty" and plenty["max_order"] is None
        only = lambda kind: {p["id"] for p in client.get("/public/catalog/products", params={"q": tag, "kind": kind}).json()["items"]}
        assert only("services") == {service["id"]} and only("products") == {with_stock["id"]}

        # Images: public for shown products only
        img = client.post(f"/products/{with_stock['id']}/images", files={"file": ("a.png", PNG, "image/png")}, headers=A).json()[0]
        hidden = client.post(f"/products/{no_stock['id']}/images", files={"file": ("a.png", PNG, "image/png")}, headers=A).json()[0]
        assert client.get("/public/catalog/products", params={"q": f"martillo {tag}"}).json()["items"][0]["image_ids"] == [img["id"]]
        r = client.get(f"/public/catalog/products/{with_stock['id']}/images/{img['id']}")
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"
        assert client.get(f"/public/catalog/products/{no_stock['id']}/images/{hidden['id']}").status_code == 404

        # No number: the catalog still shows, ordering is off
        client.patch("/settings", json={"whatsapp_number": ""}, headers=A)
        assert client.get("/public/catalog").json() | {"categories": []} == {"whatsapp_number": None, "ordering": False, "categories": []}
    finally:
        client.patch("/settings", json={"whatsapp_number": before}, headers=A)
        for p in (with_stock, no_stock):
            for i in client.get(f"/products/{p['id']}/images", headers=A).json():
                client.delete(f"/products/{p['id']}/images/{i['id']}", headers=A)
        left = float(client.get(f"/products/{with_stock['id']}", headers=H).json()["current_stock"])
        if left:
            client.post("/inventory/adjustments", json={"product_id": with_stock["id"], "quantity": str(-left), "notes": "Limpieza test"}, headers=H)
        for p in (with_stock, no_stock, service, kit):
            client.delete(f"/products/{p['id']}", headers=A)
        client.delete(f"/categories/{cat['id']}", headers=A)
        client.delete(f"/branches/{branch}", headers=A)
