import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.application.benefit_service import BenefitService
from app.infrastructure.api.permissions import require_permission
from app.infrastructure.persistence.benefit_repository import SqlBenefitRepository
from app.infrastructure.persistence.database import SessionLocal

# Packages and memberships: configured on a product (products.prices: they decide what is charged), granted by selling it.
router = APIRouter(tags=["packages and memberships"])


class BenefitIn(BaseModel):
    kind: Literal["package", "membership"]
    service_product_id: uuid.UUID | None = None  # package: the service it gives sessions of
    sessions: Annotated[int, Field(ge=1, le=500)] | None = None
    valid_days: Annotated[int, Field(ge=1, le=3660)] | None = None  # package: optional expiry; membership: its length
    price_list_id: uuid.UUID | None = None  # membership: the prices its members pay


def get_service():
    with SessionLocal() as session:
        yield BenefitService(SqlBenefitRepository(session))


Svc = Annotated[BenefitService, Depends(get_service)]
Manage = require_permission("products", "prices")
CustomersRead = require_permission("customers", "read")


@router.put("/products/{product_id}/benefit")
def set_benefit(product_id: uuid.UUID, body: BenefitIn, uid: Manage, svc: Svc):
    return svc.set(uid, product_id, body.model_dump())


@router.delete("/products/{product_id}/benefit", status_code=204)
def clear_benefit(product_id: uuid.UUID, _: Manage, svc: Svc):
    svc.clear(product_id)


@router.get("/customers/{customer_id}/benefits")
def customer_benefits(customer_id: uuid.UUID, _: CustomersRead, svc: Svc):
    return svc.of_customer(customer_id)


@router.get("/memberships/expiring")
def expiring_memberships(_: CustomersRead, svc: Svc, days: Annotated[int, Query(ge=1, le=90)] = 7):
    return svc.expiring(days)
