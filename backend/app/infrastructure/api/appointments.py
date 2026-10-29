import uuid
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import Field, AwareDatetime, BaseModel, StringConstraints

from app.application.appointment_service import AppointmentService
from app.application.appointment_billing import AppointmentBilling
from app.application.quote_service import QuoteService
from app.infrastructure.api.quotes import get_service as quote_service
from app.infrastructure.api.sales import get_service as sale_service
from app.infrastructure.api.fields import optional_text
from app.infrastructure.api.permissions import CurrentBranch, require_permission
from app.infrastructure.persistence.appointment_repository import SqlAppointmentRepository
from app.infrastructure.persistence.custom_field_repository import SqlCustomFieldRepository
from app.infrastructure.persistence.database import SessionLocal

router = APIRouter(tags=["appointments"])

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class ServiceLine(BaseModel):
    product_id: uuid.UUID
    quantity: Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=3)] = Decimal(1)


class AppointmentIn(BaseModel):
    customer_id: uuid.UUID
    title: Title  # reason of the appointment
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    assigned_to: uuid.UUID | None = None  # who attends it
    notes: optional_text(5000) = None
    status: Literal["SCHEDULED", "CONFIRMED"] = "SCHEDULED"
    services: list[ServiceLine] = Field(default_factory=list, max_length=20)  # what will be charged
    extra: dict = Field(default_factory=dict)  # the business's data of each appointment (custom fields), checked by the service
    quote_id: uuid.UUID | None = None  # booked from a quote (same customer): converting it charges the appointment


# PATCH: a non-optional type with default None means the field can be omitted but not sent as null.
class AppointmentPatch(BaseModel):
    title: Title = None
    notes: optional_text(5000) = None
    assigned_to: uuid.UUID | None = None
    services: list[ServiceLine] = Field(default=None, max_length=20)  # replaces them (only while open)
    extra: dict = None  # replaces the values (fields deleted from Settings keep theirs)


class RescheduleIn(BaseModel):
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    reason: optional_text(500) = None


class CancelIn(BaseModel):
    reason: Reason


class NoteIn(BaseModel):
    note: Note


def get_service():
    with SessionLocal() as session:
        yield AppointmentService(SqlAppointmentRepository(session), SqlCustomFieldRepository(session))


Svc = Annotated[AppointmentService, Depends(get_service)]
# create = schedule; update = edit, reschedule, confirm, attend, no-show, notes; delete = cancel
Read, Create, Update, Cancel = (require_permission("appointments", p) for p in ("read", "create", "update", "delete"))
QuotesCreate = require_permission("quotes", "create")
SalesCreate = require_permission("sales", "create")
Quotes = Annotated[QuoteService, Depends(quote_service)]


def billing(svc: Svc, sales: Annotated[object, Depends(sale_service)], quotes: Quotes):
    return AppointmentBilling(svc, sales, quotes)


Billing = Annotated[AppointmentBilling, Depends(billing)]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


@router.get("/appointments")
def list_appointments(_: Read, branch: CurrentBranch, svc: Svc, from_: Annotated[AwareDatetime | None, Query(alias="from")] = None,
                      to: AwareDatetime | None = None,
                      status: Literal["SCHEDULED", "CONFIRMED", "COMPLETED", "CANCELLED", "NO_SHOW"] | None = None,
                      hide_cancelled: bool = False, customer_id: uuid.UUID | None = None, assigned_to: uuid.UUID | None = None):
    """The branch's calendar: appointments touching [from, to)."""
    filters = {"from": from_, "to": to, "status": status, "hide_cancelled": hide_cancelled, "customer_id": customer_id,
               "assigned_to": assigned_to}
    return svc.search(branch, filters)


@router.get("/appointments/staff")
def appointment_staff(_: Read, branch: CurrentBranch, svc: Svc):
    """Who can attend appointments in this branch."""
    return svc.staff(branch)


@router.post("/appointments", status_code=201)
def create_appointment(body: AppointmentIn, uid: Create, branch: CurrentBranch, bill: Billing):
    """With services, its sale is made too (all on credit; deposits later). sale_pending: why it couldn't be made now."""
    return bill.book(uid, branch, body.model_dump())


@router.get("/appointments/{appointment_id}")
def get_appointment(appointment_id: uuid.UUID, _: Read, branch: CurrentBranch, svc: Svc):
    return svc.get(branch, appointment_id)


@router.patch("/appointments/{appointment_id}")
def update_appointment(appointment_id: uuid.UUID, body: AppointmentPatch, uid: Update, branch: CurrentBranch, svc: Svc, bill: Billing):
    fields = body.model_dump(exclude_unset=True)
    if "services" in fields:  # its sale follows its services
        fields["services"] = [line.model_dump() for line in body.services]  # with each line's default quantity
        return bill.change_services(uid, branch, appointment_id, fields)
    return svc.update(uid, branch, appointment_id, fields)


@router.post("/appointments/{appointment_id}/reschedule")
def reschedule(appointment_id: uuid.UUID, body: RescheduleIn, uid: Update, branch: CurrentBranch, svc: Svc):
    return svc.reschedule(uid, branch, appointment_id, body.starts_at, body.ends_at, body.reason)


@router.post("/appointments/{appointment_id}/confirm")
def confirm(appointment_id: uuid.UUID, uid: Update, branch: CurrentBranch, svc: Svc):
    return svc.set_status(uid, branch, appointment_id, "CONFIRMED")


@router.post("/appointments/{appointment_id}/complete")
def complete(appointment_id: uuid.UUID, uid: Update, branch: CurrentBranch, svc: Svc):
    return svc.set_status(uid, branch, appointment_id, "COMPLETED")


@router.post("/appointments/{appointment_id}/no-show")
def no_show(appointment_id: uuid.UUID, uid: Update, branch: CurrentBranch, bill: Billing):
    return bill.close(uid, branch, appointment_id, "NO_SHOW")


@router.post("/appointments/{appointment_id}/cancel")
def cancel(appointment_id: uuid.UUID, body: CancelIn, uid: Cancel, branch: CurrentBranch, bill: Billing):
    """sale_followup: has_payments (deposits paid: refund them from the sale) or why its sale couldn't go back now."""
    return bill.close(uid, branch, appointment_id, "CANCELLED", body.reason)


@router.post("/appointments/{appointment_id}/sale", status_code=201)
def appointment_sale(appointment_id: uuid.UUID, uid: SalesCreate, _: Update, branch: CurrentBranch, bill: Billing):
    """Its sale (all on credit) when it couldn't be made at booking."""
    return bill.make_sale(uid, branch, appointment_id)


@router.post("/appointments/{appointment_id}/quote", status_code=201)
def quote_from_appointment(appointment_id: uuid.UUID, uid: Update, _: QuotesCreate, branch: CurrentBranch, svc: Svc, quotes: Quotes):
    """A quote with the appointment's services for its customer, valid until it starts, tied to it."""
    quote = quotes.create(uid, branch, svc.quote_request(branch, appointment_id))
    return svc.link_quote(uid, branch, appointment_id, quote["id"])


@router.post("/appointments/{appointment_id}/reminded")
def mark_reminded(appointment_id: uuid.UUID, uid: Update, branch: CurrentBranch, svc: Svc):
    """The WhatsApp reminder was sent."""
    return svc.mark_reminded(uid, branch, appointment_id)


@router.post("/appointments/{appointment_id}/notes", status_code=201)
def add_note(appointment_id: uuid.UUID, body: NoteIn, uid: Update, branch: CurrentBranch, svc: Svc):
    return svc.add_note(uid, branch, appointment_id, body.note)


@router.get("/customers/{customer_id}/appointments")
def customer_appointments(customer_id: uuid.UUID, uid: Read, svc: Svc, page: Page = 1, page_size: PageSize = 25):
    """Follow-up of a customer: their appointments in the branches you belong to."""
    return svc.customer_appointments(uid, customer_id, page, page_size)
