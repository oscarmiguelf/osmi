from sqlalchemy import text
from sqlalchemy.orm import Session


# Linked customer for display. Deleted customers still show (flagged) so old events keep their context.
EVENT_CUSTOMER = "cu.full_name AS customer_name, cu.deleted_at IS NOT NULL AS customer_deleted"


class SqlCalendarRepository:
    def __init__(self, session: Session):
        self.session = session

    def _one(self, sql: str, **params) -> dict | None:
        row = self.session.execute(text(sql), params).mappings().first()
        return dict(row) if row else None

    def _all(self, sql: str, **params) -> list[dict]:
        return [dict(r) for r in self.session.execute(text(sql), params).mappings()]

    def access_level(self, user_id, calendar_id):
        return self.session.execute(text("SELECT fn_calendar_access_level(:uid, :cid)"),
                                    {"uid": user_id, "cid": calendar_id}).scalar()

    def list_calendars(self, user_id):
        return self._all("""
            SELECT c.id, c.name, c.description, c.color,
                   CASE WHEN c.owner_id = :uid THEN 'owner' ELSE m.access_level END AS access_level
            FROM calendars c
            LEFT JOIN calendar_members m ON m.calendar_id = c.id AND m.user_id = :uid AND m.deleted_at IS NULL
            WHERE c.deleted_at IS NULL AND (c.owner_id = :uid OR m.id IS NOT NULL)
            ORDER BY c.name
        """, uid=user_id)

    def create_calendar(self, user_id, data):
        return self._one("""
            INSERT INTO calendars (name, description, color, owner_id, created_by, updated_by)
            VALUES (:name, :description, :color, :uid, :uid, :uid) RETURNING *
        """, **data, uid=user_id)

    def update_calendar(self, user_id, calendar_id, fields):
        # fields keys come from the request model, never from raw client input
        sets = "".join(f"{k} = :{k}, " for k in fields)
        return self._one(f"""
            UPDATE calendars SET {sets}updated_by = :uid
            WHERE id = :id AND deleted_at IS NULL RETURNING *
        """, **fields, uid=user_id, id=calendar_id)

    def delete_calendar(self, user_id, calendar_id):
        self.session.execute(text("""
            UPDATE calendars SET deleted_at = NOW(), deleted_by = :uid, updated_by = :uid
            WHERE id = :id AND deleted_at IS NULL
        """), {"uid": user_id, "id": calendar_id})

    def user_is_active(self, user_id):
        return self.session.execute(text(
            "SELECT EXISTS (SELECT 1 FROM users WHERE id = :id AND is_active AND deleted_at IS NULL)"
        ), {"id": user_id}).scalar()

    def search_users(self, user_id, q):
        pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        return self._all("""
            SELECT id, first_name || ' ' || last_name AS name, email
            FROM users
            WHERE is_active AND deleted_at IS NULL AND id <> :uid
              AND (email ILIKE :p OR first_name || ' ' || last_name ILIKE :p)
            ORDER BY name
            LIMIT 20
        """, uid=user_id, p=pattern)

    def list_members(self, calendar_id):
        return self._all("""
            SELECT m.user_id, u.email, u.first_name || ' ' || u.last_name AS name, m.access_level, m.created_at
            FROM calendar_members m JOIN users u ON u.id = m.user_id
            WHERE m.calendar_id = :cid AND m.deleted_at IS NULL
            ORDER BY name
        """, cid=calendar_id)

    def add_member(self, user_id, calendar_id, member_id, level):
        return self._one("""
            INSERT INTO calendar_members (calendar_id, user_id, access_level, created_by, updated_by)
            VALUES (:cid, :member, :level, :uid, :uid)
            ON CONFLICT (calendar_id, user_id) WHERE deleted_at IS NULL DO NOTHING
            RETURNING *
        """, cid=calendar_id, member=member_id, level=level, uid=user_id)

    def update_member(self, user_id, calendar_id, member_id, level):
        return self._one("""
            UPDATE calendar_members SET access_level = :level, updated_by = :uid
            WHERE calendar_id = :cid AND user_id = :member AND deleted_at IS NULL RETURNING *
        """, cid=calendar_id, member=member_id, level=level, uid=user_id)

    def revoke_member(self, user_id, calendar_id, member_id):
        return self.session.execute(text("""
            UPDATE calendar_members SET deleted_at = NOW(), deleted_by = :uid, updated_by = :uid
            WHERE calendar_id = :cid AND user_id = :member AND deleted_at IS NULL
        """), {"cid": calendar_id, "member": member_id, "uid": user_id}).rowcount > 0

    def list_events(self, user_id, start, end, calendar_ids):
        return self._all(f"""
            SELECT e.*, {EVENT_CUSTOMER}
            FROM events e
            LEFT JOIN customers cu ON cu.id = e.customer_id
            JOIN calendars c ON c.id = e.calendar_id AND c.deleted_at IS NULL
            LEFT JOIN calendar_members m ON m.calendar_id = c.id AND m.user_id = :uid AND m.deleted_at IS NULL
            WHERE e.deleted_at IS NULL
              AND (c.owner_id = :uid OR m.id IS NOT NULL)
              AND e.start_at < :end AND e.end_at > :start
              AND (CAST(:cids AS uuid[]) IS NULL OR e.calendar_id = ANY(CAST(:cids AS uuid[])))
            ORDER BY e.start_at
        """, uid=user_id, start=start, end=end, cids=calendar_ids)

    def get_event(self, event_id):
        return self._one(f"""
            SELECT e.*, {EVENT_CUSTOMER}
            FROM events e LEFT JOIN customers cu ON cu.id = e.customer_id
            WHERE e.id = :id AND e.deleted_at IS NULL
        """, id=event_id)

    def customer_is_active(self, customer_id):
        return self.session.execute(text(
            "SELECT EXISTS (SELECT 1 FROM customers WHERE id = :id AND deleted_at IS NULL)"
        ), {"id": customer_id}).scalar()

    def create_event(self, user_id, calendar_id, data):
        return self._one("""
            INSERT INTO events (calendar_id, title, description, location, start_at, end_at, customer_id,
                                created_by, updated_by)
            VALUES (:cid, :title, :description, :location, :start_at, :end_at, :customer_id, :uid, :uid) RETURNING *
        """, **data, cid=calendar_id, uid=user_id)

    def update_event(self, user_id, event_id, fields):
        # fields keys come from the request model, never from raw client input
        sets = "".join(f"{k} = :{k}, " for k in fields)
        return self._one(f"""
            UPDATE events SET {sets}updated_by = :uid
            WHERE id = :id AND deleted_at IS NULL RETURNING *
        """, **fields, uid=user_id, id=event_id)

    def delete_event(self, user_id, event_id):
        self.session.execute(text("""
            UPDATE events SET deleted_at = NOW(), deleted_by = :uid, updated_by = :uid
            WHERE id = :id AND deleted_at IS NULL
        """), {"uid": user_id, "id": event_id})

    def audit(self, calendar_id, limit, offset):
        return self._all("""
            SELECT a.changed_at, a.entity_type, a.entity_id, a.action, u.email AS changed_by_email, a.changed_fields
            FROM calendar_audit a
            LEFT JOIN users u ON u.id = a.changed_by
            WHERE a.calendar_id = :cid
            ORDER BY a.changed_at DESC, a.id DESC
            LIMIT :limit OFFSET :offset
        """, cid=calendar_id, limit=limit, offset=offset)

    def set_timezone(self, user_id, timezone):
        return self.session.execute(text("""
            UPDATE users SET timezone = :tz
            WHERE id = :id AND EXISTS (SELECT 1 FROM pg_timezone_names WHERE name = :tz)
        """), {"tz": timezone, "id": user_id}).rowcount > 0

    def commit(self):
        self.session.commit()
