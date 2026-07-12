"""Unit tests for core.engine.MatchEngine: rally state machine, scoring,
rotation-on-side-out, deciding-set side switch, substitutions, libero
tracking, manual corrections, set/match progression and undo-by-replay."""
import pytest

from core.engine import MatchEngine, Phase
from core.events import (AttackEvent, DigEvent, LiberoSwapEvent,
                         ManualScoreEvent, RallyPointEvent, ReceptionEvent,
                         ServeEvent, ServeOverrideEvent, SetStartEvent,
                         SubstitutionEvent, TimeoutEvent)
from core.models import AWAY, HOME, MatchConfig, Player, Rating, Team, other
from core.rotation import rotate_clockwise

# --------------------------------------------------------------- fixtures


def make_teams():
    return {
        HOME: Team(name="Home", players=[Player(number=i + 1, name=f"H{i + 1}")
                                         for i in range(12)]),
        AWAY: Team(name="Away", players=[Player(number=i + 51, name=f"A{i + 1}")
                                         for i in range(12)]),
    }


@pytest.fixture
def teams():
    return make_teams()


@pytest.fixture
def engine(teams):
    return MatchEngine(MatchConfig(), teams)


def pid(engine, team_key, roster_index):
    return engine.teams[team_key].players[roster_index].id


def set_start_event(teams, set_number=1, serving=HOME, left=HOME,
                    with_liberos=True):
    """Starting lineup = roster players 0..5; libero = roster player 6."""
    lineups = {tk: [p.id for p in teams[tk].players[:6]] for tk in (HOME, AWAY)}
    liberos = {tk: ([teams[tk].players[6].id] if with_liberos else [])
               for tk in (HOME, AWAY)}
    return SetStartEvent(set_number=set_number, lineups=lineups,
                         liberos=liberos, serving_team=serving, left_team=left)


def start_set(engine, serving=HOME, left=HOME, with_liberos=True):
    return engine.append(set_start_event(
        engine.teams, set_number=engine.state.set_number + 1,
        serving=serving, left=left, with_liberos=with_liberos))


def serve(engine, rating=Rating.GOOD, team=None, player_id=None):
    team = team or engine.state.serving_team
    player_id = player_id or engine.state.team[team].lineup[0]
    return engine.append(ServeEvent(team=team, player_id=player_id,
                                    rating=rating))


def receive(engine, rating=Rating.GOOD, team=None):
    team = team or other(engine.state.serving_team)
    return engine.append(ReceptionEvent(
        team=team, player_id=engine.state.team[team].lineup[0], rating=rating))


def attack(engine, team, rating):
    return engine.append(AttackEvent(
        team=team, player_id=engine.state.team[team].lineup[1], rating=rating))


def dig(engine, team, rating):
    return engine.append(DigEvent(
        team=team, player_id=engine.state.team[team].lineup[4], rating=rating))


def score_points(engine, team, n):
    for _ in range(n):
        engine.append(RallyPointEvent(team=team))


def snapshot(engine):
    """Full comparable state picture (everything undo must restore)."""
    st = engine.state
    return {
        "phase": st.phase,
        "set_number": st.set_number,
        "scores": dict(st.scores),
        "set_scores": dict(st.set_scores),
        "serving_team": st.serving_team,
        "set_first_server": st.set_first_server,
        "left_team": st.left_team,
        "switched_mid_set": st.switched_mid_set,
        "attacking_team": st.attacking_team,
        "last_set_winner": st.last_set_winner,
        "teams": {tk: {
            "lineup": list(st.team[tk].lineup),
            "starting_lineup": list(st.team[tk].starting_lineup),
            "liberos": list(st.team[tk].liberos),
            "subs_used": st.team[tk].subs_used,
            "sub_pairs": list(st.team[tk].sub_pairs),
            "libero_replaced": dict(st.team[tk].libero_replaced),
            "timeouts": st.team[tk].timeouts,
        } for tk in (HOME, AWAY)},
    }


# --------------------------------------------------------------- set start

class TestSetStart:
    def test_initial_state_before_set(self, engine):
        assert engine.state.phase == Phase.BEFORE_SET
        assert engine.state.set_number == 0
        assert engine.state.scores == {HOME: 0, AWAY: 0}

    def test_set_start_initialises_state(self, engine):
        w = start_set(engine, serving=AWAY, left=AWAY)
        assert w == []
        st = engine.state
        assert st.phase == Phase.AWAIT_SERVE
        assert st.set_number == 1
        assert st.serving_team == AWAY
        assert st.set_first_server == AWAY
        assert st.left_team == AWAY
        assert st.scores == {HOME: 0, AWAY: 0}
        for tk in (HOME, AWAY):
            assert st.team[tk].lineup == [p.id for p in engine.teams[tk].players[:6]]
            assert st.team[tk].starting_lineup == st.team[tk].lineup
            assert st.team[tk].subs_used == 0

    def test_no_rotation_before_first_serve(self, engine):
        start_set(engine, serving=HOME)
        # P1 of the serving team's *entered* lineup serves first.
        assert engine.expected_server() == pid(engine, HOME, 0)

    def test_unexpected_set_number_warns(self, engine):
        w = engine.append(set_start_event(engine.teams, set_number=3))
        assert any("unexpected set number" in x for x in w)

    def test_set_start_mid_set_warns(self, engine):
        start_set(engine)
        w = engine.append(set_start_event(engine.teams, set_number=2))
        assert any("not finished" in x for x in w)

    def test_short_lineup_warns(self, engine, teams):
        lineups = {tk: [p.id for p in teams[tk].players[:5]] for tk in (HOME, AWAY)}
        w = engine.append(SetStartEvent(set_number=1, lineups=lineups,
                                        liberos={HOME: [], AWAY: []},
                                        serving_team=HOME, left_team=HOME))
        assert any("6 distinct players" in x for x in w)

    def test_libero_in_starting_lineup_warns(self, engine, teams):
        lineups = {tk: [p.id for p in teams[tk].players[:6]] for tk in (HOME, AWAY)}
        liberos = {HOME: [lineups[HOME][5]], AWAY: []}
        w = engine.append(SetStartEvent(set_number=1, lineups=lineups,
                                        liberos=liberos,
                                        serving_team=HOME, left_team=HOME))
        assert any("starting lineup" in x for x in w)


# ------------------------------------------------------------ serve phase

class TestServe:
    def test_ace_point_same_server_no_rotation(self, engine):
        start_set(engine, serving=HOME)
        before = list(engine.state.team[HOME].lineup)
        w = serve(engine, Rating.PERFECT)
        assert w == []
        assert engine.state.scores == {HOME: 1, AWAY: 0}
        assert engine.state.serving_team == HOME
        assert engine.state.team[HOME].lineup == before      # no rotation
        assert engine.state.phase == Phase.AWAIT_SERVE
        assert engine.expected_server() == before[0]          # same server

    def test_service_fault_point_and_side_out_rotation(self, engine):
        start_set(engine, serving=HOME)
        home_before = list(engine.state.team[HOME].lineup)
        away_before = list(engine.state.team[AWAY].lineup)
        serve(engine, Rating.ERROR)
        st = engine.state
        assert st.scores == {HOME: 0, AWAY: 1}
        assert st.serving_team == AWAY                        # receivers gain serve
        assert st.team[AWAY].lineup == rotate_clockwise(away_before)
        assert st.team[HOME].lineup == home_before            # faulting team static
        assert st.phase == Phase.AWAIT_SERVE
        # old P2 of the receiving team is the new server
        assert engine.expected_server() == away_before[1]

    @pytest.mark.parametrize("rating", [Rating.GOOD, Rating.POOR])
    def test_in_play_serve_moves_to_reception(self, engine, rating):
        start_set(engine, serving=HOME)
        w = serve(engine, rating)
        assert w == []
        assert engine.state.phase == Phase.RECEPTION
        assert engine.state.scores == {HOME: 0, AWAY: 0}
        assert engine.state.attacking_team is None

    def test_default_serve_rating_is_good(self, engine):
        start_set(engine, serving=HOME)
        engine.append(ServeEvent(team=HOME,
                                 player_id=engine.state.team[HOME].lineup[0]))
        assert engine.state.phase == Phase.RECEPTION

    def test_wrong_server_warns_but_applies(self, engine):
        start_set(engine, serving=HOME)
        w = serve(engine, Rating.PERFECT, player_id=pid(engine, HOME, 3))
        assert any("expected server" in x for x in w)
        assert engine.state.scores[HOME] == 1                 # applied anyway

    def test_wrong_team_serving_warns(self, engine):
        start_set(engine, serving=HOME)
        w = serve(engine, Rating.GOOD, team=AWAY,
                  player_id=engine.state.team[AWAY].lineup[0])
        assert any("serve possession" in x for x in w)

    def test_serve_out_of_phase_warns(self, engine):
        start_set(engine, serving=HOME)
        serve(engine, Rating.GOOD)                            # -> RECEPTION
        w = serve(engine, Rating.GOOD)
        assert any("serve entered during phase" in x for x in w)


# -------------------------------------------------------- reception phase

class TestReception:
    def test_reception_error_is_point_for_serving_team(self, engine):
        start_set(engine, serving=HOME)
        serve(engine)
        home_before = list(engine.state.team[HOME].lineup)
        receive(engine, Rating.ERROR)
        st = engine.state
        assert st.scores == {HOME: 1, AWAY: 0}
        assert st.serving_team == HOME                        # server keeps serve
        assert st.team[HOME].lineup == home_before            # no rotation
        assert st.phase == Phase.AWAIT_SERVE

    @pytest.mark.parametrize("rating",
                             [Rating.POOR, Rating.GOOD, Rating.PERFECT])
    def test_playable_reception_moves_to_attack(self, engine, rating):
        start_set(engine, serving=HOME)
        serve(engine)
        w = receive(engine, rating)
        assert w == []
        assert engine.state.phase == Phase.ATTACK
        assert engine.state.attacking_team == AWAY

    def test_reception_by_serving_team_warns(self, engine):
        start_set(engine, serving=HOME)
        serve(engine)
        w = receive(engine, Rating.GOOD, team=HOME)
        assert any("serving team" in x for x in w)

    def test_reception_out_of_phase_warns(self, engine):
        start_set(engine, serving=HOME)
        w = receive(engine, Rating.GOOD)
        assert any("reception entered during phase" in x for x in w)


# ------------------------------------------------------- attack/dig phase

class TestAttackAndDig:
    def rally_to_attack(self, engine):
        """HOME serves, AWAY receives -> AWAY in ATTACK phase."""
        start_set(engine, serving=HOME)
        serve(engine)
        receive(engine)

    def test_kill_scores_for_attacker_with_side_out(self, engine):
        self.rally_to_attack(engine)
        away_before = list(engine.state.team[AWAY].lineup)
        attack(engine, AWAY, Rating.PERFECT)
        st = engine.state
        assert st.scores == {HOME: 0, AWAY: 1}
        assert st.serving_team == AWAY                        # receivers won
        assert st.team[AWAY].lineup == rotate_clockwise(away_before)
        assert st.phase == Phase.AWAIT_SERVE

    def test_attack_error_scores_for_opponent(self, engine):
        self.rally_to_attack(engine)
        home_before = list(engine.state.team[HOME].lineup)
        attack(engine, AWAY, Rating.ERROR)
        st = engine.state
        assert st.scores == {HOME: 1, AWAY: 0}
        assert st.serving_team == HOME                        # server keeps serve
        assert st.team[HOME].lineup == home_before            # no rotation
        assert st.phase == Phase.AWAIT_SERVE

    @pytest.mark.parametrize("rating", [Rating.GOOD, Rating.POOR])
    def test_kept_attack_moves_to_defense(self, engine, rating):
        self.rally_to_attack(engine)
        w = attack(engine, AWAY, rating)
        assert w == []
        assert engine.state.phase == Phase.DEFENSE
        assert engine.state.attacking_team == AWAY

    def test_attack_by_wrong_team_warns(self, engine):
        self.rally_to_attack(engine)
        w = attack(engine, HOME, Rating.GOOD)                 # AWAY has the ball
        assert any("has the ball" in x for x in w)

    def test_dig_error_is_point_for_attackers(self, engine):
        self.rally_to_attack(engine)
        attack(engine, AWAY, Rating.GOOD)                     # -> DEFENSE
        away_before = list(engine.state.team[AWAY].lineup)
        dig(engine, HOME, Rating.ERROR)
        st = engine.state
        assert st.scores == {HOME: 0, AWAY: 1}
        assert st.serving_team == AWAY
        assert st.team[AWAY].lineup == rotate_clockwise(away_before)
        assert st.phase == Phase.AWAIT_SERVE

    @pytest.mark.parametrize("rating",
                             [Rating.POOR, Rating.GOOD, Rating.PERFECT])
    def test_successful_dig_starts_counter_attack(self, engine, rating):
        self.rally_to_attack(engine)
        attack(engine, AWAY, Rating.GOOD)
        w = dig(engine, HOME, rating)
        assert w == []
        assert engine.state.phase == Phase.ATTACK
        assert engine.state.attacking_team == HOME            # digging team attacks

    def test_dig_by_attacking_team_warns(self, engine):
        self.rally_to_attack(engine)
        attack(engine, AWAY, Rating.GOOD)
        w = dig(engine, AWAY, Rating.GOOD)
        assert any("attacking team" in x for x in w)

    def test_dig_out_of_phase_warns(self, engine):
        self.rally_to_attack(engine)
        w = dig(engine, HOME, Rating.GOOD)
        assert any("dig entered during phase" in x for x in w)

    def test_counter_attack_without_rated_dig_is_silent(self, engine):
        # Scouter skips the dig: defending team attacks straight from DEFENSE.
        self.rally_to_attack(engine)
        attack(engine, AWAY, Rating.GOOD)                     # -> DEFENSE
        w = attack(engine, HOME, Rating.GOOD)                 # implicit dig
        assert w == []
        assert engine.state.phase == Phase.DEFENSE            # ball back to AWAY side
        assert engine.state.attacking_team == HOME

    def test_counter_attack_kill_without_rated_dig(self, engine):
        self.rally_to_attack(engine)
        attack(engine, AWAY, Rating.GOOD)                     # -> DEFENSE
        w = attack(engine, HOME, Rating.PERFECT)              # implicit dig + kill
        assert w == []
        assert engine.state.scores == {HOME: 1, AWAY: 0}
        assert engine.state.phase == Phase.AWAIT_SERVE

    def test_same_team_attacking_again_from_defense_warns(self, engine):
        self.rally_to_attack(engine)
        attack(engine, AWAY, Rating.GOOD)                     # -> DEFENSE
        w = attack(engine, AWAY, Rating.GOOD)                 # AWAY again: not a dig
        assert any("attack entered during phase" in x for x in w)

    def test_long_rally_alternates_correctly(self, engine):
        self.rally_to_attack(engine)
        attack(engine, AWAY, Rating.GOOD)
        dig(engine, HOME, Rating.GOOD)
        attack(engine, HOME, Rating.POOR)
        dig(engine, AWAY, Rating.GOOD)
        w = attack(engine, AWAY, Rating.PERFECT)
        assert w == []
        assert engine.state.scores == {HOME: 0, AWAY: 1}


# --------------------------------------------------- rotation integration

class TestRotationIntegration:
    def test_six_side_outs_return_lineups_to_start(self, engine):
        start_set(engine, serving=HOME)
        home_start = list(engine.state.team[HOME].lineup)
        away_start = list(engine.state.team[AWAY].lineup)
        for _ in range(6):
            serve(engine, Rating.ERROR)   # HOME faults -> AWAY rotates, serves
            serve(engine, Rating.ERROR)   # AWAY faults -> HOME rotates, serves
        st = engine.state
        assert st.team[HOME].lineup == home_start             # identity after 6
        assert st.team[AWAY].lineup == away_start
        assert st.scores == {HOME: 6, AWAY: 6}
        assert st.serving_team == HOME

    def test_service_order_follows_starting_lineup(self, engine):
        start_set(engine, serving=HOME)
        away_start = list(engine.state.team[AWAY].lineup)
        # AWAY sides out repeatedly: servers must appear in lineup order.
        for i in range(1, 6):
            engine.append(RallyPointEvent(team=AWAY)) \
                if engine.state.serving_team == AWAY else None
            if engine.state.serving_team != AWAY:
                engine.append(RallyPointEvent(team=AWAY))
            assert engine.expected_server() == away_start[i % 6]
            # give serve back to HOME without rotating AWAY
            engine.append(ServeOverrideEvent(team=HOME))

    def test_points_won_on_serve_never_rotate(self, engine):
        start_set(engine, serving=HOME)
        before = list(engine.state.team[HOME].lineup)
        for _ in range(5):
            serve(engine, Rating.PERFECT)
        assert engine.state.team[HOME].lineup == before
        assert engine.state.scores[HOME] == 5


# --------------------------------------------------------- set/match wins

class TestScoringAndSets:
    def test_set_won_at_25_with_two_point_lead(self, engine):
        start_set(engine, serving=HOME)
        score_points(engine, HOME, 24)
        score_points(engine, AWAY, 10)
        assert engine.state.phase == Phase.AWAIT_SERVE
        score_points(engine, HOME, 1)
        st = engine.state
        assert st.scores == {HOME: 25, AWAY: 10}
        assert st.phase == Phase.SET_OVER
        assert st.set_scores == {HOME: 1, AWAY: 0}
        assert st.last_set_winner == HOME

    def test_no_set_win_at_25_24(self, engine):
        start_set(engine, serving=HOME)
        score_points(engine, HOME, 24)
        score_points(engine, AWAY, 24)
        score_points(engine, HOME, 1)                         # 25-24
        assert engine.state.phase == Phase.AWAIT_SERVE
        assert engine.state.set_scores == {HOME: 0, AWAY: 0}

    def test_set_won_26_24(self, engine):
        start_set(engine, serving=HOME)
        score_points(engine, HOME, 24)
        score_points(engine, AWAY, 24)
        score_points(engine, HOME, 2)                         # 26-24
        assert engine.state.phase == Phase.SET_OVER
        assert engine.state.set_scores == {HOME: 1, AWAY: 0}

    def test_set_won_31_29_no_cap(self, engine):
        start_set(engine, serving=HOME)
        score_points(engine, HOME, 24)
        score_points(engine, AWAY, 24)
        for _ in range(5):                                    # to 29-29
            score_points(engine, HOME, 1)
            score_points(engine, AWAY, 1)
        assert engine.state.phase == Phase.AWAIT_SERVE
        score_points(engine, HOME, 2)                         # 31-29
        assert engine.state.scores == {HOME: 31, AWAY: 29}
        assert engine.state.phase == Phase.SET_OVER

    def test_match_over_after_three_straight_sets(self, engine):
        for _ in range(3):
            if engine.state.phase == Phase.SET_OVER:
                engine.append(engine.suggest_next_set_start())
            else:
                start_set(engine, serving=HOME)
            score_points(engine, HOME, 25)
        st = engine.state
        assert st.set_scores == {HOME: 3, AWAY: 0}
        assert st.phase == Phase.MATCH_OVER
        assert engine.suggest_next_set_start() is None

    def test_full_five_set_match_deciding_set_to_15(self, engine):
        # Sets 1-4 split 2-2, then the tie-break.
        start_set(engine, serving=HOME, left=HOME)
        for winner in (HOME, AWAY, HOME, AWAY):
            score_points(engine, winner, 25)
            assert engine.state.phase == Phase.SET_OVER
            engine.append(engine.suggest_next_set_start())
        st = engine.state
        assert st.set_number == 5
        assert st.set_scores == {HOME: 2, AWAY: 2}
        # tie-break plays to 15
        score_points(engine, HOME, 14)
        score_points(engine, AWAY, 13)
        assert engine.state.phase == Phase.AWAIT_SERVE        # 14-13 not enough
        score_points(engine, HOME, 1)                         # 15-13
        assert engine.state.scores == {HOME: 15, AWAY: 13}
        assert engine.state.phase == Phase.MATCH_OVER
        assert engine.state.set_scores == {HOME: 3, AWAY: 2}

    def test_deciding_set_needs_two_point_lead_too(self, engine):
        start_set(engine, serving=HOME)
        for winner in (HOME, AWAY, HOME, AWAY):
            score_points(engine, winner, 25)
            engine.append(engine.suggest_next_set_start())
        score_points(engine, HOME, 14)
        score_points(engine, AWAY, 14)
        score_points(engine, HOME, 1)                         # 15-14
        assert engine.state.phase == Phase.AWAIT_SERVE
        score_points(engine, HOME, 1)                         # 16-14
        assert engine.state.phase == Phase.MATCH_OVER


# ---------------------------------------------------- deciding-set switch

def reach_set_five(engine):
    start_set(engine, serving=HOME, left=HOME)
    for winner in (HOME, AWAY, HOME, AWAY):
        score_points(engine, winner, 25)
        engine.append(engine.suggest_next_set_start())


class TestDecidingSetSwitch:
    def test_sides_switch_once_when_leader_reaches_8(self, engine):
        reach_set_five(engine)
        left_at_start = engine.state.left_team
        score_points(engine, HOME, 7)
        assert engine.state.left_team == left_at_start        # 7-0: not yet
        assert engine.state.switched_mid_set is False
        score_points(engine, HOME, 1)                         # 8-0: switch
        assert engine.state.left_team == other(left_at_start)
        assert engine.state.switched_mid_set is True

    def test_switch_happens_exactly_once(self, engine):
        reach_set_five(engine)
        left_at_start = engine.state.left_team
        score_points(engine, HOME, 8)                         # switch here
        score_points(engine, AWAY, 8)                         # trailing team at 8
        score_points(engine, HOME, 2)
        assert engine.state.left_team == other(left_at_start) # still only one flip
        assert engine.state.switched_mid_set is True

    def test_first_team_to_8_triggers_regardless_of_side(self, engine):
        reach_set_five(engine)
        left_at_start = engine.state.left_team
        score_points(engine, AWAY, 8)
        assert engine.state.left_team == other(left_at_start)

    def test_no_mid_set_switch_in_regular_sets(self, engine):
        start_set(engine, serving=HOME, left=HOME)
        score_points(engine, HOME, 8)
        score_points(engine, AWAY, 8)
        assert engine.state.left_team == HOME
        assert engine.state.switched_mid_set is False


# -------------------------------------------------------- next-set logic

class TestNextSetSuggestion:
    def test_none_before_first_set(self, engine):
        assert engine.suggest_next_set_start() is None

    def test_none_during_live_set(self, engine):
        start_set(engine)
        assert engine.suggest_next_set_start() is None
        serve(engine)
        assert engine.suggest_next_set_start() is None

    def test_suggestion_after_set(self, engine):
        start_set(engine, serving=HOME, left=HOME)
        home_start = list(engine.state.team[HOME].lineup)
        away_start = list(engine.state.team[AWAY].lineup)
        score_points(engine, AWAY, 3)                         # force rotations
        score_points(engine, HOME, 25)
        sug = engine.suggest_next_set_start()
        assert sug is not None
        assert sug.set_number == 2
        assert sug.left_team == AWAY                          # sides switch
        assert sug.serving_team == AWAY                       # serve alternates
        # lineups reset to the starting lineups, not the rotated ones
        assert sug.lineups[HOME] == home_start
        assert sug.lineups[AWAY] == away_start
        assert sug.liberos[HOME] == [pid(engine, HOME, 6)]

    def test_first_serve_alternates_across_sets(self, engine):
        # winners alternate so the match does not end 3-0 after three sets
        start_set(engine, serving=AWAY, left=HOME)
        servers = [AWAY]
        for winner in (HOME, AWAY, HOME):
            score_points(engine, winner, 25)
            sug = engine.suggest_next_set_start()
            servers.append(sug.serving_team)
            engine.append(sug)
        assert servers == [AWAY, HOME, AWAY, HOME]

    def test_left_team_alternates_across_sets(self, engine):
        start_set(engine, serving=HOME, left=AWAY)
        lefts = [engine.state.left_team]
        for winner in (AWAY, HOME, AWAY):
            score_points(engine, winner, 25)
            sug = engine.suggest_next_set_start()
            engine.append(sug)
            lefts.append(engine.state.left_team)
        assert lefts == [AWAY, HOME, AWAY, HOME]

    def test_no_double_set_award_after_set_over(self, engine):
        # stray points entered while SET_OVER must not award another set
        start_set(engine, serving=HOME, left=HOME)
        score_points(engine, HOME, 25)
        assert engine.state.set_scores[HOME] == 1
        score_points(engine, HOME, 3)
        assert engine.state.set_scores[HOME] == 1

    def test_manual_correction_reopens_set(self, engine):
        # set awarded at 25-20, then the score turns out to be wrong
        start_set(engine, serving=HOME, left=HOME)
        score_points(engine, AWAY, 20)
        score_points(engine, HOME, 25)
        assert engine.state.phase == Phase.SET_OVER
        engine.append(ManualScoreEvent(team=HOME, delta=-1))
        assert engine.state.set_scores[HOME] == 0
        assert engine.state.phase == Phase.AWAIT_SERVE

    def test_suggestion_undoes_libero_exchange(self, engine):
        start_set(engine, serving=AWAY, left=HOME)
        lib = pid(engine, HOME, 6)
        partner = engine.state.team[HOME].lineup[5]
        engine.append(LiberoSwapEvent(team=HOME, libero_id=lib,
                                      partner_id=partner))
        score_points(engine, HOME, 25)
        sug = engine.suggest_next_set_start()
        assert lib not in sug.lineups[HOME]
        assert partner in sug.lineups[HOME]


# ----------------------------------------------------------- substitutions

class TestSubstitutions:
    def test_clean_sub_replaces_slot_in_place(self, engine):
        start_set(engine, serving=HOME, with_liberos=False)
        out_id, in_id = pid(engine, HOME, 2), pid(engine, HOME, 8)
        w = engine.append(SubstitutionEvent(team=HOME, player_out=out_id,
                                            player_in=in_id))
        assert w == []
        ts = engine.state.team[HOME]
        assert ts.lineup[2] == in_id                          # same rotation slot
        assert ts.subs_used == 1
        assert ts.sub_pairs == [(out_id, in_id)]
        assert engine.state.team[AWAY].subs_used == 0         # other team untouched

    def test_seventh_sub_warns_but_is_applied(self, engine):
        start_set(engine, serving=HOME, with_liberos=False)
        for i in range(6):                                    # 6 legal subs
            w = engine.append(SubstitutionEvent(
                team=HOME, player_out=pid(engine, HOME, i),
                player_in=pid(engine, HOME, 6 + i)))
            assert w == []
        # 7th: legal re-entry pair-wise, but over the limit
        w = engine.append(SubstitutionEvent(
            team=HOME, player_out=pid(engine, HOME, 6),
            player_in=pid(engine, HOME, 0)))
        assert any("limit" in x for x in w)
        ts = engine.state.team[HOME]
        assert ts.subs_used == 7                              # applied anyway
        assert ts.lineup[0] == pid(engine, HOME, 0)

    def test_substitute_for_second_player_warns_but_applies(self, engine):
        start_set(engine, serving=HOME, with_liberos=False)
        p0, p1, s = (pid(engine, HOME, 0), pid(engine, HOME, 1),
                     pid(engine, HOME, 8))
        engine.append(SubstitutionEvent(team=HOME, player_out=p0, player_in=s))
        engine.append(SubstitutionEvent(team=HOME, player_out=s, player_in=p0))
        w = engine.append(SubstitutionEvent(team=HOME, player_out=p1,
                                            player_in=s))
        assert any("different player" in x for x in w)
        ts = engine.state.team[HOME]
        assert ts.lineup[1] == s                              # applied anyway
        assert ts.subs_used == 3

    def test_exhausted_pair_warns_but_applies(self, engine):
        start_set(engine, serving=HOME, with_liberos=False)
        p0, s = pid(engine, HOME, 0), pid(engine, HOME, 8)
        assert engine.append(SubstitutionEvent(team=HOME, player_out=p0,
                                               player_in=s)) == []
        assert engine.append(SubstitutionEvent(team=HOME, player_out=s,
                                               player_in=p0)) == []
        w = engine.append(SubstitutionEvent(team=HOME, player_out=p0,
                                            player_in=s))    # third exchange
        assert any("re-entry" in x for x in w)
        ts = engine.state.team[HOME]
        assert ts.lineup[0] == s                              # applied anyway
        assert ts.subs_used == 3

    def test_sub_of_player_not_on_court_warns_lineup_unchanged(self, engine):
        start_set(engine, serving=HOME, with_liberos=False)
        before = list(engine.state.team[HOME].lineup)
        w = engine.append(SubstitutionEvent(
            team=HOME, player_out=pid(engine, HOME, 9),
            player_in=pid(engine, HOME, 10)))
        assert any("not on court" in x for x in w)
        assert engine.state.team[HOME].lineup == before
        assert engine.state.team[HOME].subs_used == 1         # still counted

    def test_libero_entering_by_sub_warns(self, engine):
        start_set(engine, serving=HOME)                       # libero = player 6
        w = engine.append(SubstitutionEvent(
            team=HOME, player_out=pid(engine, HOME, 0),
            player_in=pid(engine, HOME, 6)))
        assert any("libero" in x for x in w)

    def test_sub_during_live_rally_warns(self, engine):
        start_set(engine, serving=HOME)
        serve(engine)                                         # rally live
        w = engine.append(SubstitutionEvent(
            team=HOME, player_out=pid(engine, HOME, 0),
            player_in=pid(engine, HOME, 8)))
        assert any("live rally" in x for x in w)


# ----------------------------------------------------------------- libero

class TestLibero:
    def test_swap_in_back_row_is_clean(self, engine):
        start_set(engine, serving=AWAY)                       # HOME receives
        lib = pid(engine, HOME, 6)
        partner = engine.state.team[HOME].lineup[5]           # P6
        w = engine.append(LiberoSwapEvent(team=HOME, libero_id=lib,
                                          partner_id=partner))
        assert w == []
        ts = engine.state.team[HOME]
        assert ts.lineup[5] == lib
        assert ts.libero_replaced == {lib: partner}
        assert ts.subs_used == 0                              # not a substitution

    def test_swap_toggles_back_out(self, engine):
        start_set(engine, serving=AWAY)
        lib = pid(engine, HOME, 6)
        partner = engine.state.team[HOME].lineup[5]
        engine.append(LiberoSwapEvent(team=HOME, libero_id=lib,
                                      partner_id=partner))
        w = engine.append(LiberoSwapEvent(team=HOME, libero_id=lib,
                                          partner_id=partner))
        assert w == []
        ts = engine.state.team[HOME]
        assert ts.lineup[5] == partner
        assert ts.libero_replaced == {}

    def test_entry_into_front_row_warns_but_applies(self, engine):
        start_set(engine, serving=AWAY)
        lib = pid(engine, HOME, 6)
        partner = engine.state.team[HOME].lineup[2]           # P3 = front row
        w = engine.append(LiberoSwapEvent(team=HOME, libero_id=lib,
                                          partner_id=partner))
        assert any("back-row" in x for x in w)
        assert engine.state.team[HOME].lineup[2] == lib       # applied anyway

    def test_entry_at_p1_while_serving_warns(self, engine):
        start_set(engine, serving=HOME)
        lib = pid(engine, HOME, 6)
        partner = engine.state.team[HOME].lineup[0]
        w = engine.append(LiberoSwapEvent(team=HOME, libero_id=lib,
                                          partner_id=partner))
        assert any("may not serve" in x for x in w)

    def test_entry_at_p1_ok_when_federation_allows_serving(self, teams):
        eng = MatchEngine(MatchConfig(libero_may_serve=True), teams)
        start_set(eng, serving=HOME)
        lib = eng.teams[HOME].players[6].id
        partner = eng.state.team[HOME].lineup[0]
        w = eng.append(LiberoSwapEvent(team=HOME, libero_id=lib,
                                       partner_id=partner))
        assert w == []

    def test_entry_at_p1_ok_when_team_receives(self, engine):
        start_set(engine, serving=AWAY)
        lib = pid(engine, HOME, 6)
        partner = engine.state.team[HOME].lineup[0]
        w = engine.append(LiberoSwapEvent(team=HOME, libero_id=lib,
                                          partner_id=partner))
        assert w == []

    def test_exit_with_wrong_partner_warns_restores_recorded(self, engine):
        start_set(engine, serving=AWAY)
        lib = pid(engine, HOME, 6)
        real_partner = engine.state.team[HOME].lineup[5]
        wrong_partner = engine.state.team[HOME].lineup[4]
        engine.append(LiberoSwapEvent(team=HOME, libero_id=lib,
                                      partner_id=real_partner))
        w = engine.append(LiberoSwapEvent(team=HOME, libero_id=lib,
                                          partner_id=wrong_partner))
        assert any("exchanged back" in x for x in w)
        ts = engine.state.team[HOME]
        assert ts.lineup[5] == real_partner                   # recorded partner back
        assert ts.libero_replaced == {}

    def test_unregistered_libero_warns(self, engine):
        start_set(engine, serving=AWAY)
        not_lib = pid(engine, HOME, 8)
        partner = engine.state.team[HOME].lineup[5]
        w = engine.append(LiberoSwapEvent(team=HOME, libero_id=not_lib,
                                          partner_id=partner))
        assert any("not registered as libero" in x for x in w)

    def test_entry_for_partner_not_on_court_warns_no_change(self, engine):
        start_set(engine, serving=AWAY)
        lib = pid(engine, HOME, 6)
        before = list(engine.state.team[HOME].lineup)
        w = engine.append(LiberoSwapEvent(team=HOME, libero_id=lib,
                                          partner_id=pid(engine, HOME, 9)))
        assert any("not on court" in x for x in w)
        assert engine.state.team[HOME].lineup == before
        assert engine.state.team[HOME].libero_replaced == {}


class TestPendingAlerts:
    def test_no_alerts_without_libero_on_court(self, engine):
        start_set(engine, serving=HOME)
        assert engine.pending_alerts() == []

    def test_alert_when_libero_rotates_into_front_row(self, engine):
        start_set(engine, serving=AWAY)                       # HOME receives
        lib = pid(engine, HOME, 6)
        partner = engine.state.team[HOME].lineup[4]           # P5 (back row)
        engine.append(LiberoSwapEvent(team=HOME, libero_id=lib,
                                      partner_id=partner))
        serve(engine, Rating.ERROR)                           # HOME sides out+rotates
        # libero moved from index 4 (P5) to index 3 (P4) = front row
        assert engine.state.team[HOME].lineup[3] == lib
        alerts = engine.pending_alerts()
        assert len(alerts) == 1
        assert "front row" in alerts[0]
        assert "must return" in alerts[0]

    def test_alert_when_libero_at_p1_and_team_serves(self, engine):
        start_set(engine, serving=HOME)
        lib = pid(engine, HOME, 6)
        engine.append(LiberoSwapEvent(
            team=HOME, libero_id=lib,
            partner_id=engine.state.team[HOME].lineup[0]))
        alerts = engine.pending_alerts()
        assert len(alerts) == 1
        assert "may not serve" in alerts[0]

    def test_no_p1_alert_when_team_is_receiving(self, engine):
        start_set(engine, serving=AWAY)
        lib = pid(engine, HOME, 6)
        engine.append(LiberoSwapEvent(
            team=HOME, libero_id=lib,
            partner_id=engine.state.team[HOME].lineup[0]))
        assert engine.pending_alerts() == []

    def test_no_p1_alert_when_libero_may_serve(self, teams):
        eng = MatchEngine(MatchConfig(libero_may_serve=True), teams)
        start_set(eng, serving=HOME)
        lib = eng.teams[HOME].players[6].id
        eng.append(LiberoSwapEvent(
            team=HOME, libero_id=lib,
            partner_id=eng.state.team[HOME].lineup[0]))
        assert eng.pending_alerts() == []

    def test_no_alert_for_libero_safely_in_back_row(self, engine):
        start_set(engine, serving=AWAY)
        lib = pid(engine, HOME, 6)
        engine.append(LiberoSwapEvent(
            team=HOME, libero_id=lib,
            partner_id=engine.state.team[HOME].lineup[5]))    # P6
        assert engine.pending_alerts() == []

    def test_alerts_only_between_rallies(self, engine):
        start_set(engine, serving=HOME)
        lib = pid(engine, HOME, 6)
        engine.append(LiberoSwapEvent(
            team=HOME, libero_id=lib,
            partner_id=engine.state.team[HOME].lineup[0]))
        assert engine.pending_alerts() != []                  # AWAIT_SERVE
        serve(engine)                                         # rally live
        assert engine.pending_alerts() == []


# ------------------------------------------------------- manual overrides

class TestManualEvents:
    def test_manual_score_adds_point_without_rotation(self, engine):
        start_set(engine, serving=HOME)
        home_before = list(engine.state.team[HOME].lineup)
        away_before = list(engine.state.team[AWAY].lineup)
        w = engine.append(ManualScoreEvent(team=AWAY, delta=1))
        assert w == []
        st = engine.state
        assert st.scores == {HOME: 0, AWAY: 1}
        assert st.serving_team == HOME                        # possession untouched
        assert st.team[HOME].lineup == home_before
        assert st.team[AWAY].lineup == away_before

    def test_manual_score_subtracts(self, engine):
        start_set(engine, serving=HOME)
        score_points(engine, HOME, 3)
        engine.append(ManualScoreEvent(team=HOME, delta=-2))
        assert engine.state.scores[HOME] == 1

    def test_manual_score_never_below_zero(self, engine):
        start_set(engine, serving=HOME)
        engine.append(ManualScoreEvent(team=HOME, delta=-5))
        assert engine.state.scores[HOME] == 0

    def test_manual_score_can_end_a_set(self, engine):
        start_set(engine, serving=HOME)
        score_points(engine, HOME, 24)
        score_points(engine, AWAY, 10)
        serving_before = engine.state.serving_team
        engine.append(ManualScoreEvent(team=HOME, delta=1))
        st = engine.state
        assert st.phase == Phase.SET_OVER
        assert st.set_scores == {HOME: 1, AWAY: 0}
        assert st.serving_team == serving_before

    def test_serve_override_changes_possession_only(self, engine):
        start_set(engine, serving=HOME)
        home_before = list(engine.state.team[HOME].lineup)
        away_before = list(engine.state.team[AWAY].lineup)
        w = engine.append(ServeOverrideEvent(team=AWAY))
        assert w == []
        st = engine.state
        assert st.serving_team == AWAY
        assert st.scores == {HOME: 0, AWAY: 0}                # no point
        assert st.team[HOME].lineup == home_before            # no rotation
        assert st.team[AWAY].lineup == away_before
        assert st.phase == Phase.AWAIT_SERVE

    @pytest.mark.parametrize("setup", ["await", "reception", "attack", "defense"])
    def test_rally_point_allowed_in_any_live_phase(self, engine, setup):
        start_set(engine, serving=HOME)
        if setup != "await":
            serve(engine)
        if setup in ("attack", "defense"):
            receive(engine)
        if setup == "defense":
            attack(engine, AWAY, Rating.GOOD)
        w = engine.append(RallyPointEvent(team=HOME))
        assert w == []
        assert engine.state.scores[HOME] == 1
        assert engine.state.phase == Phase.AWAIT_SERVE

    def test_rally_point_to_receiving_team_side_outs(self, engine):
        start_set(engine, serving=HOME)
        away_before = list(engine.state.team[AWAY].lineup)
        engine.append(RallyPointEvent(team=AWAY))
        assert engine.state.serving_team == AWAY
        assert engine.state.team[AWAY].lineup == rotate_clockwise(away_before)

    def test_rally_point_before_set_warns(self, engine):
        w = engine.append(RallyPointEvent(team=HOME))
        assert any("point awarded during phase" in x for x in w)

    def test_timeout_third_one_warns(self, engine):
        start_set(engine, serving=HOME)
        assert engine.append(TimeoutEvent(team=HOME)) == []
        assert engine.append(TimeoutEvent(team=HOME)) == []
        w = engine.append(TimeoutEvent(team=HOME))
        assert any("timeout limit" in x for x in w)
        assert engine.state.team[HOME].timeouts == 3
        assert engine.state.team[AWAY].timeouts == 0


# ---------------------------------------------------------- set point info

class TestSetPointInfo:
    def test_none_before_set(self, engine):
        assert engine.set_point_info() is None

    def test_none_at_start_of_set(self, engine):
        start_set(engine, serving=HOME)
        assert engine.set_point_info() is None

    def test_none_below_target(self, engine):
        start_set(engine, serving=HOME)
        score_points(engine, HOME, 23)
        score_points(engine, AWAY, 20)
        assert engine.set_point_info() is None

    def test_set_point_at_24(self, engine):
        start_set(engine, serving=HOME)
        score_points(engine, HOME, 24)
        score_points(engine, AWAY, 20)
        assert engine.set_point_info() == "set point Home"

    def test_set_point_at_24_23(self, engine):
        start_set(engine, serving=HOME)
        score_points(engine, HOME, 24)
        score_points(engine, AWAY, 23)
        assert engine.set_point_info() == "set point Home"

    def test_none_at_24_all(self, engine):
        start_set(engine, serving=HOME)
        score_points(engine, HOME, 24)
        score_points(engine, AWAY, 24)
        assert engine.set_point_info() is None

    def test_set_point_in_deuce(self, engine):
        start_set(engine, serving=HOME)
        score_points(engine, HOME, 24)
        score_points(engine, AWAY, 24)
        score_points(engine, AWAY, 1)                         # 24-25
        assert engine.set_point_info() == "set point Away"

    def test_away_set_point(self, engine):
        start_set(engine, serving=HOME)
        score_points(engine, AWAY, 24)
        assert engine.set_point_info() == "set point Away"

    def test_match_point_when_leading_two_sets(self, engine):
        start_set(engine, serving=HOME)
        for _ in range(2):
            score_points(engine, HOME, 25)
            engine.append(engine.suggest_next_set_start())
        score_points(engine, HOME, 24)                        # set 3, 24-0
        assert engine.set_point_info() == "match point Home"

    def test_match_point_in_deciding_set_at_14(self, engine):
        reach_set_five(engine)
        score_points(engine, HOME, 14)
        score_points(engine, AWAY, 12)
        assert engine.set_point_info() == "match point Home"

    def test_none_in_deciding_set_at_14_all(self, engine):
        reach_set_five(engine)
        score_points(engine, HOME, 14)
        score_points(engine, AWAY, 14)
        assert engine.set_point_info() is None


# ------------------------------------------------------------------- undo

def build_rich_event_sequence(teams):
    """Drive an engine through a messy realistic passage of play covering
    every event type; return the recorded event list."""
    eng = MatchEngine(MatchConfig(), teams)
    H = [p.id for p in teams[HOME].players]
    A = [p.id for p in teams[AWAY].players]
    ev = [
        set_start_event(teams, set_number=1, serving=HOME, left=HOME),
        ServeEvent(team=HOME, player_id=H[0], rating=Rating.GOOD),
        ReceptionEvent(team=AWAY, player_id=A[0], rating=Rating.GOOD),
        AttackEvent(team=AWAY, player_id=A[1], rating=Rating.POOR),
        DigEvent(team=HOME, player_id=H[4], rating=Rating.GOOD),
        AttackEvent(team=HOME, player_id=H[1], rating=Rating.PERFECT),  # 1-0
        ServeEvent(team=HOME, player_id=H[0], rating=Rating.PERFECT),   # ace 2-0
        ServeEvent(team=HOME, player_id=H[0], rating=Rating.ERROR),     # 2-1, AWAY rotates
        TimeoutEvent(team=HOME),
        # AWAY lineup now [A1,A2,A3,A4,A5,A0]; substitute slot 1 (A2 -> A7)
        SubstitutionEvent(team=AWAY, player_out=A[2], player_in=A[7]),
        # libero A6 in for A0 (now at P6 / index 5, back row)
        LiberoSwapEvent(team=AWAY, libero_id=A[6], partner_id=A[0]),
        ServeEvent(team=AWAY, player_id=A[1], rating=Rating.GOOD),
        ReceptionEvent(team=HOME, player_id=H[0], rating=Rating.ERROR), # 2-2
        LiberoSwapEvent(team=AWAY, libero_id=A[6], partner_id=A[0]),    # swap back
        ManualScoreEvent(team=HOME, delta=1),                           # 3-2
        ServeOverrideEvent(team=HOME),
        ServeEvent(team=HOME, player_id=H[0], rating=Rating.POOR),
        ReceptionEvent(team=AWAY, player_id=A[3], rating=Rating.POOR),
        AttackEvent(team=AWAY, player_id=A[3], rating=Rating.GOOD),
        AttackEvent(team=HOME, player_id=H[2], rating=Rating.GOOD),     # implicit dig
        DigEvent(team=AWAY, player_id=A[4], rating=Rating.POOR),
        AttackEvent(team=AWAY, player_id=A[3], rating=Rating.ERROR),    # 4-2
        RallyPointEvent(team=AWAY),                                     # 4-3
    ]
    for e in ev:
        eng.append(e)
    return ev


class TestUndo:
    def test_undo_on_empty_engine_returns_none(self, engine):
        assert engine.undo() is None
        assert engine.state.phase == Phase.BEFORE_SET

    def test_undo_returns_removed_event(self, engine):
        start_set(engine, serving=HOME)
        e = ServeEvent(team=HOME, player_id=pid(engine, HOME, 0),
                       rating=Rating.PERFECT)
        engine.append(e)
        assert engine.undo() is e
        assert len(engine.events) == 1

    def test_undo_single_point(self, engine, teams):
        start_set(engine, serving=HOME)
        reference = MatchEngine(MatchConfig(), teams)
        reference.load_events(list(engine.events))
        serve(engine, Rating.ERROR)                           # point + rotation
        engine.undo()
        assert snapshot(engine) == snapshot(reference)

    def test_undo_equals_parallel_engine_for_every_prefix(self, teams):
        events = build_rich_event_sequence(teams)
        eng = MatchEngine(MatchConfig(), teams)
        for e in events:
            eng.append(e)
        for i in range(len(events) - 1, -1, -1):
            eng.undo()
            reference = MatchEngine(MatchConfig(), teams)
            reference.load_events(events[:i])
            assert snapshot(eng) == snapshot(reference), f"prefix {i}"
        assert eng.events == []
        assert eng.state.phase == Phase.BEFORE_SET

    def test_undo_across_set_boundary(self, engine, teams):
        start_set(engine, serving=HOME)
        score_points(engine, HOME, 24)
        reference = MatchEngine(MatchConfig(), teams)
        reference.load_events(list(engine.events))
        score_points(engine, HOME, 1)                         # set over 25-0
        assert engine.state.phase == Phase.SET_OVER
        engine.undo()
        assert snapshot(engine) == snapshot(reference)
        assert engine.state.phase == Phase.AWAIT_SERVE
        assert engine.state.set_scores == {HOME: 0, AWAY: 0}
        assert engine.state.scores == {HOME: 24, AWAY: 0}

    def test_undo_across_match_end(self, engine, teams):
        start_set(engine, serving=HOME)
        for _ in range(2):
            score_points(engine, HOME, 25)
            engine.append(engine.suggest_next_set_start())
        score_points(engine, HOME, 24)
        reference = MatchEngine(MatchConfig(), teams)
        reference.load_events(list(engine.events))
        score_points(engine, HOME, 1)
        assert engine.state.phase == Phase.MATCH_OVER
        engine.undo()
        assert snapshot(engine) == snapshot(reference)
        assert engine.state.phase == Phase.AWAIT_SERVE
        assert engine.state.set_scores == {HOME: 2, AWAY: 0}

    def test_undo_substitution_restores_lineup_and_counters(self, engine, teams):
        start_set(engine, serving=HOME, with_liberos=False)
        reference = MatchEngine(MatchConfig(), teams)
        reference.load_events(list(engine.events))
        engine.append(SubstitutionEvent(team=HOME,
                                        player_out=pid(engine, HOME, 0),
                                        player_in=pid(engine, HOME, 8)))
        engine.undo()
        assert snapshot(engine) == snapshot(reference)
        assert engine.state.team[HOME].subs_used == 0

    def test_undo_libero_swap(self, engine, teams):
        start_set(engine, serving=AWAY)
        reference = MatchEngine(MatchConfig(), teams)
        reference.load_events(list(engine.events))
        engine.append(LiberoSwapEvent(
            team=HOME, libero_id=pid(engine, HOME, 6),
            partner_id=engine.state.team[HOME].lineup[5]))
        engine.undo()
        assert snapshot(engine) == snapshot(reference)
        assert engine.state.team[HOME].libero_replaced == {}

    def test_multi_step_undo_then_replay_forward_again(self, engine, teams):
        start_set(engine, serving=HOME)
        serve(engine)
        receive(engine)
        kept = list(engine.events)
        after = snapshot(engine)
        engine.undo()
        engine.undo()
        engine.undo()
        assert engine.events == []
        # re-appending the same events reproduces the same state
        for e in kept:
            engine.append(e)
        assert snapshot(engine) == after


# --------------------------------------------------------- engine helpers

class TestEngineHelpers:
    def test_side_of_and_team_on_side(self, engine):
        start_set(engine, serving=HOME, left=AWAY)
        assert engine.side_of(AWAY) == "left"
        assert engine.side_of(HOME) == "right"
        assert engine.team_on_side("left") == AWAY
        assert engine.team_on_side("right") == HOME

    def test_receiving_team(self, engine):
        start_set(engine, serving=AWAY)
        assert engine.receiving_team() == HOME

    def test_rally_live_flags(self, engine):
        start_set(engine, serving=HOME)
        assert not engine.rally_live()
        serve(engine)
        assert engine.rally_live()
        receive(engine, Rating.ERROR)                         # rally ends
        assert not engine.rally_live()

    def test_load_events_rebuilds_state(self, engine, teams):
        start_set(engine, serving=HOME)
        serve(engine, Rating.PERFECT)
        clone = MatchEngine(MatchConfig(), teams)
        clone.load_events(list(engine.events))
        assert snapshot(clone) == snapshot(engine)
