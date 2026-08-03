"""
GBO — Initialize the database.

Creates every table defined in models.py (MVP tables + future-module
stubs) against the Supabase/Postgres instance in DATABASE_URL, then seeds
lookup tables.

Usage:
    python init_db.py
"""

from database import engine, Base
import models  # noqa: F401 -- import registers all model classes with Base
from seed_lookups import run_all_seeds


def init_db():
    print("Creating tables...")
    Base.metadata.create_all(bind=engine)
    print("Tables created.")

    print("Seeding lookup tables...")
    run_all_seeds()
    print("Done.")


if __name__ == "__main__":
    init_db()
