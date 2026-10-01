"""
GBO -- Pitch type switching for the Fastball Shape Check (Oct 2026).

apply_switches: relabel the chosen Rapsodo readings (and their matched
game pitches) to the suggested type, logging each one in
PitchTypeChange. undo_switches: put them back exactly as they were.
Pure data logic, no Shiny import -- callable from a page or a script.
One commit per call (all-or-nothing).
"""

from datetime import datetime

from models import GamePitch, PitchType, PitchTypeChange, RapsodoPitch


class PitchTypeSwitchError(Exception):
    pass


def apply_switches(db, switches, user_id=None, source="shape_check"):
    """switches: list of (rapsodo_pitch_id, to_type_name, reason).
    Returns the number of pitches switched. A pitch already of the
    target type is skipped (not logged)."""
    names = {name for _rid, name, _r in switches}
    types = {t.type_name: t for t in db.query(PitchType).filter(PitchType.type_name.in_(names)).all()}
    missing = names - set(types)
    if missing:
        raise PitchTypeSwitchError(f"Unknown pitch type(s): {', '.join(sorted(missing))}")
    try:
        n = 0
        for rid, name, reason in switches:
            rp = db.query(RapsodoPitch).filter(RapsodoPitch.rapsodo_pitch_id == rid).first()
            if rp is None:
                continue
            to_id = types[name].pitch_type_id
            gp = db.query(GamePitch).filter(GamePitch.game_pitch_id == rp.game_pitch_id).first() if rp.game_pitch_id else None
            if rp.pitch_type_id == to_id and (gp is None or gp.pitch_type_id == to_id):
                continue
            db.add(PitchTypeChange(
                rapsodo_pitch_id=rp.rapsodo_pitch_id,
                game_pitch_id=gp.game_pitch_id if gp else None,
                player_id=rp.player_id,
                from_rapsodo_pitch_type_id=rp.pitch_type_id,
                from_game_pitch_type_id=gp.pitch_type_id if gp else None,
                to_pitch_type_id=to_id,
                source=source, reason=reason,
                changed_by_user_id=user_id,
            ))
            rp.pitch_type_id = to_id
            if gp is not None:
                gp.pitch_type_id = to_id
            n += 1
        db.commit()
        return n
    except Exception:
        db.rollback()
        raise


def undo_switches(db, change_ids):
    """Restores each change's previous Rapsodo/game pitch types (only if
    the pitch is still on the type the switch set -- a later manual edit
    wins) and stamps undone_at. Returns the number undone."""
    try:
        n = 0
        for ch in db.query(PitchTypeChange).filter(
            PitchTypeChange.pitch_type_change_id.in_(list(change_ids)),
            PitchTypeChange.undone_at.is_(None),
        ).all():
            if ch.rapsodo_pitch_id is not None:
                rp = db.query(RapsodoPitch).filter(RapsodoPitch.rapsodo_pitch_id == ch.rapsodo_pitch_id).first()
                if rp is not None and rp.pitch_type_id == ch.to_pitch_type_id:
                    rp.pitch_type_id = ch.from_rapsodo_pitch_type_id
            if ch.game_pitch_id is not None:
                gp = db.query(GamePitch).filter(GamePitch.game_pitch_id == ch.game_pitch_id).first()
                if gp is not None and gp.pitch_type_id == ch.to_pitch_type_id:
                    gp.pitch_type_id = ch.from_game_pitch_type_id
            ch.undone_at = datetime.utcnow()
            n += 1
        db.commit()
        return n
    except Exception:
        db.rollback()
        raise
