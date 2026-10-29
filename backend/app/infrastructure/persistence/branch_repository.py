from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.infrastructure.persistence.permissions import has_permission, is_super_admin

BRANCH_COLUMNS = """
    b.*,
    NOT EXISTS (SELECT 1 FROM document_sequences ds WHERE ds.branch_id = b.id) AS code_editable,
    (SELECT COUNT(*) FROM user_branches ub JOIN users u ON u.id = ub.user_id AND u.deleted_at IS NULL
      WHERE ub.branch_id = b.id AND ub.deleted_at IS NULL) AS user_count
"""


class SqlBranchRepository:
    def __init__(self, session: Session):
        self.session = session

    def _one(self, sql: str, **params) -> dict | None:
        row = self.session.execute(text(sql), params).mappings().first()
        return dict(row) if row else None

    def _all(self, sql: str, **params) -> list[dict]:
        return [dict(r) for r in self.session.execute(text(sql), params).mappings()]

    def _scalar(self, sql: str, **params):
        return self.session.execute(text(sql), params).scalar()

    def has_permission(self, user_id, module, permission):
        return has_permission(self.session, user_id, module, permission)

    def is_super_admin(self, user_id):
        return is_super_admin(self.session, user_id)

    def list_all(self, include_deleted):
        return self._all(f"""
            SELECT {BRANCH_COLUMNS} FROM branches b
            WHERE b.deleted_at IS NULL OR :deleted ORDER BY LOWER(b.name)
        """, deleted=include_deleted)

    def get(self, branch_id):
        return self._one(f"SELECT {BRANCH_COLUMNS} FROM branches b WHERE b.id = :id", id=branch_id)

    def conflicts(self, name, code, exclude_id):
        """Which of name / code an ACTIVE branch already uses (the unique indexes ignore deleted ones)."""
        row = self._one("""
            SELECT bool_or(LOWER(name) = LOWER(:name)) AS name, bool_or(code = :code) AS code
            FROM branches
            WHERE deleted_at IS NULL AND id IS DISTINCT FROM CAST(:id AS uuid)
              AND (LOWER(name) = LOWER(:name) OR code = :code)
        """, name=name, code=code, id=exclude_id)
        return [field for field in ("name", "code") if row and row[field]]

    def code_editable(self, branch_id):
        return self._scalar("SELECT NOT EXISTS (SELECT 1 FROM document_sequences WHERE branch_id = :id)", id=branch_id)

    def create(self, user_id, data):
        try:
            with self.session.begin_nested():  # a lost race on the unique indexes rolls back only this insert
                row = self._one("""
                    INSERT INTO branches (name, code, phone, address, created_by, updated_by)
                    VALUES (:name, :code, :phone, :address, :uid, :uid) RETURNING id
                """, **data, uid=user_id)
        except IntegrityError:
            return None
        return self.get(row["id"])

    def update(self, user_id, branch_id, fields):
        # fields keys come from the request model, never from raw client input
        sets = "".join(f"{k} = :{k}, " for k in fields)
        try:
            with self.session.begin_nested():
                row = self._one(f"""
                    UPDATE branches SET {sets}updated_by = :uid
                    WHERE id = :id AND deleted_at IS NULL RETURNING id
                """, **fields, uid=user_id, id=branch_id)
        except IntegrityError:
            return None
        return row and self.get(branch_id)

    def delete(self, user_id, branch_id):
        self.session.execute(text("""
            UPDATE branches SET deleted_at = NOW(), deleted_by = :uid, updated_by = :uid
            WHERE id = :id AND deleted_at IS NULL
        """), {"uid": user_id, "id": branch_id})

    def restore(self, user_id, branch_id):
        try:
            with self.session.begin_nested():
                row = self._one("""
                    UPDATE branches SET deleted_at = NULL, deleted_by = NULL, updated_by = :uid
                    WHERE id = :id AND deleted_at IS NOT NULL RETURNING id
                """, uid=user_id, id=branch_id)
        except IntegrityError:
            return None
        return row and self.get(branch_id)

    def delete_blockers(self, branch_id):
        return dict(self._one("""
            SELECT
              (SELECT COUNT(*) FROM product_stock
                WHERE branch_id = :id AND deleted_at IS NULL AND current_stock > 0) AS products_in_stock,
              (SELECT COUNT(*) FROM cash_register_sessions s JOIN cash_registers r ON r.id = s.cash_register_id
                WHERE r.branch_id = :id AND s.ended_at IS NULL) AS open_cash_sessions,
              (SELECT COUNT(*) FROM stocktakes WHERE branch_id = :id AND status = 'OPEN') AS open_stocktakes,
              (SELECT COUNT(*) FROM transfers t JOIN transfer_statuses st ON st.id = t.status_id
                WHERE (t.from_branch_id = :id OR t.to_branch_id = :id) AND st.name = 'IN_TRANSIT') AS transfers_in_transit
        """, id=branch_id))

    def history(self, branch_id, limit, offset):
        return self._all("""
            SELECT a.changed_at, a.entity_type, a.entity_id, a.action, u.email AS changed_by_email,
                   a.changed_fields, a.old_data, a.new_data, m.email AS member_email
            FROM branch_audit a
            LEFT JOIN users u ON u.id = a.changed_by
            -- for membership changes: who was assigned / removed
            LEFT JOIN users m ON a.entity_type = 'user_branch' AND m.id = (a.new_data ->> 'user_id')::uuid
            WHERE a.branch_id = :id ORDER BY a.changed_at DESC, a.id DESC LIMIT :limit OFFSET :offset
        """, id=branch_id, limit=limit, offset=offset)

    def members(self, branch_id):
        return self._all("""
            SELECT u.id, u.email, u.first_name, u.last_name, ub.created_at AS assigned_at
            FROM user_branches ub JOIN users u ON u.id = ub.user_id AND u.deleted_at IS NULL
            WHERE ub.branch_id = :id AND ub.deleted_at IS NULL ORDER BY u.first_name, u.last_name
        """, id=branch_id)

    def user_exists(self, user_id):
        return self._scalar("SELECT EXISTS (SELECT 1 FROM users WHERE id = :id AND deleted_at IS NULL)", id=user_id)

    def branches_of(self, user_id):
        return self._all("""
            SELECT b.id, b.name, b.code, b.phone, b.address
            FROM user_branches ub
            JOIN branches b ON b.id = ub.branch_id AND b.deleted_at IS NULL
            WHERE ub.user_id = :uid AND ub.deleted_at IS NULL
            ORDER BY b.name
        """, uid=user_id)

    def active_branch_ids(self, branch_ids):
        rows = self.session.execute(text(
            "SELECT id FROM branches WHERE id = ANY(CAST(:ids AS uuid[])) AND deleted_at IS NULL"
        ), {"ids": branch_ids})
        return {r.id for r in rows}

    def open_work(self, user_id, branch_ids):
        """Work the user has left open in these branches; removing them from the branch would strand it."""
        return dict(self._one("""
            SELECT
              (SELECT COUNT(*) FROM cash_register_sessions s JOIN cash_registers r ON r.id = s.cash_register_id
                WHERE s.user_id = :uid AND s.ended_at IS NULL AND r.branch_id = ANY(CAST(:ids AS uuid[]))) AS open_cash_sessions,
              (SELECT COUNT(*) FROM stocktakes
                WHERE created_by = :uid AND status = 'OPEN' AND branch_id = ANY(CAST(:ids AS uuid[]))) AS open_stocktakes
        """, uid=user_id, ids=branch_ids))

    def assign(self, by, user_id, branch_ids):
        return self.session.execute(text("""
            INSERT INTO user_branches (user_id, branch_id, created_by, updated_by)
            SELECT :uid, UNNEST(CAST(:ids AS uuid[])), :by, :by
            ON CONFLICT (user_id, branch_id) WHERE deleted_at IS NULL DO NOTHING
        """), {"uid": user_id, "ids": branch_ids, "by": by}).rowcount

    def unassign(self, by, user_id, branch_ids):
        # Soft delete: the membership history (and everything the user did there) stays
        return self.session.execute(text("""
            UPDATE user_branches SET deleted_at = NOW(), deleted_by = :by, updated_by = :by
            WHERE user_id = :uid AND branch_id = ANY(CAST(:ids AS uuid[])) AND deleted_at IS NULL
        """), {"uid": user_id, "ids": branch_ids, "by": by}).rowcount

    def commit(self):
        self.session.commit()
