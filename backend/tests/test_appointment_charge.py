# Integration test: services with a duration, an appointment with services, and charging it at the point of sale.
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from tests.test_calendar import A, client
from tests.test_purchases import _seed


class Branch:
    """A branch with a register the admin occupies (their own open register is put back afterwards)."""
    def __init__(self, name):
        self.tag = secrets.token_hex(3)
        mine = client.get("/cash-sessions/current", headers=A)
        self.mine = mine.json() if mine.status_code == 200 else None
        if self.mine:
            client.post(f"/cash-registers/{self.mine['cash_register_id']}/release", headers={**A, "X-Branch-Id": self.mine["branch_id"]})
        self.id = client.post("/branches", json={"name": f"{name} {self.tag}", "code": f"{name[0]}{self.tag[:4]}".upper()}, headers=A).json()["id"]
        self.H = {**A, "X-Branch-Id": self.id}
        self.reg = client.post("/cash-registers", json={"name": f"Caja {self.tag}"}, headers=self.H).json()["id"]
        self.occupy()
        methods = {m["description"]: m for m in client.get("/payment-methods", headers=A).json()}
        self.cash, self.card = methods["Cash"]["id"], methods["Card"]["id"]
        self.products, self.customers, self.appointments = [], [], []

    def occupy(self):
        client.post(f"/cash-registers/{self.reg}/occupy", headers=self.H)

    def release(self):
        client.post(f"/cash-registers/{self.reg}/release", headers=self.H)

    def service(self, name, price, minutes=None):
        p = client.post("/products", json={"name": f"{name} {self.tag}", "product_type_id": _seed("/product-types", "Service"),
                                           "unit_of_measure_id": _seed("/units", "Service"), "price": price, "duration_minutes": minutes}, headers=self.H).json()
        self.products.append(p)
        return p

    def customer(self, name, **kw):
        c = client.post("/customers", json={"full_name": f"{name} {self.tag}", "phone": "55" + str(secrets.randbelow(10**8)).zfill(8), **kw}, headers=A).json()
        self.customers.append(c)
        return c

    def book(self, customer, services=(), start=None, **kw):
        start = start or (datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0)
        r = client.post("/appointments", json={"customer_id": customer["id"], "title": "Cita", "starts_at": start.isoformat(),
                                               "ends_at": (start + timedelta(hours=1)).isoformat(), "services": [{"product_id": s["id"]} for s in services], **kw}, headers=self.H)
        if r.status_code == 201:
            self.appointments.append(r.json()["id"])
        return r

    def sale(self, sale_id):
        return client.get(f"/sales/{sale_id}", headers=self.H).json()

    def cleanup(self):
        self.occupy()
        for aid in self.appointments:
            a = client.get(f"/appointments/{aid}", headers=self.H).json()
            if a.get("sale_id"):
                d = self.sale(a["sale_id"])
                if d["status"] != "RETURNED":
                    if Decimal(str(d["credit_outstanding"])):
                        client.post(f"/sales/{d['id']}/payments", json={"payment_method_id": self.cash, "amount": d["credit_outstanding"]}, headers=self.H)
                    d = self.sale(a["sale_id"])
                    client.post(f"/sales/{d['id']}/returns", json={"items": [{"sale_item_id": i["id"], "quantity": i["returnable_quantity"]} for i in d["items"]
                                                                            if Decimal(str(i["returnable_quantity"]))],
                                                                  "refunds": [{"payment_method_id": self.cash, "amount": d["total"]}]}, headers=self.H)
            client.post(f"/appointments/{aid}/cancel", json={"reason": "Prueba"}, headers=self.H)
        self.release()
        for p in self.products:
            client.delete(f"/products/{p['id']}", headers=A)
        for c in self.customers:
            client.delete(f"/customers/{c['id']}", headers=A)
        if self.mine:
            client.post(f"/cash-registers/{self.mine['cash_register_id']}/occupy", headers={**A, "X-Branch-Id": self.mine["branch_id"]})


def test_booking_makes_the_sale():
    """An appointment with services gets its sale when booked: all on credit (no credit limit needed), paid with deposits."""
    b = Branch("Cita cobro")
    try:
        ptype, unit = _seed("/product-types", "Product"), _seed("/units", "Unit")
        cut, dye = b.service("Corte", 250, 45), b.service("Tinte", 600, 90)
        shampoo = client.post("/products", json={"name": f"Shampoo {b.tag}", "product_type_id": ptype, "unit_of_measure_id": unit,
                                                 "price": 150, "duration_minutes": 30}, headers=b.H).json()
        b.products.append(shampoo)
        cust = b.customer("Clienta")
        assert cut["duration_minutes"] == 45 and shampoo["duration_minutes"] is None  # only services have a duration
        assert b.book(cust, [shampoo]).status_code == 422  # not a service
        assert b.book(cust, [cut, cut]).status_code == 422  # twice

        # Booked (starting now: a walk-in): its sale, on credit, the appointment stays open
        appt = b.book(cust, [cut, dye], start=datetime.now(timezone.utc).replace(microsecond=0)).json()
        assert appt["sale_pending"] is None and appt["sale_id"] and appt["status"] == "SCHEDULED"
        assert Decimal(str(appt["sale_total"])) == 850 and Decimal(str(appt["sale_balance"])) == 850
        sale = b.sale(appt["sale_id"])
        assert sale["customer_id"] == cust["id"] and sale["status"] == "PENDING" and sale["appointment_id"] == appt["id"]
        # Charging it again at the register: refused
        r = client.post("/sales", json={"appointment_id": appt["id"], "items": [{"product_id": cut["id"], "quantity": 1}],
                                        "payments": [{"payment_method_id": b.cash, "amount": 250}]}, headers=b.H)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "appointment_charged"
        # A deposit in two methods at once; more than owed is refused
        assert client.post(f"/sales/{sale['id']}/payments/batch", json={"payments": [{"payment_method_id": b.cash, "amount": 900}]}, headers=b.H).status_code == 422
        paid = client.post(f"/sales/{sale['id']}/payments/batch", json={"payments": [
            {"payment_method_id": b.cash, "amount": 300, "amount_tendered": 500}, {"payment_method_id": b.card, "amount": 200, "reference": "1234"}]}, headers=b.H)
        assert paid.status_code == 201, paid.text
        assert Decimal(str(paid.json()["credit_outstanding"])) == 350
        # With payments, its services can't change here; attended: closed as usual
        r = client.patch(f"/appointments/{appt['id']}", json={"services": [{"product_id": cut["id"]}]}, headers=b.H)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "has_payments"
        assert client.post(f"/appointments/{appt['id']}/complete", headers=b.H).json()["status"] == "COMPLETED"

        # Without services: no sale
        assert b.book(cust).json()["sale_id"] is None
    finally:
        b.cleanup()


def test_booking_sale_follows_the_appointment():
    """No register: booked, its sale made later. New services: a new sale. Cancelled: its sale goes back (or deposits flagged)."""
    b = Branch("Seguimiento")
    try:
        cut, dye = b.service("Corte", 250), b.service("Tinte", 600)
        cust = b.customer("Cliente")
        b.release()
        appt = b.book(cust, [cut]).json()
        assert appt["sale_id"] is None and appt["sale_pending"] == "register"
        b.occupy()
        appt = client.post(f"/appointments/{appt['id']}/sale", headers=b.H).json()
        assert appt["sale_id"] and Decimal(str(appt["sale_balance"])) == 250
        assert client.post(f"/appointments/{appt['id']}/sale", headers=b.H).status_code == 409

        # Services changed (nothing paid): the old sale goes back, a new one with the new total
        old = appt["sale_id"]
        changed = client.patch(f"/appointments/{appt['id']}", json={"services": [{"product_id": cut["id"]}, {"product_id": dye["id"]}]}, headers=b.H).json()
        assert changed["sale_id"] != old and Decimal(str(changed["sale_total"])) == 850 and b.sale(old)["status"] == "RETURNED"

        # Cancelled with nothing paid: the sale goes back, the customer owes nothing
        done = client.post(f"/appointments/{appt['id']}/cancel", json={"reason": "Ya no viene"}, headers=b.H).json()
        assert done["status"] == "CANCELLED" and done["sale_followup"] is None and b.sale(changed["sale_id"])["status"] == "RETURNED"
        assert Decimal(str(client.get(f"/customers/{cust['id']}/credit", headers=A).json()["balance"])) == 0

        # Missed with a deposit paid: flagged (someone decides the refund in the sale)
        appt2 = b.book(cust, [dye]).json()
        client.post(f"/sales/{appt2['sale_id']}/payments/batch", json={"payments": [{"payment_method_id": b.cash, "amount": 100}]}, headers=b.H)
        missed = client.post(f"/appointments/{appt2['id']}/no-show", headers=b.H).json()
        assert missed["status"] == "NO_SHOW" and missed["sale_followup"] == "has_payments" and b.sale(appt2["sale_id"])["status"] == "PENDING"
    finally:
        b.cleanup()


def test_reminder_marked():
    """The WhatsApp reminder: marked on an open appointment, shown in its data."""
    tag = secrets.token_hex(3)
    branch = client.post("/branches", json={"name": f"Recordatorio {tag}", "code": f"R{tag[:4]}".upper()}, headers=A).json()["id"]
    H = {**A, "X-Branch-Id": branch}
    customer = client.post("/customers", json={"full_name": f"Paciente {tag}", "phone": "55" + str(secrets.randbelow(10**8)).zfill(8)}, headers=A).json()
    start = (datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0)
    try:
        appt = client.post("/appointments", json={"customer_id": customer["id"], "title": "Revisión", "starts_at": start.isoformat(),
                                                  "ends_at": (start + timedelta(minutes=30)).isoformat()}, headers=H).json()
        assert appt["reminded_at"] is None
        assert client.post(f"/appointments/{appt['id']}/reminded", headers=H).json()["reminded_at"]
        assert client.patch("/settings", json={"reminder_template": "Hola {cliente}"}, headers=A).json()["reminder_template"] == "Hola {cliente}"
        client.post(f"/appointments/{appt['id']}/cancel", json={"reason": "Prueba"}, headers=H)
        assert client.post(f"/appointments/{appt['id']}/reminded", headers=H).status_code == 409  # closed
    finally:
        client.patch("/settings", json={"reminder_template": ""}, headers=A)
        client.delete(f"/customers/{customer['id']}", headers=A)


def test_event_data_and_quote():
    """An event: its own data (custom fields of appointments); booked from a quote, its sale converts the quote."""
    b = Branch("Evento")
    venue = client.post("/custom-fields", json={"entity": "appointment", "label": f"Lugar {b.tag}", "field_type": "text", "required": True}, headers=A).json()
    guests = client.post("/custom-fields", json={"entity": "appointment", "label": f"Invitados {b.tag}", "field_type": "number"}, headers=A).json()
    try:
        show, extra = b.service("Show", 10000), b.service("Hora extra", 1500)
        cust, other = b.customer("Novios"), b.customer("Otro")
        assert any(f["id"] == venue["id"] for f in client.get("/custom-fields/appointment", headers=A).json())
        assert all(f["id"] != venue["id"] for f in client.get("/custom-fields", headers=A).json())
        r = b.book(cust, [show], extra={guests["id"]: "150"})
        assert r.status_code == 422 and r.json()["detail"]["errors"][venue["id"]] == "required"
        assert b.book(cust, [show], extra={venue["id"]: "Jardín", guests["id"]: "muchos"}).status_code == 422
        start = (datetime.now(timezone.utc) + timedelta(days=30)).replace(microsecond=0)

        # A quote first (with a discount), the event booked from it: the sale honors the quote and converts it
        q = client.post("/quotes", json={"customer_id": cust["id"], "items": [{"product_id": show["id"], "quantity": 1},
                                                                              {"product_id": extra["id"], "quantity": 2, "discount": 500}]}, headers=b.H).json()
        assert b.book(other, [show], start=start, quote_id=q["id"], extra={venue["id"]: "X"}).json()["detail"]["code"] == "quote_customer"
        appt = b.book(cust, [show, extra], start=start, quote_id=q["id"], extra={venue["id"]: "Jardín Las Flores", guests["id"]: "150"}).json()
        assert appt["extra"] == {venue["id"]: "Jardín Las Flores", guests["id"]: "150"} and appt["quote_id"] == q["id"]
        assert Decimal(str(appt["sale_total"])) == 12500 and appt["quote_status"] == "CONVERTED"
        assert b.sale(appt["sale_id"])["quote_id"] == q["id"]
        assert b.book(cust, [show], quote_id=q["id"], extra={venue["id"]: "Y"}).json()["detail"]["code"] == "quote_status"
        changed = client.patch(f"/appointments/{appt['id']}", json={"extra": {venue["id"]: "Salón Real", guests["id"]: ""}}, headers=b.H).json()
        assert changed["extra"] == {venue["id"]: "Salón Real"}

        # A quote made from an event booked without a register: its sale, made later, uses it
        b.release()
        e2 = b.book(cust, [show], start=start, extra={venue["id"]: "Z"}).json()
        assert e2["sale_pending"] == "register"
        assert client.post(f"/appointments/{e2['id']}/quote", headers=b.H).json()["quote_status"] == "OPEN"
        b.occupy()
        e2 = client.post(f"/appointments/{e2['id']}/sale", headers=b.H).json()
        assert e2["quote_status"] == "CONVERTED" and Decimal(str(e2["sale_balance"])) == 10000
    finally:
        b.cleanup()
        for f in (venue, guests):
            client.delete(f"/custom-fields/{f['id']}", headers=A)
