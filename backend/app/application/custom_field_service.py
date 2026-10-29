from app.application.errors import Conflict, Invalid, NotFound
from app.application.ports.custom_field_repository import CustomFieldRepository


class CustomFieldService:
    """Definitions of the extra data kept about customers (module "settings" changes them)."""

    def __init__(self, repo: CustomFieldRepository):
        self.repo = repo

    def list(self, entity="customer"):
        return self.repo.active(entity)

    def create(self, uid, data):
        self._check(data)
        row = self.repo.create(uid, data)
        if row is None:
            raise Conflict({"message": "another field has that name", "field": "label"})
        self.repo.commit()
        return row

    def update(self, uid, field_id, data):
        current = self.repo.get(field_id)
        if current is None or current["deleted_at"] is not None:
            raise NotFound("field not found")
        if "field_type" in data and data["field_type"] != current["field_type"]:
            # Stored values were checked against the old type: a new type would make them wrong
            raise Invalid({"message": "the type of a field can't change; create a new field", "field": "field_type"})
        self._check({**current, **data})
        row = self.repo.update(uid, field_id, data)
        if row is None:
            raise Conflict({"message": "another field has that name", "field": "label"})
        self.repo.commit()
        return row

    def delete(self, uid, field_id):
        """The definition goes; values already stored stay in each customer's history."""
        current = self.repo.get(field_id)
        if current is None or current["deleted_at"] is not None:
            raise NotFound("field not found")
        self.repo.delete(uid, field_id)
        self.repo.commit()

    @staticmethod
    def _check(data):
        options = data.get("options") or []
        if data.get("field_type") == "select" and not options:
            raise Invalid({"message": "a list needs at least one option", "field": "options"})
        if len({o.lower() for o in options}) != len(options):
            raise Invalid({"message": "options are repeated", "field": "options"})
