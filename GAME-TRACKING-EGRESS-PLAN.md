# Game Tracking egress fix -- plan (Oct 27 2026)

BUILT Oct 27 2026 (uncommitted at time of writing), first real test: Ryker entering a game that night.
Off switch: set GBO_SHARED_TRACKING=0 on Posit Connect and restart -- back to the old behavior, no code change.

Pre-test (cloud, guest demo DB, reopened game, 6 pitches incl. an in-play out + Undo):
every display block identical with the switch on vs off; game_pitches SELECTs per
pitch logged 4-5 (on) vs 17-19 (off), 39 vs 138 total.

## The problem
While a game is being charted, ~24 parts of the Game Tracking page
(shiny_app/modules/game_tracking.py) each call `_load_tracking_context(db, game_id)`
on every refresh (every pitch logged, every runner event, every lineup change).
Each call pulls the game, EVERY pitch in it, all three squad lineups (with
players + substitutions) and the opponent lineup. So one logged pitch late in a
game re-downloads ~150 pitches about 24 times. This is now the largest single
source of Supabase egress (database egress counts against the 5 GB free quota).

Already done (commit 85d05a2): the game row no longer comes back as a
cartesian product (selectinload), and the delete panel counts instead of loading.

## The fix
Load the context ONCE per refresh and share it across the page's renders.

1. Add a per-browser-session memo inside `game_tracking_server`:
   key = (game_id, _refresh_tick(), PA tick), value = (session, ctx).
   The memo owns one read-only SQLAlchemy session, kept open until the key
   changes (then closed and replaced), so lazy relationships on the shared
   objects still work.
2. Change only the READ paths (`@render.ui` blocks) to use the memo:
   `ctx = _shared_context(game_id)` instead of opening a session + calling
   `_load_tracking_context`.
3. Leave every WRITE path (`@reactive.effect` handlers that save / edit / delete)
   exactly as is: own session, fresh load, commit, then `_bump_refresh()`.
   Bumping the tick changes the memo key, so the next renders see the new data.
4. Session cleanup: close the memo's session on `session.on_ended`.
5. Guest demo: the memo uses `get_session()` like everything else, so the demo
   database keeps working.

Step 0 before writing code: go through all 24 call sites and mark each one
read vs. write (some renders may mutate ctx objects -- those stay on their own
session).

## Test checklist (live, practice game)
- Log 20+ pitches: count, outs, bases, inning, batter all advance correctly.
- Strikeout, walk, HBP, ball in play with runners, double play.
- Runner event (stolen base / pickoff) and "End half-inning early".
- Pitching change; lineup substitution; squad switch in an intrasquad.
- Edit a past pitch and delete a pitch -- every panel updates right away.
- Undo last pitch.
- Two browsers open on the same game (charter + a coach viewing).
- Then check Supabase: pg_stat_statements calls for the
  `FROM game_pitches WHERE $1 = game_pitches.game_id` query should drop ~20x.

## Measuring
pg_stat_statements was reset Oct 27 2026 12:36 pm CT (after the round-1/round-2
egress fixes), so later numbers show only post-fix traffic.
