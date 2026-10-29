import re
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import AfterValidator, AwareDatetime, BaseModel, BeforeValidator, Field, StringConstraints

from app.application.errors import Forbidden
from app.application.supplier_service import SupplierService
from app.infrastructure.api.auth import current_user_id
from app.infrastructure.api.fields import blank_to_none
from app.infrastructure.api.permissions import require_permission
from app.infrastructure.persistence.database import SessionLocal
from app.infrastructure.persistence.permissions import has_permission
from app.infrastructure.persistence.supplier_repository import SqlSupplierRepository

# Own module "suppliers" (read, create, update, delete), seeded in all_in_one_schema.sql and granted to admin.
# Linking products from the supplier side needs suppliers.update; from the product side it stays products.update.
router = APIRouter(prefix="/suppliers", tags=["suppliers"])


def _email(value: str) -> str:
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):  # same rule as the DB check
        raise ValueError("enter an email like name@domain.com")
    return value.lower()


def _phone(value: str) -> str:
    # Free text (landlines, extensions, foreign numbers): not the 10-digit rule of customers
    if not re.fullmatch(r"[0-9+\-() ]+", value):
        raise ValueError("use only digits, spaces, +, - and parentheses")
    return re.sub(r"\s+", " ", value)


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Phone = Annotated[Annotated[str, StringConstraints(max_length=20), AfterValidator(_phone)] | None, BeforeValidator(blank_to_none)]
Email = Annotated[Annotated[str, StringConstraints(max_length=255), AfterValidator(_email)] | None, BeforeValidator(blank_to_none)]


class SupplierIn(BaseModel):
    name: Name
    phone: Phone = None
    email: Email = None


# PATCH is partial: name can be omitted but not sent as null; phone / email are cleared with null
class SupplierPatch(BaseModel):
    name: Name = None
    phone: Phone = None
    email: Email = None


class ProductsIn(BaseModel):
    product_ids: list[uuid.UUID] = Field(max_length=5000)


def get_service():
    with SessionLocal() as session:
        yield SupplierService(SqlSupplierRepository(session))


def can_pick(uid: Annotated[uuid.UUID, Depends(current_user_id)]) -> uuid.UUID:
    """The supplier selector (product and purchase forms) works with suppliers, products or purchases read."""
    with SessionLocal() as session:
        if not any(has_permission(session, uid, m, "read") for m in ("suppliers", "products", "purchases")):
            raise Forbidden("missing permission suppliers.read")
    return uid


Svc = Annotated[SupplierService, Depends(get_service)]
Read, Create, Update, Delete = (require_permission("suppliers", p) for p in ("read", "create", "update", "delete"))
Pick = Annotated[uuid.UUID, Depends(can_pick)]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]
From = Annotated[AwareDatetime | None, Query(alias="from")]


@router.get("")
def search_suppliers(_: Read, svc: Svc, q: Annotated[str, Query(max_length=100)] = "", include_deleted: bool = False,
                     page: Page = 1, page_size: PageSize = 25, sort: Literal["name", "recent"] = "name"):
    return svc.search(q, include_deleted, page, page_size, sort)


@router.get("/options")
def supplier_options(_: Pick, svc: Svc, include_deleted: bool = False):
    """Every supplier, unpaginated, for selectors."""
    return svc.options(include_deleted)


@router.post("", status_code=201)
def create_supplier(body: SupplierIn, uid: Create, svc: Svc, force: bool = False):
    return svc.create(uid, body.model_dump(), force)


@router.get("/{supplier_id}")
def get_supplier(supplier_id: uuid.UUID, uid: Read, svc: Svc):
    return svc.get(uid, supplier_id)


@router.patch("/{supplier_id}")
def update_supplier(supplier_id: uuid.UUID, body: SupplierPatch, uid: Update, svc: Svc, force: bool = False):
    return svc.update(uid, supplier_id, body.model_dump(exclude_unset=True), force)


@router.delete("/{supplier_id}", status_code=204)
def delete_supplier(supplier_id: uuid.UUID, uid: Delete, svc: Svc):
    svc.delete(uid, supplier_id)


@router.post("/{supplier_id}/restore")
def restore_supplier(supplier_id: uuid.UUID, uid: Delete, svc: Svc):
    return svc.restore(uid, supplier_id)


@router.get("/{supplier_id}/history")
def supplier_history(supplier_id: uuid.UUID, uid: Read, svc: Svc, page: Page = 1, page_size: PageSize = 25):
    return svc.history(uid, supplier_id, page, page_size)


@router.get("/{supplier_id}/products")
def supplier_products(supplier_id: uuid.UUID, uid: Read, svc: Svc, page: Page = 1, page_size: PageSize = 25):
    return svc.products(uid, supplier_id, page, page_size)


@router.put("/{supplier_id}/products")
def set_supplier_products(supplier_id: uuid.UUID, body: ProductsIn, uid: Update, svc: Svc):
    return svc.set_products(uid, supplier_id, body.product_ids)


@router.post("/{supplier_id}/products/{product_id}")
def link_product(supplier_id: uuid.UUID, product_id: uuid.UUID, uid: Update, svc: Svc):
    return svc.link(uid, supplier_id, product_id)


@router.delete("/{supplier_id}/products/{product_id}", status_code=204)
def unlink_product(supplier_id: uuid.UUID, product_id: uuid.UUID, uid: Update, svc: Svc):
    svc.unlink(uid, supplier_id, product_id)


@router.get("/{supplier_id}/purchases")
def supplier_purchases(supplier_id: uuid.UUID, uid: Read, svc: Svc, from_: From = None, to: AwareDatetime | None = None,
                       page: Page = 1, page_size: PageSize = 25):
    return svc.purchases(uid, supplier_id, from_, to, page, page_size)


@router.get("/{supplier_id}/summary")
def supplier_summary(supplier_id: uuid.UUID, uid: Read, svc: Svc, from_: From = None, to: AwareDatetime | None = None):
    return svc.summary(uid, supplier_id, from_, to)


@router.get("/{supplier_id}/price-history/{product_id}")
def supplier_price_history(supplier_id: uuid.UUID, product_id: uuid.UUID, uid: Read, svc: Svc,
                           limit: Annotated[int, Query(ge=1, le=100)] = 25):
    return svc.price_history(uid, supplier_id, product_id, limit)
