"""
GBO -- Can this pair tunnel? (Oct 2026, from Paradigm's "Sequencing vs
Tunneling": past ~MAX_MOVE_IN" of movement difference or ~MAX_VELO_MPH
of velo gap, two pitches can't share a tunnel -- they still work, just
as a change of speed / shape rather than a look-alike.)

Shapes are medians of his Rapsodo readings: IVB = vb_spin, HB =
hb_trajectory (raw is fine for a difference -- same hand on both).
"""

from statistics import median

MAX_MOVE_IN = 20.0
MAX_VELO_MPH = 10.0


def _shape(ps):
    iv = [float(p.vb_spin) for p in ps if p.vb_spin is not None]
    hb = [float(p.hb_trajectory) for p in ps if p.hb_trajectory is not None]
    ve = [float(p.velocity) for p in ps if p.velocity is not None]
    if not iv or not hb:
        return None
    return {"ivb": median(iv), "hb": median(hb), "velo": median(ve) if ve else None}


def check(fb_pitches, other_pitches):
    """-> {move, velo, ok, reason} or None without both shapes."""
    a, b = _shape(fb_pitches), _shape(other_pitches)
    if a is None or b is None:
        return None
    move = ((a["ivb"] - b["ivb"]) ** 2 + (a["hb"] - b["hb"]) ** 2) ** 0.5
    velo = abs(a["velo"] - b["velo"]) if a["velo"] is not None and b["velo"] is not None else None
    reasons = []
    if move > MAX_MOVE_IN:
        reasons.append(f'{move:.0f}" apart in movement (past ~{MAX_MOVE_IN:.0f}")')
    if velo is not None and velo > MAX_VELO_MPH:
        reasons.append(f"{velo:.0f} mph apart (past ~{MAX_VELO_MPH:.0f})")
    return {"move": move, "velo": velo, "ok": not reasons, "reason": " and ".join(reasons)}
