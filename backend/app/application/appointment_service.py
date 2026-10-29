from datetime import datetime, timezone

from app.application.custom_fields import clean_extra
from app.application.errors import Conflict, Invalid, NotFound
from app.application.ports.appointment_repository import AppointmentRepository
from app.application.ports.custom_field_repository import CustomFieldRepository

OPEN = ("SCHEDULED", "CONFIRMED")
MAX_IN_RANGE = 1000  # a calendar range (a month) never needs more


class AppointmentService:
    def __init__(self, repo: AppointmentRepository, fields: CustomFieldRepository):
        self.repo = repo
        self.fields = fields  # the business's data of each appointment (custom fields, entity 'appointment')

    def search(self, branch, filters):
        if filters["from"] and filters["to"] and filters["to"] <= filters["from"]:
            raise Invalid({"message": "'to' must be after 'from'", "field": "to"})
        return self.repo.search(branch, filters, MAX_IN_RANGE)

    def staff(self, branch):
        return self.repo.staff(branch)

    def get(self, branch, appointment_id):
        appointment = self.repo.get(appointment_id)
        if appointment is None or appointment["branch_id"] != branch:
            raise NotFound("appointment not found")
        return appointment

    def create(self, uid, branch, data):
        """Schedule: a customer, a reason, a time; optionally who attends it (already confirmed if they say so)."""
        if not self.repo.customer_active(data["customer_id"]):
            raise Invalid({"message": "the customer doesn't exist or is deleted", "field": "customer_id"})
        self._check_time(data["starts_at"], data["ends_at"])
        self._check_person(branch, data.get("assigned_to"), data["starts_at"], data["ends_at"], None)
        services = self._services(data.pop("services", None) or [])
        if data.get("quote_id"):
            self._check_quote(branch, data["quote_id"], data["customer_id"])
        data["extra"] = clean_extra(self.fields.active("appointment"), data.get("extra") or {})
        appointment_id = self.repo.create(uid, branch, data)
        if services:
            self.repo.set_services(uid, appointment_id, services)
        self.repo.commit()
        return self.get(branch, appointment_id)

    def update(self, uid, branch, appointment_id, fields):
        """Reason, notes or who attends it (the time changes only by rescheduling)."""
        current = self._open(branch, appointment_id)
        services = fields.pop("services", None)
        if services is not None:
            self.repo.set_services(uid, appointment_id, self._services(services))
            self.repo.commit()
        if "assigned_to" in fields:
            self._check_person(branch, fields["assigned_to"], current["starts_at"], current["ends_at"], appointment_id)
        if "extra" in fields:
            fields["extra"] = clean_extra(self.fields.active("appointment"), fields["extra"] or {}, current["extra"])
        if fields:
            self.repo.update(uid, appointment_id, fields)
            self.repo.commit()
        return self.get(branch, appointment_id)

    def reschedule(self, uid, branch, appointment_id, starts_at, ends_at, reason):
        current = self._open(branch, appointment_id)
        self._check_time(starts_at, ends_at)
        if (starts_at, ends_at) == (current["starts_at"], current["ends_at"]):
            raise Invalid({"message": "that's the same time it already has", "field": "starts_at"})
        self._check_person(branch, current["assigned_id"], starts_at, ends_at, appointment_id)
        # The DB counts it, records old -> new times with the reason, and sends a confirmed one back to SCHEDULED
        self.repo.update(uid, appointment_id, {"starts_at": starts_at, "ends_at": ends_at}, reason)
        self.repo.commit()
        return self.get(branch, appointment_id)

    def set_status(self, uid, branch, appointment_id, status, reason=None):
        current = self._open(branch, appointment_id)
        if status == "CONFIRMED" and current["status"] == "CONFIRMED":
            raise Conflict({"message": "the appointment is already confirmed", "code": "same_status"})
        if status == "CANCELLED" and not reason:
            raise Invalid({"message": "say why it's cancelled", "field": "reason"})
        self.repo.update(uid, appointment_id, {"status": status, **({"cancel_reason": reason} if status == "CANCELLED" else {})})
        self.repo.commit()
        return self.get(branch, appointment_id)

    def mark_reminded(self, uid, branch, appointment_id):
        """The WhatsApp reminder was sent (the app opened the chat with the message)."""
        self._open(branch, appointment_id)
        self.repo.update(uid, appointment_id, {"reminded_at": datetime.now(timezone.utc)})
        self.repo.commit()
        return self.get(branch, appointment_id)

    def add_note(self, uid, branch, appointment_id, note):
        """Follow-up notes: also after it was attended (that's when most are written)."""
        self.get(branch, appointment_id)
        self.repo.add_note(uid, appointment_id, note)
        self.repo.commit()
        return self.get(branch, appointment_id)

    def customer_appointments(self, uid, customer_id, page, page_size):
        rows = self.repo.customer_appointments(uid, customer_id, page_size + 1, (page - 1) * page_size)
        return {"items": rows[:page_size], "page": page, "page_size": page_size, "has_more": len(rows) > page_size}

    # --- helpers ---
    def _services(self, lines):
        """What the appointment will charge: services only (no stock of their own, not kits), each once."""
        ids = [line["product_id"] for line in lines]
        if len(set(ids)) != len(ids):
            raise Invalid({"message": "a service is listed twice", "field": "services"})
        found = {p["id"]: p for p in self.repo.service_products(ids)}
        bad = [str(i) for i in ids if i not in found or found[i]["tracks_stock"] or found[i]["is_kit"]]
        if bad:
            raise Invalid({"message": "only active services can be booked", "field": "services", "product_ids": bad})
        return lines

    def quote_request(self, branch, appointment_id):
        """What a quote made from this appointment would carry: its customer and services, valid until it starts."""
        appointment = self._open(branch, appointment_id)
        if appointment["quote_id"]:
            raise Conflict({"message": "the appointment already has a quote", "code": "has_quote", "quote_id": str(appointment["quote_id"])})
        if not appointment["services"]:
            raise Invalid({"message": "add the services first", "code": "no_services", "field": "services"})
        starts = appointment["starts_at"]
        return {"customer_id": appointment["customer_id"], "notes": appointment["title"],
                "valid_until": starts if starts > datetime.now(timezone.utc) else None,
                "items": [{"product_id": sv["product_id"], "quantity": sv["quantity"]} for sv in appointment["services"]]}

    def link_quote(self, uid, branch, appointment_id, quote_id):
        appointment = self._open(branch, appointment_id)
        self._check_quote(branch, quote_id, appointment["customer_id"])
        self.repo.update(uid, appointment_id, {"quote_id": quote_id})
        self.repo.commit()
        return self.get(branch, appointment_id)

    def _check_quote(self, branch, quote_id, customer_id):
        quote = self.repo.quote_for_link(quote_id)
        if quote is None or quote["branch_id"] != branch:
            raise Invalid({"message": "the quote isn't from this branch", "field": "quote_id"})
        if quote["status"] != "OPEN" or quote["expired"]:
            raise Conflict({"message": "the quote is no longer open", "code": "quote_status"})
        if quote["customer_id"] != customer_id:
            raise Invalid({"message": "the quote is for another customer", "field": "quote_id", "code": "quote_customer"})
        if quote["appointment_id"]:
            raise Conflict({"message": "the quote already belongs to an appointment", "code": "quote_taken"})

    def _open(self, branch, appointment_id):
        appointment = self.get(branch, appointment_id)
        if appointment["status"] not in OPEN:
            raise Conflict({"message": f"the appointment is {appointment['status']}", "code": "closed", "status": appointment["status"]})
        return appointment

    @staticmethod
    def _check_time(starts_at, ends_at):
        if ends_at <= starts_at:
            raise Invalid({"message": "the end must be after the start", "field": "ends_at"})

    def _check_person(self, branch, assigned_to, starts_at, ends_at, exclude):
        if not assigned_to:
            return
        if assigned_to not in {s["id"] for s in self.repo.staff(branch)}:
            raise Invalid({"message": "that person doesn't belong to this branch", "field": "assigned_to"})
        clash = self.repo.clash(assigned_to, starts_at, ends_at, exclude)
        if clash:
            raise Conflict({"message": "that person already has an appointment at that time", "code": "clash",
                            "appointment": clash})
