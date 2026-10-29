from sqlalchemy import text
from sqlalchemy.orm import Session

from app.infrastructure.persistence.permissions import is_super_admin


class SqlAccessRepository:
    def __init__(self, session: Session):
        self.session = session

    def _one(self, sql: str, **params) -> dict | None:
        row = self.session.execute(text(sql), params).mappings().first()
        return dict(row) if row else None

    def _all(self, sql: str, **params) -> list[dict]:
        return [dict(r) for r in self.session.execute(text(sql), params).mappings()]

    def _scalar(self, sql: str, **params):
        return self.session.execute(text(sql), params).scalar()

    def is_super_admin(self, user_id):
        return is_super_admin(self.session, user_id)

    def list_modules(self, include_inactive, include_deleted, module_id=None):
        return self._all("""
            SELECT m.*, COALESCE(JSON_AGG(JSON_BUILD_OBJECT(
                       'id', p.id, 'code', p.code, 'name', p.name, 'description', p.description,
                       'deleted_at', p.deleted_at) ORDER BY p.code) FILTER (WHERE p.id IS NOT NULL), '[]') AS permissions
            FROM modules m
            LEFT JOIN permissions p ON p.module_id = m.id AND (p.deleted_at IS NULL OR :deleted)
            WHERE (m.deleted_at IS NULL OR :deleted) AND (m.is_active OR :inactive)
              AND (CAST(:id AS uuid) IS NULL OR m.id = CAST(:id AS uuid))
            GROUP BY m.id ORDER BY m.sort_order, m.name
        """, deleted=include_deleted, inactive=include_inactive, id=module_id)

    def module_by_code(self, code):
        return self._one("SELECT id, deleted_at FROM modules WHERE code = :code", code=code)

    def create_module(self, data):
        return self._one("""
            INSERT INTO modules (code, name, description, route, icon, sort_order)
            VALUES (:code, :name, :description, :route, :icon, :sort_order)
            ON CONFLICT (code) DO NOTHING RETURNING *
        """, **data)

    def create_crud_permissions(self, module_id):
        self.session.execute(text("""
            INSERT INTO permissions (module_id, code, name)
            SELECT :mid, p.code, p.name
            FROM (VALUES ('read','Read'),('create','Create'),('update','Update'),('delete','Delete')) AS p (code, name)
        """), {"mid": module_id})

    def update_module(self, module_id, fields):
        if not fields:
            return None
        # fields keys come from the request model, never from raw client input
        sets = ", ".join(f"{k} = :{k}" for k in fields)
        return self._one(f"UPDATE modules SET {sets} WHERE id = :id AND deleted_at IS NULL RETURNING *",
                         **fields, id=module_id)

    def delete_module(self, user_id, module_id):
        self.session.execute(text("""
            UPDATE modules SET deleted_at = NOW(), deleted_by = :uid WHERE id = :id AND deleted_at IS NULL
        """), {"uid": user_id, "id": module_id})

    def restore_module(self, module_id):
        return self.session.execute(text("""
            UPDATE modules SET deleted_at = NULL, deleted_by = NULL WHERE id = :id AND deleted_at IS NOT NULL
        """), {"id": module_id}).rowcount > 0

    def get_permission(self, permission_id):
        return self._one("""
            SELECT p.*, m.code AS module_code
            FROM permissions p JOIN modules m ON m.id = p.module_id
            WHERE p.id = :id AND p.deleted_at IS NULL
        """, id=permission_id)

    def permission_by_code(self, module_id, code):
        return self._one("SELECT id, deleted_at FROM permissions WHERE module_id = :mid AND code = :code",
                         mid=module_id, code=code)

    def create_permission(self, module_id, data):
        return self._one("""
            INSERT INTO permissions (module_id, code, name, description)
            VALUES (:mid, :code, :name, :description)
            ON CONFLICT (module_id, code) DO NOTHING RETURNING *
        """, **data, mid=module_id)

    def update_permission(self, permission_id, fields):
        # fields keys come from the request model, never from raw client input
        sets = ", ".join(f"{k} = :{k}" for k in fields) or "name = name"
        return self._one(f"UPDATE permissions SET {sets} WHERE id = :id AND deleted_at IS NULL RETURNING *",
                         **fields, id=permission_id)

    def delete_permission(self, user_id, permission_id):
        self.session.execute(text("""
            UPDATE permissions SET deleted_at = NOW(), deleted_by = :uid WHERE id = :id AND deleted_at IS NULL
        """), {"uid": user_id, "id": permission_id})

    def restore_permission(self, permission_id):
        return self.session.execute(text("""
            UPDATE permissions SET deleted_at = NULL, deleted_by = NULL WHERE id = :id AND deleted_at IS NOT NULL
        """), {"id": permission_id}).rowcount > 0

    def user_exists(self, user_id):
        return self._scalar("SELECT EXISTS (SELECT 1 FROM users WHERE id = :id AND deleted_at IS NULL)", id=user_id)

    def user_access(self, user_id):
        return self._all("""
            SELECT m.id AS module_id, m.code AS module_code, m.name AS module_name,
                   (um.user_id IS NOT NULL) AS has_module,
                   COALESCE(JSON_AGG(JSON_BUILD_OBJECT(
                       'id', p.id, 'code', p.code, 'name', p.name,
                       'granted', (ump.permission_id IS NOT NULL)) ORDER BY p.code)
                     FILTER (WHERE p.id IS NOT NULL), '[]') AS permissions
            FROM modules m
            LEFT JOIN user_modules um ON um.module_id = m.id AND um.user_id = :uid
            LEFT JOIN permissions p ON p.module_id = m.id AND p.deleted_at IS NULL
            LEFT JOIN user_module_permissions ump ON ump.user_id = :uid AND ump.permission_id = p.id
            WHERE m.deleted_at IS NULL
            GROUP BY m.id, um.user_id ORDER BY m.sort_order, m.name
        """, uid=user_id)

    def existing_modules(self, module_ids):
        rows = self.session.execute(text(
            "SELECT id FROM modules WHERE id = ANY(CAST(:ids AS uuid[])) AND deleted_at IS NULL"
        ), {"ids": module_ids})
        return {r.id for r in rows}

    def permission_modules(self, permission_ids):
        rows = self.session.execute(text(
            "SELECT id, module_id FROM permissions WHERE id = ANY(CAST(:ids AS uuid[])) AND deleted_at IS NULL"
        ), {"ids": permission_ids})
        return {r.id: r.module_id for r in rows}

    def user_grants(self, user_id):
        rows = self.session.execute(text("""
            SELECT um.module_id, p.id AS permission_id
            FROM user_modules um
            JOIN modules m ON m.id = um.module_id AND m.deleted_at IS NULL
            LEFT JOIN user_module_permissions ump ON ump.user_id = um.user_id AND ump.module_id = um.module_id
            LEFT JOIN permissions p ON p.id = ump.permission_id AND p.deleted_at IS NULL
            WHERE um.user_id = :uid
        """), {"uid": user_id}).all()
        return {r.module_id for r in rows}, {r.permission_id for r in rows if r.permission_id}

    def replace_grants(self, granted_by, user_id, module_ids, permission_ids):
        # Only grants on non-deleted modules/permissions are replaced; hidden ones survive a restore.
        # Rows that stay keep their original granted_at/granted_by.
        params = {"uid": user_id, "by": granted_by, "mids": module_ids, "pids": permission_ids}
        for sql in (
            """DELETE FROM user_modules WHERE user_id = :uid AND NOT (module_id = ANY(CAST(:mids AS uuid[])))
                 AND module_id IN (SELECT id FROM modules WHERE deleted_at IS NULL)""",
            """INSERT INTO user_modules (user_id, module_id, granted_by)
               SELECT :uid, UNNEST(CAST(:mids AS uuid[])), :by ON CONFLICT DO NOTHING""",
            """DELETE FROM user_module_permissions WHERE user_id = :uid
                 AND NOT (permission_id = ANY(CAST(:pids AS uuid[])))
                 AND permission_id IN (SELECT id FROM permissions WHERE deleted_at IS NULL)
                 AND module_id IN (SELECT id FROM modules WHERE deleted_at IS NULL)""",
            """INSERT INTO user_module_permissions (user_id, module_id, permission_id, granted_by)
               SELECT :uid, p.module_id, p.id, :by FROM permissions p
               WHERE p.id = ANY(CAST(:pids AS uuid[])) ON CONFLICT DO NOTHING""",
        ):
            self.session.execute(text(sql), params)

    def users_admin_exists(self):
        # Someone active must still hold users.update, or nobody can manage access anymore.
        return self._scalar("""
            SELECT EXISTS (
              SELECT 1 FROM user_module_permissions ump
              JOIN permissions p ON p.id = ump.permission_id AND p.deleted_at IS NULL AND p.code = 'update'
              JOIN modules m ON m.id = ump.module_id AND m.deleted_at IS NULL AND m.is_active AND m.code = 'users'
              JOIN users u ON u.id = ump.user_id AND u.is_active AND u.deleted_at IS NULL)
        """)

    def commit(self):
        self.session.commit()
