"""
GBO -- Assessment bulk importer (Sept 2026).

Lets a coach fill in GBO_Assessment_Import_Templates.xlsx (one sheet per
assessment category, headers matching AssessmentTestType names/units
exactly -- see assessment_import_spec.py) and import an entire sheet in
one upload instead of typing every value in by hand. Mirrors
services/rapsodo_import.py's design philosophy on purpose, so this reads
like the same app rather than a second, differently-shaped importer:

  - Never silently guesses a column mapping. A column this file doesn't
    recognize at all (a typo'd header, a column the sheet's own author
    added) is preserved and reported, never discarded quietly -- see
    unrecognized_columns in the preview. A column this file DOES
    recognize but has no AssessmentTestType for yet (assessment_import_
    spec.py's kind="unmapped_new" -- Body Composition's AGE_yrs/BMI/
    FFMI/TBW/ICW/ECW, Explosive Power's *NEW* CMJ metrics) is reported
    separately, with the reason, so it's clear this is a known schema
    gap rather than a typo.
  - Two-phase validate-then-commit, same split as
    validate_file_structure()/import_rapsodo_file(): preview_assessment_
    import() does every lookup and parse WITHOUT writing anything, so a
    UI can show a coach exactly what would happen first.
    commit_assessment_import() takes that same preview back and does
    the actual writes -- nothing is written on preview alone.
  - Whole-file rejection ONLY when the sheet is structurally unreadable
    (no recognized header row, or literally none of Player First Name/
    Player Last Name/Assessment Date present). An individual bad or
    duplicate row is skipped and reported, never treated as a reason to
    reject the whole file -- same as Rapsodo's per-row rejected list.
  - Duplicate guard is per VALUE, not per file or even per row: if an
    Assessment already exists for a (player, category, date), this
    importer reuses it (never creates a second Assessment for the same
    player/category/date) and, within it, skips any test value that
    already has an AssessmentResult recorded -- existing data is never
    overwritten. A row that's entirely duplicate values still gets
    reported, just with every value individually marked "already
    recorded" rather than the row being silently dropped.
  - Pure data logic, no Shiny/UI-framework import -- callable from a
    page module, a script, or a test, exactly like rapsodo_import.py.

One category per import (Ryker's explicit call) -- every call here is
scoped to exactly one AssessmentCategory; a caller uploading a whole
multi-tab workbook loops this once per sheet/category, not once for the
whole file.
"""

import io
import re
from datetime import date, datetime

import pandas as pd

from models import Assessment, AssessmentCategory, AssessmentResult, AssessmentTestType, Player
from assessment_import_spec import CATEGORY_SPECS, BASE_COLUMNS


class AssessmentImportError(Exception):
    """Base class for anything that stops an import before it completes."""


class AssessmentValidationError(AssessmentImportError):
    """The file/sheet isn't usable at all -- no recognizable header row,
    or none of the three base columns (Player First Name, Player Last
    Name, Assessment Date) could be found."""


class UnknownCategoryError(AssessmentImportError):
    """category_name isn't one of assessment_import_spec.CATEGORY_SPECS'
    keys -- either a typo, or a category this importer doesn't have a
    column spec for yet (Anthropometrics, Baseball Performance,
    Pitcher-Specific are deliberately not in that dict -- see that
    module's own docstring/CATEGORY_SPECS for which categories it
    covers)."""


_FT_IN_RE = re.compile(r"""^\s*(-?\d+)\s*'\s*(\d+(?:\.\d+)?)\s*"?\s*$""")


def _parse_ftin(val):
    """"43'10\"" -> 43 + 10/12 (decimal feet). Returns None for a blank
    cell or anything that doesn't match a plain feet'inches\" shape --
    never guesses at a malformed value (e.g. "43-10", "43 ft 10 in")."""
    s = _clean_str(val)
    if s is None:
        return None
    m = _FT_IN_RE.match(s)
    if not m:
        return None
    feet, inches = float(m.group(1)), float(m.group(2))
    return feet + inches / 12.0


def _parse_float(val):
    try:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return None
        s = str(val).strip()
        if s in ("", "-"):
            return None
        return float(s)
    except (ValueError, TypeError):
        return None


def _clean_str(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    return s if s not in ("", "-") else None


def _parse_assessment_date(val):
    """Accepts a real Excel date (pandas already gives back a Timestamp/
    datetime for a date-formatted cell), or a plain typed string in any
    of a few common shapes. Returns a python date, or None if it can't
    be read as one -- never guesses a partial/ambiguous date."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    s = str(val).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    try:
        return pd.to_datetime(s).date()
    except (ValueError, TypeError):
        return None


def read_xlsx_sheet(file_bytes: bytes, sheet_name: str) -> pd.DataFrame:
    """Parses one named sheet of the uploaded workbook. Raises
    AssessmentValidationError if the sheet doesn't exist or can't be
    read as a table at all (mirrors read_csv_bytes's role in
    rapsodo_import.py -- public so a page can call this directly for a
    sheet-name picker before committing to a category)."""
    try:
        df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=sheet_name, engine="openpyxl")
    except ValueError as e:
        raise AssessmentValidationError(
            f'Couldn\'t find a sheet named "{sheet_name}" in this workbook (or it isn\'t readable as a table). '
            f"Underlying error: {e}"
        )
    except Exception as e:
        raise AssessmentValidationError(f"This file couldn't be read as a spreadsheet. Underlying error: {e}")
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _build_column_map(columns, spec):
    """Returns (spec_by_column, unrecognized_columns):
    spec_by_column: actual df column name -> its ColumnSpec.
    unrecognized_columns: df columns that are neither a base column nor
    anywhere in this category's spec at all -- a real, unknown column
    (typo'd header, or something the sheet's author added), reported so
    nothing about it is silently dropped without at least saying so."""
    spec_by_header = {c.header: c for c in spec}
    spec_by_column = {}
    unrecognized_columns = []
    for col in columns:
        if col in BASE_COLUMNS:
            continue
        found = spec_by_header.get(col)
        if found is not None:
            spec_by_column[col] = found
        else:
            unrecognized_columns.append(col)
    return spec_by_column, unrecognized_columns


def build_player_lookup(db_session):
    """{(first_name.lower().strip(), last_name.lower().strip()): player_id}
    for every player on the roster (active and inactive both -- a sheet
    covering an old testing date may well include someone who's since
    gone inactive; excluding them would silently reject real rows).
    Case-insensitive exact match only -- no fuzzy/partial matching, so a
    real typo in the sheet surfaces as "player not found" rather than
    silently landing on the wrong person."""
    return {
        (p.first_name.strip().lower(), p.last_name.strip().lower()): p.player_id
        for p in db_session.query(Player).all()
    }


def preview_assessment_import(db_session, *, file_bytes: bytes, sheet_name: str, category_name: str):
    """Parses and validates one sheet WITHOUT writing anything to the
    database. Returns a dict:
        category_name, category_id,
        rows: [{
            file_row_num, first_name, last_name, player_id (None if not found),
            assessment_date (None if unparseable),
            values: [{test_type_id, test_name, unit, raw_header, value}],
            player_updates: {"height_in": float} and/or {"throws": "R"/"L"} (only when
                a value was given AND, for throws, the player's current throws is null),
            duplicate_test_names: [test_name, ...] -- values in this row that already
                have an AssessmentResult recorded and will be skipped, not overwritten,
            existing_assessment_id: int or None -- set when this player/category/date
                already has an Assessment (values merge into it rather than a new one),
            status: "ok" | "player_not_found" | "no_date" | "no_values",
            reason: str or None -- set for every non-"ok" status,
        }, ...],
        unrecognized_columns: [...] -- real columns this category's spec has never heard of,
        unmapped_new_columns: [...] -- recognized columns with no AssessmentTestType yet,
            only included if at least one row actually has a value in that column,
        ok_row_count, skipped_row_count,

    Raises AssessmentValidationError if the sheet can't be read at all, or
    UnknownCategoryError if category_name isn't in CATEGORY_SPECS."""
    spec = CATEGORY_SPECS.get(category_name)
    if spec is None:
        raise UnknownCategoryError(
            f'"{category_name}" has no column spec in assessment_import_spec.CATEGORY_SPECS -- either a typo, '
            f"or a category this importer doesn't support yet (available: {', '.join(sorted(CATEGORY_SPECS))})."
        )

    category = db_session.query(AssessmentCategory).filter(AssessmentCategory.category_name == category_name).first()
    if category is None:
        raise AssessmentValidationError(
            f'No AssessmentCategory named "{category_name}" exists in the database -- run seed_assessment_'
            f"categories_and_tests() before importing."
        )

    df = read_xlsx_sheet(file_bytes, sheet_name)
    missing_base = [c for c in BASE_COLUMNS if c not in df.columns]
    if missing_base:
        raise AssessmentValidationError(
            f'This sheet is missing required column(s): {", ".join(missing_base)}. GBO needs Player First '
            f"Name, Player Last Name, and Assessment Date to import any category."
        )

    spec_by_column, unrecognized_columns = _build_column_map(df.columns, spec)

    # test_name -> AssessmentTestType, for every test type this category
    # already has -- built once, not per row.
    test_types_by_name = {
        t.test_name: t
        for t in db_session.query(AssessmentTestType).filter(AssessmentTestType.category_id == category.category_id).all()
    }

    player_lookup = build_player_lookup(db_session)
    players_by_id = {p.player_id: p for p in db_session.query(Player).all()}

    unmapped_new_columns_seen = set()
    rows = []
    ok_row_count = 0
    skipped_row_count = 0

    for i, row in df.iterrows():
        file_row_num = i + 2  # +1 for 0-index, +1 for the header row -- matches what a coach sees in Excel

        first_name = _clean_str(row.get("Player First Name"))
        last_name = _clean_str(row.get("Player Last Name"))
        assessment_dt = _parse_assessment_date(row.get("Assessment Date"))

        if first_name is None and last_name is None and assessment_dt is None:
            continue  # a genuinely blank trailing row, not a real data row -- not even worth reporting

        player_id = player_lookup.get((
            (first_name or "").lower(), (last_name or "").lower(),
        ))

        entry = {
            "file_row_num": file_row_num,
            "first_name": first_name, "last_name": last_name,
            "player_id": player_id, "assessment_date": assessment_dt,
            "values": [], "player_updates": {}, "duplicate_test_names": [],
            "existing_assessment_id": None, "status": "ok", "reason": None,
        }

        if player_id is None:
            entry["status"] = "player_not_found"
            entry["reason"] = f'No player named "{first_name} {last_name}" found on the roster.'
            rows.append(entry)
            skipped_row_count += 1
            continue

        if assessment_dt is None:
            entry["status"] = "no_date"
            entry["reason"] = "Assessment Date is missing or couldn't be read."
            rows.append(entry)
            skipped_row_count += 1
            continue

        existing_assessment = (
            db_session.query(Assessment)
            .filter(
                Assessment.player_id == player_id,
                Assessment.category_id == category.category_id,
                Assessment.assessment_date == assessment_dt,
            )
            .first()
        )
        existing_result_test_type_ids = set()
        if existing_assessment is not None:
            entry["existing_assessment_id"] = existing_assessment.assessment_id
            existing_result_test_type_ids = {
                r.test_type_id for r in
                db_session.query(AssessmentResult.test_type_id)
                .filter(AssessmentResult.assessment_id == existing_assessment.assessment_id)
                .all()
            }

        player = players_by_id[player_id]

        for col, colspec in spec_by_column.items():
            raw_val = row.get(col)

            if colspec.kind == "unmapped_new":
                if _clean_str(raw_val) is not None or _parse_float(raw_val) is not None:
                    unmapped_new_columns_seen.add(col)
                continue

            if colspec.kind == "player_throws":
                s = _clean_str(raw_val)
                if s and s.upper() in ("R", "L") and not player.throws:
                    entry["player_updates"]["throws"] = s.upper()
                continue

            if colspec.kind == "player_height":
                height_ft = _parse_ftin(raw_val)  # decimal FEET, e.g. 5'11" -> 5.9167
                if height_ft is not None:
                    entry["player_updates"]["height_in"] = round(height_ft * 12.0, 2)  # Player.height_in is inches
                continue

            if colspec.kind == "value":
                value = _parse_float(raw_val)
            elif colspec.kind in ("ftin_to_in", "ftin_to_ft"):
                feet_value = _parse_ftin(raw_val)
                value = feet_value * 12.0 if (feet_value is not None and colspec.kind == "ftin_to_in") else feet_value
            else:
                value = None  # unreachable given the kinds assessment_import_spec.py defines today

            if value is None:
                continue

            test_type = test_types_by_name.get(colspec.test_name)
            if test_type is None:
                # A spec column whose AssessmentTestType doesn't actually
                # exist in THIS database yet (schema drift between this
                # file and what's actually seeded) -- same treatment as
                # unmapped_new, not a row-level failure.
                unmapped_new_columns_seen.add(col)
                continue

            if test_type.test_type_id in existing_result_test_type_ids:
                entry["duplicate_test_names"].append(colspec.test_name)
                continue

            entry["values"].append({
                "test_type_id": test_type.test_type_id, "test_name": colspec.test_name,
                "unit": colspec.unit, "raw_header": col, "value": round(value, 3),
            })

        if not entry["values"] and not entry["player_updates"]:
            entry["status"] = "no_values"
            entry["reason"] = (
                "Every value in this row is either blank or already recorded from a previous import."
                if entry["duplicate_test_names"] else
                "No values in this row -- every test column was blank."
            )
            skipped_row_count += 1
        else:
            ok_row_count += 1

        rows.append(entry)

    return {
        "category_name": category_name, "category_id": category.category_id,
        "rows": rows,
        "unrecognized_columns": unrecognized_columns,
        "unmapped_new_columns": sorted(unmapped_new_columns_seen),
        "ok_row_count": ok_row_count, "skipped_row_count": skipped_row_count,
    }


def commit_assessment_import(db_session, preview: dict, *, entered_by_user_id: int):
    """Writes everything in a previously-built preview (see
    preview_assessment_import) to the database: one Assessment per
    (player, date) that doesn't already have one for this category (an
    existing one is reused via existing_assessment_id, never
    duplicated), one AssessmentResult per queued value, and any
    player_updates (height_in / throws) applied directly to the Player
    row. Rows with status != "ok" are skipped entirely (already
    reported as such by preview_assessment_import -- nothing new to do
    with them here). Commits once at the end; rolls back and raises
    AssessmentImportError if anything goes wrong partway through, same
    all-or-nothing-per-call guarantee import_rapsodo_file gives.

    Returns {"assessments_created": int, "assessments_reused": int,
    "results_created": int, "players_updated": int}."""
    assessments_created = 0
    assessments_reused = 0
    results_created = 0
    players_updated = 0

    try:
        for row in preview["rows"]:
            if row["status"] != "ok":
                continue

            if row["existing_assessment_id"] is not None:
                assessment_id = row["existing_assessment_id"]
                assessments_reused += 1
            else:
                assessment = Assessment(
                    player_id=row["player_id"], category_id=preview["category_id"],
                    assessment_date=row["assessment_date"], entered_by_user_id=entered_by_user_id,
                )
                db_session.add(assessment)
                db_session.flush()  # assigns assessment.assessment_id
                assessment_id = assessment.assessment_id
                assessments_created += 1

            for v in row["values"]:
                db_session.add(AssessmentResult(
                    assessment_id=assessment_id, test_type_id=v["test_type_id"], value=v["value"],
                ))
                results_created += 1

            if row["player_updates"]:
                player = db_session.query(Player).filter(Player.player_id == row["player_id"]).first()
                if player is not None:
                    updated = False
                    if "height_in" in row["player_updates"]:
                        player.height_in = row["player_updates"]["height_in"]
                        updated = True
                    if "throws" in row["player_updates"] and not player.throws:
                        player.throws = row["player_updates"]["throws"]
                        updated = True
                    if updated:
                        players_updated += 1

        db_session.commit()
    except Exception:
        db_session.rollback()
        raise AssessmentImportError(
            "Import failed partway through writing to the database -- nothing from this sheet was saved. This "
            "is usually a data problem in a specific row rather than the sheet itself; check for unexpected "
            "characters or values before re-uploading."
        )

    return {
        "assessments_created": assessments_created, "assessments_reused": assessments_reused,
        "results_created": results_created, "players_updated": players_updated,
    }
