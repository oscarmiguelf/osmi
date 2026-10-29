import uuid
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query
from pydantic import AwareDatetime, BaseModel, Field

from app.application.quote_service import QuoteService
from app.application.sale_service import SaleService
from app.infrastructure.api import sales
from app.infrastructure.api.fields import optional_text
from app.infrastructure.api.permissions import CurrentBranch, require_permission
from app.infrastructure.persistence.database import SessionLocal
from app.infrastructure.persistence.quote_repository import SqlQuoteRepository

router = APIRouter(tags=["quotes"])


class QuoteItemIn(BaseModel):
    product_id: uuid.UUID
    quantity: sales.Quantity
    unit_price: sales.Money | None = None  # omitted: the catalog price; it can't differ
    discount: sales.Money = Decimal(0)


class QuoteIn(BaseModel):
    customer_id: uuid.UUID | None = None
    customer_name: optional_text(200) = None  # a prospect without a customer record
    valid_until: AwareDatetime | None = None
    valid_days: Annotated[int, Field(ge=1, le=365)] | None = None  # end of that day in the person's time zone; default 15
    discount: sales.Money = Decimal(0)
    notes: optional_text(2000) = None
    items: Annotated[list[QuoteItemIn], Field(max_length=500)]


def get_service():
    with SessionLocal() as session:
        yield QuoteService(SqlQuoteRepository(session))


Svc = Annotated[QuoteService, Depends(get_service)]
Sales = Annotated[SaleService, Depends(sales.get_service)]
Read, Create, Update = (require_permission("quotes", p) for p in ("read", "create", "update"))
SellFromQuote = require_permission("sales", "create")
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


@router.post("/quotes/preview")
def preview_quote(body: QuoteIn, uid: Create, branch: CurrentBranch, svc: Svc):
    return svc.preview(uid, branch, body.model_dump())


@router.post("/quotes", status_code=201)
def create_quote(body: QuoteIn, uid: Create, branch: CurrentBranch, svc: Svc):
    return svc.create(uid, branch, body.model_dump())


@router.get("/quotes")
def list_quotes(_: Read, branch: CurrentBranch, svc: Svc, from_: sales.From = None, to: AwareDatetime | None = None,
                status: Literal["OPEN", "EXPIRED", "CONVERTED", "CANCELLED"] | None = None,
                customer_id: uuid.UUID | None = None, q: Annotated[str, Query(max_length=100)] = "",
                page: Page = 1, page_size: PageSize = 25):
    filters = {"from": from_, "to": to, "status": status, "customer_id": customer_id, "q": q.strip()}
    return svc.search(branch, filters, page, page_size)


@router.get("/quotes/by-folio/{folio}")
def quote_by_folio(folio: Annotated[str, Path(max_length=30)], _: Read, branch: CurrentBranch, svc: Svc):
    return svc.by_folio(branch, folio.strip())


@router.get("/quotes/{quote_id}")
def get_quote(quote_id: uuid.UUID, _: Read, branch: CurrentBranch, svc: Svc):
    return svc.get(branch, quote_id)


@router.get("/quotes/{quote_id}/print")
def print_quote(quote_id: uuid.UUID, _: Read, branch: CurrentBranch, svc: Svc):
    """Printable data: the detail carries branch, customer, validity, items, totals, notes and informational tax."""
    return svc.get(branch, quote_id)


@router.post("/quotes/{quote_id}/cancel")
def cancel_quote(quote_id: uuid.UUID, uid: Update, branch: CurrentBranch, svc: Svc):
    return svc.cancel(uid, branch, quote_id)


@router.get("/quotes/{quote_id}/history")
def quote_history(quote_id: uuid.UUID, _: Read, branch: CurrentBranch, svc: Svc):
    return svc.history(branch, quote_id)


@router.post("/quotes/{quote_id}/duplicate")
def duplicate_quote(quote_id: uuid.UUID, _: Create, branch: CurrentBranch, svc: Svc):
    return svc.duplicate(branch, quote_id)


@router.get("/quotes/{quote_id}/convert-draft")
def convert_draft(quote_id: uuid.UUID, _: Read, __: SellFromQuote, branch: CurrentBranch, svc: Svc):
    return svc.convert_draft(branch, quote_id)


@router.post("/quotes/{quote_id}/convert", status_code=201)
def convert_quote(quote_id: uuid.UUID, body: sales.SaleIn, _: Read, uid: SellFromQuote, branch: CurrentBranch,
                  svc: Svc, sale_svc: Sales):
    """A normal sale with quote_id: same checks (register, stock, totals, payments); the DB marks the quote CONVERTED."""
    sale = sale_svc.create(uid, branch, {**body.model_dump(), "quote_id": quote_id})
    return {"sale": sale, "quote": svc.get(branch, quote_id)}
