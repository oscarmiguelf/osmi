import uuid

from app.application.errors import Conflict, Forbidden, Invalid, NotFound
from app.application.ports.clinical_repository import ClinicalRepository
from app.application.ports.image_storage import ImageStorage
from app.application.product_image_service import sniff

MAX_FILE = 10 * 1024 * 1024
# FDI numbering: permanent 11-48, primary (baby) 51-85
TEETH = {q * 10 + n for q in (1, 2, 3, 4) for n in range(1, 9)} | {q * 10 + n for q in (5, 6, 7, 8) for n in range(1, 6)}
FILE_EXT = {"application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def sniff_file(data: bytes) -> str | None:
    """PDF or image, from the bytes (not the name)."""
    return "application/pdf" if data[:5] == b"%PDF-" else sniff(data)


class ClinicalService:
    """Patient records. Every opening of a record is logged; signed notes are final (addenda only)."""

    def __init__(self, repo: ClinicalRepository, storage: ImageStorage):
        self.repo = repo
        self.storage = storage

    # --- record -------------------------------------------------------------
    def record(self, uid, customer_id):
        patient = self._patient(customer_id)
        self.repo.log_access(uid, customer_id, "view")
        self.repo.commit()
        return {"patient": patient, "background": self.repo.background(customer_id), "notes": self.repo.notes(customer_id),
                "prescriptions": self.repo.prescriptions(customer_id), "files": self.repo.files(customer_id),
                "dental_chart": self.repo.dental_chart(customer_id), "consents": self.repo.consents(customer_id), "privacy_notice": self.repo.setting("privacy_notice")}

    def save_background(self, uid, customer_id, data):
        self._patient(customer_id)
        self.repo.save_background(uid, customer_id, data)
        self.repo.commit()
        return self.repo.background(customer_id)

    # --- notes --------------------------------------------------------------
    def create_note(self, uid, branch, data):
        self._patient(data["customer_id"])
        if data.get("appointment_id"):
            appt = self.repo.appointment(data["appointment_id"])
            if appt is None or appt["customer_id"] != data["customer_id"] or appt["branch_id"] != branch:
                raise Invalid({"message": "the appointment isn't this patient's here", "field": "appointment_id"})
            if appt["note_id"]:
                raise Conflict({"message": "that appointment already has a note", "code": "note_exists", "note_id": str(appt["note_id"])})
        note_id = self.repo.create_note(uid, branch, data)
        self.repo.commit()
        return self.note(uid, note_id, log=False)

    def note(self, uid, note_id, log=True):
        note = self.repo.note(note_id)
        if note is None:
            raise NotFound("note not found")
        if log:
            self.repo.log_access(uid, note["customer_id"], "view")
            self.repo.commit()
        return note

    def update_note(self, uid, note_id, body):
        note = self._own_draft(uid, note_id)
        self.repo.update_note(note["id"], body)
        self.repo.commit()
        return self.note(uid, note_id, log=False)

    def sign(self, uid, note_id):
        note = self._own_draft(uid, note_id)
        if not (note["body"].get("diagnosis") or "").strip():
            raise Invalid({"message": "a note is signed with a diagnosis", "field": "diagnosis"})
        self.repo.sign_note(uid, note["id"])
        self.repo.commit()
        return self.note(uid, note_id, log=False)

    def addendum(self, uid, note_id, text):
        note = self.note(uid, note_id, log=False)
        if not note["signed_at"]:
            raise Conflict({"message": "edit the note itself until it's signed", "code": "not_signed"})
        self.repo.add_addendum(uid, note_id, text)
        self.repo.commit()
        return self.note(uid, note_id, log=False)

    def prescribe(self, uid, note_id, items):
        note = self.note(uid, note_id, log=False)
        if not items:
            raise Invalid({"message": "add at least one medicine", "field": "items"})
        presc_id = self.repo.add_prescription(uid, note_id, note["customer_id"], items)
        self.repo.commit()
        return self.repo.prescription(presc_id)

    def prescription(self, uid, presc_id):
        presc = self.repo.prescription(presc_id)
        if presc is None:
            raise NotFound("prescription not found")
        self.repo.log_access(uid, presc["customer_id"], "print")
        self.repo.commit()
        return presc

    # --- files, odontogram, consents -------------------------------------------
    def add_file(self, uid, customer_id, label, data, note_id=None):
        self._patient(customer_id)
        if len(data) > MAX_FILE:
            raise Invalid({"message": "the file is too big", "code": "too_big", "max_bytes": MAX_FILE})
        content_type = sniff_file(data)
        if content_type is None:
            raise Invalid({"message": "only PDF or images", "code": "bad_type"})
        name = f"clinical-{uuid.uuid4()}.{FILE_EXT[content_type]}"
        self.storage.save(name, data)
        try:
            row = self.repo.add_file(uid, customer_id, note_id, label or name, name, content_type, len(data))
            self.repo.commit()
        except Exception:
            self.repo.rollback()
            self.storage.delete(name)
            raise
        return row

    def file(self, uid, file_id):
        f = self.repo.file(file_id)
        if f is None:
            raise NotFound("file not found")
        self.repo.log_access(uid, f["customer_id"], "file")
        self.repo.commit()
        return self.storage.path(f["file_name"]), f["content_type"], f["label"]

    def dental(self, uid, customer_id, entries):
        self._patient(customer_id)
        if not entries:
            raise Invalid({"message": "nothing to record", "field": "entries"})
        if any(e["tooth"] not in TEETH for e in entries):
            raise Invalid({"message": "unknown tooth (FDI numbering)", "field": "tooth"})
        self.repo.add_dental(uid, customer_id, entries)
        self.repo.commit()
        return self.repo.dental_chart(customer_id)

    def consent(self, uid, customer_id, data, signature: bytes | None):
        self._patient(customer_id)
        name = None
        if signature:
            if sniff(signature) != "image/png" or len(signature) > 500_000:
                raise Invalid({"message": "the signature must be a PNG image", "field": "signature"})
            name = f"signature-{uuid.uuid4()}.png"
            self.storage.save(name, signature)
        self.repo.add_consent(uid, customer_id, {**data, "signature_file": name})
        self.repo.commit()
        return self.repo.consents(customer_id)

    def signature(self, uid, customer_id, file_name):
        if not any(c["signature_file"] == file_name for c in self.repo.consents(customer_id)):
            raise NotFound("signature not found")
        return self.storage.path(file_name)

    def access_log(self, customer_id):
        return self.repo.access_log(customer_id, 100)

    def recent(self, uid, branch):
        return self.repo.recent(uid, branch)

    # --- helpers ------------------------------------------------------------
    def _patient(self, customer_id):
        patient = self.repo.patient(customer_id)
        if patient is None:
            raise NotFound("patient not found")
        return patient

    def _own_draft(self, uid, note_id):
        note = self.note(uid, note_id, log=False)
        if note["signed_at"]:
            raise Conflict({"message": "the note is signed; add an addendum", "code": "signed"})
        if note["author_id"] != uid:
            raise Forbidden("only the author edits or signs the note")
        return note
