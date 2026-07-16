"""Desktop two-stroke block gesture: a second drag off a primed attack
that ends by the net auto-finalizes the AttackEvent with a block_touch and
the outcome-derived rating. Runs the real MainWindow headlessly (offscreen
Qt); skips cleanly where PyQt6 cannot start."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6.QtWidgets")
from PyQt6.QtWidgets import QApplication          # noqa: E402

from core.blocks import BLOCK_NET_ZONE            # noqa: E402
from core.engine import MatchEngine, Phase        # noqa: E402
from core.events import AttackEvent, ReceptionEvent, ServeEvent  # noqa: E402
from core.formations import Mode                   # noqa: E402
from core.models import AWAY, HOME, MatchConfig, Rating          # noqa: E402
from ui.main_window import MainWindow             # noqa: E402

from .test_engine import make_teams, set_start_event  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(app):
    """MainWindow with a set running, AWAY (right side) in ATTACK phase."""
    teams = make_teams()
    w = MainWindow()
    w.teams = teams
    w.config = MatchConfig()
    w.engine = MatchEngine(w.config, teams)
    w.engine.append(set_start_event(teams, serving=HOME, left=HOME))
    w.engine.append(ServeEvent(team=HOME,
                               player_id=w.engine.state.team[HOME].lineup[0]))
    w.engine.append(ReceptionEvent(team=AWAY,
                                   player_id=w.engine.state.team[AWAY].lineup[0],
                                   rating=Rating.GOOD))
    assert w.engine.state.phase == Phase.ATTACK
    assert w.engine.state.attacking_team == AWAY
    w.refresh()
    yield w
    w.close()


def _prime_near_net(win, tip=(0.2, 4.5)):
    """First drag: an AWAY attack that ends by the net (primes pending)."""
    win.on_trajectory(4.0, 4.5, tip[0], tip[1])
    assert win.pending_attack is not None
    assert abs(tip[0]) <= BLOCK_NET_ZONE


def test_deflection_out_scores_a_point(win):
    _prime_near_net(win)
    n = len(win.engine.events)
    # second stroke: block deflects the ball out past the right baseline
    win.on_trajectory(0.3, 4.6, 9.7, 4.5)
    assert win.pending_attack is None
    assert len(win.engine.events) == n + 1
    ev = win.engine.events[-1]
    assert isinstance(ev, AttackEvent)
    assert ev.team == AWAY
    assert ev.rating == Rating.PERFECT
    assert ev.block_touch == (0.2, 4.5)
    assert ev.trajectory == (4.0, 4.5, 9.7, 4.5)


def test_deflection_back_to_attacker_half_is_covered(win):
    _prime_near_net(win)
    # deflection lands in-bounds on AWAY's own (right) half -> covered
    win.on_trajectory(0.25, 4.4, 3.0, 4.0)
    ev = win.engine.events[-1]
    assert ev.rating == Rating.POOR
    assert ev.block_touch == (0.2, 4.5)
    # engine keeps the rally alive; AWAY must cover its own ball
    assert win.engine.state.phase == Phase.DEFENSE
    assert win.candidate is not None and win.candidate[0] == AWAY


def test_deflection_onto_blockers_half_stays_in_play(win):
    _prime_near_net(win)
    # deflection lands on HOME's (left) half -> in play, HOME defends
    win.on_trajectory(0.25, 4.4, -3.0, 4.0)
    ev = win.engine.events[-1]
    assert ev.rating == Rating.GOOD
    assert ev.block_touch == (0.2, 4.5)
    assert win.engine.state.phase == Phase.DEFENSE
    assert win.candidate is not None and win.candidate[0] == HOME


def test_unrated_second_drag_finalizes_previous_as_good(win):
    # primed AWAY attack ends far from the net, so no deflection is possible
    win.on_trajectory(6.0, 4.5, 5.0, 4.5)
    assert win.pending_attack is not None
    n = len(win.engine.events)
    # a second drag, not a block deflection (press nowhere near the arrow
    # tip), finalizes the previous attack as the default '+' (in play) and
    # primes the opponent's counter-attack -- letting a fast rally be
    # charted without stopping to score each contact
    win.on_trajectory(3.0, 2.0, 4.0, 3.0)
    assert len(win.engine.events) == n + 1      # previous attack committed
    ev = win.engine.events[-1]
    assert isinstance(ev, AttackEvent)
    assert ev.team == AWAY
    assert ev.rating == Rating.GOOD
    assert ev.trajectory == (6.0, 4.5, 5.0, 4.5)
    # a GOOD attack sends the ball to HOME to defend; the new drag primes
    # HOME's counter-attack, still unrated
    assert win.engine.state.phase == Phase.DEFENSE
    assert win.pending_attack is not None
    assert win.pending_attack[0] == HOME
    assert win.pending_attack[2] == (3.0, 2.0, 4.0, 3.0)
    # the formations flip to the pending attacker at once: HOME (now
    # counter-attacking) shows offence, AWAY drops to defence
    assert win._team_mode(HOME) == Mode.OFFENSE
    assert win._team_mode(AWAY) == Mode.DEFENSE
