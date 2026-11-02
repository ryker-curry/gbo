"""
GBO -- SmartPark (WIN Reality / Yakkertech) column mapping.

THE ONE FILE TO EDIT WHEN THE FIRST REAL SMARTPARK EXPORT ARRIVES.

Built Oct 2026, before SmartPark was installed at PSU, so nothing here has
been checked against a real SmartPark file yet. Yakkertech game files have
used TrackMan-style column names (PitchNo, Inning, Top/Bottom, PitchCall,
RelSpeed, InducedVertBreak, PlateLocSide, ...), so that's the starting
guess. When a real file shows up:

  1. Upload it on Import SmartPark -- the "Column check" box lists every
     column it couldn't place and every required one it couldn't find.
  2. Add the file's header text to COLUMN_ALIASES below (headers are
     matched lowercase with spaces/punctuation stripped, so "Rel Speed",
     "rel_speed" and "RelSpeed" are all the same key "relspeed").
  3. If the file's words for a pitch result / play result / hit type
     differ, add them to the *_MAP dictionaries.
  4. Check PLATE_SIDE_SIGN against one pitch you know (see its comment).

Nothing else in services/smartpark_import.py should need to change.
"""

# normalized header text -> SmartParkPitch field name
COLUMN_ALIASES = {
    # identity / game state
    "pitchno": "pitch_no", "pitchnumber": "pitch_no", "pitchofgame": "pitch_no",
    "pitchuid": "source_pitch_uid", "pitchid": "source_pitch_uid", "uid": "source_pitch_uid",
    "gameid": "source_game_uid", "gameuid": "source_game_uid",
    "date": "date", "gamedate": "date",
    "time": "time", "pitchtime": "time", "utctime": "time",
    "inning": "inning",
    "topbottom": "top_bottom", "half": "top_bottom", "inninghalf": "top_bottom", "halfinning": "top_bottom",
    "paofinning": "pa_of_inning",
    "pitchofpa": "pitch_of_pa", "papitchnumber": "pitch_of_pa",
    "outs": "outs", "balls": "balls", "strikes": "strikes",
    "pitcher": "pitcher_name", "pitchername": "pitcher_name",
    "pitcherid": "pitcher_source_id",
    "pitcherthrows": "pitcher_throws", "throws": "pitcher_throws", "pitcherhand": "pitcher_throws",
    "pitcherteam": "pitcher_team",
    "batter": "batter_name", "battername": "batter_name", "hitter": "batter_name",
    "batterid": "batter_source_id", "hitterid": "batter_source_id",
    "batterside": "batter_side", "bats": "batter_side", "batterhand": "batter_side",
    "batterteam": "batter_team",
    "taggedpitchtype": "tagged_pitch_type", "pitchtype": "tagged_pitch_type",
    "autopitchtype": "auto_pitch_type",
    "pitchcall": "pitch_call", "pitchresult": "pitch_call",
    "korbb": "kor_bb",
    "taggedhittype": "tagged_hit_type", "hittype": "tagged_hit_type", "battedballtype": "tagged_hit_type",
    "playresult": "play_result",
    "outsonplay": "outs_on_play",
    "runsscored": "runs_scored",
    # pitch tracking
    "relspeed": "rel_speed", "velocity": "rel_speed", "pitchspeed": "rel_speed", "velo": "rel_speed",
    "spinrate": "spin_rate", "totalspin": "spin_rate",
    "spinaxis": "spin_axis",
    "spinefficiency": "spin_efficiency",
    "tilt": "tilt",
    "relheight": "rel_height", "releaseheight": "rel_height",
    "relside": "rel_side", "releaseside": "rel_side",
    "extension": "extension", "releaseextension": "extension",
    "vertrelangle": "vert_rel_angle",
    "horzrelangle": "horz_rel_angle",
    "inducedvertbreak": "induced_vert_break", "ivb": "induced_vert_break",
    "horzbreak": "horz_break", "horizontalbreak": "horz_break", "hb": "horz_break",
    "vertbreak": "vert_break",
    "platelocheight": "plate_loc_height", "plateheight": "plate_loc_height",
    "platelocside": "plate_loc_side", "plateside": "plate_loc_side",
    "zonespeed": "zone_speed",
    "vertapprangle": "vert_appr_angle", "vaa": "vert_appr_angle",
    "horzapprangle": "horz_appr_angle", "haa": "horz_appr_angle",
    # batted ball / swing
    "exitspeed": "exit_speed", "exitvelo": "exit_speed", "exitvelocity": "exit_speed", "ev": "exit_speed",
    "angle": "launch_angle", "launchangle": "launch_angle", "la": "launch_angle",
    "direction": "direction", "sprayangle": "direction",
    "distance": "distance",
    "hitspinrate": "hit_spin_rate",
    "hangtime": "hang_time",
    "batspeed": "bat_speed",
}

# Fields the import can't build a game without.
REQUIRED_FIELDS = ("inning", "top_bottom", "balls", "strikes", "outs", "pitch_call", "pitcher_name", "batter_name")

INT_FIELDS = {"pitch_no", "inning", "pa_of_inning", "pitch_of_pa", "outs", "balls", "strikes", "outs_on_play", "runs_scored"}
FLOAT_FIELDS = {
    "rel_speed", "spin_rate", "spin_axis", "spin_efficiency", "rel_height", "rel_side", "extension",
    "vert_rel_angle", "horz_rel_angle", "induced_vert_break", "horz_break", "vert_break",
    "plate_loc_height", "plate_loc_side", "zone_speed", "vert_appr_angle", "horz_appr_angle",
    "exit_speed", "launch_angle", "direction", "distance", "hit_spin_rate", "hang_time", "bat_speed",
}

# Words that mean "no value" in a cell.
BLANK_VALUES = {"", "-", "--", "na", "n/a", "nan", "none", "null", "undefined"}

# Top/Bottom cell -> True if top of the inning.
TOP_VALUES = {"top", "t", "1", "away"}
BOTTOM_VALUES = {"bottom", "bot", "b", "2", "home"}

# PitchCall (normalized: lowercase, letters/digits only) -> GamePitch.pitch_outcome
PITCH_CALL_MAP = {
    "ballcalled": "Ball", "ball": "Ball", "ballindirt": "Ball", "ballintentional": "Ball",
    "intentionalball": "Ball", "pitchout": "Ball", "automaticball": "Ball",
    "strikecalled": "Called Strike", "calledstrike": "Called Strike", "automaticstrike": "Called Strike",
    "strikeswinging": "Swing and Miss", "swingingstrike": "Swing and Miss", "whiff": "Swing and Miss",
    # A caught foul tip counts like a swinging strike (always adds a strike, can be strike 3).
    "foultip": "Swing and Miss",
    "foulball": "Foul", "foul": "Foul", "foulballnotfieldable": "Foul", "foulballfieldable": "Foul",
    "inplay": "In Play", "inplayout": "In Play", "inplaynoout": "In Play", "inplayrun": "In Play",
    "hitbypitch": "HBP", "hbp": "HBP",
}
INTENTIONAL_BALL_CALLS = {"ballintentional", "intentionalball"}

# KorBB -> strikeout / walk
STRIKEOUT_VALUES = {"strikeout", "k", "so"}
WALK_VALUES = {"walk", "bb", "baseonballs"}

# PlayResult -> GamePitch.ab_outcome ("Out" and "Sacrifice" are refined by hit type below)
PLAY_RESULT_MAP = {
    "single": "1B", "1b": "1B",
    "double": "2B", "2b": "2B",
    "triple": "3B", "3b": "3B",
    "homerun": "HR", "hr": "HR",
    "error": "E", "e": "E",
    "fielderschoice": "FC", "fc": "FC",
    "out": "OUT", "sacrifice": "SAC",
    "doubleplay": "Double Play", "tripleplay": "Double Play",
    "sacfly": "Sac Fly", "sacrificefly": "Sac Fly",
    "sacbunt": "Sac Bunt", "sacrificebunt": "Sac Bunt",
    "groundout": "Groundout", "flyout": "Flyout", "lineout": "Lineout", "popout": "Flyout",
}

# TaggedHitType -> GamePitch.batted_ball_type
HIT_TYPE_MAP = {
    "groundball": "Ground Ball", "gb": "Ground Ball",
    "linedrive": "Line Drive", "ld": "Line Drive",
    "flyball": "Fly Ball", "fb": "Fly Ball",
    "popup": "Pop Up", "pu": "Pop Up",
    "bunt": "Ground Ball",
}
# Generic "Out" -> which GBO out, by hit type
OUT_BY_HIT_TYPE = {"Ground Ball": "Groundout", "Line Drive": "Lineout", "Fly Ball": "Flyout", "Pop Up": "Flyout"}

# Hand cells -> 'R' / 'L' (Switch stays None: a switch hitter's actual side
# for the at-bat should be in BatterSide; if it isn't, GBO leaves it blank).
HAND_MAP = {"right": "R", "r": "R", "rhp": "R", "rhh": "R", "left": "L", "l": "L", "lhp": "L", "lhh": "L"}

# Horizontal plate location sign. GBO (strike_zone.py): plate_x positive =
# first-base side, catcher's view. TrackMan's PlateLocSide uses the same
# catcher's-view convention, so +1. CHECK ON THE FIRST REAL FILE: find a
# pitch you know was away to a right-handed hitter -- GBO should show it on
# the first-base side (right of the plate, catcher's view). If it's mirrored,
# change this to -1.
PLATE_SIDE_SIGN = 1

# Spray angle sign for batted_ball_x (field_location.py: + = right field).
# TrackMan's Direction is + toward right field, so +1.
DIRECTION_SIGN = 1
