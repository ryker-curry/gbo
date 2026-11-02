"""
GBO -- SmartPark (WIN Reality / Yakkertech) game import.

Ryker's call (Oct 27 2026): SmartPark replaces manual game charting. One
SmartPark game file builds an empty GBO game's whole pitch-by-pitch record:

  - one GamePitch per pitch: batter/pitcher, count, result, pitch type,
    actual location, batted-ball type + landing spot, at-bat result, outs,
    runs -- then the count/outs/bases/inning/side chain and run expectancy
    are filled by game_tracking.replay_game(), the same function Pitch Log
    edits use, so an imported game behaves exactly like a hand-charted one
  - one SmartParkPitch per row: every raw tracking reading (velo, spin,
    break, release, exit velo, launch angle, bat speed...), linked to the
    GamePitch it built
  - GameRunnerEvent rows where the file shows outs or runs that happened
    between pitches (caught stealing, a run on a wild pitch...), and
    GameForcedHalfInningEnd rows where a half ended before 3 outs
    (intrasquad rules, a walk-off) -- so replay_game lands on the same
    outs the file shows
  - PitchingChange rows for our pitching changes, and the game's score

What SmartPark can't know, and stays a coach's job afterwards (Pitch Log):
intended location, unearned runs, contact quality, and exactly where base
runners stood (bases are estimated from hit results -- see warnings).

Not yet checked against a real SmartPark export (built before install).
Column names / result words live in services/smartpark_columns.py.

No Shiny import here -- pure data logic, callable from the page or a test.
"""

import hashlib
import io
import math
import re
from datetime import datetime
from types import SimpleNamespace

import pandas as pd

from models import (
    Game, GamePitch, GameRunnerEvent, GameForcedHalfInningEnd, PitchingChange, Player, OpponentPlayer,
    PitchType, RapsodoPitch, GameVideoClip, PitchTypeChange,
    SmartParkImport, SmartParkPitch, SmartParkPlayerLink,
)
from pitch_type_config import normalize_pitch_type
from strike_zone import derive_old_zone
from services import smartpark_columns as cols

SOURCE_NOTE = "SmartPark import"


class SmartParkError(Exception):
    """Anything that stops an import."""


class SmartParkValidationError(SmartParkError):
    """The file can't be used as a SmartPark game file."""


class DuplicateSmartParkFile(SmartParkError):
    def __init__(self, message, game_id=None):
        super().__init__(message)
        self.game_id = game_id


# ---------------------------------------------------------------------------
# Reading the file
# ---------------------------------------------------------------------------

def norm(text) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def compute_file_hash(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def read_csv_bytes(file_bytes: bytes) -> pd.DataFrame:
    last_err = None
    for enc in ("utf-8-sig", "latin-1"):
        try:
            df = pd.read_csv(io.BytesIO(file_bytes), dtype=str, keep_default_na=False, encoding=enc)
            break
        except Exception as e:  # noqa: BLE001 -- report any parse failure the same way
            last_err = e
    else:
        raise SmartParkValidationError(f"Couldn't read this file as a CSV ({last_err}).")
    df = df.dropna(how="all")
    if df.empty:
        raise SmartParkValidationError("The file has no rows.")
    return df


def map_columns(columns):
    """-> (header_map {file column: field}, unmapped [file columns], missing_required [fields])."""
    header_map, unmapped, taken = {}, [], set()
    for c in columns:
        field = cols.COLUMN_ALIASES.get(norm(c))
        if field and field not in taken:
            header_map[c] = field
            taken.add(field)
        else:
            unmapped.append(c)
    missing = [f for f in cols.REQUIRED_FIELDS if f not in taken]
    return header_map, unmapped, missing


def _blank(v):
    return v is None or str(v).strip().lower() in cols.BLANK_VALUES


def _to_float(v):
    if _blank(v):
        return None
    try:
        return float(str(v).strip())
    except ValueError:
        return None


def _to_int(v):
    f = _to_float(v)
    return int(round(f)) if f is not None else None


def _to_str(v):
    return None if _blank(v) else str(v).strip()


def _is_top(v):
    t = norm(v or "")
    if t in cols.TOP_VALUES:
        return True
    if t in cols.BOTTOM_VALUES:
        return False
    return None


def parse_rows(df: pd.DataFrame, header_map: dict):
    """DataFrame -> list of plain dicts keyed by SmartParkPitch field name,
    plus "date"/"time"/"source_game_uid"/"is_top"/"raw_extra"/"row_index"."""
    rows = []
    for i, rec in enumerate(df.to_dict("records")):
        r = {"row_index": i, "raw_extra": {}}
        for col, val in rec.items():
            field = header_map.get(col)
            if field is None:
                if not _blank(val):
                    r["raw_extra"][str(col)] = str(val)
            elif field in cols.INT_FIELDS:
                r[field] = _to_int(val)
            elif field in cols.FLOAT_FIELDS:
                r[field] = _to_float(val)
            else:
                r[field] = _to_str(val)
        if all(r.get(f) is None for f in ("inning", "pitch_call", "pitcher_name")):
            continue  # a blank / footer line
        r["is_top"] = _is_top(r.get("top_bottom"))
        when = " ".join(x for x in (r.get("date"), r.get("time")) if x)
        r["pitch_time"] = pd.to_datetime(when, errors="coerce") if when else None
        if r["pitch_time"] is not None and pd.isna(r["pitch_time"]):
            r["pitch_time"] = None
        elif r["pitch_time"] is not None:
            r["pitch_time"] = r["pitch_time"].to_pydatetime()
        rows.append(r)
    if rows and all(r.get("pitch_no") is not None for r in rows):
        rows.sort(key=lambda r: (r["pitch_no"], r["row_index"]))
    return rows


def check_file(file_bytes: bytes):
    """Everything the page shows before importing. Raises SmartParkValidationError
    only when the file can't be read or is missing a required column."""
    df = read_csv_bytes(file_bytes)
    header_map, unmapped, missing = map_columns(df.columns)
    if missing:
        raise SmartParkValidationError(
            "This file is missing columns GBO needs: " + ", ".join(missing)
            + ". If SmartPark names them differently, add the names to services/smartpark_columns.py."
            + (" Columns in the file GBO didn't recognise: " + ", ".join(map(str, unmapped)) if unmapped else ""))
    rows = parse_rows(df, header_map)
    if not rows:
        raise SmartParkValidationError("No pitch rows found in the file.")
    game_uids = sorted({r["source_game_uid"] for r in rows if r.get("source_game_uid")})
    if len(game_uids) > 1:
        raise SmartParkValidationError(
            f"This file has {len(game_uids)} games in it ({', '.join(game_uids)}). Export one game per file.")
    bad_half = sum(1 for r in rows if r["is_top"] is None)
    if bad_half:
        raise SmartParkValidationError(f"{bad_half} rows have a Top/Bottom value GBO doesn't recognise.")
    dates = sorted({r["pitch_time"].date() for r in rows if r.get("pitch_time")})
    return {
        "rows": rows, "header_map": header_map, "unmapped": unmapped,
        "game_uid": game_uids[0] if game_uids else None, "dates": dates,
        "file_hash": compute_file_hash(file_bytes), "row_count": len(rows),
    }


# ---------------------------------------------------------------------------
# Matching names to players
# ---------------------------------------------------------------------------

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}


def name_key(name):
    """'Curry, Ryker' / 'Ryker Curry' / 'ryker curry jr.' -> 'ryker curry'."""
    if not name:
        return ""
    s = str(name).strip()
    if "," in s:
        last, first = s.split(",", 1)
        s = f"{first} {last}"
    words = [w for w in re.sub(r"[^a-z0-9 ]", " ", s.lower()).split() if w not in _SUFFIXES]
    return " ".join(words)


def source_keys(name, source_id):
    keys = []
    if source_id:
        keys.append(f"id:{str(source_id).strip()}")
    if name_key(name):
        keys.append(f"name:{name_key(name)}")
    return keys


class RosterMatcher:
    """Resolves a SmartPark name/ID to one of our Players: a saved link first,
    then a unique exact name match on the roster (active players preferred)."""

    def __init__(self, players, links):
        self.links = dict(links)  # source_key -> player_id
        self.by_name = {}
        for p in sorted(players, key=lambda p: not p.active):
            self.by_name.setdefault(name_key(f"{p.first_name} {p.last_name}"), []).append(p)

    def match(self, name, source_id):
        for k in source_keys(name, source_id):
            if k in self.links:
                return self.links[k]
        cands = self.by_name.get(name_key(name)) or []
        active = [p for p in cands if p.active]
        pick = active if active else cands
        return pick[0].player_id if len(pick) == 1 else None


def _hand(v):
    return cols.HAND_MAP.get(norm(v or ""))


# ---------------------------------------------------------------------------
# Building the game (pure -- no DB writes)
# ---------------------------------------------------------------------------

def first_batting_is_ours(game):
    from modules.game_tracking import first_batting_is_ours as f
    return f(game)


def _pitch_outcome(call):
    return cols.PITCH_CALL_MAP.get(norm(call or ""))


def _remove_runners(bases, n):
    b = list(bases)
    for idx in (2, 1, 0):
        if n <= 0:
            break
        if b[idx] == "1":
            b[idx] = "0"
            n -= 1
    return "".join(b)


def _add_runners(bases, n):
    b = list(bases)
    for idx in (2, 1, 0):
        if n <= 0:
            break
        if b[idx] == "0":
            b[idx] = "1"
            n -= 1
    return "".join(b)


def _lead_runner(bases):
    for idx in (2, 1, 0):
        if bases[idx] == "1":
            return idx + 1
    return None


def _ab_outcome(r, outcome, balls, strikes):
    """-> (ends_pa, ab_outcome, note) for one row."""
    kor = norm(r.get("kor_bb") or "")
    call = norm(r.get("pitch_call") or "")
    if kor in cols.STRIKEOUT_VALUES:
        return True, ("K (Looking)" if outcome == "Called Strike" else "K"), None
    if kor in cols.WALK_VALUES:
        return True, ("IBB" if call in cols.INTENTIONAL_BALL_CALLS else "BB"), None
    if outcome == "HBP":
        return True, "HBP", None
    if outcome == "In Play":
        hit_type = cols.HIT_TYPE_MAP.get(norm(r.get("tagged_hit_type") or ""))
        res = cols.PLAY_RESULT_MAP.get(norm(r.get("play_result") or ""))
        oop = r.get("outs_on_play")
        if res == "OUT":
            if oop is not None and oop >= 2:
                return True, "Double Play", None
            return True, cols.OUT_BY_HIT_TYPE.get(hit_type, "Groundout"), None
        if res == "SAC":
            return True, ("Sac Bunt" if norm(r.get("tagged_hit_type") or "") == "bunt" or hit_type == "Ground Ball" else "Sac Fly"), None
        if res:
            return True, res, None
        if oop:
            return True, ("Double Play" if oop >= 2 else cols.OUT_BY_HIT_TYPE.get(hit_type, "Groundout")), \
                "a ball in play had no play result -- saved as an out"
        return True, "1B", "a ball in play had no play result -- saved as a single"
    # No KorBB column / blank: fall back to the count.
    if not kor:
        if outcome in ("Called Strike", "Swing and Miss") and (strikes or 0) >= 2:
            return True, ("K (Looking)" if outcome == "Called Strike" else "K"), None
        if outcome == "Ball" and (balls or 0) >= 3:
            return True, "BB", None
    return False, None, None


def plan_game(rows, game, matcher, opponent_players=None, pitch_type_ids=None, re_lookup=None):
    """Turn parsed rows into everything the import writes, without writing.

    opponent_players: OpponentPlayer rows for the game's opponent team (external games).
    pitch_type_ids: {canonical type_name: pitch_type_id}.
    Returns a dict -- see the keys at the bottom. "unmatched" lists our-side
    names the matcher couldn't place; the import refuses until they're linked."""
    from modules.game_tracking import suggest_after_state, replay_game

    pitch_type_ids = pitch_type_ids or {}
    opp_by_name = {name_key(o.player_name): o.opponent_player_id for o in (opponent_players or [])}
    away_is_us = first_batting_is_ours(game)
    intrasquad = bool(game.is_intrasquad)

    warnings, notes = [], []
    unmatched = {}  # source_key -> {"name", "role"}
    new_opponents = {}  # name_key -> {"name", "bats", "throws"}
    pitches, events, forced, changes = [], [], [], []

    half_no = 0
    prev_half_key = None
    prev_side = None
    outs, bases = 0, "000"
    in_pa = False
    pa_batter = None
    opp_order = 0
    seq = 0
    last_our_pitcher = None
    unknown_calls = 0
    count_mismatch = 0

    def our_id(name, sid, role):
        pid = matcher.match(name, sid)
        if pid is None:
            keys = source_keys(name, sid)
            if keys:
                unmatched.setdefault(keys[0], {"name": name or "(no name)", "role": role, "keys": keys})
        return pid

    def add_event(anchor, side, etype, from_base, to_base, is_out, note):
        events.append(SimpleNamespace(
            pitch_sequence_after=anchor, is_our_team_batting=side, batting_squad=None, event_type=etype,
            from_base=from_base, to_base=to_base, is_out=is_out, created_at=datetime(2000, 1, 1, 0, 0, len(events) % 60, len(events)),
            notes=f"{SOURCE_NOTE}: {note}"))

    for r in rows:
        is_top = r["is_top"]
        side = (is_top == away_is_us)  # is_our_team_batting
        half_key = (r.get("inning"), is_top)

        # ---- half-inning boundaries ----
        if half_key != prev_half_key:
            if prev_half_key is not None:
                if in_pa and outs == 2 and _lead_runner(bases):
                    # 3rd out on the bases mid at-bat (caught stealing / pickoff)
                    add_event(seq, prev_side, "Out on Bases", _lead_runner(bases), None, True,
                              "3rd out on the bases during an at-bat (caught stealing / pickoff?) -- check")
                    notes.append(f"Inning {prev_half_key[0]}: the half ended on a base-running out mid at-bat.")
                    outs = 3
                    if side == prev_side:
                        forced.append(SimpleNamespace(
                            pitch_sequence_after=seq, inning=half_no, is_our_team_batting=prev_side, batting_squad=None,
                            runs_scored=0, same_side_continues=True, credited_player_id=None,
                            notes=f"{SOURCE_NOTE}: same side bats again"))
                elif outs < 3:
                    forced.append(SimpleNamespace(
                        pitch_sequence_after=seq, inning=half_no, is_our_team_batting=prev_side, batting_squad=None,
                        runs_scored=0, same_side_continues=(side == prev_side), credited_player_id=None,
                        notes=f"{SOURCE_NOTE}: half-inning ended with {outs} out(s)"))
                    notes.append(f"Inning {prev_half_key[0]} ({'Top' if prev_half_key[1] else 'Bottom'}) ended with "
                                 f"{outs} out(s) -- saved as an ended half-inning.")
                elif side == prev_side:
                    forced.append(SimpleNamespace(
                        pitch_sequence_after=seq, inning=half_no, is_our_team_batting=prev_side, batting_squad=None,
                        runs_scored=0, same_side_continues=True, credited_player_id=None,
                        notes=f"{SOURCE_NOTE}: same side bats again"))
            half_no += 1
            prev_half_key, prev_side = half_key, side
            outs, bases = 0, "000"
            in_pa = False
        else:
            # Outs the file shows that our play-by-play doesn't explain -> runner outs
            fo = r.get("outs")
            if fo is not None and fo > outs:
                for _ in range(fo - outs):
                    fb = _lead_runner(bases) or 1
                    add_event(seq, side, "Out on Bases", fb, None, True,
                              "an out happened between pitches (caught stealing / pickoff?) -- check")
                    bases = bases[:fb - 1] + "0" + bases[fb:]
                notes.append(f"Inning {r.get('inning')}: {fo - outs} out(s) between pitches added as base-running outs.")
                outs = fo
            elif fo is not None and fo < outs and pitches and pitches[-1]["ends_plate_appearance"]:
                # Our estimate of the last play's outs was too high -- trust the file.
                last = pitches[-1]
                last["outs_after"] = fo
                if last.get("_bases_before_clear"):
                    last["bases_after"] = last["_bases_before_clear"]
                    bases = last["bases_after"]
                outs = fo

        # ---- who's up ----
        batter_key = (name_key(r.get("batter_name")), r.get("batter_source_id"))
        if in_pa and batter_key != pa_batter:
            warnings.append(f"Inning {r.get('inning')}: the batter changed in the middle of an at-bat "
                            f"({r.get('batter_name')}) -- check that at-bat in the Pitch Log.")
            in_pa = False
        new_pa = not in_pa
        if new_pa:
            pa_batter = batter_key
            if not side:
                opp_order = opp_order % 9 + 1

        if side:  # we're batting
            our_player = our_id(r.get("batter_name"), r.get("batter_source_id"), "batter")
            opp_hand = _hand(r.get("pitcher_throws"))
            other_name, other_sid, other_role = r.get("pitcher_name"), r.get("pitcher_source_id"), "pitcher"
        else:  # we're pitching
            our_player = our_id(r.get("pitcher_name"), r.get("pitcher_source_id"), "pitcher")
            opp_hand = _hand(r.get("batter_side"))
            other_name, other_sid, other_role = r.get("batter_name"), r.get("batter_source_id"), "batter"

        opponent_our_player = opponent_player = opponent_key = None
        if intrasquad:
            opponent_our_player = our_id(other_name, other_sid, other_role)
        elif other_name:
            opponent_key = name_key(other_name)
            opponent_player = opp_by_name.get(opponent_key)
            if opponent_player is None and opponent_key:
                info = new_opponents.setdefault(opponent_key, {"name": other_name, "bats": None, "throws": None})
                if other_role == "batter" and opp_hand:
                    info["bats"] = info["bats"] or opp_hand
                if other_role == "pitcher" and opp_hand:
                    info["throws"] = info["throws"] or opp_hand

        pitcher_id = our_player if not side else opponent_our_player
        if not side and our_player is not None and our_player != last_our_pitcher:
            changes.append({"player_id": our_player, "inning": half_no, "outs_at_entry": outs,
                            "pitch_sequence_at_entry": seq})
            last_our_pitcher = our_player

        # ---- the pitch ----
        outcome = _pitch_outcome(r.get("pitch_call"))
        if outcome is None:
            unknown_calls += 1
        ends_pa, ab, ab_note = _ab_outcome(r, outcome, r.get("balls"), r.get("strikes"))
        if ab_note:
            warnings.append(f"Inning {r.get('inning')}, {r.get('batter_name')}: {ab_note}.")

        raw_type = r.get("tagged_pitch_type")
        canon = normalize_pitch_type(raw_type) or normalize_pitch_type(r.get("auto_pitch_type"))
        pt_id = pitch_type_ids.get(canon) if canon else None

        px = r.get("plate_loc_side")
        pz = r.get("plate_loc_height")
        px = round(px * cols.PLATE_SIDE_SIGN, 3) if px is not None else None
        pz = round(pz, 3) if pz is not None else None

        bb_type = bb_x = bb_y = None
        contact = None
        if outcome == "In Play":
            bb_type = cols.HIT_TYPE_MAP.get(norm(r.get("tagged_hit_type") or ""))
            if norm(r.get("tagged_hit_type") or "") == "bunt":
                contact = "Bunt"
            d, dist = r.get("direction"), r.get("distance")
            if d is not None and dist is not None:
                a = math.radians(d * cols.DIRECTION_SIGN)
                bb_x, bb_y = round(dist * math.sin(a), 1), round(dist * math.cos(a), 1)

        seq += 1
        p = {
            "pitch_sequence": seq, "game_pitch_id": seq, "inning": half_no, "is_our_team_batting": side,
            "batting_squad": None, "our_player_id": our_player, "opponent_hand": opp_hand,
            "opponent_batting_order": opp_order if not side else None,
            "opponent_player_id": opponent_player, "_opponent_key": opponent_key,
            "opponent_our_player_id": opponent_our_player,
            "pitch_type_id": pt_id, "actual_plate_x": px, "actual_plate_z": pz,
            "pitch_zone": derive_old_zone(px, pz) if px is not None and pz is not None else None,
            "pitch_outcome": outcome, "contact_quality": contact,
            "batted_ball_type": bb_type, "batted_ball_x": bb_x, "batted_ball_y": bb_y,
            "is_pitch": True, "ends_plate_appearance": ends_pa, "ab_outcome": ab,
            "outs_after": None, "bases_after": None, "runs_scored_on_play": 0, "unearned_runs_on_play": 0,
            "_row": r, "_pitcher_id": pitcher_id, "_batter_id": our_player if side else opponent_our_player,
            "_file_count": (r.get("balls"), r.get("strikes")),
        }

        if ends_pa:
            s_outs, s_bases, s_runs = suggest_after_state(ab, bases, outs)
            if ab in ("K", "K (Looking)"):
                o_after = outs + 1 + max(0, (r.get("outs_on_play") or 0) - 1)
            elif r.get("outs_on_play") is not None and outcome == "In Play":
                o_after = outs + r["outs_on_play"]
            else:
                o_after = s_outs
            runs = r.get("runs_scored")
            if runs is None:
                runs = s_runs
            runs = max(0, min(runs, bases.count("1") + 1))
            b_after = s_bases
            if runs > s_runs:
                b_after = _remove_runners(b_after, runs - s_runs)
            elif runs < s_runs:
                b_after = _add_runners(b_after, s_runs - runs)
            o_after = min(o_after, 3)
            p["_bases_before_clear"] = b_after
            if o_after >= 3:
                b_after = "000"
            p.update(outs_after=o_after, bases_after=b_after, runs_scored_on_play=runs)
            outs, bases = o_after, b_after
            in_pa = False
        else:
            in_pa = True
            mid_runs = r.get("runs_scored") or 0
            for _ in range(mid_runs):
                fb = _lead_runner(bases) or 3
                add_event(seq, side, "Wild Pitch", fb, 4, False,
                          "a run scored during this at-bat; the file doesn't say how -- check")
                bases = bases[:fb - 1] + "0" + bases[fb:]
            if mid_runs:
                notes.append(f"Inning {r.get('inning')}: {mid_runs} run(s) scored between pitches -- saved as "
                             "wild-pitch runs; change the type in Game Tracking if it was something else.")
        pitches.append(p)

    if pitches and not pitches[-1]["ends_plate_appearance"]:
        notes.append("The file's last pitch didn't end an at-bat (game ended mid at-bat).")

    # ---- the count/outs/inning chain + run expectancy, exactly as the app computes it ----
    replay = replay_game([SimpleNamespace(**{k: v for k, v in p.items() if not k.startswith("_")}) for p in pitches],
                         events, re_lookup or {}, forced_ends=forced, game=game)
    for p in pitches:
        chain = replay["by_pitch"][p["game_pitch_id"]]
        fb, fs = p["_file_count"]
        if fb is not None and fs is not None and (fb, fs) != (chain["balls_before"], chain["strikes_before"]):
            count_mismatch += 1
        p.update({k: chain[k] for k in ("balls_before", "strikes_before", "outs_before", "bases_before",
                                         "pa_pitch_number", "re_before", "re_after", "run_value")})
    if replay["side_changed_pitch_ids"]:
        warnings.append(f"{len(replay['side_changed_pitch_ids'])} pitch(es) landed in a different half-inning "
                        "than the file says -- review the game in the Pitch Log.")
    if count_mismatch:
        warnings.append(f"{count_mismatch} pitch(es) have a different count than the file shows "
                        "(usually a missing pitch in the export).")
    if unknown_calls:
        warnings.append(f"{unknown_calls} pitch(es) had a pitch result GBO didn't recognise -- add the word to "
                        "PITCH_CALL_MAP in services/smartpark_columns.py.")
    if any(p["ab_outcome"] == "E" and p["runs_scored_on_play"] for p in pitches):
        notes.append("Runs scored on errors are saved as earned -- tag unearned runs in the Pitch Log.")
    notes.append("Base runners are estimated from each play's result (steals and wild pitches aren't in the "
                 "file), so run expectancy on those plays is approximate.")

    return {
        "pitches": pitches, "runner_events": events, "forced_ends": forced, "pitching_changes": changes,
        "our_score": replay["our_score"], "opponent_score": replay["opponent_score"],
        "unmatched": unmatched, "new_opponents": new_opponents,
        "warnings": warnings, "notes": notes,
    }


def side_sanity(plan, game):
    """External games: if none of the batters on 'our' side matched the roster
    but the other side's names would have, Home/Away on the game is likely wrong."""
    if game.is_intrasquad or not plan["pitches"]:
        return None
    ours_unmatched = sum(1 for p in plan["pitches"] if p["our_player_id"] is None)
    if ours_unmatched == len(plan["pitches"]):
        return ("None of the players on Pitt State's side of this file matched the roster. "
                "Check Home/Away on the game -- if PSU was home, the file's Bottom halves are ours.")
    return None


# ---------------------------------------------------------------------------
# DB side
# ---------------------------------------------------------------------------

def load_matcher(db):
    players = db.query(Player).all()
    links = {l.source_key: l.player_id for l in db.query(SmartParkPlayerLink).all()}
    return RosterMatcher(players, links)


def save_links(db, links):
    """links: {source_key: (source_name, player_id)} picked by a coach."""
    for key, (name, pid) in links.items():
        row = db.query(SmartParkPlayerLink).filter(SmartParkPlayerLink.source_key == key).first()
        if row:
            row.player_id, row.source_name = pid, name
        else:
            db.add(SmartParkPlayerLink(source_key=key, source_name=name, player_id=pid))
    db.flush()


def empty_games(db):
    """Games with nothing charted yet -- the ones a SmartPark file can fill."""
    has_pitch = db.query(GamePitch.game_id).distinct()
    return (db.query(Game).filter(~Game.game_id.in_(has_pitch), Game.status != "Cancelled")
            .order_by(Game.game_date.desc()).all())


def preview(db, file_bytes, game_id):
    """check_file + plan_game for one game, nothing written."""
    from modules.game_tracking import build_re_lookup
    info = check_file(file_bytes)
    game = db.query(Game).filter(Game.game_id == game_id).first()
    if game is None:
        raise SmartParkError("That game no longer exists.")
    if getattr(game, "uses_three_squad_intrasquad", False):
        raise SmartParkError("Three-team intrasquads can't be imported yet -- chart those in Game Tracking.")
    opp = []
    if game.opponent_team_id:
        opp = db.query(OpponentPlayer).filter(OpponentPlayer.team_id == game.opponent_team_id).all()
    pt_ids = {t.type_name: t.pitch_type_id for t in db.query(PitchType).all()}
    plan = plan_game(info["rows"], game, load_matcher(db), opp, pt_ids, build_re_lookup(db))
    flipped = side_sanity(plan, game)
    if flipped:
        plan["warnings"].insert(0, flipped)
    if info["dates"] and game.game_date not in info["dates"]:
        plan["warnings"].insert(0, f"The file is from {info['dates'][0]:%b %d, %Y} but the game you picked is "
                                   f"{game.game_date:%b %d, %Y}.")
    return info, game, plan


_SP_FIELDS = [c.name for c in SmartParkPitch.__table__.columns
              if c.name not in ("smartpark_pitch_id", "import_id", "game_id", "game_pitch_id", "pitcher_player_id",
                                "batter_player_id", "pitch_type_id", "plate_x_ft", "plate_z_ft", "raw_extra", "created_at")]


def import_game(db, file_bytes, filename, game_id, user_id):
    """Writes the whole game. Caller commits. Returns the SmartParkImport."""
    file_hash = compute_file_hash(file_bytes)
    dup = db.query(SmartParkImport).filter(SmartParkImport.file_hash == file_hash).first()
    if dup:
        raise DuplicateSmartParkFile("This exact file was already imported.", game_id=dup.game_id)
    if db.query(GamePitch.game_pitch_id).filter(GamePitch.game_id == game_id).first():
        raise SmartParkError("That game already has charted pitches. Pick an empty game, or delete the old import first.")

    info, game, plan = preview(db, file_bytes, game_id)
    if plan["unmatched"]:
        names = ", ".join(sorted(u["name"] for u in plan["unmatched"].values()))
        raise SmartParkError(f"Match these players to the roster first: {names}")

    # opponents GBO hasn't seen yet join the opponent team's roster
    opp_ids = {}
    if game.opponent_team_id:
        for key, o in plan["new_opponents"].items():
            row = OpponentPlayer(team_id=game.opponent_team_id, player_name=name_key(o["name"]).title(),
                                 bats=o["bats"], throws=o["throws"], notes="Added by SmartPark import")
            db.add(row)
            db.flush()
            opp_ids[key] = row.opponent_player_id

    imp = SmartParkImport(game_id=game.game_id, original_filename=filename or "smartpark.csv", file_hash=file_hash,
                          source_game_uid=info["game_uid"], uploaded_by_user_id=user_id, row_count=info["row_count"],
                          pitch_count=len(plan["pitches"]),
                          status="partial" if plan["warnings"] else "success",
                          warnings="\n".join(plan["warnings"] + plan["notes"]) or None)
    db.add(imp)
    db.flush()

    gp_fields = {c.name for c in GamePitch.__table__.columns} - {"game_pitch_id", "game_id"}
    for p in plan["pitches"]:
        if p["opponent_player_id"] is None and p["_opponent_key"] in opp_ids:
            p["opponent_player_id"] = opp_ids[p["_opponent_key"]]
        gp = GamePitch(game_id=game.game_id, **{k: v for k, v in p.items() if k in gp_fields})
        db.add(gp)
        db.flush()
        r = p["_row"]
        sp = SmartParkPitch(import_id=imp.import_id, game_id=game.game_id, game_pitch_id=gp.game_pitch_id,
                            pitcher_player_id=p["_pitcher_id"], batter_player_id=p["_batter_id"],
                            pitch_type_id=p["pitch_type_id"], plate_x_ft=p["actual_plate_x"], plate_z_ft=p["actual_plate_z"],
                            raw_extra=r.get("raw_extra") or None,
                            **{f: r.get(f) for f in _SP_FIELDS})
        db.add(sp)

    for ev in plan["runner_events"]:
        db.add(GameRunnerEvent(game_id=game.game_id, pitch_sequence_after=ev.pitch_sequence_after,
                               is_our_team_batting=ev.is_our_team_batting, event_type=ev.event_type,
                               from_base=ev.from_base, to_base=ev.to_base, is_out=ev.is_out, notes=ev.notes,
                               created_by_user_id=user_id, created_at=datetime.utcnow()))
    for fe in plan["forced_ends"]:
        db.add(GameForcedHalfInningEnd(game_id=game.game_id, pitch_sequence_after=fe.pitch_sequence_after,
                                       inning=fe.inning, is_our_team_batting=fe.is_our_team_batting, runs_scored=0,
                                       same_side_continues=fe.same_side_continues, notes=fe.notes,
                                       created_by_user_id=user_id))
    for i, ch in enumerate(plan["pitching_changes"]):
        if i == 0 and game.starting_pitcher_id in (None, ch["player_id"]):
            game.starting_pitcher_id = ch["player_id"]
        else:
            db.add(PitchingChange(game_id=game.game_id, **ch))
    if game.is_intrasquad and game.squad_b_starting_pitcher_id is None:
        first_b = next((p["opponent_our_player_id"] for p in plan["pitches"] if p["is_our_team_batting"]), None)
        game.squad_b_starting_pitcher_id = first_b

    game.our_score = plan["our_score"]
    game.opponent_score = plan["opponent_score"]
    game.status = "Final"
    db.flush()
    return imp


def delete_import(db, import_id):
    """Undo an import: clears the game's pitch-by-pitch (it was empty before
    the import) so the game can be re-imported. Caller commits."""
    imp = db.query(SmartParkImport).filter(SmartParkImport.import_id == import_id).first()
    if imp is None:
        raise SmartParkError("That import no longer exists.")
    game = db.query(Game).filter(Game.game_id == imp.game_id).first()
    gp_ids = [i for (i,) in db.query(GamePitch.game_pitch_id).filter(GamePitch.game_id == imp.game_id).all()]
    if gp_ids:
        db.query(RapsodoPitch).filter(RapsodoPitch.game_pitch_id.in_(gp_ids)).update(
            {RapsodoPitch.game_pitch_id: None}, synchronize_session=False)
        db.query(GameVideoClip).filter(GameVideoClip.matched_game_pitch_id.in_(gp_ids)).update(
            {GameVideoClip.matched_game_pitch_id: None}, synchronize_session=False)
        db.query(PitchTypeChange).filter(PitchTypeChange.game_pitch_id.in_(gp_ids)).update(
            {PitchTypeChange.game_pitch_id: None}, synchronize_session=False)
    db.query(SmartParkPitch).filter(SmartParkPitch.import_id == imp.import_id).delete(synchronize_session=False)
    for model in (GameRunnerEvent, GameForcedHalfInningEnd, PitchingChange, GamePitch):
        db.query(model).filter(model.game_id == imp.game_id).delete(synchronize_session=False)
    db.delete(imp)
    if game is not None:
        game.our_score = game.opponent_score = 0
        game.status = "Scheduled"
    db.flush()
    return imp.game_id
