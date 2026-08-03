"""
GBO — Create a staff or Player account.

Interactive helper for the "no User Management page yet" gap -- lets
you spin up a test account for any role without hand-editing the
database. Creates a Supabase Auth account + matching users row.

For the Player role, this also links the account to an existing Player
record (User.player_id) -- required for the Player-facing dashboard
(schedule, assignments, AT appointments) to know which player they are.

Run:
    python create_staff_user.py
"""

from getpass import getpass

from database import get_session
from models import Organization, Role, User, Player
from supabase_client import get_supabase_admin_client

ALL_ROLES = [
    "Administrator", "Head Coach", "Coach", "Strength Coach",
    "Athletic Trainer", "Sports Scientist", "Data Analyst", "Player",
]


def main():
    print("Choose a role for this account:")
    for i, role in enumerate(ALL_ROLES, start=1):
        print(f"  {i}. {role}")
    choice = input("Enter number: ").strip()
    try:
        role_name = ALL_ROLES[int(choice) - 1]
    except (ValueError, IndexError):
        print("Invalid choice.")
        return

    email = input("Email (this becomes their GBO login): ").strip()
    password = getpass("Password (min 6 characters): ").strip()
    first_name = input("First name: ").strip()
    last_name = input("Last name: ").strip()

    session = get_session()
    try:
        linked_player_id = None
        if role_name == "Player":
            players = session.query(Player).filter(Player.active.is_(True)).order_by(Player.last_name, Player.first_name).all()
            if not players:
                print("No players exist on the roster yet -- add one first from the Players page.")
                return
            print("\nWhich player is this account for?")
            for i, p in enumerate(players, start=1):
                print(f"  {i}. {p.first_name} {p.last_name}")
            p_choice = input("Enter number: ").strip()
            try:
                linked_player_id = players[int(p_choice) - 1].player_id
            except (ValueError, IndexError):
                print("Invalid choice.")
                return

        org = session.query(Organization).first()
        if org is None:
            print("No organization exists yet -- run create_admin_user.py first.")
            return

        role = session.query(Role).filter(Role.role_name == role_name).first()
        if role is None:
            raise RuntimeError("Roles not seeded -- run init_db.py first.")

        existing = session.query(User).filter(User.email == email).first()
        if existing:
            print(f"A users row for {email} already exists (user_id={existing.user_id}). Nothing more to do.")
            return

        admin_client = get_supabase_admin_client()
        auth_result = admin_client.auth.admin.create_user(
            {"email": email, "password": password, "email_confirm": True}
        )
        auth_subject_id = auth_result.user.id
        print(f"Created Supabase Auth account: {auth_subject_id}")

        new_user = User(
            organization_id=org.organization_id,
            auth_subject_id=auth_subject_id,
            email=email,
            first_name=first_name,
            last_name=last_name,
            role_id=role.role_id,
            player_id=linked_player_id,
            active=True,
        )
        session.add(new_user)
        session.commit()
        print(f"Created {role_name} user: {first_name} {last_name} <{email}>")
        if linked_player_id:
            print(f"Linked to player_id={linked_player_id}.")
        print("They can now log in to the app with this email and password.")
    finally:
        session.close()


if __name__ == "__main__":
    main()