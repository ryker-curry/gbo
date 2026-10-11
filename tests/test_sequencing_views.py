"""Pitcher Profile > Sequencing rebuild (Oct 2026): grid, predictability,
eye level / sides (Rapsodo location) and finishing sequences."""

from types import SimpleNamespace as NS

from analytics import sequencing as sq


def _p(seq, ptype, outcome, b=0, s=0, pa=1, ends=False, ab=None, gid=1, gp=None, is_pitch=True):
    return NS(game_id=gid, pitch_sequence=seq, game_pitch_id=gp or seq, pitch_type=NS(type_name=ptype),
              pitch_outcome=outcome, balls_before=b, strikes_before=s, pa_pitch_number=pa,
              ends_plate_appearance=ends, ab_outcome=ab, is_our_team_batting=False, our_player_id=7,
              opponent_our_player_id=None, actual_plate_x=None, actual_plate_z=None, is_pitch=is_pitch)


def _k_pa(start, types=("4-Seam Fastball", "4-Seam Fastball", "Slider")):
    out = []
    for i, t in enumerate(types):
        last = i == len(types) - 1
        out.append(_p(start + i, t, "Swing and Miss" if last else "Called Strike", s=i, pa=i + 1, ends=last, ab="K" if last else None))
    return out


def test_height_and_side():
    assert sq.height(3.4) == "up" and sq.height(1.6) == "down" and sq.height(2.5) == "mid"
    # plate x negative = 3B side, where a righty stands -> inside to a RHH
    assert sq.side_of(-0.6, "R") == "in" and sq.side_of(-0.6, "L") == "away" and sq.side_of(0.6, None) is None


def test_clock_violation_doesnt_break_a_pair():
    ps = [_p(1, "4-Seam Fastball", "Ball"), _p(2, "4-Seam Fastball", "Ball", pa=2, is_pitch=False),
          _p(3, "Slider", "Called Strike", b=2, pa=3)]
    assert [(a.pitch_sequence, b.pitch_sequence) for a, b in sq.pairs(ps)] == [(1, 3)]


def test_grid_and_predictability():
    ps = []
    for k in range(6):
        ps += _k_pa(k * 10)
    g = sq.grid(ps)
    assert g["types"] == ["4-Seam Fastball", "Slider"]
    assert g["cells"][("4-Seam Fastball", "Slider")]["share"] == 50
    pr = sq.predictability(ps)
    top = pr[0]
    assert top["flag"] and top["count"] in ("0-1", "0-2") and top["top_share"] == 100


def test_location_moves_and_finishing():
    ps = _k_pa(0) + _k_pa(10)
    hands = {p.game_pitch_id: "R" for p in ps}
    # FB up and in, then SL down and away, for both at-bats
    loc = {}
    for start in (0, 10):
        loc[start] = (-0.5, 3.4)
        loc[start + 1] = (-0.5, 3.5)
        loc[start + 2] = (0.6, 1.2)
    mv = sq.location_moves(ps, loc, hands)
    vert = {r["key"]: r["n"] for r in mv["vertical"]}
    horz = {r["key"]: r["n"] for r in mv["horizontal"]}
    assert vert == {"down": 2, "up": 0, "same": 2} and horz["away"] == 2 and horz["same"] == 2
    fin = sq.finishing(ps, loc, hands)
    assert fin["two_strike_pas"] == 2
    assert fin["rows"][0]["label"] == "FB up → SL down" and fin["rows"][0]["k"] == 2
    assert fin["k_seqs"][0] == ("FB up → FB up → SL down", 2)
