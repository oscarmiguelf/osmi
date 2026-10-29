import uuid

from app.application.errors import TooManyRequests
from app.application.ports.auth_repository import AuthRepository
from app.application.security import (
    ACCESS_TOKEN_TTL, DUMMY_HASH, create_access_token, hash_token, new_refresh_token, verify_password,
)

MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 15
# Per IP, over a longer window than the in-memory per-minute limit, and counted in the DB (survives restarts):
# a patient attacker can't keep spraying one password over many accounts
MAX_IP_FAILURES = 30
IP_WINDOW_MINUTES = 15
REFRESH_IDLE_DAYS = 7
REFRESH_MAX_DAYS = 30


class AuthError(Exception):
    """Generic auth failure. Always surfaces as 401 "invalid credentials" so accounts can't be enumerated."""


class AuthService:
    def __init__(self, repo: AuthRepository):
        self.repo = repo

    def login(self, email: str, password: str, ip: str | None, ua: str | None) -> dict:
        if ip and self.repo.recent_ip_failures(ip, IP_WINDOW_MINUTES) >= MAX_IP_FAILURES:
            raise TooManyRequests({"message": "too many failed sign-ins from this address", "retry_after_minutes": IP_WINDOW_MINUTES})
        user = self.repo.find_user_by_email(email)
        if user is None or user["locked"]:
            verify_password(password, DUMMY_HASH)
            self._fail(user and user["id"], email, "login_failed", ip, ua)
        if not verify_password(password, user["password_hash"]):
            locked = self.repo.register_failure(user["id"], MAX_FAILED_ATTEMPTS, LOCK_MINUTES)
            self._fail(user["id"], email, "account_locked" if locked else "login_failed", ip, ua)
        if not user["is_active"]:
            self._fail(user["id"], email, "login_failed", ip, ua)

        self.repo.register_success(user["id"])
        tokens, _ = self._issue(user["id"], uuid.uuid4(), None, ip, ua)
        self.repo.audit(user["id"], email, "login_success", ip, ua)
        payload = self.repo.login_payload(user["id"])
        self.repo.commit()
        return {**tokens, **payload}

    def refresh(self, refresh_token: str, ip: str | None, ua: str | None) -> dict:
        # Row stays locked (FOR UPDATE) until commit, so parallel refreshes of the same token serialize.
        row = self.repo.lock_refresh_token(hash_token(refresh_token))
        if row is None:
            raise AuthError()
        if row["revoked"] and row["revoked_reason"] == "rotated":
            self.repo.revoke_family(row["family_id"], "reuse_detected")
            self._fail(row["user_id"], row["email"], "token_reuse_detected", ip, ua)
        if row["revoked"] or row["expired"] or not row["user_ok"]:
            raise AuthError()

        tokens, new_id = self._issue(row["user_id"], row["family_id"], row["session_started_at"], ip, ua)
        self.repo.revoke_token(row["id"], "rotated", replaced_by=new_id)
        self.repo.audit(row["user_id"], row["email"], "token_refreshed", ip, ua)
        self.repo.commit()
        return tokens

    def logout(self, refresh_token: str, ip: str | None, ua: str | None) -> None:
        row = self.repo.lock_refresh_token(hash_token(refresh_token))
        if row is None:
            return
        self.repo.revoke_family(row["family_id"], "logout")
        self.repo.audit(row["user_id"], row["email"], "logout", ip, ua)
        self.repo.commit()

    def me(self, user_id: uuid.UUID) -> dict:
        payload = self.repo.login_payload(user_id)
        if payload is None:
            raise AuthError()
        return payload

    def _issue(self, user_id, family_id, session_started_at, ip, ua) -> tuple[dict, uuid.UUID]:
        token, token_hash = new_refresh_token()
        new_id = self.repo.create_refresh_token(user_id, family_id, token_hash, session_started_at,
                                                REFRESH_IDLE_DAYS, REFRESH_MAX_DAYS, ip, ua)
        tokens = {"access_token": create_access_token(user_id), "expires_in": ACCESS_TOKEN_TTL,
                  "refresh_token": token}
        return tokens, new_id

    def _fail(self, user_id, email, event, ip, ua):
        # Commit before raising so the audit row and failed_attempts survive the 401.
        self.repo.audit(user_id, email, event, ip, ua)
        self.repo.commit()
        raise AuthError()
