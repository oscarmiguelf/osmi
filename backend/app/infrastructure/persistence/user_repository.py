from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.infrastructure.persistence.permissions import has_permission, is_super_admin

# What an admin screen may see about a user: never password_hash or token data
USER = """
    u.id, u.email, u.first_name, u.last_name, u.is_active, u.timezone,
    COALESCE(u.locked_until > NOW(), FALSE) AS is_locked, u.locked_until, u.failed_attempts,
    u.last_login_at, u.password_changed_at, u.must_change_password,
    u.created_at, u.updated_at, u.deleted_at, cb.email AS created_by_email
"""
USER_FROM = "users u LEFT JOIN users cb ON cb.id = u.created_by"


def _like(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class SqlUserRepository:
    def __init__(self, session: Session):
        self.session = session

    def _one(self, sql: str, **params) -> dict | None:
        row = self.session.execute(text(sql), params).mappings().first()
        return dict(row) if row else None

    def _all(self, sql: str, **params) -> list[dict]:
        return [dict(r) for r in self.session.execute(text(sql), params).mappings()]

    def _scalar(self, sql: str, **params):
        return self.session.execute(text(sql), params).scalar()

    def _guarded(self, sql: str, **params) -> dict | None:
        """A write that may hit uq_users_email: None instead of an aborted transaction."""
        try:
            with self.session.begin_nested():
                return self._one(sql, **params)
        except IntegrityError:
            return None

    def has_permission(self, user_id, module, permission):
        return has_permission(self.session, user_id, module, permission)

    def is_super_admin(self, user_id):
        return is_super_admin(self.session, user_id)

    def permission_set(self, user_id):
        rows = self.session.execute(text("""
            SELECT m.code AS module, p.code AS permission
            FROM user_module_permissions ump
            JOIN modules m ON m.id = ump.module_id AND m.deleted_at IS NULL
            JOIN permissions p ON p.id = ump.permission_id AND p.deleted_at IS NULL
            WHERE ump.user_id = :uid
        """), {"uid": user_id})
        return {(r.module, r.permission) for r in rows}

    def other_user_admins(self, user_id):
        """Active users other than this one who can still administer users (users.update)."""
        return self._scalar("""
            SELECT COUNT(*) FROM users u
            WHERE u.deleted_at IS NULL AND u.is_active AND u.id <> :uid
              AND EXISTS (SELECT 1 FROM user_module_permissions ump
                          JOIN modules m ON m.id = ump.module_id AND m.code = 'users' AND m.deleted_at IS NULL AND m.is_active
                          JOIN permissions p ON p.id = ump.permission_id AND p.code = 'update' AND p.deleted_at IS NULL
                          WHERE ump.user_id = u.id)
        """, uid=user_id)

    def timezone_exists(self, timezone):
        return self._scalar("SELECT EXISTS (SELECT 1 FROM pg_timezone_names WHERE name = :tz)", tz=timezone)

    def search(self, q, status, branch_id, limit, offset):
        where = """
            WHERE (:q = '' OR LOWER(u.email) LIKE LOWER(:p) OR LOWER(u.first_name || ' ' || u.last_name) LIKE LOWER(:p))
              AND CASE CAST(:status AS text)
                    WHEN 'active'   THEN u.deleted_at IS NULL AND u.is_active
                    WHEN 'inactive' THEN u.deleted_at IS NULL AND NOT u.is_active
                    WHEN 'deleted'  THEN u.deleted_at IS NOT NULL
                    WHEN 'all'      THEN TRUE
                    ELSE u.deleted_at IS NULL
                  END
              AND (CAST(:branch AS uuid) IS NULL OR EXISTS (
                    SELECT 1 FROM user_branches ub
                    WHERE ub.user_id = u.id AND ub.branch_id = CAST(:branch AS uuid) AND ub.deleted_at IS NULL))
        """
        params = {"q": q, "p": _like(q), "status": status, "branch": branch_id}
        items = self._all(f"""
            SELECT {USER} FROM {USER_FROM} {where}
            ORDER BY LOWER(u.first_name), LOWER(u.last_name), u.id LIMIT :limit OFFSET :offset
        """, **params, limit=limit, offset=offset)
        total = self._scalar(f"SELECT COUNT(*) FROM users u {where}", **params)
        return items, total

    def get(self, user_id):
        return self._one(f"SELECT {USER} FROM {USER_FROM} WHERE u.id = :id", id=user_id)

    def password_hash(self, user_id):
        return self._scalar("SELECT password_hash FROM users WHERE id = :id AND deleted_at IS NULL", id=user_id)

    def create(self, by, data, password_hash):
        row = self._guarded("""
            INSERT INTO users (email, password_hash, first_name, last_name, timezone, must_change_password, created_by, updated_by)
            VALUES (:email, :hash, :first_name, :last_name, COALESCE(:timezone, 'America/Mexico_City'), TRUE, :by, :by)
            RETURNING id
        """, **data, hash=password_hash, by=by)
        return row and self.get(row["id"])

    def update(self, by, user_id, fields):
        # fields keys come from the request model, never from raw client input
        sets = "".join(f"{k} = :{k}, " for k in fields)
        row = self._guarded(f"""
            UPDATE users SET {sets}updated_by = :by WHERE id = :id AND deleted_at IS NULL RETURNING id
        """, **fields, by=by, id=user_id)
        return row and self.get(user_id)

    def set_active(self, by, user_id, active):
        self.session.execute(text("""
            UPDATE users SET is_active = :active, updated_by = :by WHERE id = :id AND deleted_at IS NULL
        """), {"active": active, "by": by, "id": user_id})

    def unlock(self, by, user_id):
        self.session.execute(text("""
            UPDATE users SET failed_attempts = 0, locked_until = NULL, updated_by = :by
            WHERE id = :id AND deleted_at IS NULL
        """), {"by": by, "id": user_id})

    def set_password(self, by, user_id, password_hash, must_change):
        self.session.execute(text("""
            UPDATE users SET password_hash = :hash, password_changed_at = NOW(), must_change_password = :must,
                             failed_attempts = 0, locked_until = NULL, updated_by = :by
            WHERE id = :id AND deleted_at IS NULL
        """), {"hash": password_hash, "must": must_change, "by": by, "id": user_id})

    def revoke_sessions(self, user_id, reason):
        return self.session.execute(text("""
            UPDATE refresh_tokens SET revoked_at = NOW(), revoked_reason = :reason
            WHERE user_id = :id AND revoked_at IS NULL
        """), {"reason": reason, "id": user_id}).rowcount

    def delete(self, by, user_id):
        # The DB revokes the user's refresh tokens on soft delete
        self.session.execute(text("""
            UPDATE users SET deleted_at = NOW(), deleted_by = :by, updated_by = :by WHERE id = :id AND deleted_at IS NULL
        """), {"by": by, "id": user_id})

    def restore(self, by, user_id):
        row = self._guarded("""
            UPDATE users SET deleted_at = NULL, deleted_by = NULL, updated_by = :by
            WHERE id = :id AND deleted_at IS NOT NULL RETURNING id
        """, by=by, id=user_id)
        return row and self.get(user_id)

    def sessions(self, user_id):
        return self._all("""
            SELECT DISTINCT ON (family_id) family_id, user_agent, ip_address, session_started_at, expires_at, created_at AS last_used_at
            FROM refresh_tokens
            WHERE user_id = :id AND revoked_at IS NULL AND expires_at > NOW()
            ORDER BY family_id, created_at DESC
        """, id=user_id)

    def login_history(self, user_id, limit, offset):
        return self._all("""
            SELECT created_at, event_type, ip_address, user_agent FROM login_audit
            WHERE user_id = :id ORDER BY created_at DESC, id DESC LIMIT :limit OFFSET :offset
        """, id=user_id, limit=limit, offset=offset)

    def history(self, user_id, limit, offset):
        return self._all("""
            SELECT a.changed_at, a.action, u.email AS changed_by_email, a.changed_fields, a.old_data, a.new_data
            FROM users_audit a LEFT JOIN users u ON u.id = a.changed_by
            WHERE a.user_id = :id ORDER BY a.changed_at DESC, a.id DESC LIMIT :limit OFFSET :offset
        """, id=user_id, limit=limit, offset=offset)

    def commit(self):
        self.session.commit()
