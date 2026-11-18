"""
Rating report -- every active player's Show-style Overall (and each
attribute) for the current season, computed with the exact same code
Player Profile uses (analytics/player_ratings.py). For tuning the
scale/weights against real data (Oct 2026, Ryker: "we might need to
adjust the scoring").

Read-only. Runs the roster-wide queries ONCE, then builds every card.

Usage (from the repo root, same environment you run the app in):
    python3 scripts/rating_report.py

Prints pitchers and hitters sorted by Overall, and writes the full
table to "Claude outputs/rating_report.csv".
"""
import csv
import os
import sys
from datetime import timedelta

sys.path.insert(0, ".")

from database import get_session
from models import Player
from bucket_system import current_season_label, season_date_range
import copy
from analytics.player_ratings import roster_context, apply_roster_percentiles, PITCHER_WEIGHTS, HITTER_WEIGHTS


def main():
    db = get_session()
    try:
        label = current_season_label()
        start, end = season_date_range(label)
        date_to = (end - timedelta(days=1)) if end else None
        print(f"Season: {label}  ({start} to {date_to})")

        ctx = roster_context(db, start, date_to, label)
        print(f"Staff velo baseline: {ctx['velo_base']}")
        print(f"Pitchers with game data: {len(ctx['pitch_rows'])} · hitters with PAs: {len(ctx['hit_lines'])}")
        names = {p.player_id: f"{p.first_name} {p.last_name}" for p in db.query(Player).filter(Player.player_id.in_(list(ctx["raw_cards"]))).all()}

        out = []
        for pid, raw in ctx["raw_cards"].items():
            card = apply_roster_percentiles(copy.deepcopy(raw), ctx["raw_cards"], pid)
            row = ctx["pitch_rows"].get(pid)
            line = ctx["hit_lines"].get(pid)
            own_v = ctx["staff_velos"].get(pid)
            rec = {
                "Player": names.get(pid, pid), "Role": card["primary_role"] or "-",
                "Overall": card["overall"], "Tier": card["tier"], "Raw overall": card.get("overall_raw"),
                "Pct": round(card["overall_pct"]) if card.get("overall_pct") is not None else None,
                "Baseball": card["baseball"], "Athlete": card["athlete"],
                "Provisional": "yes" if card["provisional"] else "",
                "BF": (row or {}).get("BF"), "PA": (line or {}).get("PA"),
                "FB velo": round(own_v[0], 1) if own_v else None,
            }
            for role, data in card["roles"].items():
                prefix = "P_" if role == "pitching" else "H_"
                for key in data["weights"]:
                    rec[prefix + key] = data["attributes"].get(key, (None, None))[0]
            out.append(rec)

        def show(title, rows, keys):
            print(f"\n=== {title} ===")
            hdr = ["Player", "Overall", "Tier", "Pct", "Raw overall", "Baseball", "Athlete", "Provisional"] + keys
            print(" | ".join(hdr))
            for r in sorted(rows, key=lambda r: -(r["Overall"] or 0)):
                print(" | ".join(str(r.get(h) if r.get(h) is not None else "-") for h in hdr))

        show("PITCHERS", [r for r in out if r["Role"] == "pitching"],
             ["BF", "FB velo"] + [f"P_{k}" for k in PITCHER_WEIGHTS])
        show("HITTERS", [r for r in out if r["Role"] == "hitting"],
             ["PA"] + [f"H_{k}" for k in HITTER_WEIGHTS])

        os.makedirs("Claude outputs", exist_ok=True)
        fields = []
        for r in out:
            for k in r:
                if k not in fields:
                    fields.append(k)
        with open("Claude outputs/rating_report.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(out)
        print('\nWrote "Claude outputs/rating_report.csv"')
    finally:
        db.close()


if __name__ == "__main__":
    main()
