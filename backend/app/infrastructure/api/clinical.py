import base64
import binascii
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Path, UploadFile
from fastapi.responses import FileResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.application.clinical_service import MAX_FILE, ClinicalService
from app.application.errors import Invalid
from app.infrastructure.api.permissions import CurrentBranch, require_permission
from app.infrastructure.persistence.clinical_repository import SqlClinicalRepository
from app.infrastructure.persistence.database import SessionLocal
from app.infrastructure.persistence.image_storage import LocalImageStorage

# Patient records (health business type). Their own module: seeing a record is clinical.read, not customers.read.
router = APIRouter(prefix="/clinical", tags=["clinical"])
Txt = Annotated[str, Field(max_length=5000)] | None
Short = Annotated[str, Field(max_length=40)] | None


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Vitals(Strict):
    weight: Short = None
    height: Short = None
    bp: Short = None
    hr: Short = None
    rr: Short = None
    temp: Short = None
    spo2: Short = None


class NoteBody(Strict):
    reason: Txt = None
    history: Txt = None
    exam: Txt = None
    vitals: Vitals | None = None
    diagnosis: Txt = None
    plan: Txt = None


class NoteIn(Strict):
    customer_id: uuid.UUID
    appointment_id: uuid.UUID | None = None
    kind: Literal["medical", "dental"] = "medical"
    visit_at: AwareDatetime | None = None
    body: NoteBody = NoteBody()


class Background(Strict):
    hereditary: Txt = None
    pathological: Txt = None
    non_pathological: Txt = None
    gyneco: Txt = None
    allergies: Txt = None
    medications: Txt = None
    surgeries: Txt = None
    notes: Txt = None


class AddendumIn(Strict):
    text: Annotated[str, Field(min_length=1, max_length=5000)]


class Medicine(Strict):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    dose: Annotated[str, Field(max_length=200)] = ""
    instructions: Annotated[str, Field(max_length=500)] = ""


class PrescriptionIn(Strict):
    items: Annotated[list[Medicine], Field(max_length=30)]


class DentalEntry(Strict):
    tooth: int
    surface: Literal["M", "D", "O", "V", "L"] | None = None
    condition: Literal["healthy", "caries", "filled", "crown", "root_canal", "missing", "extraction", "implant", "fracture", "sealant"]
    note: Annotated[str, Field(max_length=300)] | None = None


class DentalIn(Strict):
    entries: Annotated[list[DentalEntry], Field(max_length=200)]


class ConsentIn(Strict):
    kind: Literal["privacy", "treatment"]
    signer_name: Annotated[str, Field(min_length=1, max_length=200)]
    text: Annotated[str, Field(min_length=1, max_length=20000)]
    signature: Annotated[str, Field(max_length=700_000)] | None = None  # data:image/png;base64,...


def get_service():
    with SessionLocal() as session:
        yield ClinicalService(SqlClinicalRepository(session), LocalImageStorage(folder="clinical"))


Svc = Annotated[ClinicalService, Depends(get_service)]
Read, Create, Update = (require_permission("clinical", p) for p in ("read", "create", "update"))
PRIVATE = {"Cache-Control": "no-store"}


@router.get("/recent")
def recent(uid: Read, branch: CurrentBranch, svc: Svc):
    return svc.recent(uid, branch)


@router.get("/patients/{customer_id}")
def record(customer_id: uuid.UUID, uid: Read, svc: Svc):
    return svc.record(uid, customer_id)


@router.put("/patients/{customer_id}/background")
def save_background(customer_id: uuid.UUID, body: Background, uid: Update, svc: Svc):
    return svc.save_background(uid, customer_id, body.model_dump(exclude_none=True))


@router.post("/notes", status_code=201)
def create_note(body: NoteIn, uid: Create, branch: CurrentBranch, svc: Svc):
    return svc.create_note(uid, branch, body.model_dump(mode="json", exclude_none=True) | {"customer_id": body.customer_id,
                                                                                          "appointment_id": body.appointment_id})


@router.get("/notes/{note_id}")
def get_note(note_id: uuid.UUID, uid: Read, svc: Svc):
    return svc.note(uid, note_id)


@router.patch("/notes/{note_id}")
def update_note(note_id: uuid.UUID, body: NoteBody, uid: Update, svc: Svc):
    return svc.update_note(uid, note_id, body.model_dump(exclude_none=True))


@router.post("/notes/{note_id}/sign")
def sign_note(note_id: uuid.UUID, uid: Update, svc: Svc):
    return svc.sign(uid, note_id)


@router.post("/notes/{note_id}/addenda", status_code=201)
def add_addendum(note_id: uuid.UUID, body: AddendumIn, uid: Update, svc: Svc):
    return svc.addendum(uid, note_id, body.text)


@router.post("/notes/{note_id}/prescriptions", status_code=201)
def prescribe(note_id: uuid.UUID, body: PrescriptionIn, uid: Create, svc: Svc):
    return svc.prescribe(uid, note_id, [m.model_dump() for m in body.items])


@router.get("/prescriptions/{prescription_id}")
def prescription(prescription_id: uuid.UUID, uid: Read, svc: Svc):
    return svc.prescription(uid, prescription_id)


@router.post("/patients/{customer_id}/files", status_code=201)
async def upload_file(customer_id: uuid.UUID, uid: Create, svc: Svc, file: Annotated[UploadFile, File()],
                      label: Annotated[str, Form(max_length=200)] = "", note_id: Annotated[uuid.UUID | None, Form()] = None):
    data = await file.read(MAX_FILE + 1)
    if not data:
        raise Invalid({"message": "the file is empty", "code": "bad_type"})
    return svc.add_file(uid, customer_id, label.strip() or (file.filename or "")[:200], data, note_id)


@router.get("/files/{file_id}")
def get_file(file_id: uuid.UUID, uid: Read, svc: Svc):
    path, content_type, _label = svc.file(uid, file_id)
    return FileResponse(path, media_type=content_type, headers=PRIVATE)


@router.post("/patients/{customer_id}/dental", status_code=201)
def add_dental(customer_id: uuid.UUID, body: DentalIn, uid: Update, svc: Svc):
    return svc.dental(uid, customer_id, [e.model_dump() for e in body.entries])


@router.post("/patients/{customer_id}/consents", status_code=201)
def add_consent(customer_id: uuid.UUID, body: ConsentIn, uid: Create, svc: Svc):
    signature = None
    if body.signature:
        head, _, b64 = body.signature.partition(",")
        try:
            signature = base64.b64decode(b64, validate=True) if head == "data:image/png;base64" else b""
        except binascii.Error:
            signature = b""
        if not signature:
            raise Invalid({"message": "the signature must be a PNG image", "field": "signature"})
    return svc.consent(uid, customer_id, body.model_dump(exclude={"signature"}), signature)


@router.get("/patients/{customer_id}/signatures/{file_name}")
def signature(customer_id: uuid.UUID, file_name: Annotated[str, Path(pattern=r"^signature-[0-9a-f-]{36}\.png$")], uid: Read, svc: Svc):
    return FileResponse(svc.signature(uid, customer_id, file_name), media_type="image/png", headers=PRIVATE)


@router.get("/patients/{customer_id}/access-log")
def access_log(customer_id: uuid.UUID, _: Read, svc: Svc):
    return svc.access_log(customer_id)
