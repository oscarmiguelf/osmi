import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, StringConstraints

from app.application.access_service import AccessService
from app.infrastructure.api.permissions import require_permission
from app.infrastructure.persistence.access_repository import SqlAccessRepository
from app.infrastructure.persistence.database import SessionLocal

router = APIRouter(tags=["access"])

Code = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,49}$")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Description = Annotated[str, StringConstraints(max_length=255)]
Route = Annotated[str, StringConstraints(max_length=255)]
Icon = Annotated[str, StringConstraints(max_length=50)]


class ModuleIn(BaseModel):
    code: Code
    name: Name
    description: Description | None = None
    route: Route | None = None
    icon: Icon | None = None
    sort_order: int = 0
    with_crud_permissions: bool = False


# PATCH models: a non-optional type with default None means the field can be omitted but not sent as null.
class ModulePatch(BaseModel):
    name: Name = None
    description: Description | None = None
    route: Route | None = None
    icon: Icon | None = None
    sort_order: int = None
    is_active: bool = None


class PermissionIn(BaseModel):
    code: Code
    name: Name
    description: Description | None = None


class PermissionPatch(BaseModel):
    name: Name = None
    description: Description | None = None


class ModuleGrant(BaseModel):
    module_id: uuid.UUID
    permission_ids: list[uuid.UUID] = []


class AccessIn(BaseModel):
    modules: list[ModuleGrant]


def get_service():
    with SessionLocal() as session:
        yield AccessService(SqlAccessRepository(session))


Svc = Annotated[AccessService, Depends(get_service)]


Read, Create, Update, Delete = (require_permission("users", p) for p in ("read", "create", "update", "delete"))


@router.get("/modules")
def list_modules(_: Read, svc: Svc, include_inactive: bool = False, include_deleted: bool = False):
    return svc.list_modules(include_inactive, include_deleted)


@router.post("/modules", status_code=201)
def create_module(body: ModuleIn, _: Create, svc: Svc):
    return svc.create_module(body.model_dump(exclude={"with_crud_permissions"}), body.with_crud_permissions)


@router.get("/modules/{module_id}")
def get_module(module_id: uuid.UUID, _: Read, svc: Svc):
    return svc.get_module(module_id)


@router.patch("/modules/{module_id}")
def update_module(module_id: uuid.UUID, body: ModulePatch, _: Update, svc: Svc):
    return svc.update_module(module_id, body.model_dump(exclude_unset=True))


@router.delete("/modules/{module_id}", status_code=204)
def delete_module(module_id: uuid.UUID, uid: Delete, svc: Svc):
    svc.delete_module(uid, module_id)


@router.post("/modules/{module_id}/restore")
def restore_module(module_id: uuid.UUID, _: Update, svc: Svc):
    return svc.restore_module(module_id)


@router.get("/modules/{module_id}/permissions")
def list_permissions(module_id: uuid.UUID, _: Read, svc: Svc, include_deleted: bool = False):
    return svc.list_permissions(module_id, include_deleted)


@router.post("/modules/{module_id}/permissions", status_code=201)
def create_permission(module_id: uuid.UUID, body: PermissionIn, _: Create, svc: Svc):
    return svc.create_permission(module_id, body.model_dump())


@router.patch("/permissions/{permission_id}")
def update_permission(permission_id: uuid.UUID, body: PermissionPatch, _: Update, svc: Svc):
    return svc.update_permission(permission_id, body.model_dump(exclude_unset=True))


@router.delete("/permissions/{permission_id}", status_code=204)
def delete_permission(permission_id: uuid.UUID, uid: Delete, svc: Svc):
    svc.delete_permission(uid, permission_id)


@router.post("/permissions/{permission_id}/restore")
def restore_permission(permission_id: uuid.UUID, _: Update, svc: Svc):
    return svc.restore_permission(permission_id)


@router.get("/users/{user_id}/access")
def get_access(user_id: uuid.UUID, _: Read, svc: Svc):
    return svc.get_access(user_id)


@router.put("/users/{user_id}/modules")
def set_access(user_id: uuid.UUID, body: AccessIn, uid: Update, svc: Svc):
    return svc.set_access(uid, user_id, [(g.module_id, g.permission_ids) for g in body.modules])
