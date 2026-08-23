"""
GBO — Migration: Intended Location & Command Tracker, Phase 1.

Creates the new command_pitches table (models.CommandPitch). No changes
to any existing table -- BullpenSession, BullpenPitch, RapsodoPitch,
PitchType, Player, etc. are all reused as-is by the Command Tracker; see
the architecture doc agreed with Ryker (Aug 2026) for the full reasoning.

Uses the same Base.metadata.create_all(bind=engine) approach as
migrate_rapsodo_bullpen.py's table-creation step -- safe to run against
an existing database, since SQLAlchemy only creates tables that don't
already exist and leaves every other table untouched.

Run once, after pulling this update, as a module from the repo root:
    python -m migrations.migrate_command_pitches
"""

from database import engine, Base
import models  # noqa: F401 -- registers all model classes (including the new CommandPitch) with Base


def main():
    print("Creating command_pitches table (if it doesn't already exist)...")
    Base.metadata.create_all(bind=engine)
    print("Done. No existing tables were modified.")


if __name__ == "__main__":
    main()
