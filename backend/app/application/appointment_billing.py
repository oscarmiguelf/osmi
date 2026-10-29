import uuid
from decimal import Decimal

from app.application.appointment_service import AppointmentService
from app.application.errors import AppError, Conflict
from app.application.quote_service import QuoteService
from app.application.sale_service import NO_REGISTER, SaleService

D = lambda v: Decimal(str(v))  # noqa: E731


def _code(error: AppError) -> str:
    return error.detail.get("code", "failed") if isinstance(error.detail, dict) else "failed"


class AppointmentBilling:
    """The sale of each appointment with services, made when it's booked: all on credit, paid with deposits afterwards.
    Cancelled / missed: the sale goes back while nothing was paid. Its services change: the sale is made again.

    The appointment is saved even when its sale can't be made right then (no register occupied, no permission): the
    reason comes back as `sale_pending` and the sale can be made later from the appointment."""

    def __init__(self, appointments: AppointmentService, sales: SaleService, quotes: QuoteService):
        self.appointments = appointments
        self.sales = sales
        self.quotes = quotes

    def book(self, uid, branch, data):
        appointment = self.appointments.create(uid, branch, data)
        return self._with(branch, appointment, self._make_sale(uid, branch, appointment))

    def make_sale(self, uid, branch, appointment_id):
        appointment = self.appointments.get(branch, appointment_id)
        if self._active_sale(branch, appointment):
            raise Conflict({"message": "the appointment already has its sale", "code": "appointment_charged"})
        pending = self._make_sale(uid, branch, appointment)
        if pending:
            raise Conflict({**NO_REGISTER, "code": pending} if pending == "register" else {"message": "the sale couldn't be made", "code": pending})
        return self.appointments.get(branch, appointment_id)

    def change_services(self, uid, branch, appointment_id, fields):
        """Services of a charged appointment: its sale is made again (only while nothing was paid on it)."""
        appointment = self.appointments.get(branch, appointment_id)
        sale = self._active_sale(branch, appointment)
        if sale:
            if self._paid(sale):
                raise Conflict({"message": "it already has payments: adjust it in its sale", "code": "has_payments"})
            if self.sales.repo.current_register(uid, branch) is None:
                raise Conflict(NO_REGISTER)
        updated = self.appointments.update(uid, branch, appointment_id, fields)
        if sale:
            self._return(uid, branch, sale, "Cambio de servicios")
            return self._with(branch, updated, self._make_sale(uid, branch, self.appointments.get(branch, appointment_id)))
        return updated

    def close(self, uid, branch, appointment_id, status, reason=None):
        """Cancelled or missed: its sale goes back if nothing was paid; with deposits paid, someone decides the refund."""
        appointment = self.appointments.set_status(uid, branch, appointment_id, status, reason)
        sale = self._active_sale(branch, appointment)
        followup = None
        if sale:
            followup = "has_payments" if self._paid(sale) else self._return(uid, branch, sale, reason or "No asistió")
        return {**self.appointments.get(branch, appointment_id), "sale_followup": followup}

    # --- helpers ------------------------------------------------------------
    def _make_sale(self, uid, branch, appointment):
        if not appointment["services"]:
            return None
        if not self.sales.repo.has_permission(uid, "sales", "create"):
            return "permission"
        line = lambda product_id, quantity, price=None, discount=0: {  # noqa: E731
            "product_id": product_id, "quantity": D(quantity), "unit_price": None if price is None else D(price),
            "discount": D(discount), "promotion_id": None, "fulfillment": "DELIVERED", "benefit_id": None}
        body = {"id": uuid.uuid4(), "appointment_id": appointment["id"], "customer_id": appointment["customer_id"], "on_credit": True,
                "discount": Decimal(0), "items": [line(s["product_id"], s["quantity"]) for s in appointment["services"]]}
        if appointment.get("quote_id") and appointment.get("quote_status") == "OPEN" and not appointment.get("quote_expired"):
            # Booked from a quote: the quoted prices (the sale converts the quote)
            quote = self.quotes.get(branch, appointment["quote_id"])
            body.update(quote_id=quote["id"], discount=D(quote["discount"]),
                        items=[line(i["product_id"], i["quantity"], i["unit_price"], i["discount"]) for i in quote["items"] if i["product_active"]])
        try:
            self.sales.create(uid, branch, body)
        except AppError as e:
            return _code(e)
        return None

    def _active_sale(self, branch, appointment):
        if not appointment.get("sale_id"):
            return None
        sale = self.sales.get(branch, appointment["sale_id"])
        return None if sale["status"] == "RETURNED" else sale

    @staticmethod
    def _paid(sale):
        return D(sale["total"]) - D(sale["credit_outstanding"]) > 0

    def _return(self, uid, branch, sale, reason):
        items = [{"sale_item_id": i["id"], "quantity": D(i["returnable_quantity"])} for i in sale["items"] if D(i["returnable_quantity"]) > 0]
        try:
            self.sales.create_return(uid, branch, sale["id"], {"items": items, "refunds": [], "reason": reason[:500]})
        except AppError as e:
            return _code(e)
        return None

    def _with(self, branch, appointment, pending):
        return {**self.appointments.get(branch, appointment["id"]), "sale_pending": pending}
