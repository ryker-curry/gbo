"""Make already-imported Rapsodo readings use the pitch type charted in
Game Tracking instead of the label Rapsodo assigned.

New imports do this automatically when readings are matched to game
pitches. This fixes readings that were matched before that change
(e.g. Shane Holman's changeups/curveballs/sliders that Rapsodo tagged
"Fastball"). Rapsodo's own label is kept in raw_pitch_type.

Only touches readings linked to a game pitch that has a pitch type.
Bullpen readings are left alone.

    python scripts/sync_rapsodo_pitch_types_from_game.py            # preview
    python scripts/sync_rapsodo_pitch_types_from_game.py --apply    # save
"""
import sys
from collections import Counter

sys.path.insert(0, ".")

from database import get_session
from models import GamePitch, PitchType, Player, RapsodoPitch


def main(apply: bool) -> None:
    db = get_session()
    try:
        names = {pt.pitch_type_id: pt.type_name for pt in db.query(PitchType).all()}
        rows = (
            db.query(RapsodoPitch, GamePitch)
            .join(GamePitch, GamePitch.game_pitch_id == RapsodoPitch.game_pitch_id)
            .filter(GamePitch.pitch_type_id.isnot(None))
            .all()
        )
        changes = [(rp, gp) for rp, gp in rows if rp.pitch_type_id != gp.pitch_type_id]
        players = {p.player_id: p for p in db.query(Player).all()}

        by_player = Counter()
        by_switch = Counter()
        for rp, gp in changes:
            p = players.get(rp.player_id)
            who = f"{p.first_name} {p.last_name}" if p else f"player {rp.player_id}"
            by_player[who] += 1
            by_switch[(who, names.get(rp.pitch_type_id, "none"), names.get(gp.pitch_type_id, "none"))] += 1

        print(f"{len(rows)} Rapsodo readings are matched to a charted game pitch.")
        print(f"{len(changes)} have a different pitch type than Game Tracking.\n")
        for who, n in by_player.most_common():
            print(f"{who}: {n}")
            for (w, frm, to), k in sorted(by_switch.items(), key=lambda x: -x[1]):
                if w == who:
                    print(f"    {frm} -> {to}: {k}")

        if not changes:
            return
        if not apply:
            print("\nPreview only. Run with --apply to save.")
            return
        for rp, gp in changes:
            rp.pitch_type_id = gp.pitch_type_id
        db.commit()
        print(f"\nSaved. {len(changes)} readings now use the Game Tracking pitch type.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main("--apply" in sys.argv)
