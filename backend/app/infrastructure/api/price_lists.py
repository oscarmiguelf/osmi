import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, StringConstraints

from app.application.price_list_service import PriceListService
from app.infrastructure.api.permissions import require_permission
from app.infrastructure.persistence.database import SessionLocal
from app.infrastructure.persistence.price_list_repository import SqlPriceListRepository

# Read with products.read (forms list them); change with products.prices (they decide what is charged).
router = APIRouter(prefix="/price-lists", tags=["price lists"])

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Percent = Annotated[Decimal, Field(ge=-90, le=200, max_digits=6, decimal_places=2)]


class ListIn(BaseModel):
    name: Name
    percent: Percent = Decimal(0)  # products without their own price: general price adjusted by it (-10 = 10% less)


class ListPatch(BaseModel):
    name: Name = None
    percent: Percent = None


class ItemIn(BaseModel):
    product_id: uuid.UUID
    min_quantity: Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=3)] = Decimal(1)
    price: Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]


class ItemsIn(BaseModel):
    items: list[ItemIn] = Field(max_length=2000)


def get_service():
    with SessionLocal() as session:
        yield PriceListService(SqlPriceListRepository(session))


Svc = Annotated[PriceListService, Depends(get_service)]
Read = require_permission("products", "read")
Manage = require_permission("products", "prices")


@router.get("")
def list_price_lists(_: Read, svc: Svc):
    return svc.all()


@router.post("", status_code=201)
def create_price_list(body: ListIn, uid: Manage, svc: Svc):
    return svc.create(uid, body.model_dump())


@router.get("/{list_id}")
def get_price_list(list_id: uuid.UUID, _: Read, svc: Svc):
    return svc.get(list_id)


@router.patch("/{list_id}")
def update_price_list(list_id: uuid.UUID, body: ListPatch, uid: Manage, svc: Svc):
    return svc.update(uid, list_id, body.model_dump(exclude_unset=True))


@router.delete("/{list_id}", status_code=204)
def delete_price_list(list_id: uuid.UUID, uid: Manage, svc: Svc):
    svc.delete(uid, list_id)


@router.put("/{list_id}/items")
def set_price_list_items(list_id: uuid.UUID, body: ItemsIn, uid: Manage, svc: Svc):
    return svc.set_items(uid, list_id, [i.model_dump() for i in body.items])
