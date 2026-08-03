# Gorilla Baseball Operations (GBO) — Milestone 1

Foundation: repo structure, Supabase/Postgres schema, and a login-to-navigation
skeleton. This is **not** a working app yet — no module screens are built out.
That starts with Player Management (Aug 4–6 per the schedule).

## What's in this milestone

- `database.py` — SQLAlchemy engine/session pointed at Supabase Postgres
- `models.py` — every MVP table, fully normalized, plus stub tables for
  deferred modules (Training, Recovery, Video, Reports, Research, Scouting)
  so the schema never needs a breaking migration later
- `seed_lookups.py` — seeds Roles, Assessment Categories, IDP Statuses
  (placeholder names — confirm before the IDP build), and Session Types
- `init_db.py` — creates all tables and runs the seed
- `supabase_client.py` — Supabase Auth client helpers
- `create_admin_user.py` — one-time script to bootstrap your own login
- `app.py` + `pages/` — Streamlit skeleton proving Supabase email/password
  login → role lookup → role-based navigation works end-to-end

**Auth note:** login uses Supabase email/password, not Microsoft Entra/Pitt
State accounts. That switch happened because Entra login requires Pitt
State Azure/IT admin access to register an app, which isn't available —
and the Aug 17 deadline can't depend on an external approval process. Each
GBO user gets a dedicated GBO account (email + password) instead.

## Setup

1. Create a free Supabase project at supabase.com.
2. In the project, go to **Settings → Database** and copy the Postgres
   connection string (URI, "Session" mode).
3. Go to **Settings → API** and copy the Project URL, `anon` public key,
   and `service_role` key.
4. Copy `.env.example` to `.env` and fill in all four values
   (`DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`,
   `SUPABASE_SERVICE_ROLE_KEY`).
5. In Supabase, go to **Authentication → Providers** and make sure
   Email is enabled (it is by default). Under **Authentication → Settings**,
   you can turn off "Confirm email" for now so test accounts work
   immediately without email verification.
6. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
7. Initialize the database:
   ```
   python init_db.py
   ```
8. Create your own Administrator login:
   ```
   python create_admin_user.py
   ```
9. Run the app:
   ```
   streamlit run app.py
   ```
   Log in with the email/password you just created.

## Known open items before the next milestone

- **Assessment test types are not populated.** `AssessmentTestType` rows
  (the actual tests within each of the 7 buckets — e.g. specific ROM
  measurements, strength tests) are pending Ryker's protocol document.
  The table structure is final; only the rows are missing.
- **IDP status names are placeholders** (Not Started / In Progress /
  Completed / On Hold) — not yet confirmed.
- **Player.position** is a free-text field for now — flagged in code for
  future normalization to a lookup table; not blocking for MVP.
- **Row-level enforcement is app-layer only in this milestone.** Every
  query must filter by role/organization/assignment in application code
  (per `Role.can_view_all_players` etc.) — Postgres RLS policies can be
  added later for defense-in-depth but are not required for the MVP.

## Schema overview

```
organizations → teams → players → users (role, optional player_id)
                              ↓
                    staff_player_assignments (coach/staff ↔ player)

assessment_categories → assessment_test_types (STUB rows pending)
players → assessments → assessment_results

assessment_categories → idp_goals ← assessments (source_assessment_id)
idp_goals → idp_action_steps
idp_goals → idp_progress_notes

session_types → individual_sessions ← players, users (coach)

-- future-module stubs, no app logic wired yet --
training_routines · recovery_tests · videos · reports
research_projects · scouting_reports
```
