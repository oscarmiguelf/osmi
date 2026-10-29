import json
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.infrastructure.persistence.sale_repository import db_rules

APPOINTMENT = """
    a.id, a.branch_id, a.customer_id, c.full_name AS customer, c.phone AS customer_phone, a.title, a.notes,
    a.starts_at, a.ends_at, a.status, a.cancel_reason, a.reschedule_count, a.assigned_to AS assigned_id,
    NULLIF(TRIM(CONCAT(au.first_name, ' ', au.last_name)), '') AS assigned_to, cu.email AS created_by, a.created_by AS created_by_id, a.created_at,
    a.sale_id, sa.folio AS sale_folio, sa.total AS sale_total, fn_sale_credit_outstanding(sa.id) AS sale_balance, a.reminded_at, a.extra,
    a.quote_id, q.folio AS quote_folio, q.total AS quote_total, qs.name AS quote_status, (qs.name = 'OPEN' AND q.valid_until < NOW()) AS quote_expired,
    (SELECT STRING_AGG(p.name, ', ' ORDER BY s.sort_order) FROM appointment_services s JOIN products p ON p.id = s.product_id
      WHERE s.appointment_id = a.id) AS services_text
"""
FROM = """
    appointments a JOIN customers c ON c.id = a.customer_id JOIN users cu ON cu.id = a.created_by
    LEFT JOIN users au ON au.id = a.assigned_to
    LEFT JOIN sales sa ON sa.id = a.sale_id
    LEFT JOIN quotes q ON q.id = a.quote_id LEFT JOIN quote_statuses qs ON qs.id = q.status_id
"""


class SqlAppointmentRepository:
    def __init__(self, session: Session):
        self.session = session

    def _one(self, sql: str, **params) -> dict | None:
        row = self.session.execute(text(sql), params).mappings().first()
        return dict(row) if row else None

    def _all(self, sql: str, **params) -> list[dict]:
        return [dict(r) for r in self.session.execute(text(sql), params).mappings()]

    def search(self, branch_id, filters, limit):
        # Appointments that touch the range [from, to): a calendar month includes the ones crossing its edges
        return self._all(f"""
            SELECT {APPOINTMENT} FROM {FROM}
            WHERE a.branch_id = :b
              AND (CAST(:from AS timestamptz) IS NULL OR a.ends_at > CAST(:from AS timestamptz))
              AND (CAST(:to AS timestamptz) IS NULL OR a.starts_at < CAST(:to AS timestamptz))
              AND (CAST(:status AS text) IS NULL OR a.status = CAST(:status AS text))
              AND (NOT :hide_cancelled OR a.status <> 'CANCELLED')
              AND (CAST(:customer_id AS uuid) IS NULL OR a.customer_id = CAST(:customer_id AS uuid))
              AND (CAST(:assigned_to AS uuid) IS NULL OR a.assigned_to = CAST(:assigned_to AS uuid))
              AND (CAST(:only AS uuid) IS NULL OR a.assigned_to = CAST(:only AS uuid) OR a.created_by = CAST(:only AS uuid))
            ORDER BY a.starts_at, a.id LIMIT :limit
        """, b=branch_id, **{"only": None, **filters}, limit=limit)

    def get(self, appointment_id):
        appointment = self._one(f"SELECT {APPOINTMENT} FROM {FROM} WHERE a.id = :id", id=appointment_id)
        if appointment is None:
            return None
        appointment["services"] = self._all("""
            SELECT s.product_id, p.name AS product, s.quantity, p.price, p.duration_minutes, u.name AS unit
            FROM appointment_services s JOIN products p ON p.id = s.product_id JOIN units_of_measure u ON u.id = p.unit_of_measure_id
            WHERE s.appointment_id = :id ORDER BY s.sort_order, p.name
        """, id=appointment_id)
        appointment["follow_up"] = self._all("""
            SELECT n.id, n.note, n.created_at, NULLIF(TRIM(CONCAT(u.first_name, ' ', u.last_name)), '') AS created_by
            FROM appointment_notes n JOIN users u ON u.id = n.created_by
            WHERE n.appointment_id = :id ORDER BY n.created_at DESC, n.id
        """, id=appointment_id)
        appointment["history"] = self._all("""
            SELECT h.action, h.from_status, h.to_status, h.from_starts_at, h.from_ends_at, h.to_starts_at, h.to_ends_at,
                   h.reason, h.changed_fields, u.email AS changed_by, h.changed_at
            FROM appointment_history h JOIN users u ON u.id = h.changed_by
            WHERE h.appointment_id = :id ORDER BY h.changed_at DESC, h.id DESC
        """, id=appointment_id)
        return appointment

    def customer_active(self, customer_id):
        return self.session.execute(text("SELECT EXISTS (SELECT 1 FROM customers WHERE id = :id AND deleted_at IS NULL)"),
                                    {"id": customer_id}).scalar()

    def staff(self, branch_id):
        """People who can attend appointments here: active users of the branch."""
        return self._all("""
            SELECT u.id, NULLIF(TRIM(CONCAT(u.first_name, ' ', u.last_name)), '') AS name, u.email
            FROM users u
            WHERE u.deleted_at IS NULL AND u.is_active AND fn_user_in_branch(u.id, :b)
            ORDER BY LOWER(u.first_name), LOWER(u.last_name)
        """, b=branch_id)

    def clash(self, assigned_to, starts_at, ends_at, exclude):
        return self._one("""
            SELECT a.id, a.starts_at, a.ends_at, c.full_name AS customer FROM appointments a JOIN customers c ON c.id = a.customer_id
            WHERE a.assigned_to = :u AND a.status IN ('SCHEDULED', 'CONFIRMED')
              AND a.starts_at < :e AND a.ends_at > :s AND (CAST(:x AS uuid) IS NULL OR a.id <> CAST(:x AS uuid))
            ORDER BY a.starts_at LIMIT 1
        """, u=assigned_to, s=starts_at, e=ends_at, x=exclude)

    @db_rules
    def create(self, user_id, branch_id, data):
        appointment_id = uuid.uuid4()
        self.session.execute(text("""
            INSERT INTO appointments (id, branch_id, customer_id, assigned_to, title, notes, starts_at, ends_at, status, extra, quote_id,
                                      created_by, updated_by)
            VALUES (:id, :b, :customer_id, :assigned_to, :title, :notes, :starts_at, :ends_at, :status, CAST(:extra AS jsonb), :quote_id, :uid, :uid)
        """), {"assigned_to": None, "notes": None, "quote_id": None, **data, "extra": json.dumps(data.get("extra") or {}),
              "id": appointment_id, "b": branch_id, "uid": user_id})
        return appointment_id

    @db_rules
    def update(self, user_id, appointment_id, fields, reason=None):
        if reason:  # read by the history trigger (this transaction only)
            self.session.execute(text("SELECT set_config('app.appointment_reason', :r, TRUE)"), {"r": reason})
        if "extra" in fields:
            fields = {**fields, "extra": json.dumps(fields["extra"])}
        # keys come from the request model / the service
        sets = "".join(f"{k} = {'CAST(:extra AS jsonb)' if k == 'extra' else ':' + k}, " for k in fields)
        self.session.execute(text(f"UPDATE appointments SET {sets}updated_by = :uid WHERE id = :id"),
                             {**fields, "uid": user_id, "id": appointment_id})

    def quote_for_link(self, quote_id):
        """A quote that could be tied to an appointment: its branch, customer, state, and the appointment it's already on."""
        return self._one("""
            SELECT q.id, q.branch_id, q.customer_id, st.name AS status, q.valid_until < NOW() AS expired,
                   (SELECT id FROM appointments WHERE quote_id = q.id) AS appointment_id
            FROM quotes q JOIN quote_statuses st ON st.id = q.status_id WHERE q.id = :id
        """, id=quote_id)

    def service_products(self, ids):
        return self._all("""
            SELECT p.id, p.name, t.tracks_stock, t.is_kit FROM products p JOIN product_types t ON t.id = p.product_type_id
            WHERE p.id = ANY(CAST(:ids AS uuid[])) AND p.deleted_at IS NULL
        """, ids=[str(i) for i in ids])

    @db_rules
    def set_services(self, user_id, appointment_id, lines):
        self.session.execute(text("DELETE FROM appointment_services WHERE appointment_id = :a"), {"a": appointment_id})
        if lines:
            self.session.execute(text("""
                INSERT INTO appointment_services (appointment_id, product_id, quantity, sort_order, created_by)
                VALUES (:a, :product_id, :quantity, :n, :uid)
            """), [{"a": appointment_id, "product_id": l["product_id"], "quantity": l["quantity"], "n": n, "uid": user_id}
                  for n, l in enumerate(lines)])

    @db_rules
    def add_note(self, user_id, appointment_id, note):
        self.session.execute(text("INSERT INTO appointment_notes (appointment_id, note, created_by) VALUES (:a, :n, :uid)"),
                             {"a": appointment_id, "n": note, "uid": user_id})

    def customer_appointments(self, user_id, customer_id, limit, offset, only=None):
        """A customer's follow-up: their appointments in the branches the person belongs to, newest first."""
        return self._all(f"""
            SELECT {APPOINTMENT}, b.name AS branch,
                   (SELECT COUNT(*) FROM appointment_notes n WHERE n.appointment_id = a.id) AS note_count
            FROM {FROM} JOIN branches b ON b.id = a.branch_id
            WHERE a.customer_id = :c AND fn_user_in_branch(:uid, a.branch_id)
              AND (CAST(:only AS uuid) IS NULL OR a.assigned_to = CAST(:only AS uuid) OR a.created_by = CAST(:only AS uuid))
            ORDER BY a.starts_at DESC, a.id LIMIT :limit OFFSET :offset
        """, c=customer_id, uid=user_id, limit=limit, offset=offset, only=only)

    def commit(self):
        self.session.commit()
