"""
GBO -- Pitch label check across the staff (Oct 2026 reorganization, Ryker
approved: data cleanup in one place). Data Health's "Pitch labels" tab
lists every pitcher whose Rapsodo readings the two label checks flag --
Fastball Shape Check (4-seam vs 2-seam, analytics/fastball_shape.py) and
Pitch Type Check (fastball / breaking / offspeed, analytics/pitch_class.py)
-- with counts; the fixing (switch / undo) stays on those checks in
Pitcher Profile, one click away.
"""

from collections import defaultdict
from datetime import datetime, time

from sqlalchemy.orm import joinedload

from analytics import fastball_shape, pitch_class


def staff_flags(db, d0, d1):
    """[{player, n, fs, fs_unlabeled, ptc}] for pitchers with readings in range, most flags first."""
    from models import RapsodoPitch, Player, PitchType, PlayerPitchArsenal
    lo, hi = datetime.combine(d0, time.min), datetime.combine(d1, time.max)
    by_p = defaultdict(list)
    for r in (db.query(RapsodoPitch).options(joinedload(RapsodoPitch.pitch_type))
              .filter(RapsodoPitch.pitch_date >= lo, RapsodoPitch.pitch_date <= hi).all()):
        by_p[r.player_id].append(r)
    if not by_p:
        return []
    players = {p.player_id: p for p in db.query(Player).filter(Player.player_id.in_(list(by_p))).all()}
    arsenal = defaultdict(list)
    for pid, name in (db.query(PlayerPitchArsenal.player_id, PitchType.type_name)
                      .join(PitchType, PitchType.pitch_type_id == PlayerPitchArsenal.pitch_type_id)
                      .filter(PlayerPitchArsenal.player_id.in_(list(by_p)), PlayerPitchArsenal.active.is_(True)).all()):
        arsenal[pid].append(name)
    centers = pitch_class.team_centers(db)["centers"]
    out = []
    for pid, raps in by_p.items():
        pl = players.get(pid)
        if pl is None:
            continue
        fs = fastball_shape.check_pitcher(raps, pl.throws or "R", arsenal=arsenal.get(pid) or None)
        ptc = pitch_class.check_pitcher(raps, pl.throws or "R", centers)
        mism = sum(1 for f in fs["flags"] if f.get("kind") != "unlabeled")
        unl = sum(1 for f in fs["flags"] if f.get("kind") == "unlabeled")
        out.append({"player": pl, "n": len(raps), "fs": mism, "fs_unlabeled": unl, "ptc": len(ptc["flags"])})
    out.sort(key=lambda r: (-(r["fs"] + r["ptc"]), -r["fs_unlabeled"], r["player"].last_name))
    return out
