import re
import uuid
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import AfterValidator, BaseModel, BeforeValidator, Field, StringConstraints

from app.application.customer_service import CustomerService
from app.infrastructure.api.fields import OptionalPhone, Phone, blank_to_none, optional_text
from app.infrastructure.api.permissions import require_permission
from app.infrastructure.persistence.custom_field_repository import SqlCustomFieldRepository
from app.infrastructure.persistence.customer_repository import SqlCustomerRepository
from app.infrastructure.persistence.database import SessionLocal

router = APIRouter(prefix="/customers", tags=["customers"])


def _email(value: str) -> str:
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):  # same rule as the DB check
        raise ValueError("enter an email like name@domain.com")
    return value


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Email = Annotated[Annotated[str, StringConstraints(max_length=255), AfterValidator(_email)] | None,
                  BeforeValidator(blank_to_none)]
Company = optional_text(200)
Address = optional_text(500)
CreditLimit = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]


class CustomerIn(BaseModel):
    full_name: Name
    phone: Phone
    email: Email = None
    company: Company = None
    address: Address = None
    additional_phone: OptionalPhone = None
    credit_limit: CreditLimit = Decimal(0)
    extra: dict[str, Any] = Field(default_factory=dict, max_length=100)  # custom field id -> value
    price_list_id: uuid.UUID | None = None  # the prices this customer pays (mayoreo, frecuente...)


# PATCH is partial. A non-optional type with default None means the field can be omitted but not sent as null;
# optional fields are cleared by sending null.
class CustomerPatch(BaseModel):
    full_name: Name = None
    phone: Phone = None
    email: Email = None
    company: Company = None
    address: Address = None
    additional_phone: OptionalPhone = None
    credit_limit: CreditLimit = None
    extra: dict[str, Any] = Field(default=None, max_length=100)
    price_list_id: uuid.UUID | None = None


def get_service():
    with SessionLocal() as session:
        yield CustomerService(SqlCustomerRepository(session), SqlCustomFieldRepository(session))


Svc = Annotated[CustomerService, Depends(get_service)]
Read, Create, Update, Delete = (require_permission("customers", p) for p in ("read", "create", "update", "delete"))
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


@router.get("")
def search_customers(_: Read, svc: Svc, q: Annotated[str, Query(max_length=100)] = "",
                     page: Page = 1, page_size: PageSize = 25, sort: Literal["name", "recent"] = "name"):
    return svc.search(q, page, page_size, sort)


@router.post("", status_code=201)
def create_customer(body: CustomerIn, uid: Create, svc: Svc):
    return svc.create(uid, body.model_dump())


@router.get("/{customer_id}")
def get_customer(customer_id: uuid.UUID, _: Read, svc: Svc):
    return svc.get(customer_id)


@router.patch("/{customer_id}")
def update_customer(customer_id: uuid.UUID, body: CustomerPatch, uid: Update, svc: Svc):
    return svc.update(uid, customer_id, body.model_dump(exclude_unset=True))


@router.delete("/{customer_id}", status_code=204)
def delete_customer(customer_id: uuid.UUID, uid: Delete, svc: Svc):
    svc.delete(uid, customer_id)


@router.post("/{customer_id}/restore")
def restore_customer(customer_id: uuid.UUID, uid: Delete, svc: Svc):
    return svc.restore(uid, customer_id)


@router.get("/{customer_id}/history")
def customer_history(customer_id: uuid.UUID, _: Read, svc: Svc, page: Page = 1, page_size: PageSize = 25):
    return svc.history(customer_id, page, page_size)


@router.get("/{customer_id}/credit")
def customer_credit(customer_id: uuid.UUID, _: Read, svc: Svc):
    return svc.credit(customer_id)


@router.get("/{customer_id}/credit/movements")
def customer_credit_movements(customer_id: uuid.UUID, _: Read, svc: Svc, page: Page = 1, page_size: PageSize = 25):
    return svc.credit_movements(customer_id, page, page_size)


@router.get("/{customer_id}/credit/pending-sales")
def customer_pending_sales(customer_id: uuid.UUID, _: Read, svc: Svc, page: Page = 1, page_size: PageSize = 25):
    return svc.pending_sales(customer_id, page, page_size)


@router.get("/{customer_id}/sales")
def customer_sales(customer_id: uuid.UUID, _: Read, svc: Svc, page: Page = 1, page_size: PageSize = 25):
    return svc.sales(customer_id, page, page_size)
