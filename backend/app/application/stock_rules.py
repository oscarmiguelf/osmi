"""Rules every stock movement shares (adjustments, purchases, transfers). The DB doesn't enforce these."""
from decimal import Decimal

from app.application.errors import Invalid

INTEGER_UNITS = {"unit", "service"}  # counted in whole pieces; kg / lt / g allow 3 decimals


def check_stock_product(product: dict | None, quantity: Decimal, field: str = "product_id",
                        quantity_field: str = "quantity") -> None:
    """product: {id, name, tracks_stock, is_kit, unit, deleted_at} or None."""
    if product is None or product["deleted_at"] is not None:
        raise Invalid({"message": "the product doesn't exist or is deleted", "field": field})
    if not product["tracks_stock"] or product["is_kit"]:
        raise Invalid({"message": f"{product['name']} has no stock of its own (service or kit)", "field": field,
                       "product_id": str(product["id"])})
    if product["unit"].lower() in INTEGER_UNITS and quantity != quantity.to_integral_value():
        raise Invalid({"message": f"{product['name']} is counted in whole units", "field": quantity_field,
                       "product_id": str(product["id"])})
