"""Tests for core.trajectories: canonical left->right normalization of
serve / attack lines across side switches, and outcome classification."""
import pytest

from core.events import (
    AttackEvent,
    ManualScoreEvent,
    RallyPointEvent,
    ReceptionEvent,
    ServeEvent,
    SetStartEvent,
)
from core.models import HOME, AWAY, MatchConfig, Player, Rating, Skill, Team
from core.trajectories import collect_trajectories, outcome

HOME_IDS = [f"h{i}" for i in range(1, 7)]
AWAY_IDS = [f"a{i}" for i in range(1, 7)]


@pytest.fixture
def teams():
    return {
        HOME: Team("Home", players=[Player(number=i, name=f"H{i}", id=f"h{i}")
                                    for i in range(1, 7)]),
        AWAY: Team("Away", players=[Player(number=i, name=f"A{i}", id=f"a{i}")
                                    for i in range(1, 7)]),
    }


def set_start(n=1, serving=HOME, left=HOME):
    return SetStartEvent(set_number=n,
                         lineups={HOME: list(HOME_IDS), AWAY: list(AWAY_IDS)},
                         liberos={HOME: [], AWAY: []},
                         serving_team=serving, left_team=left)


def collect(teams, events):
    return collect_trajectories(MatchConfig(), teams, events)


def mirror(line):
    x1, y1, x2, y2 = line
    return (-x1, 9.0 - y1, -x2, 9.0 - y2)


# ------------------------------------------------------------ normalization

def test_serve_from_left_side_is_unchanged(teams):
    line = (-10.2, 7.5, 5.0, 3.0)
    stats = collect(teams, [
        set_start(serving=HOME, left=HOME),
        ServeEvent(HOME, "h1", Rating.GOOD, line),
    ])
    assert len(stats) == 1
    t = stats[0]
    assert (t.team, t.player_id, t.skill, t.rating, t.set_number) == \
        (HOME, "h1", Skill.SERVE, Rating.GOOD, 1)
    assert t.line == line


def test_serve_from_right_side_is_mirrored(teams):
    canonical = (-10.2, 7.5, 5.0, 3.0)
    stats = collect(teams, [
        set_start(serving=AWAY, left=HOME),          # away plays RIGHT
        ServeEvent(AWAY, "a1", Rating.GOOD, mirror(canonical)),
    ])
    assert stats[0].line == canonical


def test_attack_from_right_side_is_mirrored(teams):
    canonical = (-2.0, 5.0, 7.0, 1.0)
    stats = collect(teams, [
        set_start(serving=HOME, left=HOME),
        ServeEvent(HOME, "h1", Rating.GOOD, (-10.2, 7.5, 5.0, 3.0)),
        ReceptionEvent(AWAY, "a5", Rating.GOOD),
        AttackEvent(AWAY, "a2", Rating.PERFECT, mirror(canonical)),
    ])
    attacks = [t for t in stats if t.skill == Skill.ATTACK]
    assert len(attacks) == 1
    assert attacks[0].line == canonical
    assert attacks[0].rating == Rating.PERFECT


def test_events_without_trajectory_are_skipped(teams):
    stats = collect(teams, [
        set_start(serving=HOME, left=HOME),
        ServeEvent(HOME, "h1", Rating.GOOD, (-10.2, 7.5, 5.0, 3.0)),
        ReceptionEvent(AWAY, "a5", Rating.GOOD),
        AttackEvent(AWAY, "a2", Rating.PERFECT, None),   # rated without drag
    ])
    assert [t.skill for t in stats] == [Skill.SERVE]


def test_side_switch_between_sets(teams):
    """Same team, same real-world direction of play flips between sets;
    both serves must normalize to the identical canonical line."""
    canonical = (-10.2, 7.5, 5.0, 3.0)
    stats = collect(teams, [
        set_start(1, serving=HOME, left=HOME),
        ServeEvent(HOME, "h1", Rating.GOOD, canonical),
        ManualScoreEvent(HOME, 25),                      # home wins set 1
        set_start(2, serving=AWAY, left=AWAY),           # sides switch
        ServeEvent(HOME, "h1", Rating.GOOD, mirror(canonical)),
    ])
    assert len(stats) == 2
    assert stats[0].line == stats[1].line == canonical
    assert (stats[0].set_number, stats[1].set_number) == (1, 2)


def test_deciding_set_mid_set_switch(teams):
    """The ace that brings the leading team to 8 in the deciding set is
    still normalized with the pre-switch side; the next serve (after the
    teams walked around) is mirrored."""
    canonical = (-10.2, 7.5, 5.0, 3.0)
    events = []
    # sets 1-4: alternate winners to force a deciding 5th set
    for n, winner in enumerate((HOME, AWAY, HOME, AWAY), start=1):
        events.append(set_start(n, serving=HOME, left=HOME))
        events.append(ManualScoreEvent(winner, 25))
    events.append(set_start(5, serving=HOME, left=HOME))
    events += [RallyPointEvent(HOME)] * 7                # 7-0 home
    # ace -> 8-0: triggers the mid-set side switch AFTER this serve
    events.append(ServeEvent(HOME, "h1", Rating.PERFECT, canonical))
    # home now plays RIGHT and keeps the serve
    events.append(ServeEvent(HOME, "h1", Rating.GOOD, mirror(canonical)))
    stats = collect(teams, events)
    assert len(stats) == 2
    assert stats[0].line == stats[1].line == canonical
    assert stats[0].rating == Rating.PERFECT


# ------------------------------------------------------------ outcome class

def test_outcome_classification():
    assert outcome(Rating.ERROR) == "error"
    assert outcome(Rating.PERFECT) == "point"
    assert outcome(Rating.GOOD) == "neutral"
    assert outcome(Rating.POOR) == "neutral"
