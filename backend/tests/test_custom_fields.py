# Integration test: business type (giro), suggested custom fields, and customers' extra values.
import secrets

from app.application.custom_fields import SUGGESTED
from tests.test_calendar import A, B, client


def test_business_type_and_custom_fields():
    before = client.get("/settings", headers=A).json().get("business_type", "retail")
    existing = {f["id"] for f in client.get("/custom-fields", headers=A).json()}
    made, customer = [], None
    try:
        assert client.patch("/settings", json={"business_type": "bakery"}, headers=A).status_code == 422
        client.patch("/settings", json={"business_type": "health"}, headers=A)
        assert client.get("/auth/me", headers=A).json()["business_type"] == "health"
        fields = client.get("/custom-fields", headers=A).json()
        if not existing:  # suggested only when there were none
            assert [f["label"] for f in fields] == [s[0] for s in SUGGESTED["health"]]
        made += [f["id"] for f in fields if f["id"] not in existing]

        # Definitions: only settings.update; select needs options; the type can't change
        tag = secrets.token_hex(3)
        assert client.post("/custom-fields", json={"label": f"Peso {tag}", "field_type": "number"}, headers=B).status_code == 403
        assert client.post("/custom-fields", json={"label": f"Lista {tag}", "field_type": "select"}, headers=A).status_code == 422
        weight = client.post("/custom-fields", json={"label": f"Peso {tag}", "field_type": "number", "required": True}, headers=A).json()
        insured = client.post("/custom-fields", json={"label": f"Asegurado {tag}", "field_type": "boolean"}, headers=A).json()
        plan = client.post("/custom-fields", json={"label": f"Plan {tag}", "field_type": "select", "options": ["Básico", "Plus"]}, headers=A).json()
        made += [weight["id"], insured["id"], plan["id"]]
        assert client.post("/custom-fields", json={"label": f"PESO {tag}", "field_type": "text"}, headers=A).status_code == 409
        assert client.patch(f"/custom-fields/{weight['id']}", json={"field_type": "text"}, headers=A).status_code == 422

        # Customer values: validated by type, required, options; unknown keys refused
        new = lambda extra: client.post("/customers", json={"full_name": f"Paciente {tag}", "phone": "55" + str(secrets.randbelow(10**8)).zfill(8),
                                                             "extra": extra}, headers=A)
        r = new({weight["id"]: "abc", plan["id"]: "Gold"})
        assert r.status_code == 422 and set(r.json()["detail"]["errors"]) >= {weight["id"], plan["id"]}
        assert new({weight["id"]: "70"}).status_code in (201, 422)  # other required suggested fields may apply
        assert new({"not-a-field": "x", weight["id"]: "70"}).status_code == 422
        r = new({weight["id"]: "70.5", insured["id"]: "on", plan["id"]: "Plus"})
        assert r.status_code == 201, r.text
        customer = r.json()
        assert customer["extra"][weight["id"]] == "70.5" and customer["extra"][insured["id"]] is True
        # Missing the required one on edit
        assert client.patch(f"/customers/{customer['id']}", json={"extra": {plan["id"]: "Básico"}}, headers=A).status_code == 422
        # A deleted field: its value stays in the customer, the rest is edited
        client.delete(f"/custom-fields/{plan['id']}", headers=A)
        c = client.patch(f"/customers/{customer['id']}", json={"extra": {weight["id"]: "71"}}, headers=A).json()
        assert c["extra"][weight["id"]] == "71" and c["extra"][plan["id"]] == "Plus"
    finally:
        client.patch("/settings", json={"business_type": before}, headers=A)
        for f in made:
            client.delete(f"/custom-fields/{f}", headers=A)
        if customer:
            client.delete(f"/customers/{customer['id']}", headers=A)
