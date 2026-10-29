from app.application.errors import Invalid, NotFound
from app.application.ports.benefit_repository import BenefitRepository


class BenefitService:
    """What a product gives when sold (package of sessions / membership), and what each customer has."""

    def __init__(self, repo: BenefitRepository):
        self.repo = repo

    def set(self, uid, product_id, data):
        product = self.repo.product_kind(product_id)
        if product is None:
            raise NotFound("product not found")
        if product["tracks_stock"] or product["is_kit"]:  # it's sold like a service: nothing to take from stock
            raise Invalid({"message": "only a service-type product can be a package or a membership", "field": "kind"})
        if data["kind"] == "package":
            service = self.repo.product_kind(data.get("service_product_id")) if data.get("service_product_id") else None
            if service is None or service["tracks_stock"] or service["is_kit"] or service["id"] == product_id:
                raise Invalid({"message": "a package needs the service it gives sessions of", "field": "service_product_id"})
            if not data.get("sessions"):
                raise Invalid({"message": "how many sessions does the package give?", "field": "sessions"})
            data = {**data, "price_list_id": None}
        else:
            if not data.get("valid_days"):
                raise Invalid({"message": "how many days does the membership last?", "field": "valid_days"})
            if data.get("price_list_id") and not self.repo.price_list_active(data["price_list_id"]):
                raise Invalid({"message": "the price list doesn't exist", "field": "price_list_id"})
            data = {**data, "service_product_id": None, "sessions": None}
        self.repo.set_benefit(uid, product_id, data)
        self.repo.commit()
        return data

    def clear(self, product_id):
        self.repo.clear_benefit(product_id)
        self.repo.commit()

    def of_customer(self, customer_id):
        return self.repo.customer_benefits(customer_id)

    def expiring(self, days):
        return self.repo.expiring(days)
