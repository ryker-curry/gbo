"""
GBO -- Box score check (Oct 2026, Ryker approved; official line typed in
on Data Health). Adds up R / H / E / BB / K from the charting and lines
it up against the official box score in models.GameBoxScore.

Charted line, per side ("our" = Pitt State, "opp" = opponent):
  R  = runs_scored_on_play on that side's at-bats + runner events where
       that side's runner scored (to_base 4, not out)
  H  = PAs ending 1B/2B/3B/HR      BB = PAs ending BB
  K  = PAs ending K / K (Looking)
  E  = errors that side COMMITTED in the field: the other side's PAs that
       ended "E" + "Throwing Error" runner events while the other side ran
Intrasquads are skipped (no official box score).
"""

from models import GameBoxScore, GamePitch, GameRunnerEvent
from game_stats import HIT_OUTCOMES, K_OUTCOMES

STATS = ("r", "h", "e", "bb", "k")
LABELS = {"r": "R", "h": "H", "e": "E", "bb": "BB", "k": "K"}
SIDES = ("our", "opp")


def charted_line(db, game_id):
    pitches = db.query(GamePitch).filter(GamePitch.game_id == game_id).all()
    events = db.query(GameRunnerEvent).filter(GameRunnerEvent.game_id == game_id).all()
    out = {s: dict.fromkeys(STATS, 0) for s in SIDES}
    for p in pitches:
        bat = "our" if p.is_our_team_batting else "opp"
        field = "opp" if bat == "our" else "our"
        out[bat]["r"] += p.runs_scored_on_play or 0
        if not p.ends_plate_appearance:
            continue
        ab = p.ab_outcome
        if ab in HIT_OUTCOMES:
            out[bat]["h"] += 1
        elif ab == "BB":
            out[bat]["bb"] += 1
        elif ab in K_OUTCOMES:
            out[bat]["k"] += 1
        elif ab == "E":
            out[field]["e"] += 1
    for e in events:
        bat = "our" if e.is_our_team_batting else "opp"
        field = "opp" if bat == "our" else "our"
        if e.to_base == 4 and not e.is_out:
            out[bat]["r"] += 1
        if e.event_type in ("Throwing Error", "Fielding Error"):  # Oct 2026: fielding errors too
            out[field]["e"] += 1
    return out


def official_line(row):
    if row is None:
        return None
    return {s: {k: getattr(row, f"{s}_{k}") for k in STATS} for s in SIDES}


def get_official(db, game_id):
    try:
        return db.query(GameBoxScore).filter(GameBoxScore.game_id == game_id).first()
    except Exception:          # table not migrated yet
        db.rollback()
        return None


def compare(official, charted):
    """-> list of {side, stat, label, official, charted, diff, ok}; stats left
    blank in the official line are skipped."""
    rows = []
    if not official:
        return rows
    for s in SIDES:
        for k in STATS:
            o = official[s].get(k)
            if o is None:
                continue
            c = charted[s][k]
            rows.append({"side": s, "stat": k, "label": LABELS[k], "official": o, "charted": c,
                         "diff": c - o, "ok": c == o})
    return rows


def save(db, game_id, values, user_id=None):
    """values: {"our_r": 5, ...} (None = blank)."""
    row = db.query(GameBoxScore).filter(GameBoxScore.game_id == game_id).first()
    if row is None:
        row = GameBoxScore(game_id=game_id)
        db.add(row)
    for s in SIDES:
        for k in STATS:
            setattr(row, f"{s}_{k}", values.get(f"{s}_{k}"))
    row.entered_by_user_id = user_id
    db.commit()
    return row
