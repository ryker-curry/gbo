"""
GBO -- Migration: lock down the public Data API (Oct 31 2026).

Run once (already applied to the live DB on Oct 31 2026 via Supabase MCP):
    python3 -m migrations.migrate_enable_rls

Fixes Supabase's "rls_disabled_in_public" / "sensitive_columns_exposed"
security alerts. For every table in the public schema:
  - Row Level Security ON, with no policies -> the anon/authenticated API
    keys can't read or write any rows.
  - All table privileges revoked from anon and authenticated.
Plus: future tables created by postgres in public no longer auto-grant
anon/authenticated.

Unaffected: the GBO app (SQLAlchemy connects as postgres, which bypasses
RLS), the WHOOP Edge Functions (service_role, bypasses RLS), Supabase Auth
login, and Storage.

Going forward: new tables are already covered by the default-privileges
line below. If an Edge Function needs a new table, add
    GRANT SELECT, INSERT, UPDATE, DELETE ON public.<table> TO service_role;
in that table's migration.

Safe to re-run.
"""

from sqlalchemy import text
from database import engine

SQL = """
DO $$
DECLARE t record;
BEGIN
  FOR t IN SELECT c.relname FROM pg_class c
           JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t.relname);
    EXECUTE format('REVOKE ALL ON public.%I FROM anon, authenticated', t.relname);
  END LOOP;
END $$;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  REVOKE ALL ON TABLES FROM anon, authenticated;
"""


def main():
    with engine.begin() as conn:
        conn.execute(text(SQL))
    print("RLS enabled and anon/authenticated access revoked on all public tables.")


if __name__ == "__main__":
    main()
