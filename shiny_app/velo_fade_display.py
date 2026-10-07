"""
GBO -- "Velo fade" block (Oct 2026), shared by Bullpen Dashboard (one
session), Pitcher Game Breakdown (Pitch Shape / Rapsodo) and Pitcher
Profile's Trends view (one bar per outing). Data: analytics/velo_fade.py.
"""

from shiny import ui

import ui_helpers
from analytics import velo_fade
from visualizations.velo_fade_chart import outing_svg, season_svg

EXPLAIN = (f"Fastballs only. The line is the trend across the outing; the headline is how much velo it loses per "
           f"{velo_fade.PER} pitches. Under {velo_fade.HELD:+.1f} mph reads as held, down to {velo_fade.MILD:+.1f} as a "
           f"mild fade, more than that as a notable fade -- starting points, not proven cutoffs. Needs "
           f"{velo_fade.MIN_FB}+ fastballs with a Rapsodo velo.")


def outing_block(res, title="Velo fade"):
    head = ui.p(ui.strong(title), "  ", ui_helpers.how_to_link("velo_fade"))
    if not res.get("ok"):
        return ui.div(head, ui.p(f"Only {res['n']} fastball{'s' if res['n'] != 1 else ''} with a velo here -- needs "
                                 f"{velo_fade.MIN_FB} to trend.", class_="text-muted small"))
    e = res["edge"]
    kpis = [
        {"label": f"Per {velo_fade.PER} pitches", "value": f"{res['per']:+.1f} mph"},
        {"label": f"First {e} FB", "value": f"{res['first']:.1f} mph"},
        {"label": f"Last {e} FB", "value": f"{res['last']:.1f} mph"},
        {"label": "Change", "value": f"{res['drop']:+.1f} mph"},
    ]
    spin = (f" Spin: {res['spin_per']:+.0f} rpm per {velo_fade.PER} pitches." if res.get("spin_per") is not None else "")
    return ui.div(
        head,
        ui.p(ui.strong(res["read"].capitalize() + ": "),
             f"{res['n']} fastballs over {res['max_x']} pitches.{spin}", class_="small"),
        ui_helpers.render_kpi_cards(kpis),
        ui.HTML(outing_svg(res)),
        ui.p(EXPLAIN, class_="text-muted small"),
    )


def season_block(outings):
    ok = [o for o in outings if o["fade"].get("ok")]
    head = ui.p(ui.strong("Velo fade by outing"), "  ", ui_helpers.how_to_link("velo_fade"))
    if not ok:
        return ui.div(head, ui.p(f"No outing in this range has {velo_fade.MIN_FB}+ Rapsodo fastballs yet.",
                                 class_="text-muted small"))
    avg = sum(o["fade"]["per"] for o in ok) / len(ok)
    rows = [{
        "Date": o["date"].strftime("%b %-d") if o["date"] else "—", "Outing": o["kind"], "FB": o["fade"]["n"],
        "Pitches": o["fade"]["max_x"], f"Per {velo_fade.PER}": f"{o['fade']['per']:+.1f} mph",
        "First → last": f"{o['fade']['first']:.1f} → {o['fade']['last']:.1f}", "Read": o["fade"]["read"],
    } for o in reversed(ok)]
    return ui.div(
        head,
        ui.p(f"Average across {len(ok)} outing{'s' if len(ok) != 1 else ''}: {avg:+.1f} mph per {velo_fade.PER} "
             f"pitches ({velo_fade.read(avg)}). Each bar is one bullpen or Rapsodo game; green held, yellow mild, "
             "red notable.", class_="small"),
        ui.HTML(season_svg(outings)),
        ui_helpers.render_dict_table(rows),
        ui.p(EXPLAIN, class_="text-muted small"),
    )
