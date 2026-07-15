"""Automatic libero exchange: forced front-row exits, learned re-entry
at serve-receive, the auto_libero config gate, pairing memory and the
`auto` flag on LiberoSwapEvent."""
import pytest

from core.engine import MatchEngine, Phase
from core.events import (LiberoSwapEvent, RallyPointEvent,
                         RotationAdjustEvent, event_from_dict, event_to_dict)
from core.models import AWAY, HOME, MatchConfig, Role
from core.rotation import BACK_ROW

from .test_engine import make_teams, set_start_event

LIB = "H7-id"  # resolved in teams(); roster player 7 is the libero


@pytest.fixture
def teams():
    t = make_teams()
    # H3 and H5 are the middles the libero exchanges with
    t[HOME].players[2].role = Role.MIDDLE
    t[HOME].players[4].role = Role.MIDDLE
    return t


def hid(teams, roster_index):
    return teams[HOME].players[roster_index].id


def lib_id(teams):
    return teams[HOME].players[6].id


@pytest.fixture
def engine(teams):
    """Set running, AWAY serving, HOME receiving (lineup H1..H6, P1..P6)."""
    eng = MatchEngine(MatchConfig(), teams)
    eng.append(set_start_event(teams, serving=AWAY, left=HOME))
    return eng


def drain(engine, limit=6):
    """UI behavior: append engine-proposed swaps until there are none."""
    applied = []
    for _ in range(limit):
        e = engine.next_auto_libero_swap()
        if e is None:
            break
        engine.append(e)
        applied.append(e)
    return applied


def enter_libero(engine, teams, partner_roster_index=4):
    engine.append(LiberoSwapEvent(team=HOME, libero_id=lib_id(teams),
                                  partner_id=hid(teams, partner_roster_index)))


# ------------------------------------------------------------- forced exits


def test_no_suggestion_before_any_entry(engine):
    assert engine.next_auto_libero_swap() is None
    engine.append(RallyPointEvent(team=HOME))     # side-out, HOME rotates
    assert engine.next_auto_libero_swap() is None


def test_forced_exit_when_libero_rotates_to_front_row(engine, teams):
    enter_libero(engine, teams)                   # libero in for H5 at P5
    engine.append(RallyPointEvent(team=HOME))     # side-out: libero -> P4
    e = engine.next_auto_libero_swap()
    assert e is not None and e.auto
    assert e.team == HOME
    assert e.libero_id == lib_id(teams)
    assert e.partner_id == hid(teams, 4)
    engine.append(e)
    lineup = engine.state.team[HOME].lineup
    assert lineup[3] == hid(teams, 4)             # H5 back at P4
    assert lib_id(teams) not in lineup
    assert engine.pending_alerts() == []


def test_forced_exit_when_libero_must_serve(engine, teams):
    enter_libero(engine, teams)
    engine.append(RallyPointEvent(team=HOME))     # HOME gains serve
    # push the libero (now P4) to P1 by force
    engine.append(RotationAdjustEvent(team=HOME, steps=3))
    assert engine.state.team[HOME].lineup[0] == lib_id(teams)
    e = engine.next_auto_libero_swap()
    assert e is not None and e.auto and e.partner_id == hid(teams, 4)


def test_libero_may_serve_suppresses_p1_exit(teams):
    eng = MatchEngine(MatchConfig(libero_may_serve=True), teams)
    eng.append(set_start_event(teams, serving=AWAY, left=HOME))
    enter_libero(eng, teams)
    eng.append(RallyPointEvent(team=HOME))
    eng.append(RotationAdjustEvent(team=HOME, steps=3))
    assert eng.state.team[HOME].lineup[0] == lib_id(teams)
    assert eng.next_auto_libero_swap() is None    # serving from P1 is legal


def test_auto_libero_disabled_never_suggests(teams):
    eng = MatchEngine(MatchConfig(auto_libero=False), teams)
    eng.append(set_start_event(teams, serving=AWAY, left=HOME))
    enter_libero(eng, teams)
    eng.append(RallyPointEvent(team=HOME))        # libero at P4: exit is due
    assert eng.next_auto_libero_swap() is None
    assert len(eng.pending_alerts()) == 1         # manual alert still shown


# ---------------------------------------------------------------- re-entry


def test_no_blind_reentry_without_partner_in_back_row(engine, teams):
    enter_libero(engine, teams)
    engine.append(RallyPointEvent(team=HOME))
    drain(engine)                                 # forced exit applied
    engine.append(RallyPointEvent(team=AWAY))     # HOME receives next
    # learned partner H5 is at P4 (front) and no middle is in the back row
    assert engine.next_auto_libero_swap() is None


def test_role_fallback_picks_back_row_middle(engine, teams):
    enter_libero(engine, teams)
    engine.append(RallyPointEvent(team=HOME))
    drain(engine)
    engine.append(RallyPointEvent(team=AWAY))     # HOME receives...
    engine.append(RallyPointEvent(team=HOME))     # ...and rotates: H3 -> P1
    engine.append(RallyPointEvent(team=AWAY))     # HOME receives next
    e = engine.next_auto_libero_swap()
    assert e is not None and e.auto
    assert e.partner_id == hid(teams, 2)          # H3, role fallback
    engine.append(e)
    assert engine.state.team[HOME].libero_partners[lib_id(teams)] == [
        hid(teams, 4), hid(teams, 2)]


def test_learned_partner_preferred_at_serve_receive(engine, teams):
    # full cycle: libero has entered for both H5 and H3; when H5 arrives
    # in the back row at serve-receive the learned pairing brings the
    # libero straight back without relying on roles
    enter_libero(engine, teams)
    for winner in (HOME, AWAY, HOME, AWAY):       # exit ... fallback entry
        engine.append(RallyPointEvent(team=winner))
        drain(engine)
    for winner in (HOME, AWAY, HOME, AWAY, HOME):
        engine.append(RallyPointEvent(team=winner))
        drain(engine)                             # second forced exit inside
    engine.append(RallyPointEvent(team=AWAY))     # HOME receives next
    e = engine.next_auto_libero_swap()
    assert e is not None and e.auto
    assert e.partner_id == hid(teams, 4)          # H5, learned pairing
    lineup = engine.state.team[HOME].lineup
    assert lineup.index(e.partner_id) in BACK_ROW


def test_no_reentry_while_own_team_serves(engine, teams):
    enter_libero(engine, teams)
    engine.append(RallyPointEvent(team=HOME))     # HOME serves next
    drain(engine)                                 # forced exit only
    assert engine.state.serving_team == HOME
    assert engine.next_auto_libero_swap() is None


def test_no_reentry_when_libero_already_on_court(engine, teams):
    enter_libero(engine, teams)
    assert engine.next_auto_libero_swap() is None


def test_no_suggestions_during_live_rally(engine, teams):
    enter_libero(engine, teams)
    engine.append(RallyPointEvent(team=HOME))     # exit is due (libero at P4)
    from core.events import ServeEvent
    engine.append(ServeEvent(team=HOME,
                             player_id=engine.state.team[HOME].lineup[0]))
    assert engine.state.phase == Phase.RECEPTION
    assert engine.next_auto_libero_swap() is None


def test_drain_terminates_and_settles(engine, teams):
    enter_libero(engine, teams)
    engine.append(RallyPointEvent(team=HOME))
    applied = drain(engine)
    assert 1 <= len(applied) <= 3
    assert engine.next_auto_libero_swap() is None


def test_pairing_memory_resets_next_set(teams):
    eng = MatchEngine(MatchConfig(points_per_set=1, min_lead=1), teams)
    eng.append(set_start_event(teams, serving=AWAY, left=HOME))
    enter_libero(eng, teams)
    eng.append(RallyPointEvent(team=HOME))        # 1-0: set over
    assert eng.state.phase == Phase.SET_OVER
    eng.append(eng.suggest_next_set_start())
    ts = eng.state.team[HOME]
    assert ts.libero_partners == {}
    assert eng.next_auto_libero_swap() is None    # first entry manual again


# ------------------------------------- adopting an unregistered role libero


@pytest.fixture
def role_libero_teams(teams):
    """Roster player 7 really is a libero -- but the scouter never
    designated them for the set (set_start_event(with_liberos=False))."""
    teams[HOME].players[6].role = Role.LIBERO
    return teams


@pytest.fixture
def unregistered(role_libero_teams):
    eng = MatchEngine(MatchConfig(), role_libero_teams)
    eng.append(set_start_event(role_libero_teams, serving=AWAY, left=HOME,
                               with_liberos=False))
    return eng


def test_exchange_registers_the_libero_instead_of_burning_a_sub(
        unregistered, role_libero_teams):
    w = unregistered.append(LiberoSwapEvent(
        team=HOME, libero_id=lib_id(role_libero_teams),
        partner_id=hid(role_libero_teams, 4)))
    ts = unregistered.state.team[HOME]
    assert w == ["#7 was not registered as libero for this set "
                 "-- registered now"]
    assert ts.liberos == [lib_id(role_libero_teams)]
    assert ts.subs_used == 0                      # the whole point
    assert ts.sub_pairs == []
    assert ts.lineup[4] == lib_id(role_libero_teams)


def test_adopted_libero_drives_the_automatic_exchange(
        unregistered, role_libero_teams):
    enter_libero(unregistered, role_libero_teams)
    unregistered.append(RallyPointEvent(team=HOME))   # side-out: libero -> P4
    e = unregistered.next_auto_libero_swap()
    assert e is not None and e.auto
    assert e.libero_id == lib_id(role_libero_teams)
    assert e.partner_id == hid(role_libero_teams, 4)


def test_player_without_the_libero_role_still_warns_unregistered(unregistered,
                                                                 role_libero_teams):
    w = unregistered.append(LiberoSwapEvent(
        team=HOME, libero_id=hid(role_libero_teams, 7),   # H8, universal
        partner_id=hid(role_libero_teams, 4)))
    assert w == ["player is not registered as libero"]
    assert unregistered.state.team[HOME].liberos == []


def test_registration_is_reproduced_by_replay(unregistered, role_libero_teams):
    enter_libero(unregistered, role_libero_teams)
    unregistered.append(RallyPointEvent(team=HOME))
    registered = list(unregistered.state.team[HOME].liberos)
    unregistered.undo()                            # replays from set_start
    unregistered.append(RallyPointEvent(team=HOME))
    assert unregistered.state.team[HOME].liberos == registered


def test_registration_carries_into_the_next_set(role_libero_teams):
    eng = MatchEngine(MatchConfig(points_per_set=1, min_lead=1),
                      role_libero_teams)
    eng.append(set_start_event(role_libero_teams, serving=AWAY, left=HOME,
                               with_liberos=False))
    enter_libero(eng, role_libero_teams)
    eng.append(RallyPointEvent(team=HOME))         # 1-0: set over
    assert eng.suggest_next_set_start().liberos[HOME] == [
        lib_id(role_libero_teams)]


# ------------------------------------------------------------ serialization


def test_auto_flag_round_trip():
    e = LiberoSwapEvent(team=HOME, libero_id="L", partner_id="P", auto=True)
    d = event_to_dict(e)
    assert d["auto"] is True
    assert event_from_dict(d) == e


def test_legacy_swap_dict_defaults_to_manual():
    d = {"type": "libero_swap", "team": HOME, "libero_id": "L",
         "partner_id": "P", "ts": None}
    assert event_from_dict(d).auto is False


def test_legacy_config_defaults_auto_libero_on():
    d = MatchConfig().to_dict()
    d.pop("auto_libero")
    assert MatchConfig.from_dict(d).auto_libero is True
