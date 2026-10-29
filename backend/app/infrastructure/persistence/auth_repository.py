from sqlalchemy import text
from sqlalchemy.orm import Session

LOGIN_PAYLOAD_SQL = """
SELECT JSON_BUILD_OBJECT(
    'business_type', COALESCE((SELECT value FROM settings WHERE key = 'business_type'), 'retail'),
    'reminder_template', COALESCE((SELECT value FROM settings WHERE key = 'reminder_template'), ''),
    'logo', COALESCE((SELECT value FROM settings WHERE key = 'logo_file'), ''),
    'user', JSON_BUILD_OBJECT(
        'id', u.id, 'name', u.first_name || ' ' || u.last_name,
        'first_name', u.first_name, 'last_name', u.last_name,
        'email', u.email, 'timezone', u.timezone, 'must_change_password', u.must_change_password),
    'branches', COALESCE((
        SELECT JSON_AGG(JSON_BUILD_OBJECT(
                   'id', b.id, 'name', b.name, 'phone', b.phone, 'address', b.address) ORDER BY b.name)
        FROM user_branches ub
        JOIN branches b ON b.id = ub.branch_id AND b.deleted_at IS NULL
        WHERE ub.user_id = u.id AND ub.deleted_at IS NULL), '[]'::JSON),
    'modules', COALESCE((
        SELECT JSON_AGG(JSON_BUILD_OBJECT(
                   'code', m.code, 'name', m.name, 'route', m.route, 'icon', m.icon,
                   'permissions', COALESCE((
                       SELECT JSON_AGG(p.code ORDER BY p.code)
                       FROM user_module_permissions ump
                       JOIN permissions p ON p.id = ump.permission_id AND p.deleted_at IS NULL
                       WHERE ump.user_id = um.user_id AND ump.module_id = um.module_id), '[]'::JSON)
               ) ORDER BY m.sort_order)
        FROM user_modules um
        JOIN modules m ON m.id = um.module_id AND m.is_active AND m.deleted_at IS NULL
        WHERE um.user_id = u.id), '[]'::JSON)
) AS login_payload
FROM users u
WHERE u.id = CAST(:user_id AS uuid) AND u.deleted_at IS NULL AND u.is_active
"""


class SqlAuthRepository:
    def __init__(self, session: Session):
        self.session = session

    def _one(self, sql: str, **params) -> dict | None:
        row = self.session.execute(text(sql), params).mappings().first()
        return dict(row) if row else None

    def find_user_by_email(self, email):
        return self._one("""
            SELECT id, password_hash, is_active, COALESCE(locked_until > NOW(), FALSE) AS locked
            FROM users WHERE LOWER(email) = LOWER(:email) AND deleted_at IS NULL
        """, email=email)

    def _auth_event(self):
        # Login bookkeeping isn't an admin change: users_audit skips updates made under this flag
        self.session.execute(text("SELECT set_config('app.auth_event', 'on', TRUE)"))

    def register_failure(self, user_id, max_attempts, lock_minutes):
        self._auth_event()
        return self._one("""
            UPDATE users SET
                failed_attempts = failed_attempts + 1,
                locked_until = CASE WHEN failed_attempts + 1 >= :max
                                    THEN NOW() + make_interval(mins => :mins) ELSE locked_until END
            WHERE id = :id
            RETURNING failed_attempts >= :max AS locked
        """, id=user_id, max=max_attempts, mins=lock_minutes)["locked"]

    def register_success(self, user_id):
        self._auth_event()
        self.session.execute(text("""
            UPDATE users SET failed_attempts = 0, locked_until = NULL, last_login_at = NOW() WHERE id = :id
        """), {"id": user_id})

    def create_refresh_token(self, user_id, family_id, token_hash, session_started_at,
                             idle_days, max_days, ip, user_agent):
        # expires_at = idle expiry capped by the absolute session limit, so one check covers both.
        return self._one("""
            INSERT INTO refresh_tokens
                (user_id, family_id, token_hash, session_started_at, expires_at, user_agent, ip_address)
            SELECT :user_id, :family_id, :token_hash, s.started,
                   LEAST(NOW() + make_interval(days => :idle), s.started + make_interval(days => :max)),
                   :ua, CAST(:ip AS inet)
            FROM (SELECT COALESCE(CAST(:started AS timestamptz), NOW()) AS started) s
            RETURNING id
        """, user_id=user_id, family_id=family_id, token_hash=token_hash, started=session_started_at,
            idle=idle_days, max=max_days, ua=user_agent, ip=ip)["id"]

    def lock_refresh_token(self, token_hash):
        return self._one("""
            SELECT rt.id, rt.user_id, rt.family_id, rt.session_started_at,
                   rt.revoked_at IS NOT NULL AS revoked, rt.revoked_reason,
                   rt.expires_at <= NOW() AS expired,
                   (u.is_active AND u.deleted_at IS NULL) AS user_ok, u.email
            FROM refresh_tokens rt JOIN users u ON u.id = rt.user_id
            WHERE rt.token_hash = :token_hash
            FOR UPDATE OF rt
        """, token_hash=token_hash)

    def revoke_token(self, token_id, reason, replaced_by=None):
        self.session.execute(text("""
            UPDATE refresh_tokens SET revoked_at = NOW(), revoked_reason = :reason, replaced_by_id = :replaced_by
            WHERE id = :id
        """), {"id": token_id, "reason": reason, "replaced_by": replaced_by})

    def revoke_family(self, family_id, reason):
        self.session.execute(text("""
            UPDATE refresh_tokens SET revoked_at = NOW(), revoked_reason = :reason
            WHERE family_id = :family_id AND revoked_at IS NULL
        """), {"family_id": family_id, "reason": reason})

    def recent_ip_failures(self, ip, minutes):
        return self.session.execute(text("""
            SELECT COUNT(*) FROM login_audit
            WHERE ip_address = CAST(:ip AS inet) AND event_type IN ('login_failed', 'account_locked')
              AND created_at > NOW() - make_interval(mins => :mins)
        """), {"ip": ip, "mins": minutes}).scalar()

    def audit(self, user_id, email, event, ip, user_agent):
        self.session.execute(text("""
            INSERT INTO login_audit (user_id, email_attempted, event_type, ip_address, user_agent)
            VALUES (:user_id, :email, :event, CAST(:ip AS inet), :ua)
        """), {"user_id": user_id, "email": email, "event": event, "ip": ip, "ua": user_agent})

    def login_payload(self, user_id):
        return self.session.execute(text(LOGIN_PAYLOAD_SQL), {"user_id": user_id}).scalar()

    def commit(self):
        self.session.commit()
