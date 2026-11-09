"""
Synthetic test for strike_zone / catcher_framing / umpire_scorecard.

Plants known catcher framing skill and known umpire tendencies in fake
SmartPark-style data, then checks the metrics recover them.

Run from the project root:  python3 -m scripts.synthetic_zone_test
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analytics.strike_zone import (abs_zone_ft, signed_distance_in, nearest_edge,
                                   prepare_called_pitches)
from analytics.catcher_framing import framing_leaderboard
from analytics.umpire_scorecard import (game_scorecard, umpire_tendencies,
                                        tendency_notes)

RNG = np.random.default_rng(7)

# Planted truth --------------------------------------------------------------
# Catcher skill = inches the effective zone grows on his pitches.
CATCHERS = {"PSU_C1": 1.2, "PSU_C2": 0.0, "PSU_C3": -1.2}
OPP_CATCHERS = {f"OPP_C{i}": s for i, s in enumerate(RNG.normal(0, 0.6, 8))}
# Umpire tendencies = inches each edge is pushed out (+) or in (-).
UMPIRES = {
    "UMP_A": {"top": 0.0, "bottom": 0.0, "inside": 0.0, "outside": 0.0},
    "UMP_B": {"top": 0.0, "bottom": 1.8, "inside": 0.0, "outside": 0.0},   # gives low strike
    "UMP_C": {"top": -1.8, "bottom": 0.0, "inside": 0.0, "outside": 1.5},  # squeezes top, wide outside
}
COUNT_SHIFT = {(3, 0): 0.8}  # 3-0 zone bigger
TWO_STRIKE_SHIFT = -0.6


def fake_re(outs, on1, on2, on3, balls, strikes):
    """Rough run-expectancy for testing only (wire GBO's table in production)."""
    base = [[0.48, 0.26, 0.10], [0.86, 0.51, 0.22], [1.10, 0.66, 0.32],
            [1.44, 0.90, 0.43], [1.35, 0.95, 0.35], [1.75, 1.15, 0.48],
            [1.95, 1.37, 0.55], [2.29, 1.54, 0.75]]
    idx = int(on1) + 2 * int(on2) + 4 * int(on3)
    return base[idx][outs] * (1 + 0.05 * balls - 0.06 * strikes)


def simulate(n_games=36, pitches_per_half=70):
    rows = []
    umps = list(UMPIRES)
    opps = list(OPP_CATCHERS)
    psu_catchers = list(CATCHERS)
    for g in range(n_games):
        ump = umps[g % len(umps)]
        opp_team = f"OPP{g % 6}"
        psu_c = psu_catchers[(g // 3) % 3]  # rotate independently of umpire
        opp_c = opps[g % len(opps)]
        for half, (bat, fld, catcher) in enumerate(
                [(opp_team, "PSU", psu_c), ("PSU", opp_team, opp_c)]):
            for i in range(pitches_per_half):
                h = RNG.uniform(67, 77)
                hand = "R" if RNG.random() < 0.6 else "L"
                bot, top = abs_zone_ft(h)
                x = RNG.normal(0, 0.75)
                z = RNG.normal((bot + top) / 2, 0.75)
                balls, strikes = RNG.integers(0, 4), RNG.integers(0, 3)
                d = float(signed_distance_in(x, z, bot, top))
                edge = str(nearest_edge(x, z, bot, top, hand))
                shift = (UMPIRES[ump][edge]
                         + (CATCHERS.get(catcher) if catcher in CATCHERS
                            else OPP_CATCHERS[catcher])
                         + COUNT_SHIFT.get((balls, strikes), 0.0)
                         + (TWO_STRIKE_SHIFT if strikes == 2 else 0.0))
                p_k = 1 / (1 + np.exp((d - shift) / 0.9))
                swing = RNG.random() < 0.45
                call = ("swinging_strike" if swing
                        else "called_strike" if RNG.random() < p_k else "ball")
                rows.append(dict(
                    game_id=g, umpire_id=ump, batting_team=bat, fielding_team=fld,
                    catcher_id=catcher, batter_height_in=h, batter_hand=hand,
                    plate_x=x, plate_z=z, pitch_call=call, balls=balls, strikes=strikes,
                    outs=RNG.integers(0, 3), on_1b=RNG.random() < .3,
                    on_2b=RNG.random() < .2, on_3b=RNG.random() < .1,
                    inning=1 + i // 8, inning_half="Top" if half == 0 else "Bottom",
                    pitcher_name=f"P{RNG.integers(1, 9)}", batter_name=f"B{RNG.integers(1, 10)}",
                ))
    return pd.DataFrame(rows)


def main():
    df = simulate()
    called = prepare_called_pitches(df)
    print(f"Pitches: {len(df)}  called: {len(called)}  "
          f"(swings filtered: {(df.pitch_call == 'swinging_strike').sum()})")

    # --- Zone sanity checks
    bot, top = abs_zone_ft(73)
    assert abs(top * 12 - 39.055) < 1e-6 and abs(bot * 12 - 19.71) < 1e-6
    assert signed_distance_in(0, (bot + top) / 2, bot, top) < 0
    edge_x = (8.5 + 1.47) / 12
    assert abs(signed_distance_in(edge_x, (bot + top) / 2, bot, top)) < 1e-9
    assert abs(signed_distance_in(edge_x + 1 / 12, (bot + top) / 2, bot, top) - 1) < 1e-9
    print("Zone geometry checks: OK")

    # --- Framing
    lb = framing_leaderboard(df)
    print("\nFraming (all catchers, strikes gained per 100 called pitches):")
    print(lb[["called_pitches", "strikes_gained_per_100", "zone_net_vs_avg_per_100",
              "low_sample"]].to_string())
    psu = lb.loc[list(CATCHERS), "strikes_gained_per_100"]
    assert psu["PSU_C1"] > psu["PSU_C2"] > psu["PSU_C3"], "PSU framing order not recovered"
    truth = pd.Series({**CATCHERS, **OPP_CATCHERS})
    rho = lb["strikes_gained_per_100"].rank().corr(truth.reindex(lb.index).rank())
    print(f"Rank correlation with planted skill: {rho:.2f}")
    assert rho > 0.7
    print("Framing recovers planted skill: OK")

    # --- Umpire tendencies
    for ump in UMPIRES:
        t = umpire_tendencies(df, ump)
        print(f"\n{ump}:")
        print(t.to_string())
        for n in tendency_notes(t):
            print("  -", n)
    tb = umpire_tendencies(df, "UMP_B")
    tc = umpire_tendencies(df, "UMP_C")
    assert tb.loc["bottom", "expands_vs_avg"] > 10
    assert tc.loc["top", "squeezes_vs_avg"] > 10
    assert tc.loc["outside", "expands_vs_avg"] > 5
    ta = umpire_tendencies(df, "UMP_A")
    assert tendency_notes(ta) == ["No edge stands out from the other umpires yet."], \
        "neutral umpire should get no notes"
    print("\nUmpire tendencies recovered: OK")

    # --- One game scorecard
    card = game_scorecard(df, 1, fake_re, league_called=called)
    show = {k: v for k, v in card.items() if k != "_called"}
    print("\nGame 1 scorecard:")
    for k, v in show.items():
        print(f"  {k}: {v}")
    assert 0 < card["accuracy"] <= 100 and 0 < card["consistency"] <= 100
    f = card["favor_runs"]
    assert abs(sum(f.values())) < 1e-6, "favor should be zero-sum between teams"
    print("Scorecard checks: OK")
    return df, called, card


if __name__ == "__main__":
    main()
