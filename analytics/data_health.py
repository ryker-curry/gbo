"""
GBO -- Data Health (Oct 2026, Ryker approved: "Data Health page ... staff
only, under Game Operations"). Read-only checks on the charting behind
every report, per game, so missing pieces get fixed before they skew
Hot Zones, Swing Decisions, Stuff+, splits, ERA, etc.

check_game(db, game) -> {"game", "checks": [...], "score", "grade"}
Each check: key, label, why, missing (count), total (denominator), weight.
score = weighted % complete across checks that apply (total > 0).
The "box" check only applies once an official box score is typed in
(analytics/box_score.py); total = stats compared, missing = mismatches.
grade: green >= 95, yellow >= 80, red below.
Nothing here writes to the database.
"""

from collections import defaultdict
from datetime import timedelta

from sqlalchemy.orm import joinedload

from models import Game, GamePitch, RapsodoPitch, RapsodoImport, Player, OpponentPlayer
from analytics import box_score

GREEN, YELLOW = 95.0, 80.0

CHECKS = [
    # key, label, why it matters, weight
    ("final", "Game not marked Final", "No after-game team email, and the record/standings are wrong.", 1.0),
    ("location", "Pitches with no location", "Hot Zones, Swing Decisions, Miss Map, Best Zone and chase/zone stats skip them.", 3.0),
    ("pitch_type", "Pitches with no pitch type", "Every pitch-type table and Stuff+ breakdown misses them.", 3.0),
    ("contact", "Balls in play with no contact quality", "Hard contact %, barrels and contact tables come up short.", 2.0),
    ("bb_type", "Balls in play with no batted-ball type", "Ground ball / fly ball / line drive splits are off.", 1.0),
    ("their_pitcher", "Our at-bats with no opponent pitcher picked", "vs RHP / vs LHP splits for our hitters miss them.", 2.0),
    ("hitter_hand", "Opponent hitters with no handedness", "vs LHH / vs RHH splits for our pitchers are wrong.", 2.0),
    ("rapsodo_unmatched", "Rapsodo readings not matched to a pitch", "No Stuff+ / velo for those game pitches.", 1.5),
    ("rapsodo_type", "Rapsodo type differs from charted type", "Likely a tagging mistake -- one of the two is wrong.", 1.0),
    ("unearned", "Runs on errors with no unearned runs tagged", "ERA (and ERA+) reads high for the pitcher.", 1.0),
    ("box", "Charting doesn't match the official box score", "A missed pitch, PA or result -- every total built on this game is off.", 2.0),
]
CHECK_META = {k: (label, why, w) for k, label, why, w in CHECKS}


def _hand_known(p, players, opp_players):
    """Do we know the batter's hand on a pitch where WE pitched?"""
    if p.opponent_our_player_id:                       # intrasquad: our own hitter
        pl = players.get(p.opponent_our_player_id)
        return bool(pl and pl.bats in ("R", "L", "S"))
    if p.opponent_player_id:
        op = opp_players.get(p.opponent_player_id)
        if op and op.bats in ("R", "L", "S"):
            return True
    return p.opponent_hand in ("R", "L")


def _their_pitcher_known(p, players, opp_players):
    """Do we know the pitcher's hand on a pitch where WE batted?"""
    if p.opponent_our_player_id:                       # intrasquad: our own pitcher
        return True
    if p.opponent_player_id:
        return True
    return p.opponent_hand in ("R", "L")


def check_game(db, game, players=None, opp_players=None):
    pitches = (db.query(GamePitch).options(joinedload(GamePitch.pitch_type))
               .filter(GamePitch.game_id == game.game_id).order_by(GamePitch.pitch_sequence).all())
    players = players if players is not None else {p.player_id: p for p in db.query(Player).all()}
    if opp_players is None:
        ids = {p.opponent_player_id for p in pitches if p.opponent_player_id}
        opp_players = {o.opponent_player_id: o for o in db.query(OpponentPlayer).filter(
            OpponentPlayer.opponent_player_id.in_(ids)).all()} if ids else {}
    n = len(pitches)
    bip = [p for p in pitches if p.pitch_outcome == "In Play"]
    # external games: our pitchers = not batting; our hitters = batting
    our_pitching = [p for p in pitches if not p.is_our_team_batting]
    our_batting = [p for p in pitches if p.is_our_team_batting]

    raps = (db.query(RapsodoPitch).options(joinedload(RapsodoPitch.pitch_type))
            .join(RapsodoImport, RapsodoPitch.import_id == RapsodoImport.import_id)
            .filter(RapsodoImport.game_id == game.game_id).all())
    linked = (db.query(RapsodoPitch).options(joinedload(RapsodoPitch.pitch_type))
              .filter(RapsodoPitch.game_pitch_id.in_([p.game_pitch_id for p in pitches])).all()) if pitches else []
    by_gp = {p.game_pitch_id: p for p in pitches}
    type_mismatch = sum(1 for r in linked if r.pitch_type_id and by_gp.get(r.game_pitch_id)
                        and by_gp[r.game_pitch_id].pitch_type_id and r.pitch_type_id != by_gp[r.game_pitch_id].pitch_type_id)

    err_plays = [p for p in pitches if p.ends_plate_appearance and p.ab_outcome == "E" and (p.runs_scored_on_play or 0) > 0]

    raw = {
        "final": (0 if game.status == "Final" else 1, 1),
        "location": (sum(1 for p in pitches if p.actual_plate_x is None or p.actual_plate_z is None), n),
        "pitch_type": (sum(1 for p in pitches if not p.pitch_type_id), n),
        "contact": (sum(1 for p in bip if not p.contact_quality), len(bip)),
        "bb_type": (sum(1 for p in bip if not p.batted_ball_type), len(bip)),
        "their_pitcher": (sum(1 for p in our_batting if not _their_pitcher_known(p, players, opp_players)), len(our_batting)),
        "hitter_hand": (sum(1 for p in our_pitching if not _hand_known(p, players, opp_players)), len(our_pitching)),
        "rapsodo_unmatched": (sum(1 for r in raps if r.game_pitch_id is None), len(raps)),
        "rapsodo_type": (type_mismatch, len(linked)),
        "unearned": (sum(1 for p in err_plays if not (p.unearned_runs_on_play or 0)), len(err_plays)),
    }
    box_rows, has_box = [], False
    if not game.is_intrasquad:
        official = box_score.official_line(box_score.get_official(db, game.game_id))
        has_box = official is not None
        box_rows = box_score.compare(official, box_score.charted_line(db, game.game_id)) if has_box else []
    raw["box"] = (sum(1 for r in box_rows if not r["ok"]), len(box_rows))
    if game.is_intrasquad:
        raw["their_pitcher"] = (0, 0)   # both sides are our own players
    checks, num, den = [], 0.0, 0.0
    for key, label, why, w in CHECKS:
        missing, total = raw[key]
        if total:
            num += w * (total - missing) / total
            den += w
        checks.append({"key": key, "label": label, "why": why, "missing": missing, "total": total, "weight": w})
    score = round(100 * num / den, 1) if den else 100.0
    grade = "green" if score >= GREEN else ("yellow" if score >= YELLOW else "red")
    # Oct 2026, Ryker: list the exact balls in play to fix, so Data Health
    # can jump straight to each one in Game Tracking's Pitch Log.
    def _who(pid, opp_id=None):
        if opp_id and opp_id in opp_players:
            return opp_players[opp_id].player_name
        pl = players.get(pid)
        return f"{pl.first_name} {pl.last_name}" if pl else "—"
    bip_fix = []
    for p in bip:
        missing = [w for w, ok in (("batted-ball type", p.batted_ball_type), ("contact quality", p.contact_quality)) if not ok]
        if not missing:
            continue
        if p.is_our_team_batting:
            batter, pitcher = _who(p.our_player_id), (_who(p.opponent_our_player_id) if p.opponent_our_player_id else "their pitcher")
        else:
            batter = _who(p.opponent_our_player_id, p.opponent_player_id) if (p.opponent_player_id or p.opponent_our_player_id) else "their hitter"
            pitcher = _who(p.our_player_id)
        bip_fix.append({"game_pitch_id": p.game_pitch_id, "inning": p.inning, "seq": p.pitch_sequence,
                        "batter": batter, "pitcher": pitcher, "result": p.ab_outcome or "In play", "missing": missing})
    return {"game": game, "checks": checks, "score": score, "grade": grade, "pitches": n,
            "box_rows": box_rows, "has_box": has_box, "bip_fix": bip_fix}


def check_range(db, date_from, date_to):
    gids = {gid for (gid,) in db.query(GamePitch.game_id).distinct().all()}
    games = (db.query(Game).options(joinedload(Game.opponent_team))
             .filter(Game.game_id.in_(gids), Game.game_date >= date_from, Game.game_date <= date_to)
             .order_by(Game.game_date.desc(), Game.game_id.desc()).all()) if gids else []
    players = {p.player_id: p for p in db.query(Player).all()}
    opp = {o.opponent_player_id: o for o in db.query(OpponentPlayer).all()}
    return [check_game(db, g, players, opp) for g in games]


def weekly_trend(results):
    """[(week_start, avg score, games)] oldest first."""
    by_week = defaultdict(list)
    for r in results:
        d = r["game"].game_date
        by_week[d - timedelta(days=d.weekday())].append(r["score"])
    return [(w, round(sum(v) / len(v), 1), len(v)) for w, v in sorted(by_week.items())]
