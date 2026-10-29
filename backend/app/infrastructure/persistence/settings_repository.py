from sqlalchemy import text
from sqlalchemy.orm import Session


class SqlSettingsRepository:
    def __init__(self, session: Session):
        self.session = session

    def all(self):
        return {r.key: r.value for r in self.session.execute(text("SELECT key, value FROM settings"))}

    def set(self, user_id, key, value):
        self.session.execute(text("""
            INSERT INTO settings (key, value, updated_by) VALUES (:k, :v, :uid)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_by = EXCLUDED.updated_by
        """), {"k": key, "v": value, "uid": user_id})

    def commit(self):
        self.session.commit()
