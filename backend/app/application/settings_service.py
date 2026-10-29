import uuid

from app.application.custom_fields import SUGGESTED, SUGGESTED_APPOINTMENT
from app.application.errors import Invalid, NotFound
from app.application.ports.custom_field_repository import CustomFieldRepository
from app.application.ports.settings_repository import SettingsRepository


class SettingsService:
    """Business settings changed from the app (module "settings"). Validation of each value lives in the API model."""

    def __init__(self, repo: SettingsRepository, fields: CustomFieldRepository, storage=None, to_png=None):
        self.repo = repo
        self.fields = fields
        self.storage = storage  # ImageStorage for the logo
        self.to_png = to_png  # bytes -> clean PNG bytes | None

    def get(self):
        return self.repo.all()

    def update(self, uid, values: dict):
        for key, value in values.items():
            self.repo.set(uid, key, value)
        # A business that picks its type and has no customer fields yet gets the usual ones (editable, removable)
        if values.get("business_type") in SUGGESTED and not self.fields.active("customer"):
            for n, (label, field_type, options) in enumerate(SUGGESTED[values["business_type"]]):
                self.fields.create(None, {"label": label, "field_type": field_type, "options": options, "sort_order": n})
        if values.get("business_type") in SUGGESTED_APPOINTMENT and not self.fields.active("appointment"):
            for n, (label, field_type, options) in enumerate(SUGGESTED_APPOINTMENT[values["business_type"]]):
                self.fields.create(None, {"entity": "appointment", "label": label, "field_type": field_type, "options": options, "sort_order": n})
        self.repo.commit()
        return self.repo.all()

    # --- logo (tickets, prescriptions, catalog) ---------------------------------
    def set_logo(self, uid, data: bytes):
        png = self.to_png(data)
        if png is None:
            raise Invalid({"message": "the logo must be a JPG, PNG or WebP image", "code": "bad_type"})
        old = self.repo.all().get("logo_file")
        name = f"logo-{uuid.uuid4()}.png"
        self.storage.save(name, png)
        self.repo.set(uid, "logo_file", name)
        self.repo.commit()
        if old:
            self.storage.delete(old)
        return self.repo.all()

    def clear_logo(self, uid):
        old = self.repo.all().get("logo_file")
        self.repo.set(uid, "logo_file", "")
        self.repo.commit()
        if old:
            self.storage.delete(old)

    def logo(self):
        name = self.repo.all().get("logo_file")
        if not name or not self.storage.path(name).exists():
            raise NotFound("no logo")
        return self.storage.path(name)
