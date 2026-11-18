"""
GBO -- Migration: testing-workbook importer (Oct 2026).

Run once, after pulling this update:
    python3 -m migrations.migrate_study_workbook

  1. Creates research_fb_outcomes (models.ResearchFBOutcome) -- the study's
     fastball outcomes imported from the FB VELO&SPIN tab.
  2. Seeds the two new assessment categories ("ForceFrame", "Force Plate
     Detail") and their test types (study_workbook_spec.new_test_types()).
Nothing existing changes. Safe to run more than once.
"""

from sqlalchemy import text
from database import engine, SessionLocal


def main():
    print("Creating research_fb_outcomes...")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS research_fb_outcomes (
                outcome_id SERIAL PRIMARY KEY,
                player_id INTEGER NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
                season_label VARCHAR(20) NOT NULL,
                test_date DATE,
                avg_velo NUMERIC(6, 2),
                peak_velo NUMERIC(6, 2),
                avg_spin NUMERIC(7, 1),
                peak_spin NUMERIC(7, 1),
                n_pitches INTEGER,
                note TEXT,
                updated_at TIMESTAMP NOT NULL DEFAULT now(),
                CONSTRAINT uq_research_fb_player_season UNIQUE (player_id, season_label)
            )
        """))
    print("Seeding new assessment categories / test types...")
    import seed_lookups
    db = SessionLocal()
    try:
        seed_lookups.seed_assessment_categories_and_tests(db)
    finally:
        db.close()
    print("Done. The testing-workbook importer is ready.")


if __name__ == "__main__":
    main()
