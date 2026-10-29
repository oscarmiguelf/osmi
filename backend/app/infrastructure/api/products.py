import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, StringConstraints

from app.application.product_service import ProductService
from app.infrastructure.api.fields import optional_text
from app.infrastructure.api.permissions import OptionalBranch, require_permission
from app.infrastructure.persistence.database import SessionLocal
from app.infrastructure.persistence.product_repository import SqlProductRepository

router = APIRouter(tags=["products"])

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Money = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]
Stock = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=3)]
Barcode = optional_text(50)


class ProductIn(BaseModel):
    name: Name
    product_type_id: uuid.UUID
    unit_of_measure_id: uuid.UUID
    description: optional_text(5000) = None
    cost: Money = Decimal(0)
    price: Money = Decimal(0)  # final price, tax included
    barcode: Barcode = None
    category_id: uuid.UUID | None = None
    brand_id: uuid.UUID | None = None
    min_stock: Stock = Decimal(0)
    duration_minutes: Annotated[int, Field(ge=5, le=720)] | None = None  # services: proposes the appointment's length
    tax_rate_id: uuid.UUID | None = None  # omitted: the default tax rate
    initial_stock: Stock = Decimal(0)  # loaded into the working branch (X-Branch-Id) as an adjustment


# PATCH: a non-optional type with default None means the field can be omitted but not sent as null.
class ProductPatch(BaseModel):
    name: Name = None
    product_type_id: uuid.UUID = None
    unit_of_measure_id: uuid.UUID = None
    description: optional_text(5000) = None
    cost: Money = None
    price: Money = None
    barcode: Barcode = None
    category_id: uuid.UUID | None = None
    brand_id: uuid.UUID | None = None
    min_stock: Stock = None
    duration_minutes: Annotated[int, Field(ge=5, le=720)] | None = None
    tax_rate_id: uuid.UUID = None


class SuppliersIn(BaseModel):
    supplier_ids: list[uuid.UUID]


class ComponentIn(BaseModel):
    product_id: uuid.UUID
    quantity: Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=3)]


class ComponentsIn(BaseModel):
    components: list[ComponentIn]


def get_service():
    with SessionLocal() as session:
        yield ProductService(SqlProductRepository(session))


Svc = Annotated[ProductService, Depends(get_service)]
Read, Create, Update, Delete = (require_permission("products", p) for p in ("read", "create", "update", "delete"))
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


@router.get("/products")
def search_products(_: Read, svc: Svc, branch: OptionalBranch, q: Annotated[str, Query(max_length=100)] = "",
                    type_id: uuid.UUID | None = None, category_id: uuid.UUID | None = None,
                    supplier_id: uuid.UUID | None = None, low_stock: bool = False, include_deleted: bool = False,
                    page: Page = 1, page_size: PageSize = 25):
    filters = {"q": q.strip(), "type_id": type_id, "category_id": category_id, "supplier_id": supplier_id,
               "low_stock": low_stock and branch is not None, "include_deleted": include_deleted}
    return svc.search(branch, filters, page, page_size)


@router.get("/products/by-barcode/{barcode}")
def product_by_barcode(barcode: str, _: Read, svc: Svc, branch: OptionalBranch):
    return svc.by_barcode(barcode.strip(), branch)


@router.post("/products", status_code=201)
def create_product(body: ProductIn, uid: Create, svc: Svc, branch: OptionalBranch):
    return svc.create(uid, body.model_dump(), branch)


@router.get("/products/{product_id}")
def get_product(product_id: uuid.UUID, _: Read, svc: Svc, branch: OptionalBranch):
    return svc.get(product_id, branch)


@router.patch("/products/{product_id}")
def update_product(product_id: uuid.UUID, body: ProductPatch, uid: Update, svc: Svc, branch: OptionalBranch):
    return svc.update(uid, product_id, body.model_dump(exclude_unset=True), branch)


@router.delete("/products/{product_id}", status_code=204)
def delete_product(product_id: uuid.UUID, uid: Delete, svc: Svc):
    svc.delete(uid, product_id)


@router.post("/products/{product_id}/restore")
def restore_product(product_id: uuid.UUID, uid: Delete, svc: Svc, branch: OptionalBranch):
    return svc.restore(uid, product_id, branch)


@router.get("/products/{product_id}/history")
def product_history(product_id: uuid.UUID, _: Read, svc: Svc, page: Page = 1, page_size: PageSize = 25):
    return svc.history(product_id, page, page_size)


@router.put("/products/{product_id}/suppliers")
def set_product_suppliers(product_id: uuid.UUID, body: SuppliersIn, uid: Update, svc: Svc, branch: OptionalBranch):
    return svc.set_suppliers(uid, product_id, body.supplier_ids, branch)


@router.put("/products/{product_id}/kit-components")
def set_kit_components(product_id: uuid.UUID, body: ComponentsIn, uid: Update, svc: Svc, branch: OptionalBranch):
    return svc.set_components(uid, product_id, [(c.product_id, c.quantity) for c in body.components], branch)
