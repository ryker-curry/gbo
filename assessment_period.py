"""
GBO -- Assessment testing-period labels.

Oct 31 2026 (Ryker's call): assessments display by testing period
("Fall 2026", "Spring 2027") everywhere in the app instead of the exact
entry date. The real date is still stored on Assessment.assessment_date
and still drives sorting, season filters, and "latest result" logic --
this only changes what's shown.

Aug-Dec = Fall, Jan-Jul = Spring.
"""
import re
from datetime import date

_FALL_START_MONTH = 8

# Representative date stored when an import row says "Fall 2026" instead
# of a real date -- mid-term, safely inside the season windows.
_PERIOD_DATES = {"fall": (9, 1), "spring": (2, 1)}


def period_label(d):
    """date -> "Fall 2026" / "Spring 2027"; "—" for None."""
    if d is None:
        return "—"
    term = "Fall" if d.month >= _FALL_START_MONTH else "Spring"
    return f"{term} {d.year}"


def parse_period_label(s):
    """"Fall 2026" / "spring 2027" -> a representative date, else None."""
    if not isinstance(s, str):
        return None
    m = re.fullmatch(r"\s*(fall|spring)\s+(\d{4})\s*", s, flags=re.IGNORECASE)
    if not m:
        return None
    month, day = _PERIOD_DATES[m.group(1).lower()]
    return date(int(m.group(2)), month, day)
