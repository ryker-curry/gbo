"""
Load the Career Development data (Nov 2026, Ryker) from data/career_import/:

  rapsodo_history.csv            -> rapsodo_history
      Ryker's Rapsodo account (Oct 2022 on) + the fall 2025 intrasquad
      export in the team Drive (Raw Rapsodo.xlsx). A pitch whose Rapsodo
      unique id is already in rapsodo_pitches is skipped, so nothing is
      counted twice.
  spring_2026_pitch_splits.csv   -> season_pitch_splits
  spring_2026_leaderboard.csv    -> season_pitching_lines
      Both from the staff game-tracking workbook (Staff Total Stats
      Spring 2026), runs saved flipped so positive = good.

Players are matched by full name (aliases below for spelling differences).
Pitchers who left before GBO existed (Blake Garrett, Gavin Stowell) are
added as INACTIVE players on Ryker's team so their numbers count toward the
staff baselines; anyone else unmatched is skipped and listed.

Dry run by default. Run after migrations.migrate_career_development:
    python3 -m scripts.import_career_history            # dry run
    python3 -m scripts.import_career_history --apply    # write
"""

import csv
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from database import SessionLocal  # noqa: E402
from models import (Player, PitchType, RapsodoPitch, RapsodoHistory,  # noqa: E402
                    SeasonPitchSplit, SeasonPitchingLine)
from pitch_type_config import normalize_pitch_type  # noqa: E402

DATA = os.path.join(ROOT, "data", "career_import")
ALIASES = {"aidan sowers": "aiden sowers", "ricky hernandez": "ricardo hernandez"}
ADD_IF_MISSING = {"Blake Garrett", "Gavin Stowell"}
SPLIT_SOURCE = "Staff Total Stats Spring 2026 (game-tracking workbook)"


def _read(name):
    with open(os.path.join(DATA, name), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _num(v):
    try:
        return float(v) if v not in ("", None) else None
    except ValueError:
        return None


def _int(v):
    x = _num(v)
    return int(round(x)) if x is not None else None


def _key(name):
    k = " ".join(str(name).lower().split())
    return ALIASES.get(k, k)


def _players(db):
    return {_key(f"{p.first_name} {p.last_name}"): p for p in db.query(Player).all()}


def _get_or_add(db, by_name, name, sides, apply, added):
    p = by_name.get(_key(name))
    if p is not None or name not in ADD_IF_MISSING:
        return p
    team_id = db.query(Player.team_id).filter(Player.is_pitcher.is_(True)).first()[0]
    first, last = name.split(" ", 1)
    side = sides.get(name)
    p = Player(team_id=team_id, first_name=first, last_name=last, is_pitcher=True, active=False,
               throws=("L" if side is not None and side < 0 else "R") if side is not None else None)
    db.add(p)
    db.flush()
    by_name[_key(name)] = p
    added.append(name)
    return p


def run(db, apply=False):
    by_name = _players(db)
    types = {t.type_name: t.pitch_type_id for t in db.query(PitchType).all()}
    hist = _read("rapsodo_history.csv")
    sides = {}
    for r in hist:
        v = _num(r["release_side"])
        if v is not None:
            sides.setdefault(r["player"], []).append(v)
    sides = {k: sorted(v)[len(v) // 2] for k, v in sides.items()}
    added_players, skipped = [], set()

    # --- rapsodo_history
    live_ids = {u for (u,) in db.query(RapsodoPitch.rapsodo_unique_id).filter(RapsodoPitch.rapsodo_unique_id.isnot(None))}
    have = {(h.player_id, h.source, h.source_uid) for h in
            db.query(RapsodoHistory.player_id, RapsodoHistory.source, RapsodoHistory.source_uid)}
    n_new = n_dup = n_live = 0
    for r in hist:
        p = _get_or_add(db, by_name, r["player"], sides, apply, added_players)
        if p is None:
            skipped.add(r["player"])
            continue
        if r["source_uid"] in live_ids:
            n_live += 1
            continue
        if (p.player_id, r["source"], r["source_uid"]) in have:
            n_dup += 1
            continue
        canon = normalize_pitch_type(r["raw_pitch_type"])
        db.add(RapsodoHistory(
            player_id=p.player_id, source=r["source"], source_uid=r["source_uid"],
            pitch_date=datetime.strptime(r["pitch_date"], "%Y-%m-%d %H:%M:%S"),
            session_key=r["session_key"] or None, session_type=r["session_type"] or None,
            raw_pitch_type=r["raw_pitch_type"] or None, pitch_type_id=types.get(canon) if canon else None,
            velocity=_num(r["velocity"]), total_spin=_num(r["total_spin"]), true_spin=_num(r["true_spin"]),
            spin_efficiency=_num(r["spin_efficiency"]), spin_confidence=_num(r["spin_confidence"]),
            gyro_degree=_num(r["gyro_degree"]), spin_axis_degrees=_num(r["spin_axis_degrees"]),
            vb_spin=_num(r["vb_spin"]), hb_trajectory=_num(r["hb_trajectory"]),
            release_height=_num(r["release_height"]), release_side=_num(r["release_side"]),
            release_extension=_num(r["release_extension"]),
            is_strike=None if r["is_strike"] == "" else r["is_strike"] in ("1", "1.0", "True")))
        have.add((p.player_id, r["source"], r["source_uid"]))
        n_new += 1
    print(f"rapsodo_history: {n_new} new, {n_dup} already loaded, {n_live} already in rapsodo_pitches (skipped).")

    # --- season_pitch_splits
    s_new = s_upd = 0
    for r in _read("spring_2026_pitch_splits.csv"):
        p = _get_or_add(db, by_name, r["player"], sides, apply, added_players)
        if p is None:
            skipped.add(r["player"])
            continue
        vals = dict(pitches=_int(r["pitches"]), strike_pct=_num(r["strike_pct"]), called_pct=_num(r["called_pct"]),
                    swing_pct=_num(r["swing_pct"]), whiff_pct=_num(r["whiff_pct"]), csw_pct=_num(r["csw_pct"]),
                    putaway_pct=_num(r["putaway_pct"]), gb_pct=_num(r["gb_pct"]),
                    runs_saved_per_100=_num(r["runs_saved_per_100"]), oba=_num(r["oba"]), woba=_num(r["woba"]),
                    hits=_int(r["hits"]), hr=_int(r["hr"]), source=SPLIT_SOURCE)
        label = r["pitch_label"] if r["pitch_label"] == "All pitches" else (normalize_pitch_type(r["pitch_label"]) or r["pitch_label"])
        row = db.query(SeasonPitchSplit).filter_by(player_id=p.player_id, term=r["term"], pitch_label=label).first()
        if row is None:
            db.add(SeasonPitchSplit(player_id=p.player_id, term=r["term"], pitch_label=label, **vals))
            s_new += 1
        else:
            for k, v in vals.items():
                setattr(row, k, v)
            s_upd += 1
    print(f"season_pitch_splits: {s_new} new, {s_upd} updated.")

    # --- season_pitching_lines
    l_new = l_upd = 0
    cols = ["ip", "pitches", "strike_pct", "fps_pct", "ea_pct", "k_pct", "whiff_pct", "csw_pct", "dominance_pct",
            "putaway_pct", "gb_pct", "ld_pct", "fb_pct", "oba", "woba", "runs_saved_per_100", "era", "fip", "whip", "siera"]
    for r in _read("spring_2026_leaderboard.csv"):
        p = _get_or_add(db, by_name, r["player"], sides, apply, added_players)
        if p is None:
            skipped.add(r["player"])
            continue
        vals = {c: (_int(r[c]) if c == "pitches" else _num(r[c])) for c in cols}
        vals["source"] = SPLIT_SOURCE
        row = db.query(SeasonPitchingLine).filter_by(player_id=p.player_id, term=r["term"]).first()
        if row is None:
            db.add(SeasonPitchingLine(player_id=p.player_id, term=r["term"], **vals))
            l_new += 1
        else:
            for k, v in vals.items():
                setattr(row, k, v)
            l_upd += 1
    print(f"season_pitching_lines: {l_new} new, {l_upd} updated.")

    if added_players:
        print("Added as inactive players: " + ", ".join(added_players))
    if skipped:
        print("No player match (skipped): " + ", ".join(sorted(skipped)))
    if apply:
        db.commit()
        print("Written.")
    else:
        db.rollback()
        print("Dry run -- nothing written. Re-run with --apply.")


if __name__ == "__main__":
    db = SessionLocal()
    try:
        run(db, apply="--apply" in sys.argv)
    finally:
        db.close()
