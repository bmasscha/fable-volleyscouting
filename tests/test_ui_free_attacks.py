"""Desktop free-attack charting: the scouter may draw consecutive attacks by
the same team when a fast rally causes the opponent's play to go unrecorded.
Team attribution for a drawn attack now follows the half the drag starts
from (see ui.main_window.MainWindow._team_on_half), not the engine's
`attacking_team` bookkeeping. Runs the real MainWindow headlessly (offscreen
Qt); skips cleanly where PyQt6 cannot start."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6.QtWidgets")
from PyQt6.QtWidgets import QApplication          # noqa: E402

from core.engine import MatchEngine, Phase        # noqa: E402
from core.events import AttackEvent, ReceptionEvent, ServeEvent  # noqa: E402
from core.models import AWAY, HOME, MatchConfig, Rating          # noqa: E402
from ui.main_window import MainWindow             # noqa: E402

from .test_engine import make_teams, set_start_event  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _new_win(app):
    """Fresh MainWindow with a set running, HOME serving, HOME on the left."""
    teams = make_teams()
    w = MainWindow()
    w.teams = teams
    w.config = MatchConfig()
    w.engine = MatchEngine(w.config, teams)
    w.engine.append(set_start_event(teams, serving=HOME, left=HOME))
    w.engine.append(ServeEvent(team=HOME,
                               player_id=w.engine.state.team[HOME].lineup[0]))
    assert w.engine.state.phase == Phase.RECEPTION
    w.refresh()
    return w


def _win_in_attack(app):
    """MainWindow with AWAY (right side) already attacking, via a rated
    reception -- the ATTACK-phase entry point for tests 2 and 3."""
    w = _new_win(app)
    w.engine.append(ReceptionEvent(team=AWAY,
                                   player_id=w.engine.state.team[AWAY].lineup[0],
                                   rating=Rating.GOOD))
    assert w.engine.state.phase == Phase.ATTACK
    assert w.engine.state.attacking_team == AWAY
    w.refresh()
    return w


def test_same_half_second_drag_charges_same_team_twice(app):
    """A reception-phase drag (unrated reception + first attack in one
    gesture) followed by a second drag starting on the SAME half as the
    first attack produces two consecutive AttackEvents for the SAME team,
    with no engine warnings surfaced."""
    w = _new_win(app)
    # first drag: AWAY (right side) receives and attacks in one gesture,
    # ending far from the net so the second drag below can't be mistaken
    # for a block-deflection stroke
    w.on_trajectory(3.0, 2.0, 5.0, 3.0)
    assert w.engine.state.phase == Phase.ATTACK
    assert w.pending_attack is not None and w.pending_attack[0] == AWAY

    n = len(w.engine.events)
    # second drag starts on the SAME (right) half as the first attack --
    # the scouter missed the opponent's play entirely in a fast rally
    w.on_trajectory(4.0, 1.0, 6.0, 2.0)
    # the first (still-unrated) attack just got finalized as the default GOOD;
    # the second drag primes the next attack
    assert len(w.engine.events) == n + 1
    assert w.pending_attack is not None and w.pending_attack[0] == AWAY
    w.on_rating(Rating.GOOD)

    attacks = [e for e in w.engine.events if isinstance(e, AttackEvent)]
    assert len(attacks) == 2
    assert attacks[0].team == AWAY
    assert attacks[1].team == AWAY
    assert "⚠" not in w._transient_warning


def test_other_half_drag_still_charges_the_other_team(app):
    """DEFENSE phase: a drag starting on the OTHER team's half still charges
    the counter-attack to that other team -- pre-existing behavior,
    preserved even though it is now derived from the drag's start side
    instead of unconditionally from attacking_team."""
    w = _win_in_attack(app)   # AWAY (right) attacking
    w.engine.append(AttackEvent(team=AWAY,
                                player_id=w.engine.state.team[AWAY].lineup[1],
                                rating=Rating.GOOD, trajectory=None))
    assert w.engine.state.phase == Phase.DEFENSE
    w.refresh()

    n = len(w.engine.events)
    # drag starts on HOME's (left) half
    w.on_trajectory(-3.0, 2.0, -1.0, 3.0)
    assert w.pending_attack is not None and w.pending_attack[0] == HOME
    w.on_rating(Rating.GOOD)

    assert len(w.engine.events) == n + 1
    ev = w.engine.events[-1]
    assert isinstance(ev, AttackEvent)
    assert ev.team == HOME
    assert "⚠" not in w._transient_warning


def test_attack_phase_drag_from_non_holding_half_takes_possession(app):
    """ATTACK phase: even though the engine still has AWAY as
    attacking_team, a drag starting on HOME's half silently transfers
    possession to HOME -- the charted attack belongs to whichever team's
    half it starts from, and the engine accepts it without warning."""
    w = _win_in_attack(app)   # AWAY (right) holds the ball, phase ATTACK
    n = len(w.engine.events)

    w.on_trajectory(-3.0, 2.0, -1.0, 3.0)
    assert w.pending_attack is not None and w.pending_attack[0] == HOME
    w.on_rating(Rating.GOOD)

    assert len(w.engine.events) == n + 1
    ev = w.engine.events[-1]
    assert isinstance(ev, AttackEvent)
    assert ev.team == HOME
    assert "⚠" not in w._transient_warning
