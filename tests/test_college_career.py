"""Nov 2026: College Career (college_career.py + the CSV importer)."""

from types import SimpleNamespace as NS

import pytest

import college_career as cc

ROSTER = """Eric Bacon|Landon Bruce|Landin Midgett|Jadyn McNealy|Brett Sarwinski|James Dagenhart|Seth Dandridge|Bradyn McClure|
Ryker Curry|Lucas Vanlanduit|Ricardo Hernandez|Porter Starnes|Ethan Froud|Bradley Neill|Elijah Seitz|Cross Dowd|Destyn Dowd|
Colton Ruedy|Saben Seager|Luke Clayton|Jackson Lundquist|Jeff Zachry|Kadyn Martinez|Carter Freeland|Evan Janner|Robby Lopez|
Shane Holman|Cooper Westra|Brett Pearcy|Mitchell Johnson|Luke Schimmels|Webb Fern|Kyle Graves|Brooks Kappelmann|Gavin Derr|
Bryce Ronken|Taylor Tomlin|Miles Burhle"""


def _roster():
    out = []
    for i, n in enumerate(x.strip() for x in ROSTER.replace("\n", "").split("|")):
        first, last = n.split(" ", 1)
        out.append(NS(player_id=i + 1, first_name=first, last_name=last, active=True))
    return out


def test_innings():
    assert cc.ip_to_outs("45.1") == 136 and cc.ip_to_outs("5.0") == 15 and cc.ip_to_outs("") is None
    assert cc.outs_to_ip(136) == "45.1"
    with pytest.raises(ValueError):
        cc.ip_to_outs("4.5")


def test_every_csv_row_matches_a_roster_player():
    import os
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "college_season_stats.csv")
    roster = _roster()
    for rec in cc.read_csv(path):
        assert cc.match_player(rec["player"], roster) is not None, rec["player"]
        cc.parse_csv_row(rec)   # parses cleanly
    assert cc.match_player("Robert Lopez III", roster).first_name == "Robby"
    assert cc.match_player("Jeff Zachary", roster).last_name == "Zachry"
    assert cc.match_player("Dowd", roster) is None


def _row(side, year, school, **kw):
    base = {c: None for c in cc.STAT_COLS}
    base.update(kw)
    return NS(side=side, season_year=year, school=school, level="NJCAA D1", source_url=None,
              college_season_stat_id=year, **base)


def test_totals_skip_partial_rows_and_rates():
    full = dict(g=10, ab=40, r=8, h=12, doubles=2, triples=1, hr=1, rbi=9, bb=5, so=7, hbp=1, sf=1, sh=0, sb=3, cs=1, gdp=0)
    rows = [_row("batting", 2024, "A", **full), _row("batting", 2025, "B", **full), _row("batting", 2026, "C", g=20, h=15)]
    seasons, total, partial = cc.career_rows(rows, "batting")
    assert partial == 1 and [s["_partial"] for s in seasons] == [False, False, True]
    assert total["H"] == "24" and total["AB"] == "80" and total["BA"] == ".300"
    assert total["TB"] == str(2 * (12 + 2 + 2 + 3))
    assert seasons[2]["AB"] == cc.DASH and seasons[2]["BA"] == cc.DASH
    assert total["School"] == "Total (2 schools)"


def test_pitching_line():
    rows = [_row("pitching", 2026, "PSU", ip_outs=193, h=48, r=27, er=26, bb=25, so=61, w=6, l=0)]
    seasons, total, partial = cc.career_rows(rows, "pitching")
    assert seasons[0]["IP"] == "64.1" and seasons[0]["ERA"] == "3.64" and seasons[0]["WHIP"] == "1.13"
    assert partial == 0 and total["ERA"] == "3.64"


def test_import_into_sqlite(seeded):
    db, _info = seeded
    from models import Player, CollegeSeasonStat
    from scripts import import_college_season_stats as imp
    p = db.query(Player).first()
    import tempfile, csv, os
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["player", "side", "year", "school", "level", "AB", "H", "IP", "source_url"])
        w.writeheader()
        w.writerow({"player": f"{p.first_name} {p.last_name}", "side": "batting", "year": 2025, "school": "Test CC",
                    "level": "NJCAA D1", "AB": "10", "H": "4"})
        w.writerow({"player": "Nobody Here", "side": "pitching", "year": 2025, "school": "X", "IP": "1.0"})
    added, updated, unmatched = imp.run(db, apply=True, path=path)
    assert added == 1 and unmatched == ["Nobody Here"]
    # re-run with a blank H: existing value is kept
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["player", "side", "year", "school", "AB", "H"])
        w.writeheader()
        w.writerow({"player": f"{p.first_name} {p.last_name}", "side": "batting", "year": 2025, "school": "Test CC", "AB": "11", "H": ""})
    added, updated, _ = imp.run(db, apply=True, path=path)
    row = db.query(CollegeSeasonStat).filter_by(player_id=p.player_id, school="Test CC").one()
    assert (added, updated, row.ab, row.h) == (0, 1, 11, 4)
    os.remove(path)
