import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime, BaseModel, Field, StringConstraints, model_validator

from app.application.calendar_service import CalendarService
from app.infrastructure.api.auth import current_user_id
from app.infrastructure.persistence.calendar_repository import SqlCalendarRepository
from app.infrastructure.persistence.database import SessionLocal

router = APIRouter(tags=["calendar"])

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Description = Annotated[str, StringConstraints(max_length=500)]
Color = Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Location = Annotated[str, StringConstraints(max_length=255)]
AccessLevel = Literal["view", "edit"]


class CalendarIn(BaseModel):
    name: Name
    description: Description | None = None
    color: Color | None = None


# PATCH models: a non-optional type with default None means the field can be omitted but not sent as null.
class CalendarPatch(BaseModel):
    name: Name = None
    description: Description | None = None
    color: Color | None = None


class MemberIn(BaseModel):
    user_id: uuid.UUID
    access_level: AccessLevel


class MemberPatch(BaseModel):
    access_level: AccessLevel


class EventIn(BaseModel):
    title: Title
    description: str | None = None
    location: Location | None = None
    start_at: AwareDatetime
    end_at: AwareDatetime
    customer_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def check_range(self):
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        return self


class EventPatch(BaseModel):
    title: Title = None
    description: str | None = None
    location: Location | None = None
    start_at: AwareDatetime = None
    end_at: AwareDatetime = None
    customer_id: uuid.UUID | None = None  # null unlinks the customer


class TimezoneIn(BaseModel):
    timezone: str = Field(min_length=1, max_length=64)


def get_service():
    with SessionLocal() as session:
        yield CalendarService(SqlCalendarRepository(session))


Uid = Annotated[uuid.UUID, Depends(current_user_id)]
Svc = Annotated[CalendarService, Depends(get_service)]


@router.patch("/me/timezone")
def set_timezone(body: TimezoneIn, uid: Uid, svc: Svc):
    svc.set_timezone(uid, body.timezone)
    return {"timezone": body.timezone}


@router.get("/users/search")
def search_users(uid: Uid, svc: Svc, q: Annotated[str, Query(min_length=2, max_length=100)]):
    # Lets any logged-in user find who exists (by email or name), needed to share calendars.
    return svc.search_users(uid, q)


@router.get("/calendars")
def list_calendars(uid: Uid, svc: Svc):
    return svc.list_calendars(uid)


@router.post("/calendars", status_code=201)
def create_calendar(body: CalendarIn, uid: Uid, svc: Svc):
    return svc.create_calendar(uid, body.model_dump())


@router.patch("/calendars/{calendar_id}")
def update_calendar(calendar_id: uuid.UUID, body: CalendarPatch, uid: Uid, svc: Svc):
    return svc.update_calendar(uid, calendar_id, body.model_dump(exclude_unset=True))


@router.delete("/calendars/{calendar_id}", status_code=204)
def delete_calendar(calendar_id: uuid.UUID, uid: Uid, svc: Svc):
    svc.delete_calendar(uid, calendar_id)


@router.get("/calendars/{calendar_id}/members")
def list_members(calendar_id: uuid.UUID, uid: Uid, svc: Svc):
    return svc.list_members(uid, calendar_id)


@router.post("/calendars/{calendar_id}/members", status_code=201)
def add_member(calendar_id: uuid.UUID, body: MemberIn, uid: Uid, svc: Svc):
    return svc.add_member(uid, calendar_id, body.user_id, body.access_level)


@router.patch("/calendars/{calendar_id}/members/{user_id}")
def update_member(calendar_id: uuid.UUID, user_id: uuid.UUID, body: MemberPatch, uid: Uid, svc: Svc):
    return svc.update_member(uid, calendar_id, user_id, body.access_level)


@router.delete("/calendars/{calendar_id}/members/{user_id}", status_code=204)
def revoke_member(calendar_id: uuid.UUID, user_id: uuid.UUID, uid: Uid, svc: Svc):
    svc.revoke_member(uid, calendar_id, user_id)


@router.get("/calendars/{calendar_id}/audit")
def calendar_audit(calendar_id: uuid.UUID, uid: Uid, svc: Svc,
                   limit: Annotated[int, Query(ge=1, le=200)] = 50, offset: Annotated[int, Query(ge=0)] = 0):
    return svc.audit(uid, calendar_id, limit, offset)


@router.post("/calendars/{calendar_id}/events", status_code=201)
def create_event(calendar_id: uuid.UUID, body: EventIn, uid: Uid, svc: Svc):
    return svc.create_event(uid, calendar_id, body.model_dump())


@router.get("/events")
def list_events(uid: Uid, svc: Svc,
                from_: Annotated[AwareDatetime, Query(alias="from")],
                to: AwareDatetime,
                calendar_ids: Annotated[list[uuid.UUID] | None, Query()] = None):
    return svc.list_events(uid, from_, to, calendar_ids)


@router.get("/events/{event_id}")
def get_event(event_id: uuid.UUID, uid: Uid, svc: Svc):
    return svc.get_event(uid, event_id)


@router.patch("/events/{event_id}")
def update_event(event_id: uuid.UUID, body: EventPatch, uid: Uid, svc: Svc):
    return svc.update_event(uid, event_id, body.model_dump(exclude_unset=True))


@router.delete("/events/{event_id}", status_code=204)
def delete_event(event_id: uuid.UUID, uid: Uid, svc: Svc):
    svc.delete_event(uid, event_id)
