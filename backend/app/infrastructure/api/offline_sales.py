import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime, BaseModel, Field

from app.application.offline_sale_service import OfflineSaleService
from app.infrastructure.api.fields import optional_text
from app.infrastructure.api.permissions import CurrentBranch, require_permission
from app.infrastructure.persistence.database import SessionLocal
from app.infrastructure.persistence.offline_repository import SqlOfflineRepository
from app.infrastructure.persistence.sale_repository import SqlSaleRepository

# The point of sale without internet (installable app): what it stores, the sales it sends back, what to review.
router = APIRouter(tags=["offline sales"])

Money = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]
Amount = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]
Quantity = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=3)]


class OfflineItemIn(BaseModel):
    product_id: uuid.UUID
    quantity: Quantity
    unit_price: Money  # what was charged (the device's stored price)


class OfflinePaymentIn(BaseModel):
    payment_method_id: uuid.UUID
    amount: Amount
    amount_tendered: Money | None = None


class OfflineSaleIn(BaseModel):
    id: uuid.UUID  # made on the device: sending it twice records it once
    offline_folio: Annotated[str, Field(pattern=r"^OFF-[A-Z0-9]{4}-[0-9]{1,8}$")]
    sold_at: AwareDatetime
    cash_register_id: uuid.UUID
    customer_id: uuid.UUID | None = None
    items: Annotated[list[OfflineItemIn], Field(min_length=1, max_length=500)]
    payments: Annotated[list[OfflinePaymentIn], Field(min_length=1, max_length=5)]


class ResolveIn(BaseModel):
    note: optional_text(500) = None


def get_service():
    with SessionLocal() as session:
        yield OfflineSaleService(SqlSaleRepository(session), SqlOfflineRepository(session))


Svc = Annotated[OfflineSaleService, Depends(get_service)]
Read, Create, Update = (require_permission("sales", p) for p in ("read", "create", "update"))


@router.get("/sales/offline/snapshot")
def offline_snapshot(uid: Create, branch: CurrentBranch, svc: Svc):
    return svc.snapshot(uid, branch)


@router.post("/sales/offline", status_code=201)
def offline_sale(body: OfflineSaleIn, uid: Create, branch: CurrentBranch, svc: Svc):
    return svc.create(uid, branch, body.model_dump())


@router.get("/sales/offline/issues")
def offline_issues(_: Read, branch: CurrentBranch, svc: Svc, resolved: Annotated[bool, Query()] = False):
    return svc.issues(branch, resolved)


@router.post("/sales/offline/issues/{issue_id}/resolve", status_code=204)
def resolve_issue(issue_id: uuid.UUID, body: ResolveIn, uid: Update, branch: CurrentBranch, svc: Svc):
    svc.resolve(uid, branch, issue_id, body.note)
