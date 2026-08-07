"""
GBO — Migration: give Sports Scientist edit rights on assessment data.

Sports Scientist can now enter/edit Assessments manually, bulk-import
via Import Rapsodo Data, and upload video on Video Review -- all three
are gated by the same can_edit_assessments flag. Sessions (Bullpen/
Hitter Tracking) and IDP stay read-only for this role.

Run once, after pulling this update.

Run:
    python migrate_sports_scientist_edit_rights.py
"""

from database import get_session
from models import Role


def main():
    session = get_session()
    try:
        role = session.query(Role).filter(Role.role_name == "Sports Scientist").first()
        if role is None:
            print("Sports Scientist role not found -- nothing to update.")
            return
        role.can_edit_assessments = True
        role.description = "Assessment data (manual entry + Rapsodo import) and video upload -- edit rights. Sessions/IDP -- read-only."
        session.commit()
        print("Sports Scientist now has can_edit_assessments = True.")
    finally:
        session.close()


if __name__ == "__main__":
    main()