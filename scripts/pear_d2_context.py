"""
GBO -- PEAR Ratings D2 context pull (Nov 2026, Ryker: "set up the free api").

Pulls D2 baseball team numbers from PEAR Ratings' API (pip install
pearatings) so PSU can be compared with the MIAA and all of D2, and
saves them as CSVs in data/pear/ (git-ignored, like all player/team data).

FREE TIER (1,000 calls/month, 10/minute) covers what this script uses:
ratings, PEAR team numbers, NCAA.com team stats (runs scored/allowed, AVG,
ERA...), team -> conference list. One run = about 5 calls.

NOT on the free tier: play-by-play / box scores / run expectancy (Pro,
$9.99/mo). Runs per Scoring Chance for other teams needs play-by-play, so
the D2 version of the PEAR chart is a Pro-tier job. This script gives the
free-tier context: runs per game for/against, where PSU ranks.

Setup (once):
  1. Make a free key at https://api.pearatings.com/billing (shown once --
     copy it right away).
  2. Add a line to the project's .env (never commit it):
         PEAR_API_KEY='your-key'
     (single quotes if the key has a ! in it)
  3. pip install -r requirements-dev.txt     (adds pearatings)

Run (from the project root, on your Mac -- the API isn't reachable from
Claude's sandbox):
  python scripts/pear_d2_context.py              # last finished season (2026)
  python scripts/pear_d2_context.py --season 2025
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "pear"
PSU_MATCH = "pittsburg"          # PEAR's spelling is checked at run time
MIAA_MATCH = ("miaa", "mid-america intercollegiate")


def _load_key():
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    if not os.environ.get("PEAR_API_KEY"):
        sys.exit("No PEAR_API_KEY found. Add PEAR_API_KEY='your-key' to .env (see this file's docstring).")


def _find_col(df, *names):
    low = {c.lower(): c for c in df.columns}
    for n in names:
        if n.lower() in low:
            return low[n.lower()]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    args = ap.parse_args()
    _load_key()

    from pearatings import Pear
    pear = Pear()
    acct = pear.account()
    print(f"PEAR account: tier {acct.get('tier')}, calls used this month: {acct.get('calls_used', acct.get('usage'))}")

    OUT.mkdir(parents=True, exist_ok=True)
    s = args.season
    team_stats = pear.team_stats(s, division="d2")
    pear_stats = pear.stats(s, division="d2")
    team_stats.to_csv(OUT / f"d2_team_stats_{s}.csv", index=False)
    pear_stats.to_csv(OUT / f"d2_pear_stats_{s}.csv", index=False)
    print(f"Saved {len(team_stats)} teams -> data/pear/d2_team_stats_{s}.csv, d2_pear_stats_{s}.csv")

    team_col = _find_col(team_stats, "Team", "team", "team_name")
    conf_col = _find_col(team_stats, "Conference", "conference", "conf")
    if conf_col is None:
        try:
            confs = pear.team_conferences(s, division="d2")
            import pandas as pd
            confs = confs if isinstance(confs, pd.DataFrame) else pd.DataFrame(
                list(confs.items()), columns=["Team", "Conference"])
            c_team = _find_col(confs, "Team", "team", "team_name")
            c_conf = _find_col(confs, "Conference", "conference", "conf")
            team_stats = team_stats.merge(confs[[c_team, c_conf]].rename(columns={c_team: team_col, c_conf: "Conference"}),
                                          on=team_col, how="left")
            conf_col = "Conference"
        except Exception as e:   # conference lookup is a nice-to-have
            print(f"(Couldn't attach conferences: {e})")

    g, rs, ra = (_find_col(team_stats, "G"), _find_col(team_stats, "RS", "R"), _find_col(team_stats, "RA"))
    if not (team_col and g and rs and ra):
        print("Columns returned:", list(team_stats.columns))
        sys.exit("Couldn't find Team/G/RS/RA columns -- the CSVs are saved; send Claude the column list above.")

    df = team_stats.copy()
    df["RS/G"] = df[rs] / df[g]
    df["RA/G"] = df[ra] / df[g]
    df["Run diff/G"] = df["RS/G"] - df["RA/G"]
    for col, asc in (("RS/G", False), ("RA/G", True), ("Run diff/G", False)):
        df[f"{col} D2 rank"] = df[col].rank(ascending=asc, method="min").astype(int)

    psu = df[df[team_col].str.lower().str.contains(PSU_MATCH, na=False)]
    if psu.empty:
        print(f"PSU not found by '{PSU_MATCH}'. Close names:", [t for t in df[team_col] if "pitt" in str(t).lower()])
    else:
        r = psu.iloc[0]
        print(f"\n{r[team_col]} {s} (of {len(df)} D2 teams): "
              f"RS/G {r['RS/G']:.2f} (#{r['RS/G D2 rank']}), RA/G {r['RA/G']:.2f} (#{r['RA/G D2 rank']}), "
              f"run diff/G {r['Run diff/G']:+.2f} (#{r['Run diff/G D2 rank']})")

    if conf_col:
        miaa = df[df[conf_col].astype(str).str.lower().str.contains("|".join(MIAA_MATCH), na=False)]
        if not miaa.empty:
            miaa = miaa.sort_values("Run diff/G", ascending=False)
            miaa.to_csv(OUT / f"miaa_team_stats_{s}.csv", index=False)
            print(f"\nMIAA {s} (sorted by run differential per game):")
            print(miaa[[team_col, g, "RS/G", "RA/G", "Run diff/G"]].round(2).to_string(index=False))
    print(f"\nD2 average: RS/G {df['RS/G'].mean():.2f}, RA/G {df['RA/G'].mean():.2f}")


if __name__ == "__main__":
    main()
