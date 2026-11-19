"""Zone Whiff % season source rule (Nov 2026): Rapsodo location in the
fall, SmartPark from spring 2027, never manual/video."""
from datetime import date
from types import SimpleNamespace as NS

import strike_zone as sz
from plate_discipline import compute_hitter_discipline, compute_pitcher_command
from game_stats import compute_pitch_type_breakdown

FALL, SPRING = date(2026, 10, 1), date(2027, 2, 20)


def _p(out, src="rapsodo", d=FALL, x=0.0, z=2.5, seq=1):
    return NS(actual_plate_x=x, actual_plate_z=z, location_source=src, pitch_outcome=out,
              game=NS(game_date=d) if d else None, game_id=1, pitch_sequence=seq, pa_pitch_number=1,
              pitch_type=NS(type_name="4-Seam Fastball"), pitch_type_id=1, is_pitch=True,
              ends_plate_appearance=False, ab_outcome=None, balls_before=0, strikes_before=0,
              intended_plate_x=None, intended_plate_z=None, intended_zone=None, pitch_zone=None,
              contact_quality=None, batted_ball_type=None, is_sword=False, run_value=None)


def test_source_for_date():
    assert sz.zone_source_for_date(FALL) == "rapsodo"
    assert sz.zone_source_for_date(SPRING) == "smartpark"
    assert sz.zone_source_for_date(date(2027, 1, 1)) == "smartpark"
    assert sz.zone_source_for_date(None) is None


def test_fall_counts_rapsodo_only():
    ps = [_p("Swing and Miss"), _p("Foul"), _p("Swing and Miss", src="manual"),
          _p("Swing and Miss", src="video"), _p("Swing and Miss", src="smartpark")]
    assert sz.zone_whiff_counts(ps) == (2, 1)
    assert sz.zone_whiff_pct(ps) == 50.0


def test_spring_counts_smartpark_only():
    ps = [_p("Swing and Miss", src="smartpark", d=SPRING), _p("In Play", src="smartpark", d=SPRING),
          _p("Swing and Miss", src="rapsodo", d=SPRING)]
    assert sz.zone_whiff_counts(ps) == (2, 1)


def test_out_of_zone_and_takes_ignored():
    ps = [_p("Swing and Miss", x=1.5), _p("Called Strike"), _p("Foul")]
    assert sz.zone_whiff_counts(ps) == (1, 0)
    assert sz.zone_whiff_pct([]) is None


def test_unknown_date_accepts_either_tracker_not_manual():
    ps = [_p("Swing and Miss", d=None), _p("Foul", src="smartpark", d=None), _p("Swing and Miss", src="manual", d=None),
          _p("Swing and Miss", src=None, d=None)]
    assert sz.zone_whiff_counts(ps) == (2, 1)


def test_wired_into_discipline_and_breakdown():
    ps = [_p("Swing and Miss", seq=1), _p("Foul", seq=2), _p("Swing and Miss", src="manual", seq=3)]
    assert compute_hitter_discipline(ps)["Zone Whiff %"] == 50.0
    assert compute_pitcher_command(ps)["Zone Whiff %"] == 50.0
    total = [r for r in compute_pitch_type_breakdown(ps) if r["Pitch Type"] == "Total"]
    rows = total or compute_pitch_type_breakdown(ps)
    assert rows[0]["Zone Whiff %"] == 50.0
