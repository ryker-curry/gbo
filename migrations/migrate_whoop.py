"""
GBO -- Migration: WHOOP pilot (Oct 2026).

Run once, after pulling this update:
    python3 -m migrations.migrate_whoop

Creates (nothing existing changes):
  - whoop_connect_links, whoop_connections, whoop_daily, whoop_workouts
    (see the WHOOP section at the bottom of models.py)
  - whoop_tokens -- the players' WHOOP OAuth tokens, encrypted by the Edge
    Functions. No ORM model; only the Edge Functions read or write it.
  - Row Level Security ON for all five tables with no policies, so the
    public (anon) API key can't read any of it. The GBO app's own database
    login and the Edge Functions' service role are unaffected.
  - Two random keys in Supabase Vault (whoop_sync_key, whoop_token_key) and
    public.whoop_secret(name), callable only by the service role, so the
    Edge Functions can read them without anyone copying keys around.
  - pg_cron + pg_net, and a job that calls the whoop-sync Edge Function at
    13:15 and 19:15 UTC (8:15 am / 2:15 pm Central in CDT) every day.

Safe to re-run.
"""

from sqlalchemy import text
from database import engine

SYNC_URL = "https://zjqwirsxofosungqoyau.supabase.co/functions/v1/whoop-sync"
CRON_SCHEDULE = "15 13,19 * * *"

TABLES_SQL = [
    """
    CREATE TABLE IF NOT EXISTS whoop_connect_links (
        link_id SERIAL PRIMARY KEY,
        player_id INTEGER NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
        state VARCHAR(64) NOT NULL UNIQUE,
        created_by_user_id INTEGER REFERENCES users(user_id),
        expires_at TIMESTAMP NOT NULL,
        used_at TIMESTAMP,
        created_at TIMESTAMP NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS whoop_connections (
        connection_id SERIAL PRIMARY KEY,
        player_id INTEGER NOT NULL UNIQUE REFERENCES players(player_id) ON DELETE CASCADE,
        whoop_user_id BIGINT,
        whoop_name VARCHAR(150),
        scopes TEXT,
        status VARCHAR(20) NOT NULL DEFAULT 'connected',
        last_error TEXT,
        connected_at TIMESTAMP,
        last_synced_at TIMESTAMP,
        active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMP NOT NULL DEFAULT now(),
        updated_at TIMESTAMP NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS whoop_tokens (
        player_id INTEGER PRIMARY KEY REFERENCES players(player_id) ON DELETE CASCADE,
        access_token_enc TEXT NOT NULL,
        refresh_token_enc TEXT,
        expires_at TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS whoop_daily (
        whoop_daily_id SERIAL PRIMARY KEY,
        player_id INTEGER NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
        cycle_id BIGINT NOT NULL,
        day_date DATE NOT NULL,
        cycle_start TIMESTAMP,
        cycle_end TIMESTAMP,
        timezone_offset VARCHAR(10),
        cycle_score_state VARCHAR(20),
        day_strain NUMERIC(5,2),
        kilojoule NUMERIC(10,2),
        avg_hr INTEGER,
        max_hr INTEGER,
        recovery_score_state VARCHAR(20),
        recovery_score NUMERIC(5,1),
        hrv_rmssd_ms NUMERIC(7,2),
        resting_hr NUMERIC(5,1),
        spo2_pct NUMERIC(5,2),
        skin_temp_c NUMERIC(5,2),
        user_calibrating BOOLEAN,
        sleep_id VARCHAR(64),
        sleep_start TIMESTAMP,
        sleep_end TIMESTAMP,
        sleep_score_state VARCHAR(20),
        sleep_performance_pct NUMERIC(5,1),
        sleep_consistency_pct NUMERIC(5,1),
        sleep_efficiency_pct NUMERIC(5,1),
        respiratory_rate NUMERIC(5,2),
        total_sleep_min NUMERIC(6,1),
        in_bed_min NUMERIC(6,1),
        light_sleep_min NUMERIC(6,1),
        deep_sleep_min NUMERIC(6,1),
        rem_sleep_min NUMERIC(6,1),
        awake_min NUMERIC(6,1),
        sleep_need_min NUMERIC(6,1),
        disturbances INTEGER,
        created_at TIMESTAMP NOT NULL DEFAULT now(),
        updated_at TIMESTAMP NOT NULL DEFAULT now(),
        CONSTRAINT uq_whoop_daily_player_cycle UNIQUE (player_id, cycle_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_whoop_daily_player_day ON whoop_daily (player_id, day_date)",
    """
    CREATE TABLE IF NOT EXISTS whoop_workouts (
        whoop_workout_id VARCHAR(64) PRIMARY KEY,
        player_id INTEGER NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
        day_date DATE,
        start_time TIMESTAMP,
        end_time TIMESTAMP,
        timezone_offset VARCHAR(10),
        sport_name VARCHAR(80),
        score_state VARCHAR(20),
        strain NUMERIC(5,2),
        avg_hr INTEGER,
        max_hr INTEGER,
        kilojoule NUMERIC(10,2),
        zone_durations JSON,
        created_at TIMESTAMP NOT NULL DEFAULT now(),
        updated_at TIMESTAMP NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_whoop_workouts_player_day ON whoop_workouts (player_id, day_date)",
]

RLS_TABLES = ["whoop_connect_links", "whoop_connections", "whoop_tokens", "whoop_daily", "whoop_workouts"]

SECRETS_SQL = [
    # Random keys, created only if missing (re-running never rotates them --
    # rotating whoop_token_key would make the stored tokens unreadable).
    """
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM vault.secrets WHERE name = 'whoop_sync_key') THEN
            PERFORM vault.create_secret(encode(extensions.gen_random_bytes(32), 'hex'), 'whoop_sync_key',
                                        'GBO: shared key the pg_cron job sends to the whoop-sync Edge Function');
        END IF;
        IF NOT EXISTS (SELECT 1 FROM vault.secrets WHERE name = 'whoop_token_key') THEN
            PERFORM vault.create_secret(encode(extensions.gen_random_bytes(32), 'base64'), 'whoop_token_key',
                                        'GBO: AES-256 key the WHOOP Edge Functions encrypt OAuth tokens with');
        END IF;
    END $$
    """,
    """
    CREATE OR REPLACE FUNCTION public.whoop_secret(secret_name TEXT)
    RETURNS TEXT
    LANGUAGE sql
    SECURITY DEFINER
    SET search_path = ''
    AS $fn$
        SELECT decrypted_secret FROM vault.decrypted_secrets
        WHERE name = secret_name AND secret_name IN ('whoop_sync_key', 'whoop_token_key')
    $fn$
    """,
    "REVOKE ALL ON FUNCTION public.whoop_secret(TEXT) FROM PUBLIC",
    "REVOKE ALL ON FUNCTION public.whoop_secret(TEXT) FROM anon, authenticated",
    "GRANT EXECUTE ON FUNCTION public.whoop_secret(TEXT) TO service_role",
]

CRON_SQL = [
    "CREATE EXTENSION IF NOT EXISTS pg_net",
    "CREATE EXTENSION IF NOT EXISTS pg_cron",
    f"""
    SELECT cron.schedule('gbo-whoop-sync', '{CRON_SCHEDULE}', $job$
        SELECT net.http_post(
            url := '{SYNC_URL}',
            headers := jsonb_build_object(
                'Content-Type', 'application/json',
                'x-sync-key', (SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name = 'whoop_sync_key')
            ),
            body := '{{}}'::jsonb,
            timeout_milliseconds := 120000
        )
    $job$)
    """,
]


def main():
    print("Creating WHOOP tables...")
    with engine.begin() as conn:
        for sql in TABLES_SQL:
            conn.execute(text(sql))
        for t in RLS_TABLES:
            conn.execute(text(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY"))
    print("Creating Vault keys + whoop_secret()...")
    with engine.begin() as conn:
        for sql in SECRETS_SQL:
            conn.execute(text(sql))
    print("Scheduling the twice-daily sync (pg_cron)...")
    with engine.begin() as conn:
        for sql in CRON_SQL:
            conn.execute(text(sql))
    print("Done. Next: deploy the whoop-oauth-callback and whoop-sync Edge Functions and add "
          "WHOOP_CLIENT_ID / WHOOP_CLIENT_SECRET under Edge Functions > Secrets.")


if __name__ == "__main__":
    main()
