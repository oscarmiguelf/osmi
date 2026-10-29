from sqlalchemy import text
from sqlalchemy.orm import Session

COLUMNS = "id, content_type, size_bytes, sort_order, created_at"


class SqlProductImageRepository:
    def __init__(self, session: Session):
        self.session = session

    def product_active(self, product_id):
        return self.session.execute(text("SELECT 1 FROM products WHERE id = :id AND deleted_at IS NULL"), {"id": product_id}).first() is not None

    def list(self, product_id):
        return [dict(r) for r in self.session.execute(text(f"""
            SELECT {COLUMNS} FROM product_images WHERE product_id = :id ORDER BY sort_order, created_at, id
        """), {"id": product_id}).mappings()]

    def get(self, product_id, image_id):
        row = self.session.execute(text("""
            SELECT id, file_name, content_type FROM product_images WHERE id = :img AND product_id = :id
        """), {"img": image_id, "id": product_id}).mappings().first()
        return dict(row) if row else None

    def add(self, user_id, product_id, file_name, content_type, size):
        # New images go last; the first one uploaded becomes the main image
        return dict(self.session.execute(text(f"""
            INSERT INTO product_images (product_id, file_name, content_type, size_bytes, sort_order, created_by)
            VALUES (:id, :name, :type, :size,
                    COALESCE((SELECT MAX(sort_order) + 1 FROM product_images WHERE product_id = :id), 0), :uid)
            RETURNING {COLUMNS}
        """), {"id": product_id, "name": file_name, "type": content_type, "size": size, "uid": user_id}).mappings().one())

    def delete(self, image_id):
        self.session.execute(text("DELETE FROM product_images WHERE id = :id"), {"id": image_id})

    def set_order(self, product_id, image_ids):
        self.session.execute(text("""
            UPDATE product_images i SET sort_order = o.n - 1
            FROM UNNEST(CAST(:ids AS uuid[])) WITH ORDINALITY AS o (id, n)
            WHERE i.id = o.id AND i.product_id = :pid
        """), {"ids": [str(i) for i in image_ids], "pid": product_id})

    def commit(self):
        self.session.commit()

    def rollback(self):
        self.session.rollback()
