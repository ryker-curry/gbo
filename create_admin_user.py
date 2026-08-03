"""
GBO — Create the first Administrator account.

There's no User Management screen yet (that's part of the Aug 4-6
milestone), so this script bootstraps your own login: it creates a
Supabase Auth account and a matching row in the `users` table with the
Administrator role, tied to a starter Organization/Team.

Run once, interactively:
    python create_admin_user.py
"""

from getpass import getpass

from database import get_session
from models import Organization, Team, Role, User
from supabase_client import get_supabase_admin_client


def main():
    email = input("Your email (this becomes your GBO login): ").strip()
    password = getpass("Choose a password (min 6 characters): ").strip()
    first_name = input("First name: ").strip()
    last_name = input("Last name: ").strip()

    # 1. Create the Supabase Auth account
    admin_client = get_supabase_admin_client()
    auth_result = admin_client.auth.admin.create_user(
        {"email": email, "password": password, "email_confirm": True}
    )
    auth_subject_id = auth_result.user.id
    print(f"Created Supabase Auth account: {auth_subject_id}")

    # 2. Create matching GBO records
    session = get_session()
    try:
        org = session.query(Organization).first()
        if org is None:
            org = Organization(organization_name="Pittsburg State Gorilla Baseball")
            session.add(org)
            session.flush()
            print("Created starter Organization.")

        team = session.query(Team).filter(Team.organization_id == org.organization_id).first()
        if team is None:
            team = Team(organization_id=org.organization_id, team_name="Gorilla Baseball", season_year=2026)
            session.add(team)
            session.flush()
            print("Created starter Team.")

        admin_role = session.query(Role).filter(Role.role_name == "Administrator").first()
        if admin_role is None:
            raise RuntimeError("Administrator role not found -- run init_db.py first to seed lookup tables.")

        existing = session.query(User).filter(User.email == email).first()
        if existing:
            print(f"A users row for {email} already exists (user_id={existing.user_id}). Nothing more to do.")
            return

        admin_user = User(
            organization_id=org.organization_id,
            auth_subject_id=auth_subject_id,
            email=email,
            first_name=first_name,
            last_name=last_name,
            role_id=admin_role.role_id,
            active=True,
        )
        session.add(admin_user)
        session.commit()
        print(f"Created Administrator user: {first_name} {last_name} <{email}>")
        print("You can now log in to the app with this email and password.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
