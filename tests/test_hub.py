from datetime import date, timedelta
from types import SimpleNamespace as NS

from analytics import hub

TODAY = date(2026, 10, 30)


def _d(n):
    return TODAY - timedelta(days=n)


def test_vs_own_velo_drop_levels():
    rule = hub.FLAG_RULES["velo"]
    hist = [(_d(30), 88.0), (_d(23), 88.4), (_d(16), 87.6)]
    assert hub.vs_own(hist + [(_d(2), 87.0)], TODAY, rule)["level"] is None
    r = hub.vs_own(hist + [(_d(2), 86.3)], TODAY, rule)
    assert r["level"] == "watch" and round(r["diff"], 1) == -1.7 and r["n_prior"] == 3
    assert hub.vs_own(hist + [(_d(2), 85.0)], TODAY, rule)["level"] == "severe"


def test_vs_own_needs_recent_and_enough_history():
    rule = hub.FLAG_RULES["velo"]
    # latest outside the lookback -> nothing
    assert hub.vs_own([(_d(60), 88), (_d(50), 88), (_d(40), 88), (_d(20), 80)], TODAY, rule) is None
    # only 2 earlier outings -> nothing
    assert hub.vs_own([(_d(20), 88), (_d(10), 88), (_d(1), 80)], TODAY, rule) is None


def test_pct_and_high_is_bad():
    w = hub.FLAG_RULES["weight"]
    assert hub.vs_own([(_d(20), 200), (_d(1), 193)], TODAY, w)["level"] == "watch"     # -3.5%
    assert hub.vs_own([(_d(20), 200), (_d(1), 189)], TODAY, w)["level"] == "severe"    # -5.5%
    assert hub.vs_own([(_d(20), 200), (_d(1), 210)], TODAY, w)["level"] is None        # gaining is fine
    c = hub.FLAG_RULES["chase"]
    assert hub.vs_own([(_d(20), 20), (_d(15), 25), (_d(10), 22), (_d(1), 45)], TODAY, c)["level"] == "watch"


def test_z_rule_needs_real_gap():
    rule = hub.FLAG_RULES["decision"]
    hist = [(_d(20), 0.5), (_d(15), 0.7), (_d(10), 0.6)]
    assert hub.vs_own(hist + [(_d(1), -0.6)], TODAY, rule)["level"] == "severe"
    # tiny SD but a tiny gap -> no flag
    tight = [(_d(20), 0.50), (_d(15), 0.51), (_d(10), 0.49)]
    assert hub.vs_own(tight + [(_d(1), 0.30)], TODAY, rule)["level"] is None


def test_tiers_and_order():
    p1, p2, p3, p4 = (NS(player_id=i, last_name=n, is_pitcher=True) for i, n in enumerate("ABCD", 1))
    flags = {
        1: [hub.flag("Velo", "velo", "x", False, _d(1))],                                  # one watch flag
        2: [hub.flag("Velo", "velo", "x", False, _d(1)), hub.flag("CMJ", "cmj_ht", "y", False, _d(1))],  # two sources
        3: [hub.flag("Load", "load", "z", True, _d(1))],                                   # severe
    }
    rows = hub.watch_list([p1, p2, p3, p4], flags)
    assert [(r["player"].last_name, r["tier"]) for r in rows] == [("C", "priority"), ("B", "priority"), ("A", "watch")]
    # two flags from the SAME source stay on watch
    assert hub.tier([hub.flag("Approach", "chase", "", False, None), hub.flag("Approach", "decision", "", False, None)]) == "watch"


def test_load_flag():
    base = {"ratio": 1.2, "stress": {"ratio": 1.4, "full": True}, "seven_day": 80, "source": "auto", "status": "Available",
            "last": _d(1)}
    f = hub.load_flag(base)
    assert f and not f["severe"] and "stress" in f["text"]
    assert hub.load_flag({**base, "ratio": 1.6})["severe"]
    assert hub.load_flag({**base, "stress": None}) is None
    hold = hub.load_flag({**base, "stress": None, "source": "coach", "status": "Hold", "reason": "Coach set Hold"})
    assert hold and hold["key"] == "hold"


def test_weekly_buckets():
    pts = [(_d(0), 5), (_d(3), 5), (_d(8), 2)]
    assert hub.weekly(pts, TODAY, weeks=3) == [0, 2, 10]
    assert hub.weekly(pts, TODAY, weeks=2, agg="mean") == [2, 5]


def test_series_flags_text():
    out = hub.series_flags({(7, "velo"): [(_d(30), 88), (_d(20), 88), (_d(10), 88), (_d(1), 85.5)]}, TODAY)
    (f,) = out[7]
    assert f["source"] == "Velo" and f["severe"] and f["text"].startswith("Fastball velo -2.5 mph")


def test_build_runs_on_seed_db(db):
    from models import Player
    players = db.query(Player).filter(Player.active.is_(True)).all()
    data = hub.build(db, players, as_of=date.today())
    assert {s["name"] for s in data["sources"]} >= {"Game charting", "Rapsodo", "WHOOP"}
    assert isinstance(data["pulse"], list) and isinstance(data["watch"], list)
    from visualizations import hub_view
    html = hub_view.hub_html(data)
    assert "Watch list" in html and "Pulse" in html
