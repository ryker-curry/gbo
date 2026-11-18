"""
GBO -- player-facing release view, data layer (Nov 2026, Ryker: "would like
each pitcher to be able to see this view when they login").

Three pieces, all built on what's already here:
  * by_type()     -- every pitch type's average release vs his fastball
                     (games + bullpens, Ryker's call -- more readings per
                     pitch type in the fall than games alone).
  * outings()     -- fastball arm angle per outing, for the trend line.
  * slot_comps()  -- "Pitchers Like You": closest teammates on RELEASE ONLY
                     (release_graphics.find_comps, Release category), using
                     analytics.release_comps.staff_pool -- game pitches only
                     and its MIN_COMP_GAME_PITCHES floor, same pool as the
                     staff Arsenal Comparison page. Each comp's best pitch is
                     his top Whiff % from game_stats.compute_pitch_type_breakdown.

Arm angle everywhere is GBO's existing estimate
(analytics.bullpen_metrics.average_estimated_arm_angle), so these numbers
match Physical Profile and the release card. Display: shiny_app/release_view_display.py.
"""

from statistics import mean

from analytics import pitch_insights

MIN_TYPE_READINGS = 5     # readings of a pitch type before it gets a dot/row
MIN_OUTING_FB = 5         # fastball readings in an outing before it's on the trend
TREND_OUTINGS = 8         # outings shown on the trend
DRIFT_DEG = 3.0           # last 3 outings vs the ones before -- flag at this change
DRIFT_MIN_OUTINGS = 5
TELL_IN = pitch_insights.RELEASE_OFFSET_IN   # same 3 in "hitters can pick it up" line
MIN_BEST_PITCHES = 15     # game pitches of a type before it can be a comp's "best pitch"
MIN_BEST_SWINGS = 5


def player_pitches(db, pid, date_from=None, date_to=None):
    """Every Rapsodo reading for him in the window -- games AND bullpens."""
    from analytics.profile_queries import get_pitcher_rapsodo_pitches
    return get_pitcher_rapsodo_pitches(db, pid, date_from=date_from, date_to=date_to,
                                       game_linked_only=False) or []


def _f(v):
    return float(v) if v is not None else None


def _arm_angle(pitches, player):
    if player is None or getattr(player, "height_in", None) is None:
        return None
    try:
        from analytics.bullpen_metrics import average_estimated_arm_angle
        angle, _n = average_estimated_arm_angle(pitches, player)
        return angle
    except Exception:
        return None


def _type_name(p):
    from release_graphics import _type_name as tn
    return tn(p)


def by_type(raps, player):
    """[{type, n, height, side, ext, arm_angle, dh_in, ds_in, offset_in, is_fb, tell}]
    fastball first. side is absolute (toward his arm side), so dh/ds read the
    same for lefties and righties: ds > 0 = farther toward his arm side."""
    from release_graphics import card_pitches
    _fb_pitches, fb_label = card_pitches(raps)
    groups = {}
    for p in raps:
        if p.release_height is None or p.release_side is None:
            continue
        groups.setdefault(_type_name(p) or "Unclassified", []).append(p)
    rows = []
    for label, ps in groups.items():
        if len(ps) < MIN_TYPE_READINGS or label == "Unclassified":
            continue
        exts = [_f(p.release_extension) for p in ps if p.release_extension is not None and float(p.release_extension) > 0]
        rows.append({
            "type": label, "n": len(ps),
            "height": mean(_f(p.release_height) for p in ps),
            "side": mean(abs(_f(p.release_side)) for p in ps),
            "ext": mean(exts) if exts else None,
            "arm_angle": _arm_angle(ps, player),
            "is_fb": label == fb_label,
        })
    fb = next((r for r in rows if r["is_fb"]), None)
    for r in rows:
        if fb is None or r["is_fb"]:
            r.update(dh_in=None, ds_in=None, offset_in=None, tell=False)
            continue
        dh = (r["height"] - fb["height"]) * 12
        ds = (r["side"] - fb["side"]) * 12
        off = (dh * dh + ds * ds) ** 0.5
        r.update(dh_in=dh, ds_in=ds, offset_in=off, tell=off >= TELL_IN)
    rows.sort(key=lambda r: (not r["is_fb"], -r["n"]))
    return rows


def offset_words(r):
    """'2.4 in lower' / '1.1 in higher' / '3.0 in toward your arm side'."""
    if r.get("offset_in") is None:
        return "Baseline"
    dh, ds = r["dh_in"], r["ds_in"]
    if abs(dh) >= abs(ds):
        return f"{abs(dh):.1f} in {'lower' if dh < 0 else 'higher'}"
    return f"{abs(ds):.1f} in {'more arm side' if ds > 0 else 'more glove side'}"


def outings(raps, player, n=TREND_OUTINGS):
    """[{date, kind, arm_angle, n}] oldest -> newest, last n outings, fastball only
    (arm angle shifts by pitch type, so one pitch keeps the line honest)."""
    from release_graphics import card_pitches
    _fb, fb_label = card_pitches(raps)
    if not fb_label:
        return []
    groups = {}
    for p in raps:
        if _type_name(p) != fb_label or p.release_height is None or p.release_side is None:
            continue
        key = ("Bullpen", p.bullpen_id) if p.bullpen_id is not None else ("Game", p.import_id)
        groups.setdefault(key, []).append(p)
    out = []
    for (kind, _id), ps in groups.items():
        if len(ps) < MIN_OUTING_FB:
            continue
        angle = _arm_angle(ps, player)
        if angle is None:
            continue
        dates = [p.pitch_date for p in ps if p.pitch_date is not None]
        out.append({"date": min(dates).date() if dates else None, "kind": kind,
                    "arm_angle": float(angle), "n": len(ps)})
    out.sort(key=lambda o: (o["date"] is None, o["date"]))
    return out[-n:]


def drift(outs):
    """Last 3 outings' average arm angle minus the earlier ones' (None if too few)."""
    if len(outs) < DRIFT_MIN_OUTINGS:
        return None
    recent = [o["arm_angle"] for o in outs[-3:]]
    before = [o["arm_angle"] for o in outs[:-3]]
    return mean(recent) - mean(before)


def takeaways(types, outs):
    """[(tone, text)] plain-language lines; tone in {'watch','good','note'}."""
    lines = []
    tells = [r for r in types if r.get("tell")]
    for r in sorted(tells, key=lambda r: -r["offset_in"]):
        lines.append(("watch", f"Your {r['type'].lower()} comes out {offset_words(r)} than your fastball. "
                               "The closer they match, the harder it is for a hitter to tell them apart."))
    if types and len(types) > 1 and not tells:
        lines.append(("good", f"Every pitch comes out within {TELL_IN:.0f} in of your fastball -- "
                              "hitters get the same look on all of them."))
    d = drift(outs)
    if d is not None and abs(d) >= DRIFT_DEG:
        lines.append(("watch", f"Arm angle is {'down' if d < 0 else 'up'} about {abs(d):.0f}° over your last 3 outings "
                               "compared with before. Worth bringing up with your pitching coach."))
    lines.append(("note", "Arm angle is estimated from release height, release side and your height."))
    return lines


def headline_alert(types, outs):
    """The one line for the dashboard card, or None."""
    for tone, text in takeaways(types, outs):
        if tone == "watch":
            return text.split(". ")[0] + "."
    return None


# ---------------------------------------------------------------- comps
def slot_comps(summ, pid, n=3):
    """[(Player, similarity 0-100, ReleaseProfile)] closest on release only."""
    from release_graphics import find_comps
    pool = summ["pool"]
    if pool.empty or pid not in set(pool["player_id"]) or len(pool) < 3:
        return []
    if "arm_angle" not in pool.columns or pool.loc[pool["player_id"] == pid, "arm_angle"].isna().all():
        return []
    comps = find_comps(pid, pool, categories=["Release"], n=n, group_col=None)
    out = []
    for _, c in comps.iterrows():
        cid = int(c["player_id"])
        pl, prof = summ["players"].get(cid), summ["profiles"].get(cid)
        if pl is not None and prof is not None:
            out.append((pl, float(c["similarity"]), prof))
    return out


def staff_points(summ):
    """[(pid, side_ft, height_ft, arm_angle)] for everyone in the comp pool."""
    pool = summ["pool"]
    if pool.empty:
        return []
    out = []
    for pid in pool["player_id"]:
        prof = summ["profiles"].get(int(pid))
        if prof is not None and prof.release_side_ft is not None and prof.release_height_ft is not None:
            out.append((int(pid), float(prof.release_side_ft), float(prof.release_height_ft), float(prof.arm_angle)))
    return out


def slot_word(angle, staff_angles):
    """Staff-relative: 'higher-slot' / 'middle-slot' / 'lower-slot'."""
    a = sorted(staff_angles)
    if len(a) < 3 or angle is None:
        return None
    lo, hi = a[len(a) // 3], a[(2 * len(a)) // 3]
    return "higher-slot" if angle > hi else ("lower-slot" if angle < lo else "middle-slot")


def best_pitch(db, pid, date_from=None, date_to=None, game_scope="all"):
    """(pitch type, Whiff %) -- his top Whiff % pitch in games, or None."""
    from analytics.profile_queries import get_pitcher_profile_pitches
    from game_stats import compute_pitch_type_breakdown
    pitches = get_pitcher_profile_pitches(db, pid, date_from=date_from, date_to=date_to, game_scope=game_scope)
    if not pitches:
        return None
    best = None
    for r in compute_pitch_type_breakdown(pitches):
        if r.get("Pitch Type") == "Total" or r.get("Whiff %") is None:
            continue
        if (r.get("Total Pitches") or 0) < MIN_BEST_PITCHES or (r.get("Total Swings") or 0) < MIN_BEST_SWINGS:
            continue
        if best is None or r["Whiff %"] > best[1]:
            best = (r["Pitch Type"], float(r["Whiff %"]))
    return best
