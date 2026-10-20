"""Rapsodo Date column in non-English device locales (Oct 2026, Webb Fern 9/30 export)."""

from datetime import datetime

from services.rapsodo_import import _parse_pitch_date as parse


def test_english():
    assert parse("Wed Sep 30 2026 4:04:04 PM") == datetime(2026, 9, 30, 16, 4, 4)


def test_japanese():
    assert parse("水 9月 30 2026 4:04:04 午後") == datetime(2026, 9, 30, 16, 4, 4)
    assert parse("水 9月 30 2026 11:15:00 午前") == datetime(2026, 9, 30, 11, 15, 0)


def test_chinese_and_korean():
    assert parse("周三 9月 30 2026 4:04:04 下午") == datetime(2026, 9, 30, 16, 4, 4)
    assert parse("수 9월 30 2026 4:04:04 오후") == datetime(2026, 9, 30, 16, 4, 4)


def test_noon_and_midnight():
    assert parse("水 9月 30 2026 12:30:00 午後") == datetime(2026, 9, 30, 12, 30, 0)
    assert parse("水 9月 30 2026 12:30:00 午前") == datetime(2026, 9, 30, 0, 30, 0)


def test_junk():
    assert parse(None) is None
    assert parse("-") is None
    assert parse("水 13月 30 2026 4:04:04 午後") is None
    assert parse("水 9月 30 2026 4:04:04 黄昏") is None
