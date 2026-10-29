import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.application.custom_field_service import CustomFieldService
from app.infrastructure.api.permissions import require_permission
from app.infrastructure.persistence.custom_field_repository import SqlCustomFieldRepository
from app.infrastructure.persistence.database import SessionLocal

# Read with customers.read / appointments.read (their forms need them); change with settings.update.
router = APIRouter(prefix="/custom-fields", tags=["custom fields"])

Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Option = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
FieldType = Literal["text", "long_text", "number", "date", "select", "boolean"]


class FieldIn(BaseModel):
    entity: Literal["customer", "appointment"] = "customer"  # customers' data or each appointment's (an event's venue, guests...)
    label: Label
    field_type: FieldType
    options: list[Option] = Field(default_factory=list, max_length=50)
    required: bool = False


class FieldPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")  # e.g. field_type: stored values were checked against it, it can't change
    label: Label = None
    options: list[Option] = Field(default=None, max_length=50)
    required: bool = None
    sort_order: Annotated[int, Field(ge=0, le=999)] = None


def get_service():
    with SessionLocal() as session:
        yield CustomFieldService(SqlCustomFieldRepository(session))


Svc = Annotated[CustomFieldService, Depends(get_service)]
Read = require_permission("customers", "read")
AppointmentsRead = require_permission("appointments", "read")
Manage = require_permission("settings", "update")


@router.get("")
def list_fields(_: Read, svc: Svc):
    return svc.list()


@router.get("/appointment")
def list_appointment_fields(_: AppointmentsRead, svc: Svc):
    return svc.list("appointment")


@router.post("", status_code=201)
def create_field(body: FieldIn, uid: Manage, svc: Svc):
    return svc.create(uid, body.model_dump())


@router.patch("/{field_id}")
def update_field(field_id: uuid.UUID, body: FieldPatch, uid: Manage, svc: Svc):
    return svc.update(uid, field_id, body.model_dump(exclude_unset=True))


@router.delete("/{field_id}", status_code=204)
def delete_field(field_id: uuid.UUID, uid: Manage, svc: Svc):
    svc.delete(uid, field_id)
