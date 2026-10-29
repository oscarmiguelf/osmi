import csv
import io
import uuid
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import AwareDatetime, BaseModel, Field, StringConstraints, model_validator

from app.application.stocktake_service import StocktakeService
from app.infrastructure.api.fields import optional_text
from app.infrastructure.api.permissions import CurrentBranch, require_permission
from app.infrastructure.persistence.database import SessionLocal
from app.infrastructure.persistence.stocktake_repository import SqlStocktakeRepository

router = APIRouter(tags=["stocktakes"])

Counted = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=3)]


class OpenIn(BaseModel):
    notes: optional_text(2000) = None  # e.g. "Monthly count, aisle 3"


class CountIn(BaseModel):
    counted_quantity: Counted
    notes: optional_text(500) = None


class BulkLine(BaseModel):
    product_id: uuid.UUID | None = None
    barcode: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)] | None = None
    counted_quantity: Counted
    notes: optional_text(500) = None

    @model_validator(mode="after")
    def one_product(self):
        if (self.product_id is None) == (self.barcode is None):
            raise ValueError("send product_id or barcode")
        return self


class BulkIn(BaseModel):
    items: Annotated[list[BulkLine], Field(min_length=1, max_length=500)]  # a few hundred lines per transaction


def get_service():
    with SessionLocal() as session:
        yield StocktakeService(SqlStocktakeRepository(session))


Svc = Annotated[StocktakeService, Depends(get_service)]
# count = create; complete / cancel / remove a line = update (the supervisor, who also sees the system quantities)
Read, Count, Supervise = (require_permission("stocktakes", p) for p in ("read", "create", "update"))
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]
Q = Annotated[str, Query(max_length=100)]


@router.get("/stocktakes")
def list_stocktakes(_: Read, branch: CurrentBranch, svc: Svc, status: Literal["OPEN", "COMPLETED", "CANCELLED"] | None = None,
                    from_: Annotated[AwareDatetime | None, Query(alias="from")] = None, to: AwareDatetime | None = None,
                    page: Page = 1, page_size: PageSize = 25):
    return svc.search(branch, {"status": status, "from": from_, "to": to}, page, page_size)


@router.get("/stocktakes/current")
def current_stocktake(_: Read, branch: CurrentBranch, svc: Svc):
    st = svc.current(branch)
    return st if st else Response(status_code=204)


@router.post("/stocktakes", status_code=201)
def open_stocktake(body: OpenIn, uid: Count, branch: CurrentBranch, svc: Svc):
    return svc.open(uid, branch, body.notes)


@router.get("/stocktakes/{stocktake_id}")
def get_stocktake(stocktake_id: uuid.UUID, uid: Read, branch: CurrentBranch, svc: Svc):
    return svc.get(uid, branch, stocktake_id)


@router.get("/stocktakes/{stocktake_id}/items")
def stocktake_items(stocktake_id: uuid.UUID, uid: Read, branch: CurrentBranch, svc: Svc, only_differences: bool = False,
                    q: Q = "", page: Page = 1, page_size: PageSize = 25):
    return svc.items(uid, branch, stocktake_id, {"only_differences": only_differences, "q": q.strip()}, page, page_size)


@router.get("/stocktakes/{stocktake_id}/products")
def countable_products(stocktake_id: uuid.UUID, _: Read, branch: CurrentBranch, svc: Svc, q: Q = ""):
    """Find a product to count (name or exact barcode); no stock in the answer."""
    return svc.products(branch, stocktake_id, q.strip())


@router.put("/stocktakes/{stocktake_id}/items/{product_id}")
def count_product(stocktake_id: uuid.UUID, product_id: uuid.UUID, body: CountIn, uid: Count, branch: CurrentBranch, svc: Svc):
    return svc.count(uid, branch, stocktake_id, product_id, body.counted_quantity, body.notes)


@router.post("/stocktakes/{stocktake_id}/items/bulk")
def count_bulk(stocktake_id: uuid.UUID, body: BulkIn, uid: Count, branch: CurrentBranch, svc: Svc):
    return svc.bulk(uid, branch, stocktake_id, [line.model_dump() for line in body.items])


@router.delete("/stocktakes/{stocktake_id}/items/{product_id}", status_code=204)
def remove_count(stocktake_id: uuid.UUID, product_id: uuid.UUID, uid: Supervise, branch: CurrentBranch, svc: Svc):
    svc.remove(uid, branch, stocktake_id, product_id)


@router.get("/stocktakes/{stocktake_id}/uncounted")
def uncounted(stocktake_id: uuid.UUID, _: Read, branch: CurrentBranch, svc: Svc, q: Q = "", category_id: uuid.UUID | None = None,
              page: Page = 1, page_size: PageSize = 25):
    return svc.uncounted(branch, stocktake_id, {"q": q.strip(), "category_id": category_id}, page, page_size)


@router.get("/stocktakes/{stocktake_id}/differences")
def differences(stocktake_id: uuid.UUID, uid: Supervise, branch: CurrentBranch, svc: Svc, page: Page = 1, page_size: PageSize = 25):
    return svc.differences(uid, branch, stocktake_id, page, page_size)


@router.post("/stocktakes/{stocktake_id}/complete")
def complete(stocktake_id: uuid.UUID, uid: Supervise, branch: CurrentBranch, svc: Svc):
    return svc.complete(uid, branch, stocktake_id)


@router.post("/stocktakes/{stocktake_id}/cancel")
def cancel(stocktake_id: uuid.UUID, uid: Supervise, branch: CurrentBranch, svc: Svc):
    return svc.cancel(uid, branch, stocktake_id)


@router.get("/stocktakes/{stocktake_id}/result")
def result(stocktake_id: uuid.UUID, _: Supervise, branch: CurrentBranch, svc: Svc):
    return svc.result(branch, stocktake_id)


@router.get("/stocktakes/{stocktake_id}/history")
def history(stocktake_id: uuid.UUID, _: Read, branch: CurrentBranch, svc: Svc, page: Page = 1, page_size: PageSize = 50):
    return svc.history(branch, stocktake_id, page, page_size)


HEADERS = {
    "es": ["Producto", "Código", "Unidad", "Categoría", "Sistema", "Contado"],
    "en": ["Product", "Barcode", "Unit", "Category", "System", "Counted"],
}


@router.get("/stocktakes/{stocktake_id}/export")
def export_sheet(stocktake_id: uuid.UUID, uid: Read, branch: CurrentBranch, svc: Svc, lang: Literal["es", "en"] = "es"):
    """Count sheet (CSV): products with stock in the branch; "Counted" is blank where nothing was counted yet."""
    st, rows, supervisor = svc.sheet(uid, branch, stocktake_id)
    out = io.StringIO()
    writer = csv.writer(out)
    head = HEADERS[lang]
    writer.writerow(head if supervisor else head[:4] + head[5:])  # blind count: no system column for counters
    for r in rows:
        line = [r["name"], r["barcode"] or "", r["unit"], r["category"] or ""]
        line += [r["system_quantity"]] if supervisor else []
        writer.writerow(line + ["" if r["counted_quantity"] is None else r["counted_quantity"]])
    return Response("﻿" + out.getvalue(), media_type="text/csv; charset=utf-8",  # BOM: Excel opens accents right
                    headers={"Content-Disposition": f'attachment; filename="{st["folio"]}.csv"'})
