from datetime import timedelta

from app.application.errors import Conflict, Forbidden, Invalid, NotFound
from app.application.ports.calendar_repository import CalendarRepository

READ = ("owner", "edit", "view")
WRITE = ("owner", "edit")
OWNER = ("owner",)
MAX_RANGE = timedelta(days=366)


class CalendarService:
    def __init__(self, repo: CalendarRepository):
        self.repo = repo

    def list_calendars(self, uid):
        return self.repo.list_calendars(uid)

    def create_calendar(self, uid, data):
        row = self.repo.create_calendar(uid, data)
        self.repo.commit()
        return row

    def update_calendar(self, uid, cid, fields):
        self._require(uid, cid, OWNER)
        row = self.repo.update_calendar(uid, cid, fields)
        self.repo.commit()
        return row

    def delete_calendar(self, uid, cid):
        self._require(uid, cid, OWNER)
        self.repo.delete_calendar(uid, cid)
        self.repo.commit()

    def search_users(self, uid, q):
        return self.repo.search_users(uid, q)

    def list_members(self, uid, cid):
        self._require(uid, cid, OWNER)
        return self.repo.list_members(cid)

    def add_member(self, uid, cid, member_id, level):
        self._require(uid, cid, OWNER)
        if member_id == uid:  # only the owner can share, so "yourself" and "the owner" are the same check
            raise Invalid("cannot share a calendar with its owner")
        if not self.repo.user_is_active(member_id):
            raise NotFound("user not found")
        row = self.repo.add_member(uid, cid, member_id, level)
        if row is None:
            raise Conflict("user already has access to this calendar")
        self.repo.commit()
        return row

    def update_member(self, uid, cid, member_id, level):
        self._require(uid, cid, OWNER)
        row = self.repo.update_member(uid, cid, member_id, level)
        if row is None:
            raise NotFound("member not found")
        self.repo.commit()
        return row

    def revoke_member(self, uid, cid, member_id):
        self._require(uid, cid, OWNER)
        if not self.repo.revoke_member(uid, cid, member_id):
            raise NotFound("member not found")
        self.repo.commit()

    def list_events(self, uid, start, end, calendar_ids):
        if not start < end <= start + MAX_RANGE:
            raise Invalid("'to' must be after 'from' and at most 366 days later")
        return self.repo.list_events(uid, start, end, calendar_ids)

    def create_event(self, uid, cid, data):
        self._require(uid, cid, WRITE)
        self._check_customer(data.get("customer_id"))
        row = self.repo.create_event(uid, cid, data)
        self.repo.commit()
        return row

    def get_event(self, uid, eid):
        return self._event(uid, eid, READ)

    def update_event(self, uid, eid, fields):
        event = self._event(uid, eid, WRITE)
        if fields.get("end_at", event["end_at"]) <= fields.get("start_at", event["start_at"]):
            raise Invalid("end_at must be after start_at")
        # Only a newly chosen customer must be active; an event already linked to a since-deleted one stays editable.
        if fields.get("customer_id") != event["customer_id"]:
            self._check_customer(fields.get("customer_id"))
        row = self.repo.update_event(uid, eid, fields)
        self.repo.commit()
        return row

    def delete_event(self, uid, eid):
        self._event(uid, eid, WRITE)
        self.repo.delete_event(uid, eid)
        self.repo.commit()

    def audit(self, uid, cid, limit, offset):
        self._require(uid, cid, OWNER)
        return self.repo.audit(cid, limit, offset)

    def set_timezone(self, uid, timezone):
        if not self.repo.set_timezone(uid, timezone):
            raise Invalid("unknown timezone")
        self.repo.commit()

    def _check_customer(self, customer_id):
        if customer_id is not None and not self.repo.customer_is_active(customer_id):
            raise Invalid("customer not found or deleted")

    def _require(self, uid, cid, levels):
        level = self.repo.access_level(uid, cid)
        if level is None:  # 404, not 403, so calendars you can't see don't leak
            raise NotFound("not found")
        if level not in levels:
            raise Forbidden("insufficient access to this calendar")

    def _event(self, uid, eid, levels):
        event = self.repo.get_event(eid)
        if event is None:
            raise NotFound("not found")
        self._require(uid, event["calendar_id"], levels)
        return event
