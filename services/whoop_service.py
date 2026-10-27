"""
GBO -- WHOOP pilot helpers for the Shiny side (Oct 2026).

The WHOOP sign-in and data pulls run in Supabase Edge Functions
(supabase/functions/). The app only:
  - makes one-time "Connect WHOOP" links (whoop_connect_links), and
  - asks the whoop-sync function to run now, for one player.
"""

import json
import secrets
import urllib.request
from datetime import datetime, timedelta

from sqlalchemy import text

FUNCTIONS_BASE = "https://zjqwirsxofosungqoyau.supabase.co/functions/v1"
CALLBACK_URL = f"{FUNCTIONS_BASE}/whoop-oauth-callback"
SYNC_URL = f"{FUNCTIONS_BASE}/whoop-sync"
LINK_DAYS = 7


def connect_url(state):
    return f"{CALLBACK_URL}?connect={state}"


def make_connect_link(db, player_id, user_id=None):
    """New one-time link for this player (older unused links stay valid until
    they expire). Returns the URL to send him."""
    from models import WhoopConnectLink
    state = secrets.token_urlsafe(24)
    db.add(WhoopConnectLink(player_id=player_id, state=state, created_by_user_id=user_id,
                            expires_at=datetime.utcnow() + timedelta(days=LINK_DAYS)))
    db.commit()
    return connect_url(state)


def latest_open_link(db, player_id):
    """The newest unused, unexpired link for this player, or None."""
    from models import WhoopConnectLink
    link = (db.query(WhoopConnectLink)
            .filter(WhoopConnectLink.player_id == player_id, WhoopConnectLink.used_at.is_(None),
                    WhoopConnectLink.expires_at > datetime.utcnow())
            .order_by(WhoopConnectLink.created_at.desc()).first())
    return (connect_url(link.state), link.expires_at) if link else None


def sync_now(db, player_id, timeout=110):
    """Run the whoop-sync Edge Function for one player. Returns (ok, message)."""
    try:
        key = db.execute(text("SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name = 'whoop_sync_key'")).scalar()
    except Exception as e:  # SQLite demo / tests, or Vault not set up yet
        db.rollback()
        return False, f"Sync isn't set up on this database yet ({type(e).__name__})."
    if not key:
        return False, "Sync key missing -- run python3 -m migrations.migrate_whoop."
    req = urllib.request.Request(SYNC_URL, data=json.dumps({"player_id": int(player_id)}).encode(),
                                 headers={"Content-Type": "application/json", "x-sync-key": key}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode() or "{}")
    except Exception as e:
        return False, f"Couldn't reach the sync function: {e}"
    res = (body.get("results") or [{}])[0] if body.get("results") else {}
    if not body.get("results"):
        return False, "No active WHOOP connection for this player."
    if res.get("ok"):
        return True, f"Synced -- {res.get('days', 0)} days and {res.get('workouts', 0)} workouts updated."
    return False, res.get("error") or "Sync failed."
