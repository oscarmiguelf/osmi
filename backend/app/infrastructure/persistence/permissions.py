from sqlalchemy import text
from sqlalchemy.orm import Session


def is_super_admin(session: Session, user_id) -> bool:
    """The seed user 'admin' bypasses the "only grant what you hold" rules (it holds everything anyway)."""
    return bool(session.execute(text(
        "SELECT LOWER(email) = 'admin' FROM users WHERE id = :uid AND deleted_at IS NULL AND is_active"
    ), {"uid": user_id}).scalar())


def has_permission(session: Session, user_id, module: str, permission: str) -> bool:
    """Does the user hold <module>.<permission>? Always read from the DB, so revoked access applies at once,
    and so does deactivating or deleting the user (their access token may still have up to 15 minutes left)."""
    return session.execute(text("""
        SELECT EXISTS (
          SELECT 1 FROM user_module_permissions ump
          JOIN permissions p ON p.id = ump.permission_id AND p.deleted_at IS NULL
          JOIN modules m ON m.id = ump.module_id AND m.deleted_at IS NULL AND m.is_active
          JOIN users u ON u.id = ump.user_id AND u.is_active AND u.deleted_at IS NULL
          WHERE ump.user_id = :uid AND m.code = :module AND p.code = :perm)
    """), {"uid": user_id, "module": module, "perm": permission}).scalar()
