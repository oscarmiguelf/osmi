import uuid
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime, BaseModel, Field, StringConstraints

from app.application.inventory_service import InventoryService
from app.infrastructure.api.fields import optional_text
from app.infrastructure.api.permissions import CurrentBranch, require_permission
from app.infrastructure.persistence.database import SessionLocal
from app.infrastructure.persistence.inventory_repository import SqlInventoryRepository

router = APIRouter(tags=["inventory"])

MovementType = Literal["Sale", "Purchase", "Adjustment", "Return", "Transfer Out", "Transfer In"]


class AdjustmentIn(BaseModel):
    product_id: uuid.UUID
    quantity: Annotated[Decimal, Field(max_digits=14, decimal_places=3)]  # signed: + adds stock, - takes it out
    notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
    reference: optional_text(100) = None


def get_service():
    with SessionLocal() as session:
        yield InventoryService(SqlInventoryRepository(session))


Svc = Annotated[InventoryService, Depends(get_service)]
Read, Create = require_permission("inventory", "read"), require_permission("inventory", "create")
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]
From = Annotated[AwareDatetime | None, Query(alias="from")]


@router.get("/stock")
def branch_stock(_: Read, branch: CurrentBranch, svc: Svc, q: Annotated[str, Query(max_length=100)] = "",
                 low_stock: bool = False, category_id: uuid.UUID | None = None, page: Page = 1, page_size: PageSize = 25):
    return svc.stock(branch, {"q": q.strip(), "low_stock": low_stock, "category_id": category_id}, page, page_size)


@router.get("/products/{product_id}/stock")
def product_stock(product_id: uuid.UUID, uid: Read, svc: Svc):
    return svc.stock_in_my_branches(uid, product_id)


@router.get("/products/{product_id}/kardex")
def product_kardex(product_id: uuid.UUID, _: Read, branch: CurrentBranch, svc: Svc, from_: From = None,
                   to: AwareDatetime | None = None, type: MovementType | None = None, page: Page = 1, page_size: PageSize = 25):
    return svc.kardex(branch, product_id, {"from": from_, "to": to, "type": type}, page, page_size)


@router.get("/inventory/movements")
def inventory_movements(_: Read, branch: CurrentBranch, svc: Svc, from_: From = None, to: AwareDatetime | None = None,
                        type: MovementType | None = None, user_id: uuid.UUID | None = None,
                        page: Page = 1, page_size: PageSize = 25):
    return svc.movements(branch, {"from": from_, "to": to, "type": type, "user_id": user_id}, page, page_size)


@router.post("/inventory/adjustments", status_code=201)
def inventory_adjustment(body: AdjustmentIn, uid: Create, branch: CurrentBranch, svc: Svc):
    return svc.adjust(uid, branch, body.product_id, body.quantity, body.notes, body.reference)


@router.get("/inventory/low-stock")
def low_stock(_: Read, branch: CurrentBranch, svc: Svc):
    return svc.low_stock(branch)
