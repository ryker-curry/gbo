from types import SimpleNamespace as NS

from analytics import decision_value as dv
from analytics import hitter_game_card as hgc
from visualizations import hitter_game_card as viz


def _p(i, x, z, outcome, b=0, s=0, rv=0.0, cq=None, gid=1, ab=None):
    return NS(game_pitch_id=i, game_id=gid, pitch_sequence=i, actual_plate_x=x, actual_plate_z=z,
              pitch_outcome=outcome, balls_before=b, strikes_before=s, run_value=rv, contact_quality=cq,
              ab_outcome=ab, pitch_type=NS(type_name="4-Seam Fastball"), pa_pitch_number=1)


def _team():
    """Team history: swinging in the heart pays, chasing costs."""
    out, i = [], 1000
    for k in range(40):
        i += 1
        out.append(_p(i, 0.0, 2.5, "In Play", rv=0.15, cq="Solid", gid=9))
        i += 1
        out.append(_p(i, 0.0, 2.5, "Called Strike", rv=-0.05, gid=9))
        i += 1
        out.append(_p(i, 1.4, 1.0, "Swing and Miss", rv=-0.08, gid=9))
        i += 1
        out.append(_p(i, 1.4, 1.0, "Ball", rv=0.04, gid=9))
    return out


def _game():
    return [
        _p(1, 0.0, 2.5, "In Play", cq="Barreled/Squared Up", ab="2B"),     # heart swing (good)
        _p(2, 0.0, 2.6, "Called Strike"),                                  # heart take (poor)
        _p(3, 0.65, 2.0, "Foul", s=1),                                     # edge swing
        _p(4, 1.4, 1.0, "Ball", b=1, s=2),                                 # chase take (good), 2 strikes
        _p(5, 1.5, 0.9, "Swing and Miss", b=1, s=2, ab="K"),               # chase whiff (poor)
        _p(6, None, None, "Ball"),                                         # no location
    ]


def test_rates_and_areas():
    table = dv.build_table(_team())
    r = hgc.rates(_game(), table)
    assert r["pitches"] == 6 and r["located"] == 5 and r["swings"] == 3 and r["bip"] == 1
    assert r["zone_n"] == 3 and r["zone_swings"] == 2 and round(r["zone_swing"]) == 67
    assert r["chase_n"] == 2 and r["chase"] == 50.0
    assert r["whiff"] == 100 / 3 and r["hard_pct"] == 100.0
    assert r["areas"]["heart"]["n"] == 2 and r["areas"]["edges"]["n"] == 1 and r["areas"]["chase"]["n"] == 2
    # points = runs x 10
    runs = sum(c[0] for c in (dv.credit(table, p) for p in _game()) if c)
    assert abs(r["pts"] - 10 * runs) < 1e-9


def test_build_tiles_and_items():
    table = dv.build_table(_team())
    team = _team()
    card = hgc.build(_game(), [p for p in team if p.game_id == 9], team, table, pa_count=2)
    assert [t["label"] for t in card["tiles"]] == ["Zone Swing %", "Decision Pts", "Hard Hit %", "Chase %", "Whiff %"]
    zs = card["tiles"][0]
    assert zs["sub"] == "2 of 3 in the zone" and zs["season"] == 50.0
    items = card["pitches"]
    assert len(items) == 5
    by = {it["count"]: it for it in items}
    assert by["1-2"]["two_three"] and not by["0-0"]["two_three"]
    heart_swing, heart_take = items[0], items[1]
    assert heart_swing["decision"] == "good" and heart_take["decision"] == "poor"
    assert {it["action"] for it in items} == {"swing", "take", "foul", "whiff"}
    shares = [a["share"] for a in card["areas"]]
    assert round(sum(shares)) == 100 and len(card["swings"]) == 3


def test_card_html_renders():
    table = dv.build_table(_team())
    card = hgc.build(_game(), _team(), _team(), table, pa_count=2)
    h = viz.card_html(card, hand="R")
    for s in ("ZONE SWING %", "DECISION PTS", "EVERY PITCH", "WHERE YOU SWUNG", "HEART", "EDGES", "CHASE", "RHH",
              "2 of 3 in the zone"):
        assert s in h
    # no swings / empty team still renders
    card2 = hgc.build([_p(1, 0.0, 2.5, "Ball")], [], [], table, pa_count=1)
    assert "No swings" in viz.card_html(card2)
