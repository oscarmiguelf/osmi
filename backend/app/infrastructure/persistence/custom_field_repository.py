import json

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

COLUMNS = "id, entity, label, field_type, options, required, sort_order, deleted_at"


class SqlCustomFieldRepository:
    def __init__(self, session: Session):
        self.session = session

    def _one(self, sql, **params):
        try:
            with self.session.begin_nested():
                row = self.session.execute(text(sql), params).mappings().first()
        except IntegrityError:  # uq_custom_fields_label
            return None
        return dict(row) if row else None

    def active(self, entity):
        return [dict(r) for r in self.session.execute(text(f"""
            SELECT {COLUMNS} FROM custom_fields WHERE entity = :e AND deleted_at IS NULL ORDER BY sort_order, created_at
        """), {"e": entity}).mappings()]

    def get(self, field_id):
        row = self.session.execute(text(f"SELECT {COLUMNS} FROM custom_fields WHERE id = :id"), {"id": field_id}).mappings().first()
        return dict(row) if row else None

    def create(self, user_id, data):
        return self._one(f"""
            INSERT INTO custom_fields (entity, label, field_type, options, required, sort_order, created_by, updated_by)
            VALUES (CAST(:entity AS varchar), :label, :field_type, CAST(:options AS jsonb), :required,
                    COALESCE(:sort_order, (SELECT COALESCE(MAX(sort_order) + 1, 0) FROM custom_fields
                                           WHERE entity = CAST(:entity AS varchar) AND deleted_at IS NULL)),
                    :uid, :uid)
            RETURNING {COLUMNS}
        """, entity=data.get("entity", "customer"), label=data["label"], field_type=data["field_type"],
            options=json.dumps(data.get("options") or []), required=data.get("required", False), sort_order=data.get("sort_order"), uid=user_id)

    def update(self, user_id, field_id, data):
        params = {**data, "uid": user_id, "id": field_id}
        if "options" in params:
            params["options"] = json.dumps(params["options"])
        sets = "".join(f"{k} = {'CAST(:options AS jsonb)' if k == 'options' else ':' + k}, " for k in data)  # keys from the request model
        return self._one(f"UPDATE custom_fields SET {sets}updated_by = :uid WHERE id = :id AND deleted_at IS NULL RETURNING {COLUMNS}", **params)

    def delete(self, user_id, field_id):
        self.session.execute(text("""
            UPDATE custom_fields SET deleted_at = NOW(), deleted_by = :uid, updated_by = :uid WHERE id = :id AND deleted_at IS NULL
        """), {"uid": user_id, "id": field_id})

    def commit(self):
        self.session.commit()
