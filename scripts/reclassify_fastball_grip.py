"""
Bulk-relabel one pitcher's charted "4-Seam Fastball" pitches to
"2-Seam Fastball" (or the reverse), across every game they've been
tracked in.

Ryker, Sept 2026: he'd been charting pitch type off movement numbers
(more horizontal than vertical break -> call it a 2-seam) instead of
the pitcher's actual grip -- see the "so if a guy has a 4 seam grip
but his vertical horizontal are close together do i call it a 4 seam?"
conversation. Grip is the real source of truth for what pitch was
thrown; movement is only a fallback signal for when the grip isn't
known. Once he confirmed his own grip is a 2-seam, every one of his
own charted pitches sitting under "4-Seam Fastball" from the old
movement-based guess needed to move to "2-Seam Fastball" -- this
script does that bulk correction in one pass instead of hand-editing
each pitch through the Pitch Log's one-at-a-time Edit form.

Scope, by design (Ryker's own call): GAME-TRACKED pitches only
(GamePitch rows feeding the Pitch Log / pitcher reports) -- NOT
Rapsodo/bullpen import data (RapsodoPitch rows), which this script
deliberately leaves untouched.

Finds every GamePitch actually thrown BY the named pitcher -- handles
both an ordinary game (is_our_team_batting False, our_player_id is the
pitcher) and an intrasquad game's "other squad" pitching (is_our_team_batting
True, opponent_our_player_id is the real pitcher -- see _pitcher_id in
analytics/pitcher_game_report.py, same logic mirrored here) -- whose
pitch_type_id currently points at --from-type, and repoints it to
--to-type.

Dry-run by default -- prints every game/date this would touch and how
many pitches in each, with nothing written to the database. Pass
--apply to actually commit the change.

Usage:
    python3 scripts/reclassify_fastball_grip.py "<pitcher name>" [--from-type "4-Seam Fastball"] [--to-type "2-Seam Fastball"] [--apply]

    e.g. python3 scripts/reclassify_fastball_grip.py "Ryker Curry"
         python3 scripts/reclassify_fastball_grip.py "Ryker Curry" --apply
"""
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "shiny_app")

from database import get_session
from models import Player, Game, GamePitch, PitchType
from format_helpers import opponent_display_name


def main():
    raw_args = sys.argv[1:]
    apply = "--apply" in raw_args
    raw_args = [a for a in raw_args if a != "--apply"]

    from_type_name = "4-Seam Fastball"
    to_type_name = "2-Seam Fastball"
    if "--from-type" in raw_args:
        idx = raw_args.index("--from-type")
        from_type_name = raw_args[idx + 1]
        del raw_args[idx:idx + 2]
    if "--to-type" in raw_args:
        idx = raw_args.index("--to-type")
        to_type_name = raw_args[idx + 1]
        del raw_args[idx:idx + 2]

    if len(raw_args) != 1:
        print(f'Usage: python3 {sys.argv[0]} "<pitcher name>" [--from-type "X"] [--to-type "Y"] [--apply]')
        sys.exit(1)
    name_query = raw_args[0].strip().lower()

    db = get_session()
    try:
        players = [p for p in db.query(Player).all() if name_query in f"{p.first_name} {p.last_name}".lower()]
        if not players:
            print(f"No roster player matching '{raw_args[0]}'.")
            return
        if len(players) > 1:
            print(f"Multiple roster players match '{raw_args[0]}': " + ", ".join(f"#{p.player_id} {p.first_name} {p.last_name}" for p in players))
            return
        player = players[0]

        from_type = db.query(PitchType).filter(PitchType.type_name == from_type_name).first()
        to_type = db.query(PitchType).filter(PitchType.type_name == to_type_name).first()
        if from_type is None:
            print(f"No PitchType named '{from_type_name}' -- check spelling/capitalization.")
            return
        if to_type is None:
            print(f"No PitchType named '{to_type_name}' -- check spelling/capitalization.")
            return

        # Real pitcher on a row, regardless of which side of the
        # is_our_team_batting split it landed on -- mirrors _pitcher_id
        # in analytics/pitcher_game_report.py exactly, so an intrasquad
        # game's "other squad" pitching (is_our_team_batting True,
        # opponent_our_player_id is the real pitcher) is caught too,
        # not just this player's ordinary our_player_id pitches.
        candidates = (
            db.query(GamePitch)
            .filter(GamePitch.pitch_type_id == from_type.pitch_type_id)
            .all()
        )
        matches = [
            p for p in candidates
            if (not p.is_our_team_batting and p.our_player_id == player.player_id)
            or (p.is_our_team_batting and p.opponent_our_player_id == player.player_id)
        ]

        if not matches:
            print(f"No '{from_type_name}' pitches found for {player.first_name} {player.last_name}. Nothing to do.")
            return

        game_ids = sorted({p.game_id for p in matches})
        games = {g.game_id: g for g in db.query(Game).filter(Game.game_id.in_(game_ids)).all()}

        print(f"{player.first_name} {player.last_name}: {len(matches)} pitch(es) currently '{from_type_name}' would become '{to_type_name}':\n")
        for gid in game_ids:
            g = games.get(gid)
            count = sum(1 for p in matches if p.game_id == gid)
            label = f"{g.game_date} vs {opponent_display_name(g)}" if g else f"game_id {gid}"
            print(f"  {label}: {count} pitch(es)")

        if not apply:
            print("\nDry run only -- nothing was changed. Re-run with --apply to commit.")
            return

        for p in matches:
            p.pitch_type_id = to_type.pitch_type_id
        db.commit()
        print(f"\nApplied: {len(matches)} pitch(es) changed from '{from_type_name}' to '{to_type_name}'.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
