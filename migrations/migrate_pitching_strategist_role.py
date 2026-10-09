"""
GBO -- Migration: add the "Pitching Strategist" role (Oct 2026, Ryker).

Run once, after pulling this update:
    python3 -m migrations.migrate_pitching_strategist_role

Additive only -- one new row in roles, with the same permission flags as
"Coach". At login, shiny_app/auth.py (ROLE_ALIASES) runs a Pitching
Strategist as Coach + Pitching specialty, so they get exactly a pitching
coach's pages and edit rights; the sidebar badge shows the real title.
Then create the login in User Management and assign their pitchers in
Staff Assignments.
"""

from sqlalchemy import text
from database import engine

DESCRIPTION = ("Pitching coach access (assigned players): game planning, pitch design, bullpen usage, "
               "in-game decisions and pitch calling.")


def main():
    with engine.begin() as conn:
        if conn.execute(text("SELECT 1 FROM roles WHERE role_name = 'Pitching Strategist'")).first():
            print("Pitching Strategist role already exists -- nothing to do.")
            return
        # keep the id sequence ahead of any rows seeded with explicit ids
        conn.execute(text("SELECT setval(pg_get_serial_sequence('roles', 'role_id'), (SELECT MAX(role_id) FROM roles))"))
        conn.execute(text("""
            INSERT INTO roles (role_name, description, can_edit_assessments, can_edit_idp, can_edit_sessions,
                               can_view_all_players, is_admin)
            SELECT 'Pitching Strategist', :d, can_edit_assessments, can_edit_idp, can_edit_sessions,
                   can_view_all_players, is_admin
            FROM roles WHERE role_name = 'Coach'
        """), {"d": DESCRIPTION})
    print("Done. Pitching Strategist role added (same access as Coach + Pitching).")


if __name__ == "__main__":
    main()
