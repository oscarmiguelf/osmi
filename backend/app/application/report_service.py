import logging
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.application.errors import Forbidden, Invalid, NotFound
from app.application.ports.report_repository import ReportRepository

log = logging.getLogger(__name__)

MAX_DAYS = 366
EXPORT_ROWS = 100_000  # an export is every row, within reason


def local_range(start: date, end: date, tz: str) -> tuple[datetime, datetime]:
    """[start, end] local days -> [UTC instant of start's midnight, UTC instant of the midnight after end)."""
    zone = ZoneInfo(tz)
    first = datetime.combine(start, time.min, zone).astimezone(timezone.utc)
    after = datetime.combine(end + timedelta(days=1), time.min, zone).astimezone(timezone.utc)
    return first, after


class ReportService:
    def __init__(self, repo: ReportRepository):
        self.repo = repo

    def catalog(self, uid):
        admin = self._admin(uid)
        return [{"name": n, **self.repo.spec(n)} for n in self.repo.names() if admin or not self.repo.spec(n).get("admin")]

    def _admin(self, uid):
        return self.repo.has_permission(uid, "users", "read")

    def _branches(self, uid, branch_ids):
        """A consolidated report only over branches the person belongs to, all of them."""
        if not branch_ids:
            raise Invalid({"message": "choose at least one branch", "field": "branch_ids"})
        allowed = self.repo.user_branches(uid, branch_ids)
        refused = [str(b) for b in branch_ids if b not in allowed]
        if refused:
            raise Forbidden({"message": "you don't belong to some of those branches", "branch_ids": refused})
        return list(dict.fromkeys(branch_ids))

    def run(self, uid, name, query, export=None):
        """export: None, or 'csv' / 'xlsx' (every row; needs reports.export and is recorded in report_exports)."""
        spec = self.repo.spec(name)
        if spec is None:
            raise NotFound("report not found")
        if spec.get("admin") and not self._admin(uid):
            raise Forbidden("missing permission users.read")
        if export and not self.repo.has_permission(uid, "reports", "export"):
            raise Forbidden("missing permission reports.export")
        tz = self.repo.timezone(uid)
        branches = self._branches(uid, query["branch_ids"])
        params = {"branches": branches, "tz": tz, "group": query.get("group") or "day",
                  "from": None, "to": None, "limit": 0, "offset": 0}
        if spec.get("range", True):
            start, end = query.get("from"), query.get("to")
            if not start or not end:
                raise Invalid({"message": "choose the period (from / to)", "field": "from"})
            if end < start:
                raise Invalid({"message": "'to' must not be before 'from'", "field": "to"})
            if (end - start).days >= MAX_DAYS:
                raise Invalid({"message": f"the period can be {MAX_DAYS} days at most", "field": "to"})
            params["from"], params["to"] = local_range(start, end, tz)
        for extra in spec.get("extras", []):
            if query.get(extra) is None:
                raise Invalid({"message": f"{extra} is required for this report", "field": extra})
            params[extra] = query[extra]
        page, page_size = query.get("page", 1), query.get("page_size", 25)
        if spec.get("paged"):
            params["limit"], params["offset"] = (EXPORT_ROWS, 0) if export else (page_size + 1, (page - 1) * page_size)
        rows, extra_totals = self.repo.run(name, params, (query.get("order") or "revenue", query.get("direction") or "desc"))
        has_more = bool(spec.get("paged")) and not export and len(rows) > page_size
        rows = rows[:page_size] if has_more else rows
        totals = {k: sum((Decimal(str(r[k] or 0)) for r in rows), Decimal(0)) for k in spec.get("totals", [])}
        parameters = {"branch_ids": [str(b) for b in branches], "from": query.get("from"), "to": query.get("to"),
                      **{k: query[k] for k in ("group", "order", "direction", *spec.get("extras", [])) if query.get(k) is not None}}
        if export:
            self.repo.record_export(uid, name, export, parameters, len(rows))
            log.info("report export: user=%s report=%s format=%s rows=%s", uid, name, export, len(rows))
        return {
            "report": name,
            "parameters": parameters,
            "generated_at": datetime.now(timezone.utc),
            "timezone": tz,
            "columns": [{"key": k, "type": t} for k, t in spec["columns"]],
            "rows": rows,
            "totals": {**totals, **extra_totals} if not spec.get("paged") else {},
            **({"page": page, "page_size": page_size, "has_more": has_more} if spec.get("paged") else {}),
        }

    def dashboard(self, uid, branch_ids, day):
        """Today (or the given day) vs yesterday vs the same weekday last week; cheap by design."""
        tz = self.repo.timezone(uid)
        branches = self._branches(uid, branch_ids)
        day = day or datetime.now(ZoneInfo(tz)).date()
        days = [day, day - timedelta(days=1), day - timedelta(days=7)]
        data = self.repo.dashboard(branches, [local_range(d, d, tz) for d in days], tz)
        labels = ["day", "previous_day", "same_weekday_last_week"]
        # Admins see security events of the last 24 h without having to open the reports (A09: someone must notice)
        security = self.repo.security_events(24) if self._admin(uid) else None
        return {"day": day, "timezone": tz, "generated_at": datetime.now(timezone.utc), "security": security,
                **{label: {"date": d, **p} for label, d, p in zip(labels, days, data.pop("periods"))}, **data}
