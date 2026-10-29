import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, BeforeValidator, StringConstraints

from app.application.branch_service import BranchService
from app.infrastructure.api.auth import current_user_id
from app.infrastructure.api.fields import OptionalPhone, optional_text
from app.infrastructure.api.permissions import require_permission
from app.infrastructure.persistence.branch_repository import SqlBranchRepository
from app.infrastructure.persistence.database import SessionLocal

router = APIRouter(tags=["branches"])


def _upper(value):
    return value.strip().upper() if isinstance(value, str) else value


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
Code = Annotated[str, BeforeValidator(_upper), StringConstraints(pattern=r"^[A-Z0-9]{1,10}$")]
Address = optional_text(500)


class BranchIn(BaseModel):
    name: Name
    code: Code
    phone: OptionalPhone = None
    address: Address = None


# PATCH: a non-optional type with default None means the field can be omitted but not sent as null.
class BranchPatch(BaseModel):
    name: Name = None
    code: Code = None
    phone: OptionalPhone = None
    address: Address = None


class MemberIn(BaseModel):
    user_id: uuid.UUID


class UserBranchesIn(BaseModel):
    branch_ids: list[uuid.UUID]


def get_service():
    with SessionLocal() as session:
        yield BranchService(SqlBranchRepository(session))


Svc = Annotated[BranchService, Depends(get_service)]
Uid = Annotated[uuid.UUID, Depends(current_user_id)]
Read, Create, Update, Delete = (require_permission("branches", p) for p in ("read", "create", "update", "delete"))


@router.get("/branches")
def list_branches(uid: Uid, svc: Svc, include_deleted: bool = False):
    return svc.list_branches(uid, include_deleted)


@router.post("/branches", status_code=201)
def create_branch(body: BranchIn, uid: Create, svc: Svc):
    return svc.create(uid, body.model_dump())


@router.get("/branches/{branch_id}")
def get_branch(branch_id: uuid.UUID, _: Read, svc: Svc):
    return svc.get(branch_id)


@router.patch("/branches/{branch_id}")
def update_branch(branch_id: uuid.UUID, body: BranchPatch, uid: Update, svc: Svc):
    return svc.update(uid, branch_id, body.model_dump(exclude_unset=True))


@router.delete("/branches/{branch_id}", status_code=204)
def delete_branch(branch_id: uuid.UUID, uid: Delete, svc: Svc):
    svc.delete(uid, branch_id)


@router.post("/branches/{branch_id}/restore")
def restore_branch(branch_id: uuid.UUID, uid: Delete, svc: Svc):
    return svc.restore(uid, branch_id)


@router.get("/branches/{branch_id}/history")
def branch_history(branch_id: uuid.UUID, _: Read, svc: Svc,
                   page: Annotated[int, Query(ge=1)] = 1, page_size: Annotated[int, Query(ge=1, le=100)] = 25):
    return svc.history(branch_id, page, page_size)


@router.get("/branches/{branch_id}/users")
def branch_members(branch_id: uuid.UUID, _: Read, svc: Svc):
    return svc.members(branch_id)


@router.post("/branches/{branch_id}/users", status_code=204)
def add_branch_member(branch_id: uuid.UUID, body: MemberIn, uid: Update, svc: Svc):
    svc.add_member(uid, branch_id, body.user_id)


@router.delete("/branches/{branch_id}/users/{user_id}", status_code=204)
def remove_branch_member(branch_id: uuid.UUID, user_id: uuid.UUID, uid: Update, svc: Svc):
    svc.remove_member(uid, branch_id, user_id)


@router.get("/users/{user_id}/branches")
def user_branches(user_id: uuid.UUID, _: Read, svc: Svc):
    return svc.branches_of(user_id)


@router.put("/users/{user_id}/branches")
def set_user_branches(user_id: uuid.UUID, body: UserBranchesIn, uid: Update, svc: Svc):
    return svc.set_branches(uid, user_id, body.branch_ids)
