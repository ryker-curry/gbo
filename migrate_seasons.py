"""
GBO — Migration: add Seasons (seasons, games.season_id).

Keeps fall/practice game stats separate from real spring regular-
season stats once games get aggregated into a stats page. Seeds a
default "Fall 2026" season (is_official=False, since fall ball
doesn't count toward a real record) and backfills any existing games
to it, since everything tracked so far has been fall/test games.

Run once, after pulling this update. Depends on Game Tracking already
being migrated.

Run:
    python migrate_seasons.py
"""

from sqlalchemy import text
from database import engine, Base, get_session
import models  # noqa: F401 -- registers all model classes with Base
from models import Season, Game, User


def main():
    print("Step 1: creating seasons table...")
    Base.metadata.create_all(bind=engine)
    print("Done.")

    print("Step 2: adding season_id to games...")
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE games ADD COLUMN IF NOT EXISTS season_id INTEGER REFERENCES seasons(season_id)"
        ))
    print("Done.")

    print("Step 3: seeding a default Fall 2026 season and backfilling existing games...")
    session = get_session()
    try:
        fall_season = session.query(Season).filter(Season.season_name == "Fall 2026").first()
        if fall_season is None:
            # Attribute the season to whichever admin/coach created the
            # earliest existing user, just so created_by_user_id has a
            # sensible value -- falls back to the first user found.
            any_user = session.query(User).order_by(User.user_id).first()
            if any_user is None:
                print("No users found -- can't seed a default season without a created_by user. Skipping seed (games will need season_id set manually).")
            else:
                fall_season = Season(season_name="Fall 2026", is_official=False, created_by_user_id=any_user.user_id)
                session.add(fall_season)
                session.commit()
                print("Created default season: Fall 2026 (is_official=False).")

        if fall_season:
            unassigned_games = session.query(Game).filter(Game.season_id.is_(None)).all()
            if unassigned_games:
                for g in unassigned_games:
                    g.season_id = fall_season.season_id
                session.commit()
                print(f"Backfilled {len(unassigned_games)} existing game(s) to Fall 2026.")
            else:
                print("No existing games needed backfilling.")
    finally:
        session.close()

    print("\nMigration complete.")


if __name__ == "__main__":
    main()