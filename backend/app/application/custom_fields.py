"""Values of custom fields (customers.extra): one validation for create and edit."""
import re
from datetime import date

from app.application.errors import Invalid

MAX_TEXT, MAX_LONG = 200, 2000


def clean_extra(fields: list[dict], values: dict, previous: dict | None = None) -> dict:
    """Checks `values` (field id -> raw value) against the active field definitions and returns what to store.
    Values of fields that were deleted stay as they were (history); unknown keys are refused."""
    active = {str(f["id"]): f for f in fields}
    unknown = [k for k in values if k not in active]
    if unknown:
        raise Invalid({"message": "unknown custom fields", "field": "extra", "keys": unknown})
    out = {k: v for k, v in (previous or {}).items() if k not in active}
    errors = {}
    for key, f in active.items():
        raw = values.get(key)
        empty = raw is None or (isinstance(raw, str) and not raw.strip())
        if empty:
            if f["required"]:
                errors[key] = "required"
            continue
        try:
            out[key] = _value(f, raw)
        except ValueError as e:
            errors[key] = str(e)
    if errors:
        raise Invalid({"message": "check the additional fields", "field": "extra", "errors": errors})
    return out


def _value(f: dict, raw):
    t = f["field_type"]
    if t in ("text", "long_text"):
        text = str(raw).strip()
        if len(text) > (MAX_TEXT if t == "text" else MAX_LONG):
            raise ValueError("too_long")
        return text
    if t == "number":
        if isinstance(raw, bool) or not re.fullmatch(r"-?\d+(\.\d+)?", str(raw).strip()):
            raise ValueError("number")
        return str(raw).strip()  # as text: no float rounding
    if t == "date":
        try:
            return date.fromisoformat(str(raw).strip()).isoformat()
        except ValueError:
            raise ValueError("date") from None
    if t == "select":
        if str(raw) not in f["options"]:
            raise ValueError("option")
        return str(raw)
    if t == "boolean":
        if raw in (True, "true", "1", "on", "yes"):
            return True
        if raw in (False, "false", "0", "off", "no"):
            return False
        raise ValueError("boolean")
    raise ValueError("type")


# Suggested when a business picks its type and has no customer fields yet (they can edit or remove them)
SUGGESTED = {
    "health": [
        ("Fecha de nacimiento", "date", []), ("Sexo", "select", ["Femenino", "Masculino", "Otro"]),
        ("Tipo de sangre", "select", ["O+", "O-", "A+", "A-", "B+", "B-", "AB+", "AB-", "No sabe"]),
        ("Alergias", "long_text", []), ("Contacto de emergencia", "text", []),
    ],
    "beauty": [
        ("Fecha de nacimiento", "date", []), ("Tipo de cabello", "select", ["Liso", "Ondulado", "Rizado", "Afro"]),
        ("Alergias o sensibilidades", "long_text", []), ("Preferencias", "long_text", []),
    ],
    "music": [
        ("Tipo de cliente", "select", ["Particular", "Empresa", "Salón o recinto", "Agencia o wedding planner"]),
        ("Cómo nos conoció", "select", ["Recomendación", "Redes sociales", "Evento anterior", "Otro"]),
        ("Géneros o canciones favoritas", "long_text", []),
    ],
}


# Suggested data of each appointment / event when a business picks its type and has none yet
SUGGESTED_APPOINTMENT = {
    "music": [
        ("Tipo de evento", "select", ["Boda", "XV años", "Cumpleaños", "Empresa", "Bautizo", "Otro"]),
        ("Lugar", "text", []), ("Dirección", "long_text", []), ("Invitados", "number", []),
        ("Hora de montaje", "text", []), ("Contacto en el lugar", "text", []),
    ],
}
