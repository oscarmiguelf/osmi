import uuid
from collections.abc import Callable

from app.application.errors import Conflict, Invalid, NotFound
from app.application.ports.image_storage import ImageStorage
from app.application.ports.product_image_repository import ProductImageRepository

MAX_IMAGES = 5
MAX_BYTES = 8 * 1024 * 1024  # phone photos are usually 2-6 MB
EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def sniff(data: bytes) -> str | None:
    """The real type from the file's first bytes (the browser's content type or the name can say anything)."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


class ProductImageService:
    def __init__(self, repo: ProductImageRepository, storage: ImageStorage, clean: Callable[[bytes, str], bytes | None]):
        self.repo = repo
        self.storage = storage
        self.clean = clean  # re-encodes without metadata (EXIF/GPS: catalog photos are public); None = not an image

    def list(self, product_id):
        return self.repo.list(product_id)

    def add(self, uid, product_id, data: bytes):
        if not self.repo.product_active(product_id):
            raise NotFound("product not found")
        if len(data) > MAX_BYTES:
            raise Invalid({"message": "the image is too big", "code": "too_big", "max_bytes": MAX_BYTES})
        content_type = sniff(data)
        if content_type is None:
            raise Invalid({"message": "only JPG, PNG or WebP images", "code": "bad_type"})
        data = self.clean(data, content_type)
        if data is None:
            raise Invalid({"message": "only JPG, PNG or WebP images", "code": "bad_type"})
        if len(self.repo.list(product_id)) >= MAX_IMAGES:
            raise Conflict({"message": f"a product can have at most {MAX_IMAGES} images", "code": "too_many", "max": MAX_IMAGES})
        name = f"{uuid.uuid4()}.{EXTENSIONS[content_type]}"
        self.storage.save(name, data)
        try:
            self.repo.add(uid, product_id, name, content_type, len(data))  # the DB re-checks the limit (concurrent uploads)
            self.repo.commit()
        except Exception:
            self.repo.rollback()
            self.storage.delete(name)  # no row: don't leave the file behind
            raise
        return self.repo.list(product_id)

    def file(self, product_id, image_id):
        image = self.repo.get(product_id, image_id)
        if image is None:
            raise NotFound("image not found")
        return self.storage.path(image["file_name"]), image["content_type"]

    def delete(self, product_id, image_id):
        image = self.repo.get(product_id, image_id)
        if image is None:
            raise NotFound("image not found")
        self.repo.delete(image_id)
        self.repo.commit()
        self.storage.delete(image["file_name"])  # after the commit: a rollback must not lose the file
        return self.repo.list(product_id)

    def set_order(self, product_id, image_ids):
        """image_ids: every image of the product, the first one is the main image."""
        current = {i["id"] for i in self.repo.list(product_id)}
        if len(image_ids) != len(set(image_ids)) or set(image_ids) != current:
            raise Invalid({"message": "send every image of the product exactly once", "field": "image_ids"})
        self.repo.set_order(product_id, image_ids)
        self.repo.commit()
        return self.repo.list(product_id)
