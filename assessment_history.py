"""
GBO -- Assessment history query + row formatting, shared between the
Assessments page and Player Profile.

Sept 2026: Assessments page was pared down to a pure data-entry page
(Ryker's call -- "the assessment page is purely just for inputting
data", viewing moved to Player Profile). Assessments.py still needs a
list of a player's past entries for its "which entry do you want to
edit?" picker (that's data correction, not a view), and Player
Profile's new Full History section needs the same list, just for
display -- this one shared query/formatting pair is what keeps those
two call sites from drifting apart, the same reasoning behind every
other shared query-layer file in this app (e.g. analytics/
profile_queries.py for Pitcher/Hitter Profile).
"""

from sqlalchemy.orm import joinedload

from models import Assessment, AssessmentResult, BullpenPitch


def assessment_history_query(db, player_id, category_id, pitch_type_id=None, limit=500):
    """Every Assessment for one player/category, newest first, eager-
    loaded for row formatting -- excludes entries linked to a Bullpen
    Tracking import (BullpenPitch.linked_assessment_id), same as every
    other reader of this data: that data already has a home on Bullpen
    Tracking, not here. `limit` caps how many rows come back (500 by
    default, same cap the original Assessments-page history view used)
    -- callers that hit it should tell the user only the most recent
    `limit` are shown."""
    q = (
        db.query(Assessment)
        .options(
            joinedload(Assessment.results).joinedload(AssessmentResult.test_type),
            joinedload(Assessment.pitch_type),
        )
        .filter(Assessment.player_id == player_id, Assessment.category_id == category_id)
        .filter(~Assessment.assessment_id.in_(
            db.query(BullpenPitch.linked_assessment_id).filter(BullpenPitch.linked_assessment_id.isnot(None))
        ))
    )
    if pitch_type_id is not None:
        q = q.filter(Assessment.pitch_type_id == pitch_type_id)
    return q.order_by(Assessment.assessment_date.desc()).limit(limit)


def assessment_history_rows(assessments):
    """Format already-loaded Assessment rows (see assessment_history_
    query) into plain dicts for ui_helpers.render_dict_table -- Date/
    Pitch Type (when set)/Notes, plus one column per test result named
    "{test name} ({unit})". Pure formatting, no DB access, so a caller
    that filtered/queried differently can still reuse it."""
    rows = []
    for a in assessments:
        row = {"Date": a.assessment_date.strftime("%Y-%m-%d (%a)")}
        if a.pitch_type:
            row["Pitch Type"] = a.pitch_type.type_name
        row["Notes"] = a.notes or ""
        for r in a.results:
            unit_label = f" ({r.test_type.unit})" if r.test_type.unit else ""
            row[f"{r.test_type.test_name}{unit_label}"] = round(float(r.value), 2)
        rows.append(row)
    return rows
