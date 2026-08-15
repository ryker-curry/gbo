"""
GBO — Supabase client helper (used for Auth, not for data queries).

Data queries still go through SQLAlchemy (database.py / models.py) against
the same Postgres instance. This client is only for Supabase's Auth API
(sign in, sign out, and -- for admins -- creating new user accounts).

Reads from a local .env file (via python-dotenv) when running on a
laptop, or from the deployment platform's own environment variables in
production -- same os.environ path either way. (Previously also fell
back to st.secrets for Streamlit Cloud; removed now that the UI layer
is Shiny, not Streamlit -- this module has no UI-framework dependency
at all anymore.)
"""

import os
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()


def _get_secret(key: str):
    return os.environ.get(key)


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
