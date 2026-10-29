import threading
import time
import uuid
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.application.auth_service import REFRESH_MAX_DAYS, AuthError, AuthService
from app.application.security import decode_access_token
from app.infrastructure.persistence.auth_repository import SqlAuthRepository
from app.infrastructure.persistence.database import SessionLocal

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE = "refresh_token"
COOKIE_PATH = "/auth"  # refresh + logout both need it


class RateLimiter:
    # shortcut: in-memory per process, wrong with several workers/replicas; move to Redis when scaling out.
    def __init__(self, limit: int, window_seconds: int):
        self.limit, self.window = limit, window_seconds
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def hit(self, key: str | None) -> None:
        now = time.monotonic()
        with self.lock:
            q = self.hits[key or "?"]
            while q and q[0] <= now - self.window:
                q.popleft()
            if len(q) >= self.limit:
                raise HTTPException(429, "too many requests")
            q.append(now)


login_ip_limit = RateLimiter(20, 60)
login_email_limit = RateLimiter(10, 60)
refresh_ip_limit = RateLimiter(60, 60)


class LoginIn(BaseModel):
    email: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=1024)


class RefreshIn(BaseModel):
    refresh_token: str | None = Field(default=None, max_length=256)


def get_service():
    with SessionLocal() as session:
        yield AuthService(SqlAuthRepository(session))


bearer = HTTPBearer(auto_error=False)


def current_user_id(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> uuid.UUID:
    user_id = creds and decode_access_token(creds.credentials)
    if not user_id:
        raise AuthError()
    return user_id


def _client(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    return ip, request.headers.get("user-agent", "")[:500] or None


def _deliver(result: dict, response: Response, as_cookie: bool) -> dict:
    # Web gets the refresh token only as an HttpOnly cookie; mobile/desktop get it in the body.
    if as_cookie:
        response.set_cookie(COOKIE, result.pop("refresh_token"), max_age=REFRESH_MAX_DAYS * 86400,
                            path=COOKIE_PATH, httponly=True, secure=True, samesite="strict")
    return result


def _presented_token(request: Request, body: RefreshIn | None) -> str | None:
    return request.cookies.get(COOKIE) or (body and body.refresh_token)


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, service: AuthService = Depends(get_service)):
    ip, ua = _client(request)
    login_ip_limit.hit(ip)
    login_email_limit.hit(body.email.lower())
    result = service.login(body.email, body.password, ip, ua)
    return _deliver(result, response, as_cookie=request.headers.get("x-client") != "mobile")


@router.post("/refresh")
def refresh(request: Request, response: Response, body: RefreshIn | None = None,
            service: AuthService = Depends(get_service)):
    ip, ua = _client(request)
    refresh_ip_limit.hit(ip)
    token = _presented_token(request, body)
    if not token:
        raise AuthError()
    result = service.refresh(token, ip, ua)
    return _deliver(result, response, as_cookie=COOKIE in request.cookies)


@router.post("/logout", status_code=204)
def logout(request: Request, body: RefreshIn | None = None, service: AuthService = Depends(get_service)):
    token = _presented_token(request, body)
    if token:
        service.logout(token, *_client(request))
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, path=COOKIE_PATH, httponly=True, secure=True, samesite="strict")
    return response


@router.get("/me")
def me(user_id: uuid.UUID = Depends(current_user_id), service: AuthService = Depends(get_service)):
    return service.me(user_id)
