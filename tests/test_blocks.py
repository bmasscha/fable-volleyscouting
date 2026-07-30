"""Block handling: deflection classification geometry, the engine's
covered-ball (block cover) branch, serialization of block_touch and
vertex normalization in the trajectory charts."""
import pytest

from core.blocks import (BLOCK_NET_ZONE, BLOCK_OUT, COVERED, IN_PLAY,
                         classify_block_deflection, is_block_touch,
                         landing_in_bounds, unblocked_attack_is_error)
from core.engine import MatchEngine, Phase
from core.events import (AttackEvent, DigEvent, ReceptionEvent, ServeEvent,
                         event_from_dict, event_to_dict)
from core.models import AWAY, HOME, MatchConfig, Rating, other
from core.rotation import LEFT, RIGHT
from core.trajectories import collect_trajectories

from .test_engine import make_teams, set_start_event

# ----------------------------------------------------------- classification


@pytest.mark.parametrize("x,y", [
    (9.5, 4.5),      # beyond right baseline
    (-9.5, 4.5),     # beyond left baseline
    (3.0, -0.5),     # beyond north sideline
    (3.0, 9.5),      # beyond south sideline
    (-12.0, 11.0),   # far out
])
def test_out_of_bounds_is_block_out_for_both_sides(x, y):
    assert classify_block_deflection(LEFT, x, y) == BLOCK_OUT
    assert classify_block_deflection(RIGHT, x, y) == BLOCK_OUT


def test_out_tolerance_matches_serve_tolerance():
    # 0.4 m beyond the line is still "in", just past it is out
    assert landing_in_bounds(9.4, 4.5)
    assert not landing_in_bounds(9.41, 4.5)
    assert landing_in_bounds(3.0, -0.4)
    assert not landing_in_bounds(3.0, -0.41)


def test_landing_on_attacker_half_is_covered():
    assert classify_block_deflection(LEFT, -3.0, 4.0) == COVERED
    assert classify_block_deflection(RIGHT, 3.0, 4.0) == COVERED


def test_landing_on_blocker_half_stays_in_play():
    assert classify_block_deflection(LEFT, 3.0, 4.0) == IN_PLAY
    assert classify_block_deflection(RIGHT, -3.0, 4.0) == IN_PLAY


def test_landing_exactly_on_net_plane_counts_as_blocker_side():
    assert classify_block_deflection(LEFT, 0.0, 4.5) == IN_PLAY
    assert classify_block_deflection(RIGHT, 0.0, 4.5) == IN_PLAY


# ----------------------------------- unblocked attacks / block-touch tips
#
# The same three landing zones settle an attack drawn WITHOUT a block touch,
# with the opposite verdict: only a ball that reached the opponents' court
# keeps the rally alive.


@pytest.mark.parametrize("side,x,y", [
    (LEFT, 9.5, 4.5),       # past the far baseline
    (RIGHT, -9.5, 4.5),     # past the far baseline
    (LEFT, 3.0, 9.5),       # past a sideline
    (RIGHT, 3.0, -0.5),     # past a sideline
])
def test_attack_landing_out_of_bounds_is_an_error(side, x, y):
    assert unblocked_attack_is_error(side, x, y)


@pytest.mark.parametrize("side,x", [(LEFT, -3.0), (RIGHT, 3.0)])
def test_attack_that_never_crossed_the_net_is_an_error(side, x):
    """Landing in bounds but on the attacker's own half means the ball never
    made it over -- hit into the net."""
    assert unblocked_attack_is_error(side, x, 4.0)


@pytest.mark.parametrize("side,x", [(LEFT, 3.0), (RIGHT, -3.0)])
def test_attack_into_the_opponents_court_still_needs_a_rating(side, x):
    assert not unblocked_attack_is_error(side, x, 4.0)


def test_error_and_block_touch_are_exact_opposites_at_the_net():
    """The same arrow tip cannot be both: just across the net it is a block
    contact (prime the second stroke), just short of it the ball never
    crossed (score '!'). This is what keeps the two gestures apart."""
    for side, across, short in ((LEFT, 0.5, -0.5), (RIGHT, -0.5, 0.5)):
        assert is_block_touch(side, across, 4.5)
        assert not unblocked_attack_is_error(side, across, 4.5)
        assert not is_block_touch(side, short, 4.5)
        assert unblocked_attack_is_error(side, short, 4.5)


def test_block_touch_must_be_within_the_net_zone():
    # deep in the opponents' court is a normal attack, not a block contact
    assert not is_block_touch(LEFT, BLOCK_NET_ZONE + 0.1, 4.5)
    assert is_block_touch(LEFT, BLOCK_NET_ZONE, 4.5)


def test_block_touch_out_of_bounds_is_not_a_block_touch():
    assert not is_block_touch(LEFT, 0.5, 9.9)


# ------------------------------------------------------------ engine flows


@pytest.fixture
def teams():
    return make_teams()


@pytest.fixture
def engine(teams):
    """Set running, HOME serving from the LEFT, rally advanced to the
    point where AWAY (right side) is in the attack phase."""
    eng = MatchEngine(MatchConfig(), teams)
    eng.append(set_start_event(teams, serving=HOME, left=HOME))
    eng.append(ServeEvent(team=HOME,
                          player_id=eng.state.team[HOME].lineup[0]))
    eng.append(ReceptionEvent(team=AWAY,
                              player_id=eng.state.team[AWAY].lineup[0],
                              rating=Rating.GOOD))
    assert eng.state.phase == Phase.ATTACK
    assert eng.state.attacking_team == AWAY
    return eng


def blocked_attack(engine, team, rating, landing, touch=(0.2, 4.5)):
    x1, y1 = (4.0, 4.5) if engine.side_of(team) == RIGHT else (-4.0, 4.5)
    return AttackEvent(team=team,
                       player_id=engine.state.team[team].lineup[1],
                       rating=rating,
                       trajectory=(x1, y1, landing[0], landing[1]),
                       block_touch=touch)


def test_covered_ball_returns_play_to_attacking_team(engine):
    # AWAY attacks from the right; the block returns the ball into the
    # right (AWAY) half in-bounds -> AWAY must cover its own ball
    w = engine.append(blocked_attack(engine, AWAY, Rating.POOR,
                                     landing=(3.0, 3.0)))
    assert w == []
    assert engine.state.phase == Phase.DEFENSE
    assert engine.state.attacking_team == HOME  # "ball comes from" HOME side

    # the cover dig charged to AWAY is legal...
    w = engine.append(DigEvent(team=AWAY,
                               player_id=engine.state.team[AWAY].lineup[4],
                               rating=Rating.GOOD))
    assert w == []
    # ...and AWAY attacks again
    assert engine.state.phase == Phase.ATTACK
    assert engine.state.attacking_team == AWAY


def test_dig_by_blockers_after_covered_ball_warns(engine):
    engine.append(blocked_attack(engine, AWAY, Rating.POOR,
                                 landing=(3.0, 3.0)))
    w = engine.append(DigEvent(team=HOME,
                               player_id=engine.state.team[HOME].lineup[4],
                               rating=Rating.GOOD))
    assert any("dig charged to the attacking team" in x for x in w)


def test_covered_ball_then_direct_attack_uses_implicit_dig(engine):
    engine.append(blocked_attack(engine, AWAY, Rating.POOR,
                                 landing=(3.0, 3.0)))
    # scouter skips the cover dig and logs the next AWAY attack directly
    w = engine.append(AttackEvent(team=AWAY,
                                  player_id=engine.state.team[AWAY].lineup[2],
                                  rating=Rating.GOOD))
    assert w == []
    assert engine.state.phase == Phase.DEFENSE
    assert engine.state.attacking_team == AWAY


def test_block_out_kill_awards_point_to_attacker(engine):
    before = engine.state.scores[AWAY]
    engine.append(blocked_attack(engine, AWAY, Rating.PERFECT,
                                 landing=(-2.0, 10.0)))     # deflected out
    assert engine.state.scores[AWAY] == before + 1
    assert engine.state.phase == Phase.AWAIT_SERVE


def test_deflection_on_blocker_side_is_normal_defense(engine):
    w = engine.append(blocked_attack(engine, AWAY, Rating.GOOD,
                                     landing=(-4.0, 4.0)))
    assert w == []
    assert engine.state.phase == Phase.DEFENSE
    assert engine.state.attacking_team == AWAY   # HOME digs as usual


def test_attack_without_block_touch_unchanged(engine):
    engine.append(AttackEvent(team=AWAY,
                              player_id=engine.state.team[AWAY].lineup[1],
                              rating=Rating.GOOD,
                              trajectory=(4.0, 4.5, -3.0, 3.0)))
    assert engine.state.phase == Phase.DEFENSE
    assert engine.state.attacking_team == AWAY


def test_undo_restores_pre_block_state(engine):
    engine.append(blocked_attack(engine, AWAY, Rating.POOR,
                                 landing=(3.0, 3.0)))
    engine.undo()
    assert engine.state.phase == Phase.ATTACK
    assert engine.state.attacking_team == AWAY


# ---------------------------------------------------------- serialization


def test_block_touch_round_trip():
    e = AttackEvent(team=HOME, player_id="H2", rating=Rating.POOR,
                    trajectory=(-4.0, 4.5, -3.0, 3.0),
                    block_touch=(-0.2, 4.5))
    d = event_to_dict(e)
    assert d["block_touch"] == [-0.2, 4.5]
    back = event_from_dict(d)
    assert back == e
    assert isinstance(back.block_touch, tuple)


def test_legacy_attack_dict_without_block_touch_loads():
    d = {"type": "attack", "team": HOME, "player_id": "H2", "rating": "+",
         "trajectory": [-4.0, 4.5, 3.0, 3.0], "ts": None}
    e = event_from_dict(d)
    assert e.block_touch is None


# ------------------------------------------------------------ chart stats


def test_block_touch_normalized_like_line(teams):
    """An attack from the RIGHT half is mirrored to the canonical
    left -> right orientation, vertex included."""
    config = MatchConfig()
    engine = MatchEngine(config, teams)
    events = [set_start_event(teams, serving=HOME, left=HOME)]
    engine.load_events(events)
    events.append(ServeEvent(team=HOME,
                             player_id=engine.state.team[HOME].lineup[0]))
    events.append(ReceptionEvent(team=AWAY,
                                 player_id=engine.state.team[AWAY].lineup[0],
                                 rating=Rating.GOOD))
    events.append(AttackEvent(team=AWAY,
                              player_id=teams[AWAY].players[1].id,
                              rating=Rating.PERFECT,
                              trajectory=(4.0, 4.5, -2.0, 10.0),
                              block_touch=(0.2, 4.0)))
    stats = collect_trajectories(config, teams, events)
    atk = [s for s in stats if s.block_touch is not None]
    assert len(atk) == 1
    # RIGHT-side mirror: (x, y) -> (-x, 9 - y)
    assert atk[0].line == (-4.0, 4.5, 2.0, -1.0)
    assert atk[0].block_touch == (-0.2, 5.0)


def test_serve_trajectory_has_no_block_touch(teams):
    config = MatchConfig()
    events = [set_start_event(teams, serving=HOME, left=HOME),
              ServeEvent(team=HOME, player_id=teams[HOME].players[0].id,
                         trajectory=(-10.0, 7.5, 5.0, 3.0))]
    stats = collect_trajectories(config, teams, events)
    assert stats[0].block_touch is None
