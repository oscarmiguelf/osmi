import uuid
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime, BaseModel, Field, StringConstraints

from app.application.promotion_service import PromotionService
from app.infrastructure.api.fields import optional_text
from app.infrastructure.api.permissions import require_permission
from app.infrastructure.persistence.database import SessionLocal
from app.infrastructure.persistence.promotion_repository import SqlPromotionRepository

router = APIRouter(tags=["promotions"])

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
Kind = Literal["PERCENT", "AMOUNT", "BUY_X_GET_Y"]
Percent = Annotated[Decimal, Field(gt=0, le=100, max_digits=5, decimal_places=2)]
Amount = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]
Units = Annotated[int, Field(ge=1, le=1000)]
Ids = Annotated[list[uuid.UUID], Field(max_length=500)]


class PromotionIn(BaseModel):
    name: Name
    description: optional_text(500) = None
    kind: Kind
    percent: Percent | None = None  # PERCENT: % off the line
    amount: Amount | None = None  # AMOUNT: money off per unit
    buy_quantity: Units | None = None  # BUY_X_GET_Y: units paid...
    get_quantity: Units | None = None  # ...and units free (2x1 = buy 1 get 1)
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    is_enabled: bool = True
    product_ids: Ids
    branch_ids: Ids = []  # empty: every branch


# PATCH: a non-optional type with default None means the field can be omitted but not sent as null.
class PromotionPatch(BaseModel):
    name: Name = None
    description: optional_text(500) = None
    kind: Kind = None
    percent: Percent | None = None
    amount: Amount | None = None
    buy_quantity: Units | None = None
    get_quantity: Units | None = None
    starts_at: AwareDatetime = None
    ends_at: AwareDatetime = None
    is_enabled: bool = None
    product_ids: Ids = None  # replaces the products
    branch_ids: Ids = None  # replaces the branches ([] = every branch)


def get_service():
    with SessionLocal() as session:
        yield PromotionService(SqlPromotionRepository(session))


Svc = Annotated[PromotionService, Depends(get_service)]
Read, Create, Update, Delete = (require_permission("promotions", p) for p in ("read", "create", "update", "delete"))
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


@router.get("/promotions")
def list_promotions(_: Read, svc: Svc, status: Literal["ACTIVE", "SCHEDULED", "ENDED", "DISABLED"] | None = None,
                    q: Annotated[str, Query(max_length=100)] = "", product_id: uuid.UUID | None = None,
                    include_deleted: bool = False, page: Page = 1, page_size: PageSize = 25):
    filters = {"status": status, "q": q.strip(), "product_id": product_id, "include_deleted": include_deleted}
    return svc.search(filters, page, page_size)


@router.post("/promotions", status_code=201)
def create_promotion(body: PromotionIn, uid: Create, svc: Svc):
    return svc.create(uid, body.model_dump())


@router.get("/promotions/{promotion_id}")
def get_promotion(promotion_id: uuid.UUID, _: Read, svc: Svc):
    return svc.get(promotion_id)


@router.patch("/promotions/{promotion_id}")
def update_promotion(promotion_id: uuid.UUID, body: PromotionPatch, uid: Update, svc: Svc):
    return svc.update(uid, promotion_id, body.model_dump(exclude_unset=True))


@router.delete("/promotions/{promotion_id}", status_code=204)
def delete_promotion(promotion_id: uuid.UUID, uid: Delete, svc: Svc):
    svc.delete(uid, promotion_id)


@router.post("/promotions/{promotion_id}/restore")
def restore_promotion(promotion_id: uuid.UUID, uid: Delete, svc: Svc):
    return svc.restore(uid, promotion_id)


@router.get("/promotions/{promotion_id}/history")
def promotion_history(promotion_id: uuid.UUID, _: Read, svc: Svc, page: Page = 1, page_size: PageSize = 25):
    return svc.history(promotion_id, page, page_size)
