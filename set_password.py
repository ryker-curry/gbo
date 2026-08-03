"""
GBO — Directly set/reset a user's password via the Supabase Admin API.

Bypasses password-reset emails entirely (which require a working redirect
URL that this local-dev setup doesn't have). Use this any time you need
to set or reset a GBO account's password during development.

Run interactively:
    python set_password.py
"""

from getpass import getpass

from supabase_client import get_supabase_admin_client


def main():
    email = input("Email of the account to update: ").strip()
    new_password = getpass("New password (min 6 characters): ").strip()
    confirm = getpass("Confirm new password: ").strip()

    if new_password != confirm:
        print("Passwords did not match. Nothing was changed.")
        return

    admin_client = get_supabase_admin_client()

    # Find the auth user by email
    users_page = admin_client.auth.admin.list_users()
    match = next((u for u in users_page if u.email == email), None)

    if match is None:
        print(f"No Supabase Auth account found for {email}.")
        return

    admin_client.auth.admin.update_user_by_id(match.id, {"password": new_password})
    print(f"Password updated for {email}. You can log in with the new password now.")


if __name__ == "__main__":
    main()