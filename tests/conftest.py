"""Shared pytest setup for GBO.

Points DATABASE_URL at a dummy Postgres URL (database.py refuses to import
without one -- nothing ever connects to it) and gives tests an in-memory
SQLite session loaded with the fake season in tests/seed.py."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost:1/db")
for p in (ROOT, os.path.join(ROOT, "shiny_app")):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402


@pytest.fixture(scope="session")
def seeded():
    from tests import seed
    engine = create_engine("sqlite://")
    db = sessionmaker(bind=engine)()
    info = seed.build(db, engine)
    yield db, info
    db.close()


@pytest.fixture(scope="session")
def db(seeded):
    return seeded[0]
