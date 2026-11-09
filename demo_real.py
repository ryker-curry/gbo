"""
GBO -- guest demo built from the REAL team, anonymized (Nov 2026, Ryker:
"change the guest demo to use our players data and not fake names, instead
use player 1, 2, 3. Also include hitting data we have").

populate_from_live(dst_session) copies every GBO table from Supabase into
the guest demo's private in-memory SQLite master (see demo_db.py) and
scrubs anything that identifies a person on the way in:

  - Players become "Player 1", "Player 2", ... numbered in a shuffled
    (seeded) order, so the numbers are stable between restarts but don't
    follow the alphabet or the roster. Jersey numbers, hometowns, previous
    schools, photos, emails and birthdates are removed. Height/weight stay
    (arm angle and body comp need them).
  - Staff users become "Staff 1", "Staff 2", ... with fake emails and no
    Supabase auth id. Three demo logins are added on top (coach, pitcher,
    hitter) for the guest's View As buttons.
  - Opponent teams keep their real names; opponent players become
    "Opponent 1", "Opponent 2", ... within each team, no jersey numbers.
  - Every text and JSON value is scrubbed for real player, staff and
    opponent names: any capitalized first or last name is replaced with
    that person's label (names typed in all lowercase are not caught).
  - Video/photo URLs are dropped (faces can't be anonymized, and the links
    point at private storage), and tables that only hold secrets or
    outgoing-mail logs are skipped: WHOOP connect links, app error logs,
    report-send logs, game video clips and per-pitch video links. WHOOP
    connections keep their status but lose the WHOOP account name/id.
  - Previous-college stat lines keep the numbers but the school name
    becomes "Previous school" unless it's Pittsburg State.

Per Ryker's call, everything else is copied as-is (recovery, availability,
AT appointments, notes), with names scrubbed. If Supabase can't be reached,
demo_db.py falls back to the made-up team.
"""

import random
import re

from sqlalchemy import JSON, String, Text, select

import models as m

SHUFFLE_SEED = 20261107

SKIP_TABLES = {
    "whoop_connect_links", "app_errors", "weekly_report_sends", "team_report_sends",
    "game_video_clips", "bullpen_pitch_videos",
}
URL_COLUMNS_SUFFIX = ("url",)

# Nov 2026 fix: GBO's own built-in labels are never names. An opposing
# player surnamed "Peak" turned every "... Peak ..." test name into
# "Opponent N", which emptied 6 of the 9 athlete-archetype radar axes in
# the demo. These lookup tables are copied as-is, and every word in them
# (plus exercise / routine names) is kept out of the name scrub, so a test
# name inside a note survives too.
REFERENCE_TABLES = {
    "assessment_categories", "assessment_test_types", "body_comp_targets", "bullpen_types",
    "hitter_session_types", "idp_statuses", "opponent_teams", "organizations", "pitch_types",
    "player_classes", "player_statuses", "positions", "roles", "run_expectancy", "seasons",
    "session_types", "team_event_types", "teams", "research_projects",
}
VOCAB_COLUMNS = (("assessment_test_types", "test_name"), ("assessment_categories", "category_name"),
                 ("pitch_types", "type_name"), ("bullpen_types", "type_name"), ("session_types", "type_name"),
                 ("hitter_session_types", "type_name"), ("positions", "position_name"),
                 ("routine_exercises", "exercise_name"), ("training_routines", "routine_name"))


def _label_maps(src):
    """Build id -> anonymized label maps and the name -> label scrub list."""
    players = src.execute(select(m.Player.__table__)).mappings().all()
    users = src.execute(select(m.User.__table__)).mappings().all()
    opps = src.execute(select(m.OpponentPlayer.__table__)).mappings().all()

    order = sorted(p["player_id"] for p in players)
    random.Random(SHUFFLE_SEED).shuffle(order)
    player_num = {pid: i + 1 for i, pid in enumerate(order)}

    staff_ids = sorted(u["user_id"] for u in users if not u["player_id"])
    staff_num = {uid: i + 1 for i, uid in enumerate(staff_ids)}

    opp_num = {}
    by_team = {}
    for o in sorted(opps, key=lambda r: r["opponent_player_id"]):
        by_team.setdefault(o["team_id"], []).append(o["opponent_player_id"])
    for team_ids in by_team.values():
        for i, oid in enumerate(team_ids):
            opp_num[oid] = i + 1

    pairs = []   # (kind, text, label): kind "full" = case-insensitive phrase, "word" = exact capitalized word

    def add_person(first, last, label):
        first = (first or "").strip()
        last = (last or "").strip()
        if first and last:
            pairs.append(("full", f"{first} {last}", label))
            pairs.append(("full", f"{last}, {first}", label))
        if len(last) >= 3:
            pairs.append(("word", last, label))
        if len(first) >= 3:
            pairs.append(("word", first, label))

    for p in players:
        add_person(p["first_name"], p["last_name"], f"Player {player_num[p['player_id']]}")
    for u in users:
        if u["player_id"] in player_num:
            add_person(u["first_name"], u["last_name"], f"Player {player_num[u['player_id']]}")
        elif u["user_id"] in staff_num:
            add_person(u["first_name"], u["last_name"], f"Staff {staff_num[u['user_id']]}")
    for o in opps:
        parts = (o["player_name"] or "").strip().split()
        label = f"Opponent {opp_num[o['opponent_player_id']]}"
        if len(parts) >= 2:
            add_person(parts[0], " ".join(parts[1:]), label)
        elif parts:
            add_person("", parts[0], label)
    return player_num, staff_num, opp_num, pairs


_TOKEN = re.compile(r"\b[A-Z][A-Za-z'\-]*\b")
_DUP = re.compile(r"\b((?:Player|Staff|Opponent) \d+)(?:\s*,?\s+\1\b)+")


def _vocab(src):
    """Capitalized words used in GBO's own labels -- never treated as names."""
    from sqlalchemy import text
    words = set()
    for tbl, col in VOCAB_COLUMNS:
        try:
            for (v,) in src.execute(text(f"SELECT {col} FROM {tbl}")):
                words |= set(_TOKEN.findall(v or ""))
        except Exception:
            src.rollback()
    return words


def _scrubber(pairs, keep=frozenset()):
    """Fast name scrub: every capitalized word is looked up in one dict of
    real first/last names (a single regex pass + dict lookups, so it stays
    quick across thousands of rows), then "Player 7 Player 7" (a first and
    last name side by side) collapses to "Player 7". Names typed all in
    lowercase are not caught."""
    word = {}
    for kind, text, label in pairs:
        if kind == "word" and text not in keep:
            word.setdefault(text, label)

    def scrub(value):
        if isinstance(value, str):
            if not any(c.isupper() for c in value):
                return value
            value = _TOKEN.sub(lambda mm: word.get(mm.group(0), mm.group(0)), value)
            return _DUP.sub(r"\1", value)
        if isinstance(value, list):
            return [scrub(v) for v in value]
        if isinstance(value, dict):
            return {scrub(k) if isinstance(k, str) else k: scrub(v) for k, v in value.items()}
        return value
    return scrub


def _row_transform(table, row, player_num, staff_num, opp_num, scrub):
    t = table.name
    r = dict(row)
    if t == "players":
        r.update(first_name="Player", last_name=str(player_num[r["player_id"]]), jersey_number=None,
                 hometown=None, previous_school=None, photo_url=None, date_of_birth=None, email=None)
    elif t == "users":
        if r["player_id"] in player_num:
            r.update(first_name="Player", last_name=str(player_num[r["player_id"]]))
        else:
            r.update(first_name="Staff", last_name=str(staff_num.get(r["user_id"], r["user_id"])))
        r.update(email=f"user{r['user_id']}@demo.gbo", auth_subject_id=None, photo_url=None)
    elif t == "opponent_players":
        r.update(player_name=f"Opponent {opp_num[r['opponent_player_id']]}", jersey_number=None)
    elif t == "whoop_connections":
        r.update(whoop_user_id=None, whoop_name=None, last_error=None)
    elif t == "college_season_stats":
        if "pittsburg" not in (r.get("school") or "").lower():
            # (player, side, year, school) is unique -- number repeats so two
            # prior schools in one year can't collide once both are renamed.
            key = (r.get("player_id"), r.get("side"), r.get("season_year"))
            seen = _row_transform.__dict__.setdefault("_prev_school_seen", {})
            seen[key] = seen.get(key, 0) + 1
            r["school"] = "Previous school" + (f" {seen[key]}" if seen[key] > 1 else "")
        r["source_url"] = None
    elif t == "rapsodo_history":
        # source_uid is part of a (player, source, source_uid) unique key and
        # held Rapsodo's per-pitch id, so keep it unique per row.
        r["source_uid"] = f"demo-{r['rapsodo_history_id']}"
    elif t == "smartpark_player_links":
        r["source_name"] = f"Player {player_num.get(r['player_id'], '?')}"
        r["source_key"] = f"demo:{r['link_id']}"
    elif t == "weekly_report_sends":
        r["email"] = None
    # URLs anywhere -> gone; text/JSON anywhere -> names scrubbed
    for col in table.columns:
        name = col.name
        if name not in r or r[name] is None:
            continue
        if name.endswith(URL_COLUMNS_SUFFIX):
            r[name] = None if col.nullable else ""
        elif isinstance(col.type, (String, Text, JSON)) and t not in ("players", "users", "opponent_players") and t not in REFERENCE_TABLES:
            r[name] = scrub(r[name])
    return r


def populate_from_live(dst):
    """Copy the live database into `dst` (a SQLAlchemy Session on the empty
    demo master), anonymized. Returns {table: rows copied}."""
    import database
    counts = {}
    skipped = {}
    _row_transform.__dict__.pop("_prev_school_seen", None)
    with database.engine.connect() as src:
        player_num, staff_num, opp_num, pairs = _label_maps(src)
        scrub = _scrubber(pairs, _vocab(src))
        dconn = dst.connection()
        for table in m.Base.metadata.sorted_tables:
            if table.name in SKIP_TABLES:
                continue
            try:
                rows = src.execute(select(table)).mappings().all()
            except Exception:
                src.rollback()
                continue           # table not migrated on the live DB yet
            if not rows:
                continue
            out = [_row_transform(table, r, player_num, staff_num, opp_num, scrub) for r in rows]
            copied = 0
            for i in range(0, len(out), 500):
                chunk = out[i:i + 500]
                try:
                    with dconn.begin_nested():
                        dconn.execute(table.insert(), chunk)
                    copied += len(chunk)
                except Exception:
                    # One bad row shouldn't cost the guest the whole real
                    # demo: retry the chunk row by row and skip only the
                    # rows SQLite refuses (noted in `skipped`).
                    for row in chunk:
                        try:
                            with dconn.begin_nested():
                                dconn.execute(table.insert(), [row])
                            copied += 1
                        except Exception as exc:
                            skipped.setdefault(table.name, [0, repr(exc)[:300]])[0] += 1
            counts[table.name] = copied
    dst.flush()
    _add_demo_logins(dst)
    dst.commit()
    if skipped:
        _log_skipped(skipped)
    return counts


def _log_skipped(skipped):
    """Save a one-line note to app_errors when some rows couldn't be copied
    (the demo still runs on everything else)."""
    try:
        import error_log
        msg = "; ".join(f"{t}: {n} rows skipped ({why})" for t, (n, why) in skipped.items())
        try:
            raise RuntimeError(f"Guest demo copy skipped rows -- {msg}")
        except RuntimeError as exc:
            import sys
            error_log.record(type(exc), exc, sys.exc_info()[2], output_name="guest_demo_real_copy_skipped")
    except Exception:
        pass


def _add_demo_logins(db):
    """Guest View As logins: coach (Administrator), the pitcher with the
    most charted game pitches, and the hitter with the most plate
    appearances. Emails match demo_db's constants."""
    from sqlalchemy import func
    import demo_db
    roles = {r.role_name: r.role_id for r in db.query(m.Role).all()}
    org_id = db.query(m.Organization.organization_id).order_by(m.Organization.organization_id).first()
    org_id = org_id[0] if org_id else None
    next_id = (db.query(func.max(m.User.user_id)).scalar() or 0) + 1

    top_pitcher = (db.query(m.GamePitch.our_player_id, func.count())
                   .filter(m.GamePitch.is_our_team_batting.is_(False))
                   .group_by(m.GamePitch.our_player_id).order_by(func.count().desc()).first())
    top_hitter = (db.query(m.GamePitch.our_player_id, func.count())
                  .filter(m.GamePitch.is_our_team_batting.is_(True), m.GamePitch.ends_plate_appearance.is_(True))
                  .group_by(m.GamePitch.our_player_id).order_by(func.count().desc()).first())
    if top_hitter is None:   # fall back to intrasquad hitters facing our pitchers
        top_hitter = (db.query(m.GamePitch.opponent_our_player_id, func.count())
                      .filter(m.GamePitch.opponent_our_player_id.isnot(None), m.GamePitch.ends_plate_appearance.is_(True))
                      .group_by(m.GamePitch.opponent_our_player_id).order_by(func.count().desc()).first())

    def add(email, first, last, role, player_id=None):
        nonlocal next_id
        db.add(m.User(user_id=next_id, organization_id=org_id, email=email, first_name=first, last_name=last,
                      role_id=roles[role], player_id=player_id, active=True))
        next_id += 1

    add(demo_db.DEMO_COACH_EMAIL, "Demo", "Coach", "Administrator")
    for email, row in ((demo_db.DEMO_PLAYER_EMAIL, top_pitcher), (demo_db.DEMO_HITTER_EMAIL, top_hitter)):
        if row is not None:
            p = db.get(m.Player, row[0])
            add(email, p.first_name, p.last_name, "Player", p.player_id)
    db.flush()
