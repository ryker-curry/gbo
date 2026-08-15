"""
GBO — Database connection setup.

Milestone 1: points SQLAlchemy at Supabase/Postgres instead of the
old SQLite file. Nothing about the ORM models needs to change to make
this swap — only the connection string.

Reads DATABASE_URL from a local .env file (via python-dotenv) when
running on a laptop, or from the deployment platform's own environment
variables in production -- same os.environ path either way. (Previously
also fell back to st.secrets for Streamlit Cloud; removed now that the
UI layer is Shiny, not Streamlit -- this module has no UI-framework
dependency at all anymore.)
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Copy .env.example to .env and fill in "
        "your Supabase connection string before running the app."
    )

# pool_pre_ping avoids stale-connection errors after Supabase idles a connection.
# connect_timeout means a real connectivity problem raises a clear error within
# 10 seconds instead of the app spinning forever with no message.
# pool_size/max_overflow kept small and pool_recycle set so this app doesn't
# accumulate more open connections than it actually needs -- Supabase's
# pooler (especially session mode) has a hard cap on total connections, and
# this ran into it once already.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=3,
    max_overflow=2,
    pool_recycle=300,
    connect_args={"connect_timeout": 10},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

Base = declarative_base()


def get_session():
    """Yield a database session; caller is responsible for closing it.

    Usage:
        session = get_session()
        try:
            ...
        finally:
            session.close()
    """
    return SessionLocal()
