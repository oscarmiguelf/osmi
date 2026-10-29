import json
import os

from sqlalchemy import text
from sqlalchemy.orm import Session

# The key never leaves the API: the database only ever sees ciphertext (pgp_sym_encrypt / pgp_sym_decrypt)
KEY = os.environ.get("CLINICAL_KEY", "")
if len(KEY) < 32:
    raise RuntimeError("CLINICAL_KEY must be set to a random string of at least 32 characters (openssl rand -hex 32)")
ENC = "pgp_sym_encrypt(CAST(:data AS text), :k)"
DEC = "CAST(pgp_sym_decrypt({col}, :k) AS jsonb)"


def _who(alias):
    return f"NULLIF(TRIM(CONCAT({alias}.first_name, ' ', {alias}.last_name)), '')"


class SqlClinicalRepository:
    def __init__(self, session: Session):
        self.session = session

    def _one(self, sql, **params):
        row = self.session.execute(text(sql), {"k": KEY, **params}).mappings().first()
        return dict(row) if row else None

    def _all(self, sql, **params):
        return [dict(r) for r in self.session.execute(text(sql), {"k": KEY, **params}).mappings()]

    def _run(self, sql, **params):
        return self.session.execute(text(sql), {"k": KEY, **params})

    def patient(self, customer_id):
        return self._one("SELECT id, full_name, phone, email, extra FROM customers WHERE id = :id AND deleted_at IS NULL", id=customer_id)

    def log_access(self, user_id, customer_id, action):
        self._run("INSERT INTO clinical_access_log (customer_id, user_id, action) VALUES (:c, :u, :a)", c=customer_id, u=user_id, a=action)

    def background(self, customer_id):
        row = self._one(f"""
            SELECT {DEC.format(col='r.data_enc')} AS data, r.updated_at, {_who('u')} AS updated_by
            FROM clinical_records r JOIN users u ON u.id = r.updated_by WHERE r.customer_id = :c
        """, c=customer_id)
        return row or {"data": {}, "updated_at": None, "updated_by": None}

    def save_background(self, user_id, customer_id, data):
        self._run(f"""
            INSERT INTO clinical_records (customer_id, data_enc, updated_by) VALUES (:c, {ENC}, :u)
            ON CONFLICT (customer_id) DO UPDATE SET data_enc = EXCLUDED.data_enc, updated_by = EXCLUDED.updated_by, updated_at = NOW()
        """, c=customer_id, data=json.dumps(data), u=user_id)

    NOTE = f"""n.id, n.customer_id, n.branch_id, n.appointment_id, n.kind, n.visit_at, n.author_id, {_who('a')} AS author,
        n.signed_at, n.created_at, n.updated_at, {DEC.format(col='n.body_enc')} AS body"""

    def notes(self, customer_id):
        rows = self._all(f"SELECT {self.NOTE} FROM clinical_notes n JOIN users a ON a.id = n.author_id WHERE n.customer_id = :c ORDER BY n.visit_at DESC",
                         c=customer_id)
        return [{**{k: v for k, v in r.items() if k != "body"}, "reason": r["body"].get("reason"), "diagnosis": r["body"].get("diagnosis")}
                for r in rows]

    def note(self, note_id):
        note = self._one(f"SELECT {self.NOTE} FROM clinical_notes n JOIN users a ON a.id = n.author_id WHERE n.id = :id", id=note_id)
        if note:
            note["addenda"] = self._all(f"""
                SELECT d.id, CAST(pgp_sym_decrypt(d.text_enc, :k) AS text) AS text, {_who('u')} AS author, d.created_at
                FROM clinical_addenda d JOIN users u ON u.id = d.author_id WHERE d.note_id = :id ORDER BY d.created_at
            """, id=note_id)
            note["prescriptions"] = [p for p in self.prescriptions(note["customer_id"]) if p["note_id"] == note_id]
        return note

    def create_note(self, user_id, branch_id, data):
        return self._run(f"""
            INSERT INTO clinical_notes (customer_id, branch_id, appointment_id, kind, visit_at, body_enc, author_id)
            VALUES (:c, :b, :a, :kind, COALESCE(CAST(:visit_at AS timestamptz), NOW()), {ENC}, :u) RETURNING id
        """, c=data["customer_id"], b=branch_id, a=data.get("appointment_id"), kind=data.get("kind", "medical"),
            visit_at=data.get("visit_at"), data=json.dumps(data.get("body") or {}), u=user_id).scalar()

    def update_note(self, note_id, body):
        self._run(f"UPDATE clinical_notes SET body_enc = {ENC} WHERE id = :id", data=json.dumps(body), id=note_id)

    def sign_note(self, user_id, note_id):
        self._run("UPDATE clinical_notes SET signed_at = NOW(), signed_by = :u WHERE id = :id", u=user_id, id=note_id)

    def add_addendum(self, user_id, note_id, text_):
        self._run("INSERT INTO clinical_addenda (note_id, text_enc, author_id) VALUES (:n, pgp_sym_encrypt(:t, :k), :u)", n=note_id, t=text_, u=user_id)

    def add_prescription(self, user_id, note_id, customer_id, items):
        return self._run(f"""
            INSERT INTO prescriptions (note_id, customer_id, items_enc, author_id) VALUES (:n, :c, {ENC}, :u) RETURNING id
        """, n=note_id, c=customer_id, data=json.dumps(items), u=user_id).scalar()

    PRESC = f"""p.id, p.note_id, p.customer_id, c.full_name AS patient, c.phone AS patient_phone, p.created_at, {_who('a')} AS author,
        {DEC.format(col='p.items_enc')} AS items"""

    def prescription(self, prescription_id):
        return self._one(f"""
            SELECT {self.PRESC}, (SELECT value FROM settings WHERE key = 'doctor_header') AS doctor_header,
                   b.name AS branch, b.address AS branch_address, b.phone AS branch_phone,
                   {DEC.format(col='n.body_enc')} ->> 'diagnosis' AS diagnosis
            FROM prescriptions p JOIN customers c ON c.id = p.customer_id JOIN users a ON a.id = p.author_id
            JOIN clinical_notes n ON n.id = p.note_id JOIN branches b ON b.id = n.branch_id
            WHERE p.id = :id
        """, id=prescription_id)

    def prescriptions(self, customer_id):
        return self._all(f"""
            SELECT {self.PRESC} FROM prescriptions p JOIN customers c ON c.id = p.customer_id JOIN users a ON a.id = p.author_id
            WHERE p.customer_id = :c ORDER BY p.created_at DESC
        """, c=customer_id)

    def add_file(self, user_id, customer_id, note_id, label, file_name, content_type, size):
        return self._one("""
            INSERT INTO clinical_files (customer_id, note_id, label, file_name, content_type, size_bytes, uploaded_by)
            VALUES (:c, :n, :l, :f, :t, :s, :u) RETURNING id, label, content_type, size_bytes, created_at
        """, c=customer_id, n=note_id, l=label[:200], f=file_name, t=content_type, s=size, u=user_id)

    def files(self, customer_id):
        return self._all(f"""
            SELECT f.id, f.label, f.content_type, f.size_bytes, f.note_id, f.created_at, {_who('u')} AS uploaded_by
            FROM clinical_files f JOIN users u ON u.id = f.uploaded_by WHERE f.customer_id = :c ORDER BY f.created_at DESC
        """, c=customer_id)

    def file(self, file_id):
        return self._one("SELECT id, customer_id, label, file_name, content_type FROM clinical_files WHERE id = :id", id=file_id)

    def dental_chart(self, customer_id):
        """The current chart: the latest finding per tooth and surface."""
        return self._all(f"""
            SELECT DISTINCT ON (e.tooth, COALESCE(e.surface, '-')) e.tooth, e.surface, e.condition, e.note, e.recorded_at, {_who('u')} AS recorded_by
            FROM dental_chart_entries e JOIN users u ON u.id = e.recorded_by
            WHERE e.customer_id = :c ORDER BY e.tooth, COALESCE(e.surface, '-'), e.recorded_at DESC
        """, c=customer_id)

    def add_dental(self, user_id, customer_id, entries):
        self.session.execute(text("""
            INSERT INTO dental_chart_entries (customer_id, tooth, surface, condition, note, recorded_by)
            VALUES (:c, :tooth, :surface, :condition, :note, :u)
        """), [{"c": customer_id, "u": user_id, "surface": None, "note": None, **e} for e in entries])

    def add_consent(self, user_id, customer_id, data):
        self._run("""
            INSERT INTO consents (customer_id, kind, text_snapshot, signer_name, signature_file, recorded_by)
            VALUES (:c, :kind, :text, :signer, :sig, :u)
        """, c=customer_id, kind=data["kind"], text=data["text"], signer=data["signer_name"], sig=data.get("signature_file"), u=user_id)

    def consents(self, customer_id):
        return self._all(f"""
            SELECT x.id, x.kind, x.signer_name, x.signature_file, x.accepted_at, {_who('u')} AS recorded_by, x.text_snapshot
            FROM consents x JOIN users u ON u.id = x.recorded_by WHERE x.customer_id = :c ORDER BY x.accepted_at DESC
        """, c=customer_id)

    def access_log(self, customer_id, limit):
        return self._all(f"""
            SELECT l.action, l.at, u.email, {_who('u')} AS name FROM clinical_access_log l JOIN users u ON u.id = l.user_id
            WHERE l.customer_id = :c ORDER BY l.at DESC LIMIT :limit
        """, c=customer_id, limit=limit)

    def recent(self, user_id, branch_id):
        """Notes of this branch in the last 30 days (my drafts first)."""
        rows = self._all(f"""
            SELECT n.id, n.customer_id, c.full_name AS patient, n.kind, n.visit_at, n.signed_at, n.author_id, {_who('a')} AS author,
                   {DEC.format(col='n.body_enc')} ->> 'reason' AS reason
            FROM clinical_notes n JOIN customers c ON c.id = n.customer_id JOIN users a ON a.id = n.author_id
            WHERE n.branch_id = :b AND n.visit_at > NOW() - INTERVAL '30 days'
            ORDER BY (n.signed_at IS NULL AND n.author_id = :u) DESC, n.visit_at DESC LIMIT 100
        """, b=branch_id, u=user_id)
        return rows

    def appointment(self, appointment_id):
        return self._one("""
            SELECT a.id, a.customer_id, a.branch_id, (SELECT id FROM clinical_notes WHERE appointment_id = a.id) AS note_id
            FROM appointments a WHERE a.id = :id
        """, id=appointment_id)

    def setting(self, key):
        return self.session.execute(text("SELECT value FROM settings WHERE key = :k"), {"k": key}).scalar() or ""

    def commit(self):
        self.session.commit()

    def rollback(self):
        self.session.rollback()
