"""Oct 2026 coach-usability pass."""
import sys
sys.path.insert(0, "shiny_app")

from analytics import coach_summary as cs


def _row(t, n, rv, whiff=20, avg=.2, hard=30, bip=5):
    return {"type": t, "n": n, "rv100": rv, "whiff": whiff, "avg": avg, "hard": hard, "bip": bip}


def test_best_and_worst():
    card = {"rows": [_row("Slider", 30, -2.0), _row("4-Seam Fastball", 60, 1.1, whiff=30, avg=.320), _row("Changeup", 5, -9)]}
    b, w = cs.best_and_worst(card)
    assert b["type"] == "Slider" and w["type"] == "4-Seam Fastball"
    assert "lean on it" in cs.pitch_line(b)
    assert "location problem" in cs.pitch_line(w, best=False)
    assert cs.best_and_worst({"rows": [_row("Slider", 30, -1.0)]}) == (None, None)


def test_leaderboard_ip_decimal():
    from modules.pitching_leaderboard import _ip_decimal
    assert _ip_decimal("10.1") == 10 + 1 / 3 and _ip_decimal("12.0") == 12 and _ip_decimal("x") is None
