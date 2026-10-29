import uuid
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query
from pydantic import AwareDatetime, BaseModel, Field

from app.application.sale_service import SaleService
from app.infrastructure.api.fields import optional_text
from app.infrastructure.api.permissions import CurrentBranch, require_permission
from app.infrastructure.persistence.database import SessionLocal
from app.infrastructure.persistence.sale_repository import SqlSaleRepository

router = APIRouter(tags=["sales"])

Money = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]
Amount = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]
Quantity = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=3)]


class ItemIn(BaseModel):
    product_id: uuid.UUID
    quantity: Quantity
    unit_price: Money | None = None  # omitted: the product's price; it can't differ (except the quoted price on a conversion)
    discount: Money = Decimal(0)  # money off the whole line (not with a promotion)
    promotion_id: uuid.UUID | None = None  # the discount is then calculated
    fulfillment: Literal["DELIVERED", "RESERVED"] = "DELIVERED"
    benefit_id: uuid.UUID | None = None  # use sessions of the customer's package: the line is charged at $0


class PaymentIn(BaseModel):
    payment_method_id: uuid.UUID
    amount: Amount
    amount_tendered: Money | None = None  # what the customer handed over (cash); the change is tendered - amount
    reference: optional_text(100) = None  # card authorization, transfer reference


class SaleIn(BaseModel):
    id: uuid.UUID | None = None  # send one to make retries safe: the same id returns the sale already saved
    customer_id: uuid.UUID | None = None
    appointment_id: uuid.UUID | None = None  # charging an appointment: the sale is linked to it and it becomes attended
    quote_id: uuid.UUID | None = None  # preview of a conversion: honors the quoted prices (converting is /quotes/{id}/convert)
    discount: Money = Decimal(0)  # extra discount on the whole sale
    items: Annotated[list[ItemIn], Field(max_length=500)]
    payments: Annotated[list[PaymentIn], Field(max_length=20)] = []


class DeliverIn(BaseModel):
    sale_item_ids: Annotated[list[uuid.UUID], Field(min_length=1)]


class AbonoIn(BaseModel):
    payment_method_id: uuid.UUID
    amount: Amount
    amount_tendered: Money | None = None
    reference: optional_text(100) = None


class AbonosIn(BaseModel):
    payments: Annotated[list[AbonoIn], Field(min_length=1, max_length=5)]


class CustomerAbonoIn(AbonoIn):
    customer_id: uuid.UUID


class ReturnItemIn(BaseModel):
    sale_item_id: uuid.UUID
    quantity: Quantity


class RefundIn(BaseModel):
    payment_method_id: uuid.UUID
    amount: Amount
    reference: optional_text(100) = None


class ReturnPreviewIn(BaseModel):
    items: Annotated[list[ReturnItemIn], Field(max_length=500)]


class ReturnIn(ReturnPreviewIn):
    refunds: Annotated[list[RefundIn], Field(max_length=20)] = []  # the credit part is added for you when missing
    reason: optional_text(500) = None


def get_service():
    with SessionLocal() as session:
        yield SaleService(SqlSaleRepository(session))


Svc = Annotated[SaleService, Depends(get_service)]
# deliver + abonos = update; returns = delete (money and stock go back)
Read, Create, Update, Refund = (require_permission("sales", p) for p in ("read", "create", "update", "delete"))
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]
From = Annotated[AwareDatetime | None, Query(alias="from")]


# Fixed paths first: /sales/{sale_id} would take them as ids
@router.post("/sales/preview")
def preview_sale(body: SaleIn, uid: Create, branch: CurrentBranch, svc: Svc):
    return svc.preview(uid, branch, body.model_dump())


@router.post("/sales", status_code=201)
def create_sale(body: SaleIn, uid: Create, branch: CurrentBranch, svc: Svc):
    return svc.create(uid, branch, body.model_dump(exclude={"quote_id"}))  # converting a quote has its own endpoint


@router.get("/sales")
def list_sales(_: Read, branch: CurrentBranch, svc: Svc, from_: From = None, to: AwareDatetime | None = None,
               status: Literal["PAID", "PENDING", "RETURNED"] | None = None, customer_id: uuid.UUID | None = None,
               seller_id: uuid.UUID | None = None, register_id: uuid.UUID | None = None,
               q: Annotated[str, Query(max_length=30)] = "", page: Page = 1, page_size: PageSize = 25):
    filters = {"from": from_, "to": to, "status": status, "customer_id": customer_id, "seller_id": seller_id,
               "register_id": register_id, "q": q.strip()}
    return svc.search(branch, filters, page, page_size)


@router.get("/sales/pending-credit")
def pending_credit(_: Read, branch: CurrentBranch, svc: Svc, customer_id: uuid.UUID | None = None):
    return svc.credit_pending(branch, customer_id)


@router.get("/sales/pending-deliveries")
def pending_deliveries(_: Read, branch: CurrentBranch, svc: Svc):
    return svc.pending_deliveries(branch)


@router.get("/sales/report")
def sales_report(_: Read, branch: CurrentBranch, svc: Svc, from_: Annotated[AwareDatetime, Query(alias="from")],
                 to: AwareDatetime):
    return svc.report(branch, from_, to)


@router.post("/sales/credit-payments", status_code=201)
def customer_abono(body: CustomerAbonoIn, uid: Update, branch: CurrentBranch, svc: Svc):
    """A customer pays part of their debt in this branch: spread over their sales, oldest first."""
    return svc.customer_abono(uid, branch, body.customer_id, body.model_dump(exclude={"customer_id"}))


@router.get("/sales/by-folio/{folio}")
def sale_by_folio(folio: Annotated[str, Path(max_length=30)], _: Read, branch: CurrentBranch, svc: Svc):
    return svc.by_folio(branch, folio.strip())


@router.get("/sales/{sale_id}")
def get_sale(sale_id: uuid.UUID, _: Read, branch: CurrentBranch, svc: Svc):
    return svc.get(branch, sale_id)


@router.get("/sales/{sale_id}/ticket")
def sale_ticket(sale_id: uuid.UUID, _: Read, branch: CurrentBranch, svc: Svc):
    """Printable data: the detail already carries the branch, items, tax breakdown, payments and change."""
    return svc.get(branch, sale_id)


@router.get("/sales/{sale_id}/history")
def sale_history(sale_id: uuid.UUID, _: Read, branch: CurrentBranch, svc: Svc):
    return svc.history(branch, sale_id)


@router.post("/sales/{sale_id}/deliver")
def deliver_items(sale_id: uuid.UUID, body: DeliverIn, uid: Update, branch: CurrentBranch, svc: Svc):
    return svc.deliver(uid, branch, sale_id, list(dict.fromkeys(body.sale_item_ids)))


@router.post("/sales/{sale_id}/payments/batch", status_code=201)
def add_abonos(sale_id: uuid.UUID, body: AbonosIn, uid: Update, branch: CurrentBranch, svc: Svc):
    """Several payments (methods) to one sale in one go, e.g. an event's deposit part cash, part card."""
    return svc.abonos(uid, branch, sale_id, [p.model_dump() for p in body.payments])


@router.post("/sales/{sale_id}/payments", status_code=201)
def add_abono(sale_id: uuid.UUID, body: AbonoIn, uid: Update, branch: CurrentBranch, svc: Svc):
    return svc.abono(uid, branch, sale_id, body.model_dump())


@router.get("/sales/{sale_id}/returnable")
def returnable(sale_id: uuid.UUID, _: Read, branch: CurrentBranch, svc: Svc):
    return svc.returnable(branch, sale_id)


@router.post("/sales/{sale_id}/returns/preview")
def preview_return(sale_id: uuid.UUID, body: ReturnPreviewIn, _: Refund, branch: CurrentBranch, svc: Svc):
    return svc.preview_return(branch, sale_id, [i.model_dump() for i in body.items])


@router.post("/sales/{sale_id}/returns", status_code=201)
def create_return(sale_id: uuid.UUID, body: ReturnIn, uid: Refund, branch: CurrentBranch, svc: Svc):
    return svc.create_return(uid, branch, sale_id, body.model_dump())


@router.get("/returns")
def list_returns(_: Read, branch: CurrentBranch, svc: Svc, from_: From = None, to: AwareDatetime | None = None,
                 page: Page = 1, page_size: PageSize = 25):
    return svc.returns(branch, {"from": from_, "to": to}, page, page_size)


@router.get("/returns/{return_id}")
def get_return(return_id: uuid.UUID, _: Read, branch: CurrentBranch, svc: Svc):
    return svc.get_return(branch, return_id)


@router.get("/promotions/active")
def active_promotions(_: Read, branch: CurrentBranch, svc: Svc):
    return svc.active_promotions(branch)
