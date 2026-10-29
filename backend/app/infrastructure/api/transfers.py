import uuid
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime, BaseModel, Field

from app.application.transfer_service import TransferService
from app.infrastructure.api.fields import optional_text
from app.infrastructure.api.permissions import CurrentBranch, require_permission
from app.infrastructure.persistence.database import SessionLocal
from app.infrastructure.persistence.transfer_repository import SqlTransferRepository

router = APIRouter(tags=["transfers"])


class ItemIn(BaseModel):
    product_id: uuid.UUID
    quantity: Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=3)]


class TransferIn(BaseModel):
    to_branch_id: uuid.UUID
    notes: optional_text(1000) = None
    items: list[ItemIn]


def get_service():
    with SessionLocal() as session:
        yield TransferService(SqlTransferRepository(session))


Svc = Annotated[TransferService, Depends(get_service)]
# transfers.delete is unused: transfers are never deleted, they are cancelled
Read, Create, Update = (require_permission("transfers", p) for p in ("read", "create", "update"))


@router.get("/transfers")
def list_transfers(_: Read, branch: CurrentBranch, svc: Svc,
                   direction: Literal["outgoing", "incoming", "all"] = "all",
                   status: Literal["IN_TRANSIT", "RECEIVED", "CANCELLED"] | None = None,
                   from_: Annotated[AwareDatetime | None, Query(alias="from")] = None, to: AwareDatetime | None = None,
                   page: Annotated[int, Query(ge=1)] = 1, page_size: Annotated[int, Query(ge=1, le=100)] = 25):
    filters = {"direction": None if direction == "all" else direction, "status": status, "from": from_, "to": to}
    return svc.search(branch, filters, page, page_size)


@router.get("/transfers/in-transit")
def incoming_in_transit(_: Read, branch: CurrentBranch, svc: Svc):
    return svc.in_transit(branch)


@router.get("/transfers/available-products")
def available_products(_: Read, branch: CurrentBranch, svc: Svc, q: Annotated[str, Query(max_length=100)] = "",
                       limit: Annotated[int, Query(ge=1, le=100)] = 25):
    return svc.available_products(branch, q.strip(), limit)


@router.post("/transfers", status_code=201)
def send_transfer(body: TransferIn, uid: Create, branch: CurrentBranch, svc: Svc):
    return svc.send(uid, branch, body.to_branch_id, body.notes, [i.model_dump() for i in body.items])


@router.get("/transfers/{transfer_id}")
def get_transfer(transfer_id: uuid.UUID, _: Read, branch: CurrentBranch, svc: Svc):
    return svc.get(branch, transfer_id)


@router.get("/transfers/{transfer_id}/history")
def transfer_history(transfer_id: uuid.UUID, _: Read, branch: CurrentBranch, svc: Svc):
    return svc.get(branch, transfer_id)["history"]


@router.post("/transfers/{transfer_id}/receive")
def receive_transfer(transfer_id: uuid.UUID, uid: Update, branch: CurrentBranch, svc: Svc):
    return svc.receive(uid, branch, transfer_id)


@router.post("/transfers/{transfer_id}/cancel")
def cancel_transfer(transfer_id: uuid.UUID, uid: Update, branch: CurrentBranch, svc: Svc):
    return svc.cancel(uid, branch, transfer_id)
