import uuid
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import AwareDatetime, BaseModel, Field, StringConstraints

from app.application.cash_service import CashService
from app.infrastructure.api.fields import optional_text
from app.infrastructure.api.permissions import CurrentBranch, require_permission
from app.infrastructure.persistence.cash_repository import SqlCashRepository
from app.infrastructure.persistence.database import SessionLocal

router = APIRouter(tags=["cash"])

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Money = Annotated[Decimal, Field(max_digits=12, decimal_places=2)]
Notes = optional_text(500)


class RegisterIn(BaseModel):
    name: Name


class PaymentMethodPatch(BaseModel):
    # is_credit is deliberately not editable
    description: Name = None
    is_enabled: bool = None


class MovementIn(BaseModel):
    movement_type: Literal["Cash In", "Cash Out"]
    payment_method_id: uuid.UUID
    amount: Money
    notes: Notes = None


class CountIn(BaseModel):
    payment_method_id: uuid.UUID
    counted: Annotated[Money, Field(ge=0)]


class CutIn(BaseModel):
    counts: list[CountIn]
    notes: Notes = None
    withdrawal: Annotated[Money, Field(ge=0)] = Decimal(0)  # cash taken out at the cut (0 or more, up to the cash counted)
    withdrawal_reason: optional_text(200) = None  # why ("Retiro de corte" when empty)


def get_service():
    with SessionLocal() as session:
        yield CashService(SqlCashRepository(session))


Svc = Annotated[CashService, Depends(get_service)]
Read, Create, Update, Delete = (require_permission("cash", p) for p in ("read", "create", "update", "delete"))
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


# --- payment methods ---

@router.get("/payment-methods")
def list_payment_methods(_: Read, svc: Svc, include_disabled: bool = False):
    return svc.payment_methods(include_disabled)


@router.patch("/payment-methods/{method_id}")
def update_payment_method(method_id: uuid.UUID, body: PaymentMethodPatch, uid: Update, svc: Svc):
    return svc.update_payment_method(uid, method_id, body.model_dump(exclude_unset=True))


# --- registers (all scoped to the working branch from X-Branch-Id) ---

@router.get("/cash-registers")
def list_registers(_: Read, branch: CurrentBranch, svc: Svc):
    return svc.list_registers(branch)


@router.post("/cash-registers", status_code=201)
def create_register(body: RegisterIn, uid: Update, branch: CurrentBranch, svc: Svc):
    return svc.create_register(uid, branch, body.name)


@router.get("/cash-registers/{register_id}")
def get_register(register_id: uuid.UUID, _: Read, branch: CurrentBranch, svc: Svc):
    return svc.get_register(branch, register_id, include_deleted=True)


@router.patch("/cash-registers/{register_id}")
def rename_register(register_id: uuid.UUID, body: RegisterIn, uid: Update, branch: CurrentBranch, svc: Svc):
    return svc.rename_register(uid, branch, register_id, body.name)


@router.delete("/cash-registers/{register_id}", status_code=204)
def delete_register(register_id: uuid.UUID, uid: Delete, branch: CurrentBranch, svc: Svc):
    svc.delete_register(uid, branch, register_id)


@router.post("/cash-registers/{register_id}/restore")
def restore_register(register_id: uuid.UUID, uid: Delete, branch: CurrentBranch, svc: Svc):
    return svc.restore_register(uid, branch, register_id)


@router.get("/cash-registers/{register_id}/history")
def register_history(register_id: uuid.UUID, _: Read, branch: CurrentBranch, svc: Svc,
                     page: Page = 1, page_size: PageSize = 25):
    return svc.register_history(branch, register_id, page, page_size)


# --- occupancy ---

@router.get("/cash-sessions/current")
def current_session(uid: Read, svc: Svc):
    return svc.current_session(uid) or Response(status_code=204)


@router.post("/cash-registers/{register_id}/occupy")
def occupy_register(register_id: uuid.UUID, uid: Create, branch: CurrentBranch, svc: Svc):
    return svc.occupy(uid, branch, register_id)


@router.post("/cash-registers/{register_id}/release")
def release_register(register_id: uuid.UUID, uid: Create, branch: CurrentBranch, svc: Svc, force: bool = False):
    return svc.release(uid, branch, register_id, force)


# --- money ---

@router.get("/cash-registers/{register_id}/balances")
def register_balances(register_id: uuid.UUID, _: Read, branch: CurrentBranch, svc: Svc):
    return svc.balances(branch, register_id)


@router.get("/cash-registers/{register_id}/movements")
def register_movements(register_id: uuid.UUID, _: Read, branch: CurrentBranch, svc: Svc,
                       from_: Annotated[AwareDatetime | None, Query(alias="from")] = None,
                       to: AwareDatetime | None = None,
                       type: Literal["Cash In", "Cash Out", "Sale", "Return", "Adjustment"] | None = None,
                       payment_method_id: uuid.UUID | None = None,
                       page: Page = 1, page_size: PageSize = 25):
    filters = {"from": from_, "to": to, "type": type, "pm": payment_method_id}
    return svc.movements(branch, register_id, filters, page, page_size)


@router.post("/cash-registers/{register_id}/movements", status_code=201)
def add_movement(register_id: uuid.UUID, body: MovementIn, uid: Create, branch: CurrentBranch, svc: Svc):
    return svc.add_movement(uid, branch, register_id, body.movement_type, body.payment_method_id, body.amount, body.notes)


@router.get("/cash-registers/{register_id}/sales-totals")
def sales_totals(register_id: uuid.UUID, _: Read, branch: CurrentBranch, svc: Svc,
                 from_: Annotated[AwareDatetime, Query(alias="from")], to: AwareDatetime):
    return svc.sales_totals(branch, register_id, from_, to)


# --- cuts ---

@router.get("/cash-registers/{register_id}/cuts")
def register_cuts(register_id: uuid.UUID, _: Read, branch: CurrentBranch, svc: Svc,
                  page: Page = 1, page_size: PageSize = 25):
    return svc.cuts(branch, register_id, page, page_size)


@router.post("/cash-registers/{register_id}/cuts", status_code=201)
def create_cut(register_id: uuid.UUID, body: CutIn, uid: Create, branch: CurrentBranch, svc: Svc):
    counts = [(c.payment_method_id, c.counted) for c in body.counts]
    return svc.create_cut(uid, branch, register_id, counts, body.notes, body.withdrawal, body.withdrawal_reason)


@router.get("/cash-cuts/{cut_id}")
def get_cut(cut_id: uuid.UUID, _: Read, branch: CurrentBranch, svc: Svc):
    return svc.get_cut(branch, cut_id)
