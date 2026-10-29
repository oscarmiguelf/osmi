"""Request field types shared by several APIs."""
import re
from typing import Annotated

from pydantic import AfterValidator, BeforeValidator, StringConstraints


def blank_to_none(value):
    if isinstance(value, str):
        return value.strip() or None
    return value


def _phone(value: str) -> str:
    digits = re.sub(r"[\s\-().]", "", value)  # people type "(55) 1234-5678"; the DB stores 5512345678
    if not re.fullmatch(r"[0-9]{10}", digits):
        raise ValueError("phone must have exactly 10 digits, without country code")
    return digits


Phone = Annotated[str, AfterValidator(_phone)]
OptionalPhone = Annotated[Phone | None, BeforeValidator(blank_to_none)]


def optional_text(max_length: int):
    """Trimmed text up to max_length; blank becomes null."""
    return Annotated[Annotated[str, StringConstraints(max_length=max_length)] | None, BeforeValidator(blank_to_none)]
