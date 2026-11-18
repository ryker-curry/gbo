"""
Diagnostic: print every break-related field Rapsodo exports (VB/HB
trajectory AND spin-induced, plus SSW) per pitch for one pitcher's
outing, grouped by pitch type -- so a discrepancy between GBO's
Pitcher Game Report HB/IVB numbers and Rapsodo's own displayed
session averages can be tracked to exactly which column GBO should be
reading (Ryker, Sept 2026: Porter Starnes's 2-seam HB shows 10.7 in
GBO but 16.4 on Rapsodo's own site, matching the average of his two
individual 2-seam HB readings there).

Read-only -- makes no changes.

Usage:
    python3 scripts/diagnose_rapsodo_break_fields.py "<pitcher name>" <game_date YYYY-MM-DD>

    e.g. python3 scripts/diagnose_rapsodo_break_fields.py "Porter Starnes" 2026-09-08
"""
import sys
from datetime import datetime
from statistics import mean

sys.path.insert(0, ".")

from database import get_session
from models import Player, Game, RapsodoImport, RapsodoPitch


def fmt(v):
    return f"{float(v):.2f}" if v is not None else "  —  "


def avg(vals):
    vals = [float(v) for v in vals if v is not None]
    return round(mean(vals), 2) if vals else None


def main():
    args = sys.argv[1:]
    if len(args) != 2:
        print(f'Usage: python3 {sys.argv[0]} "<pitcher name>" <game_date YYYY-MM-DD>')
        sys.exit(1)
    name_query = args[0].strip().lower()
    try:
        game_date = datetime.strptime(args[1].strip(), "%Y-%m-%d").date()
    except ValueError:
        print(f"Couldn't parse date '{args[1]}' -- use YYYY-MM-DD.")
        sys.exit(1)

    db = get_session()
    try:
        players = [p for p in db.query(Player).all() if name_query in f"{p.first_name} {p.last_name}".lower()]
        if not players:
            print(f"No roster player matching '{args[0]}'.")
            return
        if len(players) > 1:
            print(f"Multiple roster players match '{args[0]}': " + ", ".join(f"#{p.player_id} {p.first_name} {p.last_name}" for p in players))
            return
        pitcher = players[0]

        games = db.query(Game).filter(Game.game_date == game_date).all()
        if not games:
            print(f"No game found on {game_date}.")
            return
        if len(games) > 1:
            print(f"Multiple games found on {game_date}: " + ", ".join(f"game_id={g.game_id}" for g in games))
            return
        game = games[0]

        pitches = (
            db.query(RapsodoPitch)
            .join(RapsodoImport, RapsodoPitch.import_id == RapsodoImport.import_id)
            .filter(RapsodoImport.game_id == game.game_id, RapsodoImport.player_id == pitcher.player_id)
            .order_by(RapsodoPitch.pitch_number)
            .all()
        )
        if not pitches:
            print(f"No RapsodoPitch rows found for {pitcher.first_name} {pitcher.last_name} in game_id={game.game_id}.")
            return

        print(f"{pitcher.first_name} {pitcher.last_name}, game_id={game.game_id}, {game_date} -- {len(pitches)} Rapsodo pitch(es)\n")

        by_type = {}
        for rp in pitches:
            label = rp.pitch_type.type_name if rp.pitch_type else (rp.raw_pitch_type or "—")
            by_type.setdefault(label, []).append(rp)

        for label, rows in by_type.items():
            print(f"=== {label} ({len(rows)} pitch(es)) ===")
            print(f"{'Rapsodo#':>9} {'vb_spin':>9} {'vb_traj':>9} {'ssw_vb':>9} {'hb_spin':>9} {'hb_traj':>9} {'ssw_hb':>9}")
            for rp in rows:
                print(
                    f"{rp.pitch_number:>9} {fmt(rp.vb_spin):>9} {fmt(rp.vb_trajectory):>9} {fmt(rp.ssw_vb):>9} "
                    f"{fmt(rp.hb_spin):>9} {fmt(rp.hb_trajectory):>9} {fmt(rp.ssw_hb):>9}"
                )
            print(
                f"{'AVG':>9} {str(avg([r.vb_spin for r in rows])):>9} {str(avg([r.vb_trajectory for r in rows])):>9} "
                f"{str(avg([r.ssw_vb for r in rows])):>9} {str(avg([r.hb_spin for r in rows])):>9} "
                f"{str(avg([r.hb_trajectory for r in rows])):>9} {str(avg([r.ssw_hb for r in rows])):>9}"
            )
            print()

        print("Compare these averages to Rapsodo's own session table V-Break/H-Break columns for this pitcher/session --")
        print("whichever column (vb_spin/vb_trajectory, hb_spin/hb_trajectory) matches is the one GBO should be reading.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
