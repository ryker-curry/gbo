"""
GBO -- Pitch Calling Card renderer (Oct 2026). Pocket size: a quarter of a
letter sheet (5.5in x 4.25in, landscape) per pitcher, light "paper" look
with its own scoped CSS so screen and print match. Code cells are
contenteditable on screen (data-* attributes say which hitter / count
group / primary-or-backup they are) so a coach can change a call before
saving and printing. Pure string building -- no Shiny/DB.
"""

from html import escape

from analytics import pitch_card as pc

CARD_CSS = """
.gbo-pcard{--ink:#15181c;--muted:#5d6670;--line:#c9cfd6;--soft:#f1f3f5;--brand:#7a1f2b;
  background:#fff;color:var(--ink);width:5.5in;height:4.25in;box-sizing:border-box;padding:.12in .14in;
  font-family:"Helvetica Neue",Arial,sans-serif;font-size:7.5px;line-height:1.15;overflow:hidden;
  box-shadow:0 2px 10px rgba(0,0,0,.35);margin:0 0 14px;page-break-after:always;break-after:page;
  -webkit-print-color-adjust:exact;print-color-adjust:exact}
.gbo-pcard *{box-sizing:border-box}
.gbo-pcard .hd{display:flex;justify-content:space-between;align-items:baseline;border-bottom:2px solid var(--ink);padding-bottom:2px;margin-bottom:2px}
.gbo-pcard .nm{font-size:12px;font-weight:800}
.gbo-pcard .gm{font-size:8px;color:var(--muted)}
.gbo-pcard .lg{font-size:6.5px;color:var(--muted);margin-bottom:2px}
.gbo-pcard table{width:100%;border-collapse:collapse;table-layout:fixed}
.gbo-pcard th{font-size:6.5px;text-transform:uppercase;letter-spacing:.3px;color:var(--muted);font-weight:700;border-bottom:1px solid var(--ink);padding:1px 2px;text-align:center}
.gbo-pcard th.h{text-align:left;width:31%}
.gbo-pcard td{border-bottom:1px solid var(--line);padding:1px 2px;text-align:center;vertical-align:middle}
.gbo-pcard td.h{text-align:left;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.gbo-pcard td.h b{font-size:8px}
.gbo-pcard td.h .nt{display:block;font-size:6px;color:var(--muted);overflow:hidden;text-overflow:ellipsis}
.gbo-pcard .p{display:block;font-size:10.5px;font-weight:800;letter-spacing:.5px;font-variant-numeric:tabular-nums}
.gbo-pcard .b{display:block;font-size:7px;color:var(--muted);font-variant-numeric:tabular-nums}
.gbo-pcard [contenteditable]{outline:none;border-radius:2px;min-height:9px}
.gbo-pcard [contenteditable]:focus{background:#fff4c2}
.gbo-pcard tr.gen td{background:var(--soft)}
.gbo-pcard .ft{font-size:6px;color:var(--muted);margin-top:2px}
"""

LEGEND = ("Level-Pitch-Zone · Level 1 dirt · 2 knees · 3 mid · 4 top+ · Pitch 1 FB · 2 CB · 3 SL · 4 CH · 5 CT · "
          "Zone 1 (3B side) → 5 (1B side) · big = call · small = backup")


def _cell(row_key, group, cell, editable=True):
    ce = ' contenteditable="true"' if editable else ""
    p = escape((cell or {}).get("primary", ""))
    b = escape((cell or {}).get("backup", ""))
    return (f'<td><span class="p" data-hk="{escape(row_key)}" data-g="{group}" data-k="primary"{ce}>{p}</span>'
            f'<span class="b" data-hk="{escape(row_key)}" data-g="{group}" data-k="backup"{ce}>{b}</span></td>')


def card_html(card, game_label, editable=True):
    digits = " ".join(f"{d} {pc.DIGIT_NAME[d]}" for d in card.get("digits", []))
    head = "".join(f"<th>{escape(lab)}</th>" for _g, lab, _c in pc.GROUPS)
    rows = []
    for i, r in enumerate(card.get("rows", []), start=1):
        key = f"{r['key'][0]}:{r['key'][1]}"
        cells = "".join(_cell(key, g, r["cells"].get(g), editable) for g, _l, _c in pc.GROUPS)
        rows.append(f'<tr><td class="h"><b>{i}. {escape(r["name"])}</b> ({escape(r["hand"])})'
                    f'<span class="nt">{escape(r.get("note", ""))}</span></td>{cells}</tr>')
    for hand in ("R", "L"):
        cells = "".join(_cell(f"gen:{hand}", g, card.get("generic", {}).get(hand, {}).get(g), editable)
                        for g, _l, _c in pc.GROUPS)
        rows.append(f'<tr class="gen"><td class="h"><b>Any {hand}HH</b><span class="nt">not on the card</span></td>{cells}</tr>')
    return (f'<div class="gbo-pcard" data-pid="{card["pitcher_id"]}">'
            f'<div class="hd"><span class="nm">{escape(card["pitcher"])} ({escape(card.get("throws") or "?")}HP)</span>'
            f'<span class="gm">{escape(game_label)} · throws: {escape(digits)}</span></div>'
            f'<div class="lg">{escape(LEGEND)}</div>'
            f'<table><thead><tr><th class="h">Hitter</th>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table>'
            f'<div class="ft">{("Angles: " + escape(card["angle_note"]) + " · ") if card.get("angle_note") else ""}'
            f'GBO Pitch Calling Card -- built from {card.get("n", 0):,} charted pitches; a starting '
            f'point, not a script.</div></div>')
