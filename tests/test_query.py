"""Tests for core.query: flattening the event log into filterable actions and
selecting them (the video-review selection engine)."""
from core.events import (AttackEvent, DigEvent, ReceptionEvent, ServeEvent,
                         SetStartEvent)
from core.models import AWAY, HOME, Player, Rating, Role, Skill, Team
from core.query import ActionFilter, Action, build_actions, filter_actions


def make_teams():
    return {
        HOME: Team(name="Home", players=[
            Player(number=1, name="Setter", role=Role.SETTER, id="h1"),
            Player(number=7, name="Libero", role=Role.LIBERO, id="h7"),
            Player(number=12, name="Wing", role=Role.OUTSIDE, id="h12"),
        ]),
        AWAY: Team(name="Away", players=[
            Player(number=5, name="Ace", role=Role.OPPOSITE, id="a5"),
            Player(number=12, name="AwayWing", role=Role.OUTSIDE, id="a12"),
        ]),
    }


def sample_events():
    """Set 1: home serves; away receives with the libero; away #12 attacks;
    home #7 (libero) digs. Then set 2 opens and away #12 attacks again."""
    return [
        SetStartEvent(set_number=1, lineups={HOME: [], AWAY: []},
                      liberos={HOME: ["h7"], AWAY: []},
                      serving_team=HOME, left_team=HOME, ts=100.0),
        ServeEvent(team=HOME, player_id="h1", rating=Rating.ERROR, ts=101.0),
        ServeEvent(team=HOME, player_id="h1", rating=Rating.GOOD, ts=110.0),
        ReceptionEvent(team=AWAY, player_id="a5", rating=Rating.GOOD, ts=111.0),
        AttackEvent(team=AWAY, player_id="a12", rating=Rating.PERFECT, ts=112.0),
        DigEvent(team=HOME, player_id="h7", rating=Rating.POOR, ts=113.0),
        SetStartEvent(set_number=2, lineups={HOME: [], AWAY: []},
                      liberos={HOME: ["h7"], AWAY: []},
                      serving_team=AWAY, left_team=AWAY, ts=200.0),
        ServeEvent(team=AWAY, player_id="a5", rating=Rating.GOOD, ts=201.0),
        AttackEvent(team=AWAY, player_id="a12", rating=Rating.GOOD, ts=203.0),
    ]


def test_build_actions_skips_non_skill_events():
    actions = build_actions(sample_events(), make_teams())
    # 2 serves + 1 reception + 1 attack + 1 dig in set 1, then 1 serve + 1 attack
    assert len(actions) == 7
    assert all(isinstance(a, Action) for a in actions)
    # set_start events are not actions
    assert {a.skill for a in actions} == {Skill.SERVE, Skill.RECEPTION,
                                          Skill.ATTACK, Skill.DIG}


def test_actions_carry_resolved_player_and_context():
    actions = build_actions(sample_events(), make_teams())
    attack = next(a for a in actions if a.skill == Skill.ATTACK and a.set_number == 1)
    assert attack.team_key == AWAY
    assert attack.player_number == 12
    assert attack.player_name == "AwayWing"
    assert attack.role == Role.OUTSIDE
    assert attack.rating == Rating.PERFECT
    assert attack.ts == 112.0
    assert attack.set_number == 1
    assert attack.rally_index == 2  # follows the 2nd serve of the set


def test_rally_index_increments_per_serve_and_resets_per_set():
    actions = build_actions(sample_events(), make_teams())
    set1 = [a for a in actions if a.set_number == 1]
    # first serve is its own rally (1), second serve opens rally 2 with its
    # reception/attack/dig
    assert [a.rally_index for a in set1] == [1, 2, 2, 2, 2]
    set2 = [a for a in actions if a.set_number == 2]
    assert set2[0].rally_index == 1  # reset at the new set


def test_filter_attacks_by_away_number_12():
    actions = build_actions(sample_events(), make_teams())
    spec = ActionFilter(team_key=AWAY, player_number=12, skill=Skill.ATTACK)
    result = filter_actions(actions, spec)
    assert [a.ts for a in result] == [112.0, 203.0]


def test_filter_serve_receive_by_home_libero_by_role():
    """'serve-receive actions by the libero of the home team' -> reception +
    role=LIBERO. In this sample the home libero digs (defence) but does not
    receive, so serve-receive filtering returns nothing for reception."""
    actions = build_actions(sample_events(), make_teams())
    recv = filter_actions(actions, ActionFilter(
        team_key=HOME, role=Role.LIBERO, skill=Skill.RECEPTION))
    assert recv == []
    # the libero's dig is found by role across skills
    digs = filter_actions(actions, ActionFilter(team_key=HOME, role=Role.LIBERO))
    assert [a.skill for a in digs] == [Skill.DIG]


def test_filter_failed_serves_by_player():
    actions = build_actions(sample_events(), make_teams())
    spec = ActionFilter(player_id="h1", skill=Skill.SERVE, rating=Rating.ERROR)
    result = filter_actions(actions, spec)
    assert len(result) == 1
    assert result[0].rating == Rating.ERROR
    assert result[0].ts == 101.0


def test_filter_by_set_number():
    actions = build_actions(sample_events(), make_teams())
    result = filter_actions(actions, ActionFilter(set_number=2))
    assert {a.set_number for a in result} == {2}
    assert len(result) == 2  # serve + attack


def test_unknown_player_is_kept_without_roster_data():
    events = [
        SetStartEvent(set_number=1, lineups={HOME: [], AWAY: []},
                      liberos={HOME: [], AWAY: []},
                      serving_team=HOME, left_team=HOME),
        ServeEvent(team=HOME, player_id="ghost", rating=Rating.GOOD, ts=5.0),
    ]
    actions = build_actions(events, make_teams())
    assert len(actions) == 1
    assert actions[0].player_number is None
    assert actions[0].role is None
    assert actions[0].player_name == ""


def test_filter_sorts_timeless_actions_last_in_event_order():
    events = [
        SetStartEvent(set_number=1, lineups={HOME: [], AWAY: []},
                      liberos={HOME: [], AWAY: []},
                      serving_team=HOME, left_team=HOME),
        ServeEvent(team=HOME, player_id="h1", rating=Rating.GOOD),        # no ts
        ServeEvent(team=HOME, player_id="h1", rating=Rating.GOOD, ts=1.0),
    ]
    actions = build_actions(events, make_teams())
    result = filter_actions(actions, ActionFilter(skill=Skill.SERVE))
    assert [a.ts for a in result] == [1.0, None]
