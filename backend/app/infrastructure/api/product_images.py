import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.application.errors import Invalid
from app.application.product_image_service import MAX_BYTES, ProductImageService
from app.infrastructure.api.permissions import require_permission
from app.infrastructure.images import clean_image
from app.infrastructure.persistence.database import SessionLocal
from app.infrastructure.persistence.image_storage import LocalImageStorage
from app.infrastructure.persistence.product_image_repository import SqlProductImageRepository

# Images of a product (up to 5), guarded by the products module: see with read, change with update.
router = APIRouter(prefix="/products/{product_id}/images", tags=["products"])


class OrderIn(BaseModel):
    image_ids: list[uuid.UUID] = Field(min_length=1, max_length=5)


def get_service():
    with SessionLocal() as session:
        yield ProductImageService(SqlProductImageRepository(session), LocalImageStorage(), clean_image)


Svc = Annotated[ProductImageService, Depends(get_service)]
Read, Update = (require_permission("products", p) for p in ("read", "update"))


@router.get("")
def list_images(product_id: uuid.UUID, _: Read, svc: Svc):
    return svc.list(product_id)


@router.post("", status_code=201)
async def upload_image(product_id: uuid.UUID, uid: Update, svc: Svc, file: Annotated[UploadFile, File()]):
    data = await file.read(MAX_BYTES + 1)  # never more than the limit in memory
    if not data:
        raise Invalid({"message": "the file is empty", "code": "bad_type"})
    return svc.add(uid, product_id, data)


@router.put("/order")
def order_images(product_id: uuid.UUID, body: OrderIn, _: Update, svc: Svc):
    """Every image id, the first one is the main image."""
    return svc.set_order(product_id, body.image_ids)


@router.get("/{image_id}")
def image_file(product_id: uuid.UUID, image_id: uuid.UUID, _: Read, svc: Svc):
    path, content_type = svc.file(product_id, image_id)
    # An id always names the same bytes (a new upload gets a new id): browsers may keep it for a long time
    return FileResponse(path, media_type=content_type, headers={"Cache-Control": "private, max-age=31536000, immutable"})


@router.delete("/{image_id}")
def delete_image(product_id: uuid.UUID, image_id: uuid.UUID, _: Update, svc: Svc):
    return svc.delete(product_id, image_id)
