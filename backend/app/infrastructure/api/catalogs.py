import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, StringConstraints

from app.application.catalog_service import CatalogService
from app.infrastructure.api.permissions import require_permission
from app.infrastructure.persistence.catalog_repository import SqlCatalogRepository
from app.infrastructure.persistence.database import SessionLocal

router = APIRouter(tags=["catalogs"])


def text_field(max_length: int):
    return Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=max_length)]


Rate = Annotated[Decimal, Field(ge=0, lt=1, max_digits=5, decimal_places=4)]  # 0.16 = 16%


# PATCH models: a non-optional type with default None means the field can be omitted but not sent as null.
class CategoryIn(BaseModel):
    name: text_field(100)


class CategoryPatch(BaseModel):
    name: text_field(100) = None


class UnitIn(BaseModel):
    name: text_field(50)


class UnitPatch(BaseModel):
    name: text_field(50) = None


class BrandIn(BaseModel):
    name: text_field(100)


class BrandPatch(BaseModel):
    name: text_field(100) = None


class ProductTypeIn(BaseModel):
    name: text_field(100)
    tracks_stock: bool = True
    is_kit: bool = False


class ProductTypePatch(BaseModel):
    # tracks_stock / is_kit are fixed once created: changing them would break existing stock and kits
    name: text_field(100) = None


class TaxRateIn(BaseModel):
    name: text_field(100)
    rate: Rate
    is_default: bool = False


class TaxRatePatch(BaseModel):
    name: text_field(100) = None
    rate: Rate = None  # affects future sales only: sale lines keep their own snapshot
    is_default: bool = None  # true makes it the default (the previous one stops being it)


def get_service():
    with SessionLocal() as session:
        yield CatalogService(SqlCatalogRepository(session))


Svc = Annotated[CatalogService, Depends(get_service)]

Read, Create, Update, Delete = (require_permission("products", p) for p in ("read", "create", "update", "delete"))


def _register(path: str, catalog: str, model_in: type[BaseModel], model_patch: type[BaseModel], restore: bool = True):
    """GET / POST / PATCH / DELETE / restore for one catalog, all guarded by the products module (suppliers have their own API)."""

    @router.get(f"/{path}", name=f"list_{catalog}")
    def list_items(_: Read, svc: Svc, include_deleted: bool = False):
        return svc.list(catalog, include_deleted)

    @router.post(f"/{path}", status_code=201, name=f"create_{catalog}")
    def create_item(body: model_in, uid: Create, svc: Svc):  # type: ignore[valid-type]
        return svc.create(catalog, uid, body.model_dump())

    @router.patch(f"/{path}/{{item_id}}", name=f"update_{catalog}")
    def update_item(item_id: uuid.UUID, body: model_patch, uid: Update, svc: Svc):  # type: ignore[valid-type]
        return svc.update(catalog, uid, item_id, body.model_dump(exclude_unset=True))

    @router.delete(f"/{path}/{{item_id}}", status_code=204, name=f"delete_{catalog}")
    def delete_item(item_id: uuid.UUID, uid: Delete, svc: Svc):
        svc.delete(catalog, uid, item_id)

    if not restore:  # hard-deleted: nothing to restore
        return

    @router.post(f"/{path}/{{item_id}}/restore", name=f"restore_{catalog}")
    def restore_item(item_id: uuid.UUID, uid: Delete, svc: Svc):
        return svc.restore(catalog, uid, item_id)


_register("categories", "categories", CategoryIn, CategoryPatch)
_register("units", "units", UnitIn, UnitPatch)
_register("product-types", "product_types", ProductTypeIn, ProductTypePatch)
_register("tax-rates", "tax_rates", TaxRateIn, TaxRatePatch)
_register("brands", "brands", BrandIn, BrandPatch, restore=False)


class BrandMergeIn(BaseModel):
    from_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    to_id: uuid.UUID


@router.post("/brands/merge")
def merge_brands(body: BrandMergeIn, uid: Update, _: Delete, svc: Svc):
    """Unify spellings: the products of `from_ids` move to `to_id` and those brands are removed (needs update and delete)."""
    return svc.merge_brands(uid, body.from_ids, body.to_id)
