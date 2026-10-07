"""
GBO -- Rapsodo data check (Oct 2026, from Luke VanHouten's "Pitch
Clustering, Part 2": bad sensor reads make fake pitch groups -- with only
a few pitches per pitcher, one bad session quietly skews Stuff+, IVB over
expected, the classifiers, everything). Read-only; lives on Data Health.

Per OUTING (a bullpen, or a Rapsodo game import) in the date range:

  shifted   a pitch type whose median velo / spin / IVB / run that day is
            more than Z_FLAG robust SDs off the same pitcher's own norm
            for that pitch type (median and MAD*1.4826 over ALL his
            readings of it, with a floor so a very consistent pitcher
            isn't flagged for normal noise). Needs MIN_NORM readings to
            have a norm and MIN_DAY that day. Usually a misread (indoor /
            bad setup), a mislabeled pitch, or a real change worth
            knowing about.
  unclassified  Rapsodo couldn't tag it ("-") or it never matched a GBO type
  low confidence  spin confidence under LOW_CONF
  no release / no location  missing release height or plate location --
            those readings drop out of arm angle, VAA, VAAA, IVB over expected

Each outing gets one row with every issue found.
"""

from collections import defaultdict
from statistics import median

Z_FLAG = 2.5
MIN_NORM = 15
MIN_DAY = 3
LOW_CONF = 0.5
FLOOR = {"velocity": 1.0, "total_spin": 80.0, "vb_spin": 1.5, "hb_trajectory": 1.5, "bauer": 1.0}
NAMES = {"velocity": ("velo", " mph", 1), "total_spin": ("spin", " rpm", 0),
         "vb_spin": ("ride", '"', 1), "hb_trajectory": ("run", '"', 1), "bauer": ("Bauer units", "", 1)}


def _val(p, f):
    """Field value; "bauer" = total spin / velo (Oct 2026). A day's spin is
    only flagged when Bauer units moved too -- spin that rose because he
    threw harder isn't a misread."""
    if f == "bauer":
        if p.total_spin is None or p.velocity is None or float(p.velocity) <= 0:
            return None
        return float(p.total_spin) / float(p.velocity)
    v = getattr(p, f)
    return float(v) if v is not None else None


def _label(p):
    return p.pitch_type.type_name if p.pitch_type is not None else None


def outing_key(p):
    return ("bp", p.bullpen_id) if p.bullpen_id is not None else ("imp", p.import_id)


def norms(all_pitches):
    """{(player_id, type): {field: (median, sd)}}"""
    groups = defaultdict(list)
    for p in all_pitches:
        lab = _label(p)
        if lab:
            groups[(p.player_id, lab)].append(p)
    out = {}
    for key, ps in groups.items():
        if len(ps) < MIN_NORM:
            continue
        stats = {}
        for f in FLOOR:
            vals = [v for v in (_val(p, f) for p in ps) if v is not None]
            if len(vals) < MIN_NORM:
                continue
            med = median(vals)
            mad = median(abs(v - med) for v in vals) * 1.4826
            stats[f] = (med, max(mad, FLOOR[f]))
        out[key] = stats
    return out


def check(range_pitches, all_pitches):
    """-> [{key, date, player_id, kind, bullpen_id, n, issues: [str], severity}] worst first."""
    nm = norms(all_pitches)
    outs = defaultdict(list)
    for p in range_pitches:
        outs[outing_key(p)].append(p)
    rows = []
    for key, ps in outs.items():
        issues = []
        by_type = defaultdict(list)
        for p in ps:
            if _label(p):
                by_type[_label(p)].append(p)
        sev = 0
        for lab, tps in sorted(by_type.items()):
            stats = nm.get((ps[0].player_id, lab))
            if not stats or len(tps) < MIN_DAY:
                continue
            shifted = {}
            for f, (med, sd) in stats.items():
                vals = [v for v in (_val(p, f) for p in tps) if v is not None]
                if len(vals) < MIN_DAY:
                    continue
                day = median(vals)
                z = (day - med) / sd
                if abs(z) >= Z_FLAG:
                    shifted[f] = (day, med, z)
            if "total_spin" in shifted and "bauer" not in stats:
                pass                                   # no Bauer norm: judge spin on its own
            elif "total_spin" in shifted and "bauer" not in shifted:
                del shifted["total_spin"]              # spin moved with velo -- not a misread
            for f, (day, med, z) in shifted.items():
                if f == "bauer":
                    continue                           # reported with spin below
                name, unit, d = NAMES[f]
                sign = "+" if day > med else "-"
                line = (f"{lab} {name} {day:.{d}f}{unit} vs his usual {med:.{d}f}{unit} "
                        f"({sign}{abs(day - med):.{d}f}{unit}, {abs(z):.1f} SD)")
                if f == "total_spin" and "bauer" in shifted:
                    bd, bm, _bz = shifted["bauer"]
                    line += f" -- Bauer units {bd:.1f} vs {bm:.1f} too, so it isn't just velo"
                issues.append(line)
                sev += 3
        unc = sum(1 for p in ps if p.pitch_type is None)
        if unc:
            issues.append(f"{unc} unclassified reading{'s' if unc != 1 else ''}")
            sev += 1
        low = sum(1 for p in ps if p.spin_confidence is not None and float(p.spin_confidence) < LOW_CONF)
        if low:
            issues.append(f"{low} low spin-confidence reading{'s' if low != 1 else ''} (under {LOW_CONF:.1f})")
            sev += 1
        no_rel = sum(1 for p in ps if p.release_height is None or p.release_side is None)
        if no_rel:
            issues.append(f"{no_rel} without a release point")
            sev += 1
        no_loc = sum(1 for p in ps if p.plate_x_ft is None or p.plate_z_ft is None)
        if no_loc:
            issues.append(f"{no_loc} without a plate location")
            sev += 1
        if not issues:
            continue
        dates = [p.pitch_date for p in ps if p.pitch_date is not None]
        rows.append({"key": key, "date": min(dates).date() if dates else None, "player_id": ps[0].player_id,
                     "kind": "Bullpen" if key[0] == "bp" else "Game import", "bullpen_id": ps[0].bullpen_id,
                     "n": len(ps), "issues": issues, "severity": sev})
    rows.sort(key=lambda r: (-r["severity"], r["date"] is None, r["date"]))
    return rows
