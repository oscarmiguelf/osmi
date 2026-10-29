import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.application.errors import Invalid
from app.application.report_service import ReportService
from app.infrastructure.api.permissions import OptionalBranch, require_permission
from app.infrastructure.persistence.database import SessionLocal
from app.infrastructure.persistence.report_repository import SqlReportRepository

router = APIRouter(tags=["reports"])


def get_service():
    with SessionLocal() as session:
        yield ReportService(SqlReportRepository(session))


Svc = Annotated[ReportService, Depends(get_service)]
Read = require_permission("reports", "read")


def _branch_ids(raw: str | None, working: uuid.UUID | None) -> list[uuid.UUID]:
    """branch_ids=a,b,c; default: the working branch (X-Branch-Id)."""
    if not raw:
        return [working] if working else []
    try:
        return [uuid.UUID(x.strip()) for x in raw.split(",") if x.strip()]
    except ValueError:
        raise Invalid({"message": "branch_ids must be a comma separated list of ids", "field": "branch_ids"}) from None


BranchIds = Annotated[str | None, Query(max_length=2000, description="Comma separated; default: the working branch")]


@router.get("/reports")
def report_catalog(uid: Read, svc: Svc):
    """The reports this person can open, with their columns and parameters (the front end renders any of them)."""
    return svc.catalog(uid)


@router.get("/reports/dashboard")
def report_dashboard(uid: Read, svc: Svc, branch: OptionalBranch, branch_ids: BranchIds = None, day: date | None = None):
    return svc.dashboard(uid, _branch_ids(branch_ids, branch), day)


@router.get("/reports/{section}/{name}")
def run_report(section: str, name: str, uid: Read, svc: Svc, branch: OptionalBranch, branch_ids: BranchIds = None,
               from_: Annotated[date | None, Query(alias="from")] = None, to: date | None = None,
               group: Literal["day", "week", "month"] = "day",
               order: Literal["revenue", "units", "margin"] = "revenue", direction: Literal["asc", "desc"] = "desc",
               customer_id: uuid.UUID | None = None, product_id: uuid.UUID | None = None,
               days: Annotated[int, Query(ge=1, le=3650)] = 60,
               page: Annotated[int, Query(ge=1)] = 1, page_size: Annotated[int, Query(ge=1, le=100)] = 25,
               export: Literal["csv", "xlsx"] | None = None):
    """Any report of the catalog. from / to are local days of the person (their time zone). export=csv|xlsx needs
    reports.export, returns every row and is recorded (the front end writes the file in the person's language)."""
    query = {"branch_ids": _branch_ids(branch_ids, branch), "from": from_, "to": to, "group": group, "order": order,
             "direction": direction, "customer_id": customer_id, "product_id": product_id, "days": days,
             "page": page, "page_size": page_size}
    return svc.run(uid, f"{section}/{name}", query, export)
