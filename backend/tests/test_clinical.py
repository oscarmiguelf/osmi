# Integration test: the patient record (health). Encrypted at rest, every opening logged, signed notes are final.
import base64
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.infrastructure.persistence.database import SessionLocal
from tests.test_calendar import ADMIN, OTHER, A, B, client

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


def _grant_other(on: bool):
    with SessionLocal() as s:
        if on:
            s.execute(text("""
                INSERT INTO user_modules (user_id, module_id, granted_by) SELECT :u, id, :a FROM modules WHERE code = 'clinical'
                ON CONFLICT DO NOTHING
            """), {"u": OTHER, "a": ADMIN})
            s.execute(text("""
                INSERT INTO user_module_permissions (user_id, module_id, permission_id, granted_by)
                SELECT :u, p.module_id, p.id, :a FROM permissions p JOIN modules m ON m.id = p.module_id AND m.code = 'clinical'
                ON CONFLICT DO NOTHING
            """), {"u": OTHER, "a": ADMIN})
        else:
            for table in ("user_module_permissions", "user_modules"):
                s.execute(text(f"DELETE FROM {table} WHERE user_id = :u AND module_id = (SELECT id FROM modules WHERE code = 'clinical')"), {"u": OTHER})
        s.commit()


def test_clinical_record():
    tag = secrets.token_hex(3)
    branch = client.post("/branches", json={"name": f"Consultorio {tag}", "code": f"C{tag[:4]}".upper()}, headers=A).json()["id"]
    H = {**A, "X-Branch-Id": branch}
    pat = client.post("/customers", json={"full_name": f"Paciente {tag}", "phone": "55" + str(secrets.randbelow(10**8)).zfill(8)}, headers=A).json()
    start = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(microsecond=0)
    appt = client.post("/appointments", json={"customer_id": pat["id"], "title": "Consulta", "starts_at": start.isoformat(),
                                              "ends_at": (start + timedelta(minutes=30)).isoformat()}, headers=H).json()
    try:
        # Its own module: customers.read isn't enough
        assert client.get(f"/clinical/patients/{pat['id']}", headers=B).status_code == 403

        # Background, stored encrypted
        bg = client.put(f"/clinical/patients/{pat['id']}/background", json={"allergies": f"Penicilina {tag}"}, headers=A).json()
        assert bg["data"]["allergies"] == f"Penicilina {tag}"
        assert client.put(f"/clinical/patients/{pat['id']}/background", json={"bogus": 1}, headers=A).status_code == 422
        with SessionLocal() as s:
            raw = s.execute(text("SELECT data_enc FROM clinical_records WHERE customer_id = :c"), {"c": pat["id"]}).scalar()
        assert tag.encode() not in bytes(raw)

        # A note from the appointment; only one per appointment
        note = client.post("/clinical/notes", json={"customer_id": pat["id"], "appointment_id": appt["id"],
                                                    "body": {"reason": "Dolor de cabeza", "vitals": {"bp": "120/80"}}}, headers=H)
        assert note.status_code == 201, note.text
        note = note.json()
        r = client.post("/clinical/notes", json={"customer_id": pat["id"], "appointment_id": appt["id"]}, headers=H)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "note_exists"

        # Signing needs a diagnosis; only the author edits or signs
        assert client.post(f"/clinical/notes/{note['id']}/sign", headers=A).status_code == 422
        _grant_other(True)
        assert client.patch(f"/clinical/notes/{note['id']}", json={"diagnosis": "x"}, headers=B).status_code == 403
        body = {**note["body"], "diagnosis": "Cefalea tensional", "plan": "Paracetamol"}
        assert client.patch(f"/clinical/notes/{note['id']}", json=body, headers=A).json()["body"]["diagnosis"] == "Cefalea tensional"
        signed = client.post(f"/clinical/notes/{note['id']}/sign", headers=A).json()
        assert signed["signed_at"]

        # Signed: no more edits, addenda only (anyone with the permission)
        r = client.patch(f"/clinical/notes/{note['id']}", json=body, headers=A)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "signed"
        assert client.post(f"/clinical/notes/{note['id']}/addenda", json={"text": "Regresa en 1 semana"}, headers=B).json()["addenda"][0]["text"] == "Regresa en 1 semana"

        # Prescription (print logs the access)
        p = client.post(f"/clinical/notes/{note['id']}/prescriptions", json={"items": [{"name": "Paracetamol 500 mg", "dose": "1 tableta c/8 h"}]}, headers=A).json()
        printed = client.get(f"/clinical/prescriptions/{p['id']}", headers=A).json()
        assert printed["items"][0]["name"] == "Paracetamol 500 mg" and printed["diagnosis"] == "Cefalea tensional"

        # Files: PDF or image by its bytes, not its name
        assert client.post(f"/clinical/patients/{pat['id']}/files", files={"file": ("x.pdf", b"not a pdf", "application/pdf")}, headers=A).status_code == 422
        f = client.post(f"/clinical/patients/{pat['id']}/files", data={"label": "Biometría"},
                        files={"file": ("lab.pdf", b"%PDF-1.4\n%test\n", "application/pdf")}, headers=A)
        assert f.status_code == 201, f.text
        got = client.get(f"/clinical/files/{f.json()['id']}", headers=A)
        assert got.content.startswith(b"%PDF") and got.headers["cache-control"] == "no-store"

        # Odontogram: the latest finding per tooth/surface wins; invalid teeth rejected
        assert client.post(f"/clinical/patients/{pat['id']}/dental", json={"entries": [{"tooth": 19, "condition": "caries"}]}, headers=A).status_code == 422
        client.post(f"/clinical/patients/{pat['id']}/dental", json={"entries": [{"tooth": 16, "surface": "O", "condition": "caries"}]}, headers=A)
        chart = client.post(f"/clinical/patients/{pat['id']}/dental", json={"entries": [{"tooth": 16, "surface": "O", "condition": "filled"}]}, headers=A).json()
        assert [(e["tooth"], e["condition"]) for e in chart] == [(16, "filled")]

        # Consent with a drawn signature (PNG only)
        bad = client.post(f"/clinical/patients/{pat['id']}/consents", json={"kind": "privacy", "signer_name": "X", "text": "Aviso",
                                                                         "signature": "data:image/png;base64,AAAA"}, headers=A)
        assert bad.status_code == 422
        consents = client.post(f"/clinical/patients/{pat['id']}/consents", json={"kind": "privacy", "signer_name": pat["full_name"], "text": "Aviso de privacidad",
                                                                              "signature": "data:image/png;base64," + base64.b64encode(PNG).decode()}, headers=A).json()
        sig = client.get(f"/clinical/patients/{pat['id']}/signatures/{consents[0]['signature_file']}", headers=A)
        assert sig.status_code == 200 and sig.content == PNG

        # The whole record, and who opened it
        rec = client.get(f"/clinical/patients/{pat['id']}", headers=A).json()
        assert len(rec["notes"]) == 1 and rec["notes"][0]["diagnosis"] == "Cefalea tensional" and rec["files"] and rec["consents"]
        log = client.get(f"/clinical/patients/{pat['id']}/access-log", headers=A).json()
        assert {"view", "print", "file"} <= {e["action"] for e in log}
        assert any(n["id"] == note["id"] for n in client.get("/clinical/recent", headers=H).json())
    finally:
        _grant_other(False)
        client.post(f"/appointments/{appt['id']}/cancel", json={"reason": "Prueba"}, headers=H)
        client.delete(f"/customers/{pat['id']}", headers=A)
