import uuid
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from pydantic import AfterValidator, AwareDatetime, BaseModel, Field

from app.application.purchase_service import PurchaseService
from app.infrastructure.api.fields import optional_text
from app.infrastructure.api.permissions import CurrentBranch, require_permission
from app.infrastructure.persistence.database import SessionLocal
from app.infrastructure.persistence.purchase_repository import SqlPurchaseRepository

router = APIRouter(tags=["purchases"])


Money = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]


class ItemIn(BaseModel):
    product_id: uuid.UUID
    quantity: Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=3)]
    unit_cost: Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]


class PurchaseIn(BaseModel):
    supplier_id: uuid.UUID | None = None
    purchased_at: AwareDatetime | None = None  # omitted: now
    reference: optional_text(100) = None  # supplier invoice / order number
    notes: optional_text(2000) = None
    items: list[ItemIn]
    cash_amount: Money = Decimal(0)   # taken now from the register the person occupies
    other_amount: Money = Decimal(0)  # paid another way (own money, transfer...); the rest is owed to the supplier


class PaymentIn(BaseModel):
    cash_amount: Money = Decimal(0)
    other_amount: Money = Decimal(0)
    notes: optional_text(200) = None


# PATCH: a non-optional type with default None means the field can be omitted but not sent as null.
class PurchasePatch(BaseModel):
    supplier_id: uuid.UUID | None = None
    purchased_at: AwareDatetime = None
    reference: optional_text(100) = None
    notes: optional_text(2000) = None


def _zone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ValueError, KeyError, OSError):
        raise ValueError("unknown time zone") from None
    return value


Zone = Annotated[str, AfterValidator(_zone)]


def get_service():
    with SessionLocal() as session:
        yield PurchaseService(SqlPurchaseRepository(session))


Svc = Annotated[PurchaseService, Depends(get_service)]
Read, Create, Update, Delete = (require_permission("purchases", p) for p in ("read", "create", "update", "delete"))
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


@router.get("/purchases")
def list_purchases(_: Read, branch: CurrentBranch, svc: Svc,
                   from_: Annotated[AwareDatetime | None, Query(alias="from")] = None, to: AwareDatetime | None = None,
                   supplier_id: uuid.UUID | None = None, q: Annotated[str, Query(max_length=100)] = "",
                   include_voided: bool = False, status: Literal["all", "owed", "paid"] = "all", page: Page = 1, page_size: PageSize = 25):
    filters = {"from": from_, "to": to, "supplier_id": supplier_id, "q": q.strip(), "include_voided": include_voided, "status": status}
    return svc.search(branch, filters, page, page_size)


# Before /purchases/{purchase_id}, which would otherwise take "summary" as an id
@router.get("/purchases/summary")
def purchases_summary(_: Read, branch: CurrentBranch, svc: Svc, from_: Annotated[AwareDatetime, Query(alias="from")],
                      to: AwareDatetime, tz: Zone = "UTC"):
    """Spending by supplier and by day (days in `tz`, the person's time zone)."""
    return svc.summary(branch, from_, to, tz)


@router.post("/purchases", status_code=201)
def create_purchase(body: PurchaseIn, uid: Create, branch: CurrentBranch, svc: Svc):
    return svc.create(uid, branch, body.model_dump(exclude={"items"}), [i.model_dump() for i in body.items])


@router.get("/purchases/{purchase_id}")
def get_purchase(purchase_id: uuid.UUID, _: Read, branch: CurrentBranch, svc: Svc):
    return svc.get(branch, purchase_id)


@router.patch("/purchases/{purchase_id}")
def update_purchase(purchase_id: uuid.UUID, body: PurchasePatch, uid: Update, branch: CurrentBranch, svc: Svc):
    return svc.update(uid, branch, purchase_id, body.model_dump(exclude_unset=True))


@router.delete("/purchases/{purchase_id}")
def void_purchase(purchase_id: uuid.UUID, uid: Delete, branch: CurrentBranch, svc: Svc):
    return svc.void(uid, branch, purchase_id)


@router.post("/purchases/{purchase_id}/payments")
def pay_purchase(purchase_id: uuid.UUID, body: PaymentIn, uid: Update, branch: CurrentBranch, svc: Svc):
    """Pay (part of) what is still owed to the supplier."""
    return svc.pay(uid, branch, purchase_id, body.cash_amount, body.other_amount, body.notes)


@router.get("/purchases/{purchase_id}/history")
def purchase_history(purchase_id: uuid.UUID, _: Read, branch: CurrentBranch, svc: Svc,
                     page: Page = 1, page_size: PageSize = 25):
    return svc.history(branch, purchase_id, page, page_size)


@router.get("/products/{product_id}/purchase-price")
def last_purchase_price(product_id: uuid.UUID, _: Read, svc: Svc):
    """Last unit cost paid in any branch, or null if it was never bought."""
    return svc.last_price(product_id)


@router.get("/products/{product_id}/purchases")
def product_purchases(product_id: uuid.UUID, _: Read, branch: CurrentBranch, svc: Svc, page: Page = 1, page_size: PageSize = 25):
    return svc.product_lines(branch, product_id, page, page_size)
