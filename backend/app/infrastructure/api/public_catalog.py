import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse

from app.application.public_catalog_service import PublicCatalogService
from app.infrastructure.persistence.database import SessionLocal
from app.infrastructure.persistence.image_storage import LocalImageStorage
from app.infrastructure.persistence.public_catalog_repository import SqlPublicCatalogRepository

# PUBLIC (no sign-in): the customer catalog. Read-only; it only shows what the catalog is meant to show.
router = APIRouter(prefix="/public/catalog", tags=["public catalog"])


def get_service():
    with SessionLocal() as session:
        yield PublicCatalogService(SqlPublicCatalogRepository(session), LocalImageStorage())


Svc = Annotated[PublicCatalogService, Depends(get_service)]


@router.get("")
def catalog_info(svc: Svc):
    """WhatsApp number for orders (null = ordering off) and the categories with something to show."""
    return svc.info()


@router.get("/products")
def catalog_products(svc: Svc, q: Annotated[str, Query(max_length=100)] = "", category_id: uuid.UUID | None = None,
                     kind: Literal["all", "products", "services"] = "all", page: Annotated[int, Query(ge=1)] = 1,
                     page_size: Annotated[int, Query(ge=1, le=60)] = 24):
    return svc.products(q, category_id, kind, page, page_size)


@router.get("/products/{product_id}/images/{image_id}")
def catalog_image(product_id: uuid.UUID, image_id: uuid.UUID, svc: Svc):
    path, content_type = svc.image(product_id, image_id)
    return FileResponse(path, media_type=content_type, headers={"Cache-Control": "public, max-age=86400"})
