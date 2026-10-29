import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Every connection works in UTC so TIMESTAMPTZ values are read and written as UTC.
engine = create_engine(os.environ["DATABASE_URL"], connect_args={"options": "-c timezone=UTC"})
SessionLocal = sessionmaker(bind=engine)
