import uuid
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy import text

from app.application.errors import Forbidden, Invalid
from app.infrastructure.api.auth import current_user_id
from app.infrastructure.persistence.database import SessionLocal
from app.infrastructure.persistence.permissions import has_permission


def require_permission(module: str, permission: str):
    """Dependency: the caller must hold <module>.<permission>. Returns the caller's id."""
    def check(uid: Annotated[uuid.UUID, Depends(current_user_id)]) -> uuid.UUID:
        with SessionLocal() as session:
            if not has_permission(session, uid, module, permission):
                raise Forbidden(f"missing permission {module}.{permission}")
        return uid
    return Annotated[uuid.UUID, Depends(check)]


def current_branch(
    uid: Annotated[uuid.UUID, Depends(current_user_id)],
    x_branch_id: Annotated[uuid.UUID | None, Header()] = None,
) -> uuid.UUID:
    """The working branch for branch-scoped endpoints, from the X-Branch-Id header.

    Never trusted as sent: the user must belong to it right now (active membership, branch and user not deleted).
    Use it as `branch: CurrentBranch` and filter every branch-scoped query by it.
    """
    if x_branch_id is None:
        raise Invalid("X-Branch-Id header is required")
    with SessionLocal() as session:
        if not session.execute(text("SELECT fn_user_in_branch(:u, :b)"), {"u": uid, "b": x_branch_id}).scalar():
            raise Forbidden("you don't belong to that branch")
    return x_branch_id


CurrentBranch = Annotated[uuid.UUID, Depends(current_branch)]


def optional_branch(
    uid: Annotated[uuid.UUID, Depends(current_user_id)],
    x_branch_id: Annotated[uuid.UUID | None, Header()] = None,
) -> uuid.UUID | None:
    """For global endpoints that add branch data (e.g. stock) when a working branch is sent; validated the same way."""
    return None if x_branch_id is None else current_branch(uid, x_branch_id)


OptionalBranch = Annotated[uuid.UUID | None, Depends(optional_branch)]
