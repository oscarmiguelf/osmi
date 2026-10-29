import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, BeforeValidator, StringConstraints

from app.application.settings_service import SettingsService
from app.application.errors import Invalid
from app.infrastructure.images import logo_png
from app.infrastructure.persistence.image_storage import LocalImageStorage
from app.infrastructure.api.permissions import require_permission
from app.infrastructure.persistence.custom_field_repository import SqlCustomFieldRepository
from app.infrastructure.persistence.database import SessionLocal
from app.infrastructure.persistence.settings_repository import SqlSettingsRepository

# Own module "settings" (read, update), seeded in all_in_one_schema.sql and granted to admin.
router = APIRouter(prefix="/settings", tags=["settings"])


def _whatsapp(value):
    """Digits with country code: '+52 1 55 1234 5678' -> '5215512345678'. Empty = ordering off."""
    digits = re.sub(r"[\s\-().+]", "", value or "")
    if digits and not re.fullmatch(r"[0-9]{10,15}", digits):
        raise ValueError("enter the number with country code, 10 to 15 digits (e.g. 5215512345678)")
    return digits


class SettingsPatch(BaseModel):
    whatsapp_number: Annotated[str, BeforeValidator(_whatsapp)] = None
    business_type: Literal["retail", "beauty", "health", "music"] = None  # which modules show and how things are called
    reminder_template: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] = None  # WhatsApp reminder text
    doctor_header: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] = None  # prescriptions: name, license (cédula), school
    privacy_notice: Annotated[str, StringConstraints(strip_whitespace=True, max_length=20000)] = None  # what patients sign (LFPDPPP)


def get_service():
    with SessionLocal() as session:
        yield SettingsService(SqlSettingsRepository(session), SqlCustomFieldRepository(session), LocalImageStorage(folder="branding"), logo_png)


Svc = Annotated[SettingsService, Depends(get_service)]
Read, Update = (require_permission("settings", p) for p in ("read", "update"))


@router.get("")
def get_settings(_: Read, svc: Svc):
    return svc.get()


@router.patch("")
def update_settings(body: SettingsPatch, uid: Update, svc: Svc):
    return svc.update(uid, body.model_dump(exclude_unset=True))


MAX_LOGO = 5 * 1024 * 1024


@router.put("/logo")
async def upload_logo(uid: Update, svc: Svc, file: Annotated[UploadFile, File()]):
    data = await file.read(MAX_LOGO + 1)
    if not data or len(data) > MAX_LOGO:
        raise Invalid({"message": "the logo must be an image up to 5 MB", "code": "bad_type"})
    return svc.set_logo(uid, data)


@router.delete("/logo", status_code=204)
def delete_logo(uid: Update, svc: Svc):
    svc.clear_logo(uid)


# Public: the business's own logo, shown on tickets, prescriptions and the customer catalog
@router.get("/logo")
def logo(svc: Svc):
    return FileResponse(svc.logo(), media_type="image/png", headers={"Cache-Control": "public, max-age=300"})
