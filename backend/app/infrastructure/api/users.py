import re
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import AfterValidator, BaseModel, StringConstraints

from app.application.user_service import UserService
from app.infrastructure.api.auth import current_user_id
from app.infrastructure.api.permissions import require_permission
from app.infrastructure.persistence.database import SessionLocal
from app.infrastructure.persistence.user_repository import SqlUserRepository

router = APIRouter(tags=["users"])


def _email(value: str) -> str:
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
        raise ValueError("enter an email like name@domain.com")
    return value


# Format is checked for emails set through this API; the seed 'admin' login keeps working as it is.
Email = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, max_length=255), AfterValidator(_email)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Timezone = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
Password = Annotated[str, StringConstraints(max_length=128)]  # policy lives in one place: password_problems()


class UserIn(BaseModel):
    email: Email
    first_name: Name
    last_name: Name
    timezone: Timezone | None = None
    password: Password | None = None  # omitted: the API generates a temporary one and returns it once


# PATCH: a non-optional type with default None means the field can be omitted but not sent as null.
class UserPatch(BaseModel):
    email: Email = None
    first_name: Name = None
    last_name: Name = None
    timezone: Timezone = None


class ResetIn(BaseModel):
    password: Password | None = None


class MePatch(BaseModel):
    first_name: Name = None
    last_name: Name = None
    timezone: Timezone = None


class ChangePasswordIn(BaseModel):
    current_password: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    new_password: Password


def get_service():
    with SessionLocal() as session:
        yield UserService(SqlUserRepository(session))


Svc = Annotated[UserService, Depends(get_service)]
Me = Annotated[uuid.UUID, Depends(current_user_id)]
Read, Create, Update, Delete = (require_permission("users", p) for p in ("read", "create", "update", "delete"))
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


# --- me: your own profile and password, no users permission needed ---

@router.patch("/me")
def update_me(body: MePatch, uid: Me, svc: Svc):
    return svc.update_me(uid, body.model_dump(exclude_unset=True))


@router.post("/me/change-password", status_code=204)
def change_password(body: ChangePasswordIn, uid: Me, svc: Svc):
    svc.change_password(uid, body.current_password, body.new_password)


# --- administration ---

@router.get("/users")
def list_users(_: Read, svc: Svc, q: Annotated[str, Query(max_length=100)] = "",
               status: Literal["active", "inactive", "deleted", "all"] | None = None,
               branch_id: uuid.UUID | None = None, page: Page = 1, page_size: PageSize = 25):
    return svc.list(q, status, branch_id, page, page_size)


@router.post("/users", status_code=201)
def create_user(body: UserIn, uid: Create, svc: Svc):
    return svc.create(uid, body.model_dump(exclude={"password"}), body.password)


@router.get("/users/{user_id}")
def get_user(user_id: uuid.UUID, _: Read, svc: Svc):
    return svc.get(user_id)


@router.patch("/users/{user_id}")
def update_user(user_id: uuid.UUID, body: UserPatch, uid: Update, svc: Svc):
    return svc.update(uid, user_id, body.model_dump(exclude_unset=True))


@router.post("/users/{user_id}/activate")
def activate_user(user_id: uuid.UUID, uid: Update, svc: Svc):
    return svc.set_active(uid, user_id, True)


@router.post("/users/{user_id}/deactivate")
def deactivate_user(user_id: uuid.UUID, uid: Update, svc: Svc):
    return svc.set_active(uid, user_id, False)


@router.post("/users/{user_id}/unlock")
def unlock_user(user_id: uuid.UUID, uid: Update, svc: Svc):
    return svc.unlock(uid, user_id)


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: uuid.UUID, body: ResetIn, uid: Update, svc: Svc):
    return svc.reset_password(uid, user_id, body.password)


@router.post("/users/{user_id}/logout-all")
def logout_all(user_id: uuid.UUID, uid: Update, svc: Svc):
    return svc.logout_all(uid, user_id)


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: uuid.UUID, uid: Delete, svc: Svc):
    svc.delete(uid, user_id)


@router.post("/users/{user_id}/restore")
def restore_user(user_id: uuid.UUID, uid: Delete, svc: Svc):
    return svc.restore(uid, user_id)


@router.get("/users/{user_id}/sessions")
def user_sessions(user_id: uuid.UUID, _: Read, svc: Svc):
    return svc.sessions(user_id)


@router.get("/users/{user_id}/login-history")
def user_login_history(user_id: uuid.UUID, _: Read, svc: Svc, page: Page = 1, page_size: PageSize = 25):
    return svc.login_history(user_id, page, page_size)


@router.get("/users/{user_id}/history")
def user_history(user_id: uuid.UUID, _: Read, svc: Svc, page: Page = 1, page_size: PageSize = 25):
    return svc.history(user_id, page, page_size)
