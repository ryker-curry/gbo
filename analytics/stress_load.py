"""
GBO -- Stress-weighted workload (Oct 2026, from Samuel Midgette's "Pitch
Counts Don't Measure Stress": pitch counts count events, not stress; a 95
mph fastball loads the elbow more than an 82 mph changeup. Driveline's
PULSE sums elbow valgus torque per throw; acute = exponentially weighted
9-day average, chronic = 28-day average, ACWR < 1.3 green, 1.3-1.5
caution, > 1.5 red; build chronic load ~20% a week).

We don't have a torque sensor, so each pitch is weighted by intensity:

    stress units = (pitch velo / his max fastball velo) ^ 2  x  setting

Squared because torque rises roughly with the square of arm speed -- GBO's
approximation, not a measured torque. One max-effort game fastball = 1.0
unit. Setting: game pitches x GAME_MULT (adrenaline, full intent);
bullpen pitches x 1. No velo on a pitch -> NO_VELO_INTENSITY (pens) or
1.0 / OFFSPEED_INTENSITY (game fastball / other). Long toss, plyos and
catch play aren't logged in GBO, so they're missing from every number --
the article's point that a pitcher can burn 6+ units before his first
competitive pitch applies here too.

  acute    EWMA of daily units, span 9 days (lambda = 2 / 10)
  chronic  plain mean of the last 28 days of daily units
  budget   the most units he can add TODAY and keep the ratio <= 1.3,
           turned into pitches at his average game-pitch units
  growth   last 7 days vs the 7 before (flag above 20%)
"""

from datetime import timedelta
from statistics import median

ACUTE_SPAN = 9
LAMBDA = 2.0 / (ACUTE_SPAN + 1)
CHRONIC_DAYS = 28
GREEN_MAX, CAUTION_MAX, LOW = 1.3, 1.5, 0.8
GAME_MULT = 1.2
NO_VELO_INTENSITY = 0.85
OFFSPEED_INTENSITY = 0.85
GROWTH_FLAG = 0.20
FASTBALLS = ("4-Seam Fastball", "Fastball", "2-Seam Fastball", "Sinker", "Cutter")


def zone(r):
    if r is None:
        return None
    if r > CAUTION_MAX:
        return "Red"
    if r > GREEN_MAX:
        return "Caution"
    if r < LOW:
        return "Low"
    return "Green"


def pitch_units(velo, max_velo, game, is_fastball=True):
    if velo and max_velo:
        inten = min(1.15, float(velo) / float(max_velo)) ** 2
    elif game:
        inten = 1.0 if is_fastball else OFFSPEED_INTENSITY ** 2
    else:
        inten = NO_VELO_INTENSITY ** 2
    return inten * (GAME_MULT if game else 1.0)


def series(daily, start, end, tracking_start=None):
    """daily {date: units}. -> [{"date", "units", "acute", "chronic", "ratio", "full"}] for start..end
    (history before start is used to warm up the averages)."""
    first = tracking_start or (min(daily) if daily else start)
    d = min(first, start)
    acute = None
    window = []
    out = []
    while d <= end:
        u = daily.get(d, 0.0) if d >= first else 0.0
        acute = u if acute is None else LAMBDA * u + (1 - LAMBDA) * acute
        window.append(u)
        if len(window) > CHRONIC_DAYS:
            window.pop(0)
        chronic = sum(window) / CHRONIC_DAYS
        full = (d - first).days + 1 >= CHRONIC_DAYS
        ratio = (acute / chronic) if chronic > 0 and full else None
        if d >= start:
            out.append({"date": d, "units": u, "acute": acute, "chronic": chronic, "ratio": ratio, "full": full})
        d += timedelta(days=1)
    return out


def budget(daily, today, tracking_start=None, per_pitch=1.0):
    """Units (and pitches) he can throw today with ACWR staying <= GREEN_MAX."""
    rows = series(daily, today - timedelta(days=1), today - timedelta(days=1), tracking_start)
    if not rows or not rows[-1]["full"]:
        return None
    a_prev = rows[-1]["acute"]
    s27 = sum(daily.get(today - timedelta(days=k), 0.0) for k in range(1, CHRONIC_DAYS))
    denom = LAMBDA - GREEN_MAX / CHRONIC_DAYS
    units = (GREEN_MAX * s27 / CHRONIC_DAYS - (1 - LAMBDA) * a_prev) / denom
    units = max(0.0, units)
    return {"units": units, "pitches": int(units / per_pitch) if per_pitch > 0 else None}


def growth(daily, today):
    this = sum(daily.get(today - timedelta(days=k), 0.0) for k in range(0, 7))
    prev = sum(daily.get(today - timedelta(days=k), 0.0) for k in range(7, 14))
    if prev <= 0:
        return None
    g = (this - prev) / prev
    return {"this": this, "prev": prev, "pct": 100 * g, "flag": g > GROWTH_FLAG}


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------

def daily_units(db, pid, start, end):
    """-> (daily {date: units}, tracking_start, avg game-pitch units, max FB velo)."""
    from sqlalchemy.orm import joinedload
    from models import Game, GamePitch, BullpenSession, BullpenPitch, RapsodoPitch, CommandPitch, PitchType
    from sqlalchemy import func

    fb_q = (db.query(RapsodoPitch.velocity).join(PitchType, RapsodoPitch.pitch_type_id == PitchType.pitch_type_id)
            .filter(RapsodoPitch.player_id == pid, PitchType.type_name.in_(FASTBALLS), RapsodoPitch.velocity.isnot(None))
            .filter(RapsodoPitch.pitch_date >= end - timedelta(days=365)))
    vs = sorted(float(v) for (v,) in fb_q.all())
    max_velo = vs[int(0.95 * (len(vs) - 1))] if len(vs) >= 5 else (vs[-1] if vs else None)

    daily = {}
    # Games
    gq = (db.query(GamePitch, Game.game_date).join(Game, GamePitch.game_id == Game.game_id)
          .options(joinedload(GamePitch.pitch_type))
          .filter(((GamePitch.is_our_team_batting.is_(False)) & (GamePitch.our_player_id == pid))
                  | ((GamePitch.is_our_team_batting.is_(True)) & (GamePitch.opponent_our_player_id == pid)),
                  GamePitch.is_pitch.isnot(False), Game.game_date >= start, Game.game_date <= end))
    rows = gq.all()
    velo_by = {}
    ids = [g.game_pitch_id for g, _d in rows]
    for i in range(0, len(ids), 500):
        for gid, v in (db.query(RapsodoPitch.game_pitch_id, RapsodoPitch.velocity)
                       .filter(RapsodoPitch.game_pitch_id.in_(ids[i:i + 500])).all()):
            velo_by[gid] = v
    game_units = []
    for g, d in rows:
        name = g.pitch_type.type_name if g.pitch_type else None
        u = pitch_units(velo_by.get(g.game_pitch_id), max_velo, True, name in FASTBALLS if name else True)
        daily[d] = daily.get(d, 0.0) + u
        game_units.append(u)
    # Bullpens: count = max of the three logs (same rule as workload_queries),
    # intensity from that session's Rapsodo velos when there are any.
    sessions = (db.query(BullpenSession.bullpen_id, BullpenSession.session_date)
                .filter(BullpenSession.player_id == pid, BullpenSession.session_date >= start,
                        BullpenSession.session_date <= end).all())
    if sessions:
        bids = [s.bullpen_id for s in sessions]

        def counts(model, pk):
            return dict(db.query(model.bullpen_id, func.count(pk)).filter(model.bullpen_id.in_(bids))
                        .group_by(model.bullpen_id).all())
        bp, cp = counts(BullpenPitch, BullpenPitch.bullpen_pitch_id), counts(CommandPitch, CommandPitch.command_pitch_id)
        raps = {}
        for bid, v in db.query(RapsodoPitch.bullpen_id, RapsodoPitch.velocity).filter(RapsodoPitch.bullpen_id.in_(bids)).all():
            raps.setdefault(bid, []).append(v)
        for s in sessions:
            rv = raps.get(s.bullpen_id, [])
            n = max(bp.get(s.bullpen_id, 0), cp.get(s.bullpen_id, 0), len(rv))
            if not n:
                continue
            known = [pitch_units(v, max_velo, False) for v in rv if v is not None]
            per = (sum(known) / len(known)) if known else pitch_units(None, max_velo, False)
            daily[s.session_date] = daily.get(s.session_date, 0.0) + per * n
    eg = (db.query(func.min(Game.game_date)).join(GamePitch, GamePitch.game_id == Game.game_id)
          .filter(((GamePitch.is_our_team_batting.is_(False)) & (GamePitch.our_player_id == pid))
                  | ((GamePitch.is_our_team_batting.is_(True)) & (GamePitch.opponent_our_player_id == pid))).scalar())
    eb = db.query(func.min(BullpenSession.session_date)).filter(BullpenSession.player_id == pid).scalar()
    cands = [d for d in (eg, eb) if d is not None]
    per_pitch = median(game_units) if game_units else GAME_MULT
    return daily, (min(cands) if cands else None), per_pitch, max_velo


def pitcher_summary(db, pid, as_of):
    start = as_of - timedelta(days=CHRONIC_DAYS + 40)
    daily, tstart, per_pitch, max_velo = daily_units(db, pid, start, as_of)
    if tstart is None:
        return None
    s = series(daily, as_of, as_of, max(tstart, start))
    row = s[-1] if s else None
    return {"ratio": row["ratio"] if row else None, "zone": zone(row["ratio"]) if row else None,
            "acute": row["acute"] if row else None, "chronic": row["chronic"] if row else None,
            "full": bool(row and row["full"]), "budget": budget(daily, as_of, max(tstart, start), per_pitch),
            "growth": growth(daily, as_of), "max_velo": max_velo, "per_pitch": per_pitch,
            "trend": series(daily, as_of - timedelta(days=27), as_of, max(tstart, start))}
