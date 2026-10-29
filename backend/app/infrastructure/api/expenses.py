import uuid
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, Query
from pydantic import AwareDatetime, BaseModel, Field, StringConstraints

from app.application.expense_service import ExpenseService
from app.infrastructure.api.fields import optional_text
from app.infrastructure.api.permissions import CurrentBranch, require_permission
from app.infrastructure.persistence.database import SessionLocal
from app.infrastructure.persistence.expense_repository import SqlExpenseRepository

# Own module "expenses" (read, create, update, delete), seeded in all_in_one_schema.sql and granted to admin.
router = APIRouter(prefix="/expenses", tags=["expenses"])

Money = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]


class ExpenseIn(BaseModel):
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    amount: Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]
    spent_at: AwareDatetime | None = None  # omitted: now
    supplier_id: uuid.UUID | None = None
    reference: optional_text(100) = None
    notes: optional_text(2000) = None
    cash_amount: Money = Decimal(0)   # taken now from the register the person occupies
    other_amount: Money = Decimal(0)  # paid another way; the rest is owed


# PATCH: the amount can't change (void and record it again); a non-optional type with default None can be omitted, not nulled
class ExpensePatch(BaseModel):
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] = None
    spent_at: AwareDatetime = None
    supplier_id: uuid.UUID | None = None
    reference: optional_text(100) = None
    notes: optional_text(2000) = None


class PaymentIn(BaseModel):
    cash_amount: Money = Decimal(0)
    other_amount: Money = Decimal(0)
    notes: optional_text(200) = None


def get_service():
    with SessionLocal() as session:
        yield ExpenseService(SqlExpenseRepository(session))


Svc = Annotated[ExpenseService, Depends(get_service)]
Read, Create, Update, Delete = (require_permission("expenses", p) for p in ("read", "create", "update", "delete"))
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]
From = Annotated[AwareDatetime | None, Query(alias="from")]


@router.get("")
def list_expenses(_: Read, branch: CurrentBranch, svc: Svc, from_: From = None, to: AwareDatetime | None = None,
                  q: Annotated[str, Query(max_length=100)] = "", status: Literal["all", "owed", "paid"] = "all",
                  include_voided: bool = False, page: Page = 1, page_size: PageSize = 25):
    filters = {"from": from_, "to": to, "q": q.strip(), "status": status, "include_voided": include_voided}
    return svc.search(branch, filters, page, page_size)


# Before /{expense_id}
@router.get("/summary")
def expenses_summary(_: Read, branch: CurrentBranch, svc: Svc, from_: From = None, to: AwareDatetime | None = None):
    return svc.summary(branch, from_, to)


@router.post("", status_code=201)
def create_expense(body: ExpenseIn, uid: Create, branch: CurrentBranch, svc: Svc):
    return svc.create(uid, branch, body.model_dump())


@router.get("/{expense_id}")
def get_expense(expense_id: uuid.UUID, _: Read, branch: CurrentBranch, svc: Svc):
    return svc.get(branch, expense_id)


@router.patch("/{expense_id}")
def update_expense(expense_id: uuid.UUID, body: ExpensePatch, uid: Update, branch: CurrentBranch, svc: Svc):
    return svc.update(uid, branch, expense_id, body.model_dump(exclude_unset=True))


@router.post("/{expense_id}/payments")
def pay_expense(expense_id: uuid.UUID, body: PaymentIn, uid: Update, branch: CurrentBranch, svc: Svc):
    """Pay (part of) what is still owed."""
    return svc.pay(uid, branch, expense_id, body.cash_amount, body.other_amount, body.notes)


@router.delete("/{expense_id}")
def void_expense(expense_id: uuid.UUID, uid: Delete, branch: CurrentBranch, svc: Svc,
                 reason: Annotated[str | None, Body(embed=True, max_length=500)] = None):
    return svc.void(uid, branch, expense_id, reason.strip() if reason else None)
