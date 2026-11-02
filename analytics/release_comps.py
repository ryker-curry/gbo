"""
GBO -- Release card + PSU teammate comps, data layer (Nov 2026, Ryker:
Past The Eye Test-style release point card and pitcher similarity comps,
PSU vs PSU only -- no MLB pool).

One row per pitcher who threw a charted game pitch in the window:
  Release  -- most-thrown fastball's average release height / side
              (absolute, so lefties and righties compare) / extension
              and GBO's estimated arm angle, from GAME-linked Rapsodo
              pitches only (bullpens never count, same as Physical
              Profile and the research-study rules).
  Arsenal  -- usage % per pitch family from charted game pitches, plus
              fastball velo / IVB / HB (abs = arm side) from Rapsodo.
  Whiff / Command / Contact -- straight from
              profile_queries.pitching_staff_leaderboard_rows, so the
              numbers match the Pitching Leaderboard exactly.

Feeds release_graphics.find_comps()/similarity()/comparison_html().
Cached briefly (same pattern as analytics/outperform.py) because the
leaderboard rows are the expensive part.
"""

import time

import pandas as pd

_cache = {}
CACHE_SECONDS = 600
MIN_COMP_GAME_PITCHES = 20   # fewer charted game pitches -> not in the comp pool


def _rapsodo_game_pitches(db, pids, date_from, date_to, game_scope):
    from sqlalchemy.orm import joinedload
    from models import RapsodoPitch, GamePitch, Game
    q = (db.query(RapsodoPitch)
         .options(joinedload(RapsodoPitch.pitch_type))
         .join(GamePitch, RapsodoPitch.game_pitch_id == GamePitch.game_pitch_id)
         .join(Game, GamePitch.game_id == Game.game_id)
         .filter(RapsodoPitch.player_id.in_(list(pids))))
    if date_from is not None:
        q = q.filter(Game.game_date >= date_from)
    if date_to is not None:
        q = q.filter(Game.game_date <= date_to)
    if game_scope == "intrasquad":
        q = q.filter(Game.is_intrasquad.is_(True))
    elif game_scope == "external":
        q = q.filter(Game.is_intrasquad.is_(False))
    out = {}
    for r in q.all():
        out.setdefault(r.player_id, []).append(r)
    return out


def _usage(game_pitches):
    from release_graphics import PITCH_FAMILY
    fams = [PITCH_FAMILY.get(p.pitch_type.type_name) if p.pitch_type is not None else None
            for p in game_pitches]
    fams = [f for f in fams if f]
    if not fams:
        return {}
    return {f"usage_{k}": round(100.0 * fams.count(k) / len(fams), 1)
            for k in ("fb", "si", "fc", "sl", "cu", "ch")}


def _fb_shape(raps):
    from release_graphics import card_pitches, _avg
    fb, label = card_pitches(raps)
    if not fb or label not in ("4-Seam Fastball", "Fastball", "2-Seam Fastball"):
        return {}
    return {"fb_velo": _avg(p.velocity for p in fb),
            "fb_ivb": _avg(p.vb_spin for p in fb),
            "fb_hb": _avg(abs(float(p.hb_spin)) for p in fb if p.hb_spin is not None)}


def staff_pool(db, date_from=None, date_to=None, game_scope="all"):
    """-> {"pool": DataFrame (one row per pitcher, player_id + features),
           "profiles": {pid: ReleaseProfile or None},
           "players": {pid: Player}}"""
    from sqlalchemy import func
    from models import GamePitch, RapsodoPitch
    from analytics.profile_queries import pitching_staff_leaderboard_rows, _pitching_staff_query
    from release_graphics import profile_from_rapsodo

    stamp = (db.query(func.count(GamePitch.game_pitch_id)).scalar(),
             db.query(func.count(RapsodoPitch.rapsodo_pitch_id)).scalar())
    key = (id(db.get_bind()), date_from, date_to, game_scope, stamp)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]

    rows = pitching_staff_leaderboard_rows(db, date_from=date_from, date_to=date_to, game_scope=game_scope)
    players = {r["player"].player_id: r["player"] for r in rows}

    by_pid = {}
    for p in _pitching_staff_query(db, date_from, date_to, game_scope).all():
        pid = p.opponent_our_player_id if p.is_our_team_batting else p.our_player_id
        if pid in players:
            by_pid.setdefault(pid, []).append(p)
    raps = _rapsodo_game_pitches(db, players.keys(), date_from, date_to, game_scope) if players else {}

    recs, profiles = [], {}
    for r in rows:
        pid = r["player"].player_id
        prof = profile_from_rapsodo(r["player"], raps.get(pid, []))
        profiles[pid] = prof
        rec = {"player_id": pid, "_n_game_pitches": len(by_pid.get(pid, []))}
        if prof is not None:
            rec.update(arm_angle=prof.arm_angle, release_side_ft=prof.release_side_ft,
                       release_height_ft=prof.release_height_ft,
                       extension_ft=prof.extension_ft or None)
        rec.update(_usage(by_pid.get(pid, [])))
        rec.update(_fb_shape(raps.get(pid, [])))
        rec.update(stuff_plus=r.get("Stuff+"), k_pct=r.get("K %"), csw_pct=r.get("CSW %"),
                   location_plus=r.get("Location+"), command_plus=r.get("Command+"),
                   bb_pct=r.get("BB %"), first_pitch_strike_pct=r.get("FPS %"),
                   oba=r.get("OBA"), rv_per_100=r.get("RV/100"))
        recs.append(rec)

    pool = pd.DataFrame(recs)
    if not pool.empty:
        pool = pool[pool["_n_game_pitches"] >= MIN_COMP_GAME_PITCHES].reset_index(drop=True)
        for c in pool.columns:
            if c != "player_id":
                pool[c] = pd.to_numeric(pool[c], errors="coerce")
    res = {"pool": pool, "profiles": profiles, "players": players}
    _cache.clear()
    _cache[key] = (time.time(), res)
    return res


def closest_teammates(summ, pid, n=3):
    """[(Player, overall_similarity, {category: sim})] for the n closest
    teammates, or [] if he isn't in the pool / the pool is too small."""
    from release_graphics import find_comps
    pool = summ["pool"]
    if pool.empty or pid not in set(pool["player_id"]) or len(pool) < 3:
        return []
    comps = find_comps(pid, pool, n=n, group_col=None)
    out = []
    for _, c in comps.iterrows():
        cats = {k[4:].capitalize(): v for k, v in c.items()
                if k.startswith("sim_") and pd.notna(v)}
        out.append((summ["players"].get(int(c["player_id"])), float(c["similarity"]), cats))
    return [o for o in out if o[0] is not None]


def compare(summ, pid_a, pid_b):
    """(row_a, row_b, sim dict) or None if either pitcher isn't in the pool."""
    from release_graphics import zscore_pool, similarity
    pool = summ["pool"]
    if pool.empty:
        return None
    ids = set(pool["player_id"])
    if pid_a not in ids or pid_b not in ids:
        return None
    z = zscore_pool(pool, None)
    za = z[z["player_id"] == pid_a].iloc[0]
    zb = z[z["player_id"] == pid_b].iloc[0]
    ra = pool[pool["player_id"] == pid_a].iloc[0]
    rb = pool[pool["player_id"] == pid_b].iloc[0]
    return ra, rb, similarity(za, zb)
