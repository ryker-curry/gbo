"""
GBO — Migration: add Bullpen Scripts (bullpen_scripts, bullpen_script_pitches).

Run once, after pulling this update. Depends on bullpen_types and
pitch_types already existing.

Run:
    python migrate_bullpen_scripts.py
"""

from database import engine, Base
import models  # noqa: F401 -- registers all model classes with Base


def main():
    Base.metadata.create_all(bind=engine)
    print("Created bullpen_scripts and bullpen_script_pitches tables.")


if __name__ == "__main__":
    main()