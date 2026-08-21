"""
GBO — Rapsodo bullpen import service.

Reads a Rapsodo pitch-level export, normalizes/validates it, and inserts
RapsodoPitch rows tied to a RapsodoImport audit record and a
BullpenSession. This is the Phase 1 replacement for the old
pages/import_rapsodo.py workflow (which still exists and still works,
but writes to Assessment/AssessmentResult -- see the architecture
review for why that's being phased out).

Design constraints from the spec (Section 21, "Import Reliability") and
the architecture review:
  - Preserve every raw column, even ones GBO doesn't chart yet.
  - Never silently guess at a column mapping -- unmapped columns go into
    a JSON catch-all (RapsodoPitch.raw_extra), not discarded.
  - Two independent duplicate-import guards: a whole-file sha256 hash
    (RapsodoImport.file_hash) and a per-pitch natural key
    (RapsodoPitch.rapsodo_unique_id), since a coach could re-upload a
    file that partially overlaps a previous one (e.g. a re-export
    covering a wider time range) without it being byte-for-byte
    identical.
  - Whole-file rejection only when the file is structurally unreadable
    as a Rapsodo export (no recognizable header, or a required raw
    field is missing from every row) -- individual bad/duplicate ROWS
    are skipped and reported, not treated as reasons to reject the
    whole file, since one corrupted row out of sixty shouldn't lose an
    entire bullpen's data.
  - Pitch chronology is derived from the parsed pitch Date, NOT the
    file's own "No" column -- see RapsodoPitch's docstring in models.py
    for why ("No" was found to be most-recent-first in the real export
    reviewed).

Kept deliberately free of any Streamlit import -- this is pure data
logic, callable from a page, a script, or a test, per the spec's
"keep database operations separate from UI code" instruction.
"""

import hashlib
import io
from datetime import datetime

import pandas as pd

from models import RapsodoImport, RapsodoPitch, PitchType
from pitch_type_config import normalize_pitch_type
from rapsodo_conventions import spin_clock_to_degrees, strike_zone_inches_to_plate_feet


class RapsodoImportError(Exception):
    """Base class for anything that stops an import before it completes."""


class DuplicateImportError(RapsodoImportError):
    """This exact file has already been imported for this player."""


class RapsodoValidationError(RapsodoImportError):
    """The file isn't a usable Rapsodo export -- missing required columns,
    unreadable structure, or no usable pitch rows at all."""


class RapsodoImportNotFoundError(RapsodoImportError):
    """No RapsodoImport exists with the given import_id (already deleted,
    or a bad id -- e.g. a stale button click after someone else deleted
    the same import a moment earlier)."""


# Normalized (lowercase, alnum-only) column-header text -> RapsodoPitch raw
# field name. Multiple keys can point at the same field to tolerate export
# naming variants (e.g. an older/different Rapsodo report using
# underscored names, or omitting a parenthetical unit suffix). Built from
# the real export reviewed (Rapsodo "Pitching" report) plus the naming
# variants already guessed at in the older pages/import_rapsodo.py, so
# both known naming styles are covered.
_HEADER_ALIASES = {
    "date": "pitch_date",  # special-cased: parsed to a datetime, not stored as text
    "pitchid": "rapsodo_pitch_id_raw",
    "pitchtype": "raw_pitch_type",
    "isstrike": "is_strike",
    "strikezoneside": "strike_zone_side",
    "strikezoneheight": "strike_zone_height",
    "velocity": "velocity",
    "totalspin": "total_spin",
    "spinrate": "total_spin",  # older naming convention
    "truespin": "true_spin",
    "truespinrelease": "true_spin",
    "spinefficiency": "spin_efficiency",
    "spinefficiencyrelease": "spin_efficiency",
    "spindirection": "spin_direction_clock",
    "spinaxis": "spin_direction_clock",  # older naming convention
    "spinconfidence": "spin_confidence",
    "vbtrajectory": "vb_trajectory",
    "hbtrajectory": "hb_trajectory",
    "sswvb": "ssw_vb",
    "sswhb": "ssw_hb",
    "vbspin": "vb_spin",
    "inducedverticalbreak": "vb_spin",  # older naming convention
    "hbspin": "hb_spin",
    "horizontalbreak": "hb_spin",  # older naming convention
    "horizontalangle": "horizontal_angle",
    "releaseangle": "release_angle",
    "releaseheight": "release_height",
    "releaseside": "release_side",
    "gyrodegree": "gyro_degree",
    "gyrodegreedeg": "gyro_degree",
    "uniqueid": "rapsodo_unique_id",
    "deviceserialnumber": "device_serial_number",
    "horizontalapproachangle": "horizontal_approach_angle",
    "verticalapproachangle": "vertical_approach_angle",
    "sessionname": "rapsodo_session_name",
    "intenttype": "intent_type",
    "releaseextension": "release_extension",
    "releaseextensionft": "release_extension",
    # NOTE: deliberately NOT aliasing "Plate Height"/"Plate Side" (feet,
    # already plate-centered) onto strike_zone_side/height (inches,
    # zone-relative) -- those are different units/references. If a
    # Rapsodo export variant with true feet-based plate coordinates
    # shows up, it needs its own dedicated columns, not a silent reuse
    # of the strike-zone fields. Until then, those columns (if present)
    # fall through to raw_extra, unmapped.
}

# Columns intentionally excluded from raw_extra even though they're not
# mapped to a dedicated field -- "No" is the file's own row-order column,
# which is NOT reliable as chronological order (see module docstring), so
# it's kept for reference in raw_extra rather than given its own column.
_NORMALIZED_ROW_NUMBER_KEY = "no"

REQUIRED_RAW_FIELDS = {"pitch_date", "velocity"}


def _normalize_header(col_name: str) -> str:
    return "".join(ch for ch in str(col_name).lower() if ch.isalnum())


def compute_file_hash(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def read_csv_bytes(file_bytes: bytes) -> pd.DataFrame:
    """Parse the uploaded bytes as a Rapsodo CSV export. Handles the
    metadata-rows-before-the-header case (the real export reviewed opens
    with "Player ID:"/"Player Name:" lines before the real header row) --
    logic ported unchanged from the proven fallback already in
    pages/import_rapsodo.py. Public (not underscore-prefixed) since the
    upload page also calls this directly to show a validation preview
    before the user commits to an import."""
    try:
        df = pd.read_csv(io.BytesIO(file_bytes), encoding="utf-8-sig")
    except pd.errors.ParserError:
        raw_text = file_bytes.decode("utf-8-sig", errors="replace")
        raw_lines = raw_text.splitlines()
        known_markers = ["Player_Name", "Pitch_Type", "Date", "Velocity", "Spin Rate", "Pitch Type"]
        header_row_idx = next(
            (i for i, line in enumerate(raw_lines) if sum(1 for marker in known_markers if marker in line) >= 2),
            None,
        )
        if header_row_idx is None:
            raise RapsodoValidationError(
                "This file couldn't be read as a Rapsodo export -- the parser hit an inconsistent number of "
                "columns per row, and no line in the file looks like a normal Rapsodo header row (Date, "
                "Velocity, Pitch Type, etc. together on one line)."
            )
        try:
            df = pd.read_csv(io.BytesIO(file_bytes), encoding="utf-8-sig", skiprows=header_row_idx)
        except pd.errors.ParserError as e:
            raise RapsodoValidationError(
                f"Still couldn't parse this file after skipping what looked like {header_row_idx} metadata "
                f"row(s) above the header. Underlying error: {e}"
            )
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _build_header_map(columns):
    """Returns (field_to_column, unmapped_columns):
    field_to_column: RapsodoPitch raw field name -> actual df column name.
    unmapped_columns: df columns with no recognized alias -- these go
    into raw_extra per pitch, never discarded."""
    field_to_column = {}
    unmapped_columns = []
    for col in columns:
        normalized = _normalize_header(col)
        if normalized == _NORMALIZED_ROW_NUMBER_KEY:
            unmapped_columns.append(col)  # kept in raw_extra as "No", not discarded, but not chronological
            continue
        field = _HEADER_ALIASES.get(normalized)
        if field:
            field_to_column[field] = col
        else:
            unmapped_columns.append(col)
    return field_to_column, unmapped_columns


def _parse_float(val):
    try:
        if val is None or pd.isna(val):
            return None
        s = str(val).strip()
        if s in ("", "-"):
            return None
        return float(s)
    except (ValueError, TypeError):
        return None


def _parse_bool_yn(val):
    s = str(val).strip().upper() if val is not None and not pd.isna(val) else ""
    if s == "Y":
        return True
    if s == "N":
        return False
    return None


def _parse_str(val):
    if val is None or pd.isna(val):
        return None
    s = str(val).strip()
    return s if s not in ("", "-") else None


def _parse_pitch_date(val):
    """Rapsodo's real "Date" format: 'Sat Aug 08 2026 6:03:29 PM'."""
    try:
        return datetime.strptime(str(val).strip(), "%a %b %d %Y %I:%M:%S %p")
    except (ValueError, TypeError):
        return None


def validate_file_structure(df: pd.DataFrame):
    """Raises RapsodoValidationError if required raw fields (pitch date,
    velocity) can't be found in the header at all. Returns
    (field_to_column, unmapped_columns) on success. Called separately
    from import_rapsodo_file so a page can preview validation results
    before committing to an import."""
    field_to_column, unmapped_columns = _build_header_map(df.columns)
    missing = REQUIRED_RAW_FIELDS - set(field_to_column.keys())
    if missing:
        raise RapsodoValidationError(
            "This file is missing required column(s): "
            + ", ".join(sorted(missing))
            + ". GBO needs at least a Date and a Velocity column to import a Rapsodo export."
        )
    return field_to_column, unmapped_columns


def _get_or_create_pitch_type(db_session, canonical_name):
    if canonical_name is None:
        return None
    existing = db_session.query(PitchType).filter(PitchType.type_name == canonical_name).first()
    if existing:
        return existing
    # Shouldn't normally happen post-migration (all 8 canonical types are
    # seeded), but create rather than fail if it's somehow missing --
    # matches the get-or-create pattern already used elsewhere in GBO.
    new_type = PitchType(type_name=canonical_name, display_order=99)
    db_session.add(new_type)
    db_session.flush()
    return new_type


def import_rapsodo_file(
    db_session,
    *,
    file_bytes: bytes,
    original_filename: str,
    player_id: int,
    bullpen_id: int,
    uploaded_by_user_id: int,
):
    """Parses and imports one Rapsodo export file for one player into one
    existing BullpenSession. Raises DuplicateImportError or
    RapsodoValidationError without touching the database on failure.
    Commits on success and returns the created RapsodoImport (with
    .pitches populated).
    """
    file_hash = compute_file_hash(file_bytes)

    existing_import = (
        db_session.query(RapsodoImport)
        .filter(RapsodoImport.player_id == player_id, RapsodoImport.file_hash == file_hash)
        .first()
    )
    if existing_import:
        raise DuplicateImportError(
            f"This exact file was already imported for this player on "
            f"{existing_import.uploaded_at.strftime('%Y-%m-%d %H:%M')} "
            f"({existing_import.imported_row_count} pitch(es) imported at the time). "
            f"Re-uploading it again would create duplicate pitches -- if this is intentionally a "
            f"different/corrected file, re-save it or note the difference before uploading."
        )

    df = read_csv_bytes(file_bytes)
    field_to_column, unmapped_columns = validate_file_structure(df)

    # Second dedup layer: pitches already imported for this player under
    # a DIFFERENT file (e.g. a re-export with partial date overlap).
    already_imported_unique_ids = {
        row[0] for row in
        db_session.query(RapsodoPitch.rapsodo_unique_id)
        .filter(RapsodoPitch.player_id == player_id, RapsodoPitch.rapsodo_unique_id.isnot(None))
        .all()
    }

    parsed_rows = []
    rejected = []  # list of (row_number_in_file, reason) -- row_number is 1-based, matches a spreadsheet row a coach could look up

    for i, row in df.iterrows():
        file_row_num = i + 2  # +1 for 0-index, +1 for the header row itself, so this matches what a coach sees in Excel/Sheets

        raw = {}
        for field, col in field_to_column.items():
            val = row.get(col)
            if field == "pitch_date":
                raw[field] = _parse_pitch_date(val)
            elif field == "is_strike":
                raw[field] = _parse_bool_yn(val)
            elif field in ("rapsodo_pitch_id_raw", "raw_pitch_type", "spin_direction_clock",
                           "device_serial_number", "rapsodo_unique_id", "rapsodo_session_name", "intent_type"):
                raw[field] = _parse_str(val)
            else:
                raw[field] = _parse_float(val)

        if raw.get("pitch_date") is None:
            rejected.append((file_row_num, "unparseable or missing Date -- can't establish chronological order"))
            continue

        has_any_measurement = any(
            raw.get(k) is not None for k in ("velocity", "total_spin", "vb_spin", "hb_spin", "true_spin")
        )
        if not has_any_measurement:
            rejected.append((file_row_num, "no velocity, spin, or break data present -- nothing usable to import"))
            continue

        unique_id = raw.get("rapsodo_unique_id")
        if unique_id is not None and unique_id in already_imported_unique_ids:
            rejected.append((file_row_num, f"duplicate pitch (Unique ID {unique_id} already imported for this player from a previous file)"))
            continue

        raw_extra = {}
        for col in unmapped_columns:
            val = row.get(col)
            if val is not None and not (isinstance(val, float) and pd.isna(val)):
                s = str(val).strip()
                if s not in ("", "-"):
                    raw_extra[col] = s

        parsed_rows.append({"raw": raw, "raw_extra": raw_extra, "file_row_num": file_row_num})

    if not parsed_rows:
        reason_summary = "; ".join(f"row {n}: {r}" for n, r in rejected[:10])
        raise RapsodoValidationError(
            f"No usable pitches found in this file -- all {len(df)} row(s) were rejected. "
            f"First few reasons: {reason_summary}"
        )

    # Chronological order derived from the parsed Date, NOT the file's own
    # row order -- see module docstring.
    parsed_rows.sort(key=lambda r: r["raw"]["pitch_date"])

    import_record = RapsodoImport(
        player_id=player_id,
        bullpen_id=bullpen_id,
        original_filename=original_filename,
        file_hash=file_hash,
        uploaded_by_user_id=uploaded_by_user_id,
        row_count=len(df),
        imported_row_count=len(parsed_rows),
        rejected_row_count=len(rejected),
        status="success" if not rejected else "partial",
        error_summary="; ".join(f"Row {n}: {r}" for n, r in rejected) if rejected else None,
    )
    db_session.add(import_record)
    db_session.flush()  # assigns import_record.import_id

    try:
        pitch_type_cache = {}
        for pitch_number, entry in enumerate(parsed_rows, start=1):
            raw = entry["raw"]

            canonical_type_name = normalize_pitch_type(raw.get("raw_pitch_type"))
            if canonical_type_name is not None:
                if canonical_type_name not in pitch_type_cache:
                    pitch_type_cache[canonical_type_name] = _get_or_create_pitch_type(db_session, canonical_type_name)
                pitch_type = pitch_type_cache[canonical_type_name]
            else:
                pitch_type = None

            spin_axis_degrees = spin_clock_to_degrees(raw.get("spin_direction_clock"))
            plate_x_ft, plate_z_ft = strike_zone_inches_to_plate_feet(
                raw.get("strike_zone_side"), raw.get("strike_zone_height")
            )

            db_session.add(RapsodoPitch(
                bullpen_id=bullpen_id,
                player_id=player_id,
                import_id=import_record.import_id,
                pitch_number=pitch_number,
                rapsodo_pitch_id_raw=raw.get("rapsodo_pitch_id_raw"),
                rapsodo_unique_id=raw.get("rapsodo_unique_id"),
                pitch_date=raw.get("pitch_date"),
                raw_pitch_type=raw.get("raw_pitch_type"),
                is_strike=raw.get("is_strike"),
                strike_zone_side=raw.get("strike_zone_side"),
                strike_zone_height=raw.get("strike_zone_height"),
                velocity=raw.get("velocity"),
                total_spin=raw.get("total_spin"),
                true_spin=raw.get("true_spin"),
                spin_efficiency=raw.get("spin_efficiency"),
                spin_direction_clock=raw.get("spin_direction_clock"),
                spin_confidence=raw.get("spin_confidence"),
                vb_trajectory=raw.get("vb_trajectory"),
                hb_trajectory=raw.get("hb_trajectory"),
                ssw_vb=raw.get("ssw_vb"),
                ssw_hb=raw.get("ssw_hb"),
                vb_spin=raw.get("vb_spin"),
                hb_spin=raw.get("hb_spin"),
                horizontal_angle=raw.get("horizontal_angle"),
                release_angle=raw.get("release_angle"),
                release_height=raw.get("release_height"),
                release_side=raw.get("release_side"),
                gyro_degree=raw.get("gyro_degree"),
                device_serial_number=raw.get("device_serial_number"),
                horizontal_approach_angle=raw.get("horizontal_approach_angle"),
                vertical_approach_angle=raw.get("vertical_approach_angle"),
                rapsodo_session_name=raw.get("rapsodo_session_name"),
                intent_type=raw.get("intent_type"),
                release_extension=raw.get("release_extension"),
                raw_extra=entry["raw_extra"] or None,
                pitch_type_id=pitch_type.pitch_type_id if pitch_type else None,
                spin_axis_degrees=spin_axis_degrees,
                plate_x_ft=plate_x_ft,
                plate_z_ft=plate_z_ft,
            ))
        db_session.commit()
    except Exception:
        db_session.rollback()
        raise RapsodoImportError(
            "Import failed partway through writing pitches to the database -- nothing from this file was saved. "
            "This is usually a data problem in a specific row rather than the file itself; check for unexpected "
            "characters or values before re-uploading."
        )

    return import_record


def delete_rapsodo_import(db_session, import_id: int) -> dict:
    """Deletes one previously-imported Rapsodo file: every RapsodoPitch row
    it created, plus the RapsodoImport audit record itself. This is what
    lets a coach recover from uploading the wrong file (or a bad export)
    without leaving orphaned pitches behind -- see the DuplicateImportError
    message above, which points a coach here when a re-upload is a
    correction rather than a mistake.

    RapsodoPitch rows are deleted explicitly rather than relying on ORM
    cascade -- RapsodoImport.pitches has no cascade="delete-orphan"
    configured (only BullpenSession -> RapsodoPitch has that, for deleting
    a whole session at once), so an unqualified db_session.delete() on the
    RapsodoImport row alone would violate RapsodoPitch.import_id's NOT
    NULL foreign key instead of cleaning up.

    Deliberately does NOT touch the parent BullpenSession -- a session can
    hold pitches from more than one import, or a mix of Rapsodo and
    manually-tracked BullpenPitch rows, so only this one import's pitches
    are removed. If this was the session's only data, the session is left
    behind as an empty shell rather than auto-deleted; that's a
    deliberate choice (the session itself may carry its own notes/date a
    coach still wants), not an oversight.

    Raises RapsodoImportNotFoundError if the import doesn't exist (already
    deleted, or a bad id). Raises RapsodoImportError if the delete itself
    fails partway through, leaving nothing changed. Commits on success and
    returns a small summary dict (player_id, bullpen_id,
    original_filename, uploaded_at, deleted_pitch_count) so the caller can
    build a confirmation message without a second query.
    """
    import_record = db_session.query(RapsodoImport).filter(RapsodoImport.import_id == import_id).first()
    if import_record is None:
        raise RapsodoImportNotFoundError(
            f"No Rapsodo import found with id {import_id} -- it may have already been deleted."
        )

    summary = {
        "player_id": import_record.player_id,
        "bullpen_id": import_record.bullpen_id,
        "original_filename": import_record.original_filename,
        "uploaded_at": import_record.uploaded_at,
    }

    try:
        deleted_pitch_count = (
            db_session.query(RapsodoPitch)
            .filter(RapsodoPitch.import_id == import_id)
            .delete(synchronize_session=False)
        )
        db_session.delete(import_record)
        db_session.commit()
    except Exception:
        db_session.rollback()
        raise RapsodoImportError(
            f"Couldn't delete this import (id {import_id}) -- nothing was removed. Try again, and if it keeps "
            f"failing check for other data (e.g. a report) that might still reference these pitches."
        )

    summary["deleted_pitch_count"] = deleted_pitch_count
    return summary
