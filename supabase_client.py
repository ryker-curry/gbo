"""
GBO — Supabase client helper (used for Auth, not for data queries).

Data queries still go through SQLAlchemy (database.py / models.py) against
the same Postgres instance. This client is only for Supabase's Auth API
(sign in, sign out, and -- for admins -- creating new user accounts).

Reads from a local .env file (via python-dotenv) when running on a
laptop, or from Streamlit Cloud's secrets manager once deployed there --
.env files aren't used in that environment, so this falls back to
st.secrets if the environment variable isn't set.
"""

import os
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()


def _get_secret(key: str):
    value = os.environ.get(key)
    if not value:
        try:
            import streamlit as st
            value = st.secrets.get(key)
        except Exception:
            pass
    return value


SUPABASE_URL = _get_secret("SUPABASE_URL")
SUPABASE_ANON_KEY = _get_secret("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_ROLE_KEY = _get_secret("SUPABASE_SERVICE_ROLE_KEY")


def get_supabase_client() -> Client:
    """Client for regular auth actions (login/logout) -- safe to use anywhere."""
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_ANON_KEY must be set in .env "
            "(see .env.example)."
        )
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


def get_supabase_admin_client() -> Client:
    """Client with the service-role key -- can create/delete user accounts.

    Only use this in Administrator-only code paths (e.g. the future User
    Management page). Never expose the service role key to end users.
    """
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env "
            "to use admin account-creation features."
        )
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
