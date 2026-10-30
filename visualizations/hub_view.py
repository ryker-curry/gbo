"""
GBO -- Morning hub HTML (Oct 2026). Draws analytics.hub.build()'s dict:
what's in (source freshness), the pulse row, and the watch list. Plain
HTML + inline SVG on the app's CSS variables (dark and light mode).
"""

from datetime import date
from html import escape

MUTED = "var(--gbo-text-muted,#8A8A8E)"
TEXT = "var(--gbo-text,#F3F2EE)"
BORDER = "var(--gbo-border,#272729)"
CARD = "var(--gbo-bg-card,#141415)"
RAISED = "var(--gbo-bg-raised,#1D1D20)"
TONE = {"good": "#2E9C62", "watch": "#C9A227", "flag": "#D94F3D", None: "var(--gbo-text,#F3F2EE)"}
SOURCE_C = {"Load": "#3E8EDE", "Velo": "#D9782A", "Command": "#8E7CC3", "Approach": "#2BB3A3", "CMJ": "#C9793D",
            "Weight": "#6E7681", "WHOOP": "#2E9C62"}


def _e(s):
    return escape(str(s)) if s is not None else ""


def _ago(d, today):
    if d is None:
        return "no data yet", MUTED
    n = (today - d).days
    txt = "today" if n <= 0 else "yesterday" if n == 1 else f"{n} days ago"
    col = "#2E9C62" if n <= 2 else "#C9A227" if n <= 7 else MUTED
    return txt, col


def sources_html(sources, today):
    chips = []
    for s in sources:
        txt, col = _ago(s["last"], today)
        when = s["last"].strftime("%a %b %d") if s["last"] else ""
        chips.append(
            f'<div style="flex:1 1 120px;min-width:110px;border-left:3px solid {col};padding:2px 10px">'
            f'<div style="font-size:.62rem;font-weight:800;letter-spacing:.07em;color:{MUTED}">{_e(s["name"].upper())}</div>'
            f'<div style="font-size:.82rem;font-weight:700">{_e(when) or "—"}</div>'
            f'<div style="font-size:.68rem;color:{col}">{_e(txt)}</div></div>')
    return f'<div style="display:flex;flex-wrap:wrap;gap:8px 4px">{"".join(chips)}</div>'


def spark(values, w=96, h=26, color="#3E8EDE"):
    vals = [v for v in (values or []) if v is not None]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    n = len(values)
    pts = []
    for i, v in enumerate(values):
        if v is None:
            continue
        x = 2 + (w - 4) * i / (n - 1)
        y = h - 3 - (h - 6) * (v - lo) / rng
        pts.append(f"{x:.1f},{y:.1f}")
    last = pts[-1].split(",")
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}"><polyline points="{" ".join(pts)}" fill="none" '
            f'stroke="{color}" stroke-width="1.8" stroke-linejoin="round"/>'
            f'<circle cx="{last[0]}" cy="{last[1]}" r="2.6" fill="{color}"/></svg>')


def pulse_html(tiles):
    if not tiles:
        return f'<div style="color:{MUTED};font-size:.8rem">No team numbers yet.</div>'
    out = []
    for t in tiles:
        col = TONE.get(t.get("tone"))
        out.append(
            f'<div style="flex:1 1 150px;border:1px solid {BORDER};border-radius:8px;padding:9px 11px;background:{RAISED}">'
            f'<div style="font-size:.62rem;font-weight:800;letter-spacing:.07em;color:{MUTED}">{_e(t["label"].upper())}</div>'
            f'<div style="display:flex;align-items:center;justify-content:space-between;gap:6px">'
            f'<div style="font-size:1.45rem;font-weight:800;color:{col}">{_e(t["display"])}</div>'
            f'{spark(t.get("trend"), color=col if t.get("tone") else "#3E8EDE")}</div>'
            f'<div style="font-size:.66rem;color:{MUTED};line-height:1.3">{_e(t["sub"])}</div></div>')
    return f'<div style="display:flex;flex-wrap:wrap;gap:8px">{"".join(out)}</div>'


def _flag_line(f, today):
    c = SOURCE_C.get(f["source"], "#6E7681")
    when = ""
    if f.get("date"):
        n = (today - f["date"]).days
        when = f' · {f["date"].strftime("%m/%d")}' + (" (today)" if n <= 0 else "")
    sev = (f'<span style="color:#D94F3D;font-weight:800;font-size:.62rem;margin-left:4px">SEVERE</span>'
           if f["severe"] else "")
    return (f'<div style="display:flex;gap:7px;align-items:flex-start;margin-top:5px">'
            f'<span style="background:{c};color:#fff;font-size:.58rem;font-weight:800;letter-spacing:.05em;'
            f'padding:2px 5px;border-radius:3px;white-space:nowrap">{_e(f["source"].upper())}</span>'
            f'<span style="font-size:.74rem;line-height:1.3">{_e(f["text"])}{sev}'
            f'<span style="color:{MUTED}">{_e(when)}</span></span></div>')


def _player_card(r, today):
    p = r["player"]
    edge = "#D94F3D" if r["tier"] == "priority" else "#C9A227"
    role = "P" if getattr(p, "is_pitcher", False) else "H"
    return (f'<div style="flex:1 1 280px;border:1px solid {BORDER};border-left:4px solid {edge};border-radius:8px;'
            f'padding:8px 11px;background:{CARD}">'
            f'<div style="display:flex;justify-content:space-between;align-items:baseline">'
            f'<a href="#" class="gbo-hub-player" data-player-id="{p.player_id}" style="font-weight:800;color:{TEXT};'
            f'text-decoration:none">{_e(p.first_name)} {_e(p.last_name)}</a>'
            f'<span style="font-size:.66rem;color:{MUTED}">{role}</span></div>'
            f'{"".join(_flag_line(f, today) for f in r["flags"])}</div>')


def watch_html(rows, today, lookback):
    if not rows:
        return (f'<div style="color:{MUTED};font-size:.8rem">Nobody is far outside his own history in the last '
                f'{lookback} days.</div>')
    parts = []
    for t, label in (("priority", "PRIORITY"), ("watch", "WATCH")):
        grp = [r for r in rows if r["tier"] == t]
        if not grp:
            continue
        dot = "#D94F3D" if t == "priority" else "#C9A227"
        parts.append(f'<div style="display:flex;align-items:center;gap:6px;margin:10px 0 6px;font-size:.72rem;'
                     f'font-weight:800;letter-spacing:.08em"><span style="width:8px;height:8px;border-radius:50%;'
                     f'background:{dot};display:inline-block"></span>{label} · {len(grp)}</div>')
        parts.append(f'<div style="display:flex;flex-wrap:wrap;gap:8px">{"".join(_player_card(r, today) for r in grp)}</div>')
    return "".join(parts)


def _section(title, sub, body):
    return (f'<div style="border:1px solid {BORDER};border-radius:10px;padding:12px 14px;background:{CARD};margin-bottom:12px">'
            f'<div style="display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:4px">'
            f'<b style="font-size:.95rem">{_e(title)}</b><span style="font-size:.7rem;color:{MUTED}">{_e(sub)}</span></div>'
            f'<div style="margin-top:8px">{body}</div></div>')


def hub_html(data):
    today = data.get("as_of") or date.today()
    lb = data.get("lookback", 14)
    return (
        '<div class="gbo-hub">'
        + _section("What's in", "the last day each source brought in new data", sources_html(data["sources"], today))
        + _section("Pulse", "team numbers · line = last 8 weeks", pulse_html(data["pulse"]))
        + _section("Watch list",
                   f"far outside his OWN history in the last {lb} days · one flag = watch · severe or 2+ sources = "
                   f"priority · click a name to open him",
                   watch_html(data["watch"], today, lb)
                   + f'<div style="font-size:.66rem;color:{MUTED};margin-top:10px">Each flag compares a player only to '
                     f'himself: his latest outing, game, jump, weigh-in or WHOOP day against his own earlier numbers. '
                     f'Load = acute:chronic workload ratio (over 1.3 watch, over 1.5 severe). Starting cutoffs, not '
                     f'proven -- tell the staff what feels too loud or too quiet. Weight room isn\'t tracked yet.</div>')
        + '</div>')
