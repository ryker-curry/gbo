"""
GBO -- Throw sensor CSV import (PULSE / Motus / any sensor). Nov 2026: GBO
doesn't have sensors yet, so this reads a CSV loosely instead of one fixed
layout -- once a real export is in hand, tighten COLUMN_HINTS to it.

Two shapes work:
  per-day   one row per athlete per day with a throw-count column
  per-throw one row per throw (no throw-count column) -- rows are counted
Columns are found by name (case / spacing ignored); see COLUMN_HINTS.
Names: an athlete / player / name column ("First Last" or "Last, First"),
or separate first / last columns. Matched to the roster with the same
exact-then-close rules as the testing workbook import.

Re-importing replaces: each player/day in the file deletes that player's
earlier rows from the same source on that day first, so an overlapping
export never double counts.
"""

import csv
import io
import re
from collections import defaultdict
from datetime import datetime

from models import Player, ThrowLog
from services.study_workbook_import import match_names, name_key

COLUMN_HINTS = {
    "date": ["date", "day", "sessiondate", "throwdate", "timestamp", "datetime", "time"],
    "name": ["athlete", "athletename", "player", "playername", "name", "user", "username", "fullname"],
    "first": ["first", "firstname"],
    "last": ["last", "lastname"],
    "throws": ["throws", "throwcount", "totalthrows", "numthrows", "count", "throwstotal"],
    "high": ["highintent", "highintentthrows", "higheffort", "higheffortthrows", "highthrows"],
    "workload": ["workload", "dailyworkload", "workloadscore", "stress", "acuteworkload"],
    "torque": ["peaktorque", "maxtorque", "torque", "elbowtorque", "varustorque", "elbowvarustorque"],
}
DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%d-%b-%Y", "%b %d, %Y", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y %I:%M %p", "%m/%d/%Y %H:%M:%S"]


def _k(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def find_columns(headers):
    keys = {_k(h): h for h in headers}
    found = {}
    for field, hints in COLUMN_HINTS.items():
        for h in hints:                       # exact first, in hint order
            if h in keys:
                found[field] = keys[h]
                break
        else:
            for kh, orig in keys.items():     # then "contains"
                if field == "throws" and ("high" in kh or "effort" in kh):
                    continue
                if any(h in kh for h in hints if len(h) > 4) and orig not in found.values():
                    found[field] = orig
                    break
    return found


def parse_date(v):
    s = (v or "").strip()
    if not s:
        return None
    s2 = re.sub(r"(\.\d+)?(Z|[+-]\d\d:?\d\d)$", "", s)
    for f in DATE_FORMATS:
        try:
            return datetime.strptime(s2, f).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s2).date()
    except ValueError:
        return None


def _num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _split_name(row, cols):
    if "first" in cols and "last" in cols:
        return (row.get(cols["first"]) or "").strip(), (row.get(cols["last"]) or "").strip()
    n = (row.get(cols.get("name")) or "").strip()
    if "," in n:
        last, first = [x.strip() for x in n.split(",", 1)]
        return first, last
    parts = n.split()
    return (parts[0], " ".join(parts[1:])) if len(parts) > 1 else (n, "")


def build_plan(db, file_bytes):
    """Read the CSV and match names. Returns {"ok", "error", "columns",
    "per_throw", "days": [{player_id, player, sheet_name, how, date, throws,
    high_intent, workload, peak_torque}], "unmatched": [...], "bad_rows"}."""
    text = file_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []
    cols = find_columns(headers)
    if "date" not in cols or not ("name" in cols or ("first" in cols and "last" in cols)):
        return {"ok": False, "error": "Couldn't find a date column and an athlete name column. Columns in the file: "
                + ", ".join(headers), "columns": cols}
    per_throw = "throws" not in cols
    agg = defaultdict(lambda: {"throws": 0, "high": None, "workload": None, "torque": None})
    bad = 0
    for row in reader:
        d = parse_date(row.get(cols["date"]))
        first, last = _split_name(row, cols)
        if d is None or not (first or last):
            bad += 1
            continue
        a = agg[(name_key(first, last), first, last, d)]
        if per_throw:
            a["throws"] += 1
        else:
            n = _num(row.get(cols["throws"]))
            if n is None:
                bad += 1
                continue
            a["throws"] += int(round(n))
        if "high" in cols and _num(row.get(cols["high"])) is not None:
            a["high"] = (a["high"] or 0) + int(round(_num(row.get(cols["high"]))))
        if "workload" in cols and _num(row.get(cols["workload"])) is not None:
            a["workload"] = (a["workload"] or 0) + _num(row.get(cols["workload"]))
        if "torque" in cols and _num(row.get(cols["torque"])) is not None:
            a["torque"] = max(a["torque"] or 0, _num(row.get(cols["torque"])))
    players = db.query(Player).filter(Player.active.is_(True)).all()
    by_id = {p.player_id: p for p in players}
    matches = match_names(players, sorted({k[0] for k in agg}))
    days, unmatched = [], set()
    for (key, first, last, d), a in sorted(agg.items(), key=lambda kv: (kv[0][2], kv[0][1], kv[0][3])):
        m = matches.get(key) or {}
        pid = m.get("player_id")
        if pid is None:
            unmatched.add(f"{first} {last}".strip())
            continue
        p = by_id[pid]
        days.append({"player_id": pid, "player": f"{p.first_name} {p.last_name}", "sheet_name": f"{first} {last}".strip(),
                     "how": m.get("how"), "date": d, "throws": a["throws"], "high_intent": a["high"],
                     "workload": a["workload"], "peak_torque": a["torque"]})
    return {"ok": bool(days), "error": None if days else "No rows matched a GBO player.", "columns": cols,
            "per_throw": per_throw, "days": days, "unmatched": sorted(unmatched), "bad_rows": bad}


def commit_plan(db, plan, source, user_id):
    """Replace this source's rows for each player/day in the plan, then add."""
    n = 0
    for d in plan["days"]:
        (db.query(ThrowLog).filter(ThrowLog.player_id == d["player_id"], ThrowLog.log_date == d["date"],
                                   ThrowLog.source == source).delete(synchronize_session=False))
        db.add(ThrowLog(player_id=d["player_id"], log_date=d["date"], throw_type="Sensor total", throws=d["throws"],
                        high_intent=d["high_intent"], source=source,
                        workload=round(d["workload"], 2) if d["workload"] is not None else None,
                        peak_torque=round(d["peak_torque"], 1) if d["peak_torque"] is not None else None,
                        notes=f"Imported {source.upper()} export", created_by_user_id=user_id,
                        created_at=datetime.utcnow()))
        n += 1
    db.commit()
    return n
