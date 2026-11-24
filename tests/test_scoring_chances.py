"""Runs per Scoring Chance (analytics/scoring_chances.py): inherited runner
charged to the pitcher who put him on, wild-pitch advance, solo HR chance,
hitter RISP PA, outside-game side split."""
from types import SimpleNamespace as N
from analytics.scoring_chances import compute



def P(seq, inn, our_bat, bb, ba, outs_after, ends, outcome, runs, pid, opp_our=None, rv=0.0, intra=False):
    return N(game_pitch_id=1000+seq, game_id=1, pitch_sequence=seq, inning=inn, is_our_team_batting=our_bat,
             batting_squad=None, bases_before=bb, bases_after=ba, outs_after=outs_after, ends_plate_appearance=ends,
             ab_outcome=outcome, runs_scored_on_play=runs, run_value=rv, our_player_id=pid,
             opponent_our_player_id=opp_our, opponent_player_id=None, is_intrasquad=intra)
A, B = 1, 2  # our pitchers
H1 = 50       # our hitter
ps = [
 # top 1 (opponent bats, outside game): A walks leadoff, A gives up double -> runners 2nd & 3rd
 P(1,1,False,"000","100",0,True,"BB",0,A),
 P(2,1,False,"100","011",0,True,"2B",0,A),
 # B relieves: single scores both (both A's runners) -> runner on 1st (B's)
 P(3,1,False,"011","100",0,True,"1B",2,B),
 # wild pitch moves B's runner to 2nd (runner event after seq 3), then K, K, groundout
 P(4,1,False,"010","010",1,True,"K",0,B),
 P(5,1,False,"010","010",2,True,"K",0,B),
 P(6,1,False,"010","000",3,True,"Groundout",0,B),
 # bottom 1: our hitter H1 batting with RISP, single scores 1
 P(7,1,True,"000","100",0,True,"1B",0,99),
 P(8,1,True,"100","010",0,True,"SB?",0,99),   # placeholder, not a result of note
 P(9,1,True,"010","100",0,True,"1B",1,H1,rv=0.8),
 P(10,1,True,"100","000",3,True,"Double Play",0,H1,rv=-0.6),
 # top 2: A? no -- B again: HR solo, three outs, no RISP
 P(11,2,False,"000","000",0,True,"HR",1,B),
 P(12,2,False,"000","000",3,True,"Groundout",0,B),
]
ps[7].ab_outcome = "1B"
ev = [N(runner_event_id=1, game_id=1, pitch_sequence_after=3, is_our_team_batting=False, batting_squad=None,
        event_type="Wild Pitch", from_base=1, to_base=2, is_out=False, our_player_id=None, opponent_player_id=None,
        created_at=0)]


def test_scoring_chances_synthetic_game():
    r = compute({1: ps}, {1: ev}, {})
    st = r["team"]["staff"]    ; assert st["half_innings"]==2 and st["chances"]==2 and st["runs"]==3, st
    assert r["pitchers"][A]["runs"]==2 and r["pitchers"][A]["chances"]==1, "A charged both inherited runs"
    assert r["pitchers"][B]["runs"]==1 and r["pitchers"][B]["chances"]==2 and r["pitchers"][B]["escaped"]==1, r["pitchers"][B]
    assert r["hitters"][H1]["risp_pa"]==1 and r["hitters"][H1]["risp_runs"]==1
    assert r["team"]["offense"]["runs"]==1 and r["team"]["offense"]["chances"]==1
