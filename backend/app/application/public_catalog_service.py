from app.application.errors import NotFound
from app.application.ports.image_storage import ImageStorage
from app.application.ports.public_catalog_repository import PublicCatalogRepository


class PublicCatalogService:
    """What anyone can see without signing in: products with stock (in any branch) and services, no kits.
    Ordering is a WhatsApp message built by the browser; nothing is recorded here."""

    def __init__(self, repo: PublicCatalogRepository, storage: ImageStorage):
        self.repo = repo
        self.storage = storage

    def info(self):
        number = self.repo.whatsapp_number()
        return {"whatsapp_number": number or None, "ordering": bool(number), "categories": self.repo.categories()}

    def products(self, q, category_id, kind, page, page_size):
        rows = self.repo.products(q.strip(), category_id, kind, page_size + 1, (page - 1) * page_size)
        return {"items": rows[:page_size], "page": page, "page_size": page_size, "has_more": len(rows) > page_size}

    def image(self, product_id, image_id):
        """Only images of products the catalog shows."""
        image = self.repo.image(product_id, image_id)
        if image is None:
            raise NotFound("image not found")
        return self.storage.path(image["file_name"]), image["content_type"]
