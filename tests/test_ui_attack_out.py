"""Desktop auto-scored attack errors: an attack drawn to a landing the ball
could not legally reach -- outside the lines, or short on the attacker's own
half -- ends the rally with '!' on the drag itself, no rating tap, mirroring
the way an out serve is auto-rated. The override chips fix the one case the
geometry cannot see: a defensive touch that put the ball out.
Runs the real MainWindow headlessly (offscreen Qt); skips cleanly where
PyQt6 cannot start."""
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


def _score(win):
    return dict(win.engine.state.scores)


def test_attack_past_the_baseline_scores_for_the_other_team(win):
    before = _score(win)
    n = len(win.engine.events)

    # AWAY attacks from its own half clean past HOME's baseline
    win.on_trajectory(4.0, 4.5, -9.8, 4.5)

    assert win.pending_attack is None          # no rating tap needed
    assert len(win.engine.events) == n + 1
    ev = win.engine.events[-1]
    assert isinstance(ev, AttackEvent)
    assert ev.team == AWAY
    assert ev.rating == Rating.ERROR
    assert ev.trajectory == (4.0, 4.5, -9.8, 4.5)
    assert ev.block_touch is None
    # the rally is over: the point and the serve go to HOME
    assert _score(win)[HOME] == before[HOME] + 1
    assert _score(win)[AWAY] == before[AWAY]
    assert win.engine.state.phase == Phase.AWAIT_SERVE
    assert win.engine.state.serving_team == HOME


def test_attack_wide_of_the_sideline_scores_for_the_other_team(win):
    before = _score(win)
    win.on_trajectory(4.0, 4.5, -3.0, 9.8)
    assert win.engine.events[-1].rating == Rating.ERROR
    assert _score(win)[HOME] == before[HOME] + 1


def test_attack_that_never_crossed_the_net_is_an_error(win):
    """A ball hit into the net stops on the attacker's own side."""
    before = _score(win)
    win.on_trajectory(4.0, 4.5, 2.0, 4.5)
    assert win.pending_attack is None
    ev = win.engine.events[-1]
    assert isinstance(ev, AttackEvent)
    assert ev.team == AWAY
    assert ev.rating == Rating.ERROR
    assert _score(win)[HOME] == before[HOME] + 1


def test_attack_landing_in_the_opponents_court_still_waits_for_a_rating(win):
    before = _score(win)
    n = len(win.engine.events)
    win.on_trajectory(4.0, 4.5, -5.0, 4.5)
    # nothing committed yet -- the scouter still scores it
    assert len(win.engine.events) == n
    assert win.pending_attack is not None
    assert win.pending_attack[0] == AWAY
    assert _score(win) == before


def test_just_inside_the_line_is_not_an_error(win):
    """The 0.4 m OUT_TOLERANCE keeps a drag along the line in play."""
    n = len(win.engine.events)
    win.on_trajectory(4.0, 4.5, -9.4, 4.5)
    assert len(win.engine.events) == n
    assert win.pending_attack is not None


def test_chips_offer_a_fix_for_a_defensive_touch_out(win):
    """A defender who puts the ball out makes it the attacker's point; the
    geometry cannot see that touch, so the chips re-rate the auto '!'."""
    before = _score(win)
    win.on_trajectory(4.0, 4.5, -9.8, 4.5)
    n = len(win.engine.events)
    assert win.engine.events[-1].rating == Rating.ERROR

    win.on_rate_chip(Rating.PERFECT)

    assert len(win.engine.events) == n         # replaced, not appended
    ev = win.engine.events[-1]
    assert isinstance(ev, AttackEvent)
    assert ev.rating == Rating.PERFECT
    assert ev.trajectory == (4.0, 4.5, -9.8, 4.5)
    # the point swings to the attackers, who now serve
    assert _score(win)[AWAY] == before[AWAY] + 1
    assert _score(win)[HOME] == before[HOME]
    assert win.engine.state.serving_team == AWAY
    # the chips stay up, so an override can be taken back without undo
    assert not win.rating_bar._chip_widgets[Rating.ERROR].isHidden()
    win.on_rate_chip(Rating.ERROR)
    assert win.engine.events[-1].rating == Rating.ERROR
    assert _score(win)[HOME] == before[HOME] + 1


def test_chips_are_shown_after_an_auto_scored_attack_error(win):
    # isHidden(), not isVisible(): the window itself is never shown offscreen
    win.on_trajectory(4.0, 4.5, -9.8, 4.5)
    assert not win.rating_bar._chip_widgets[Rating.ERROR].isHidden()
    # and they are labelled for the attack, not the serve
    assert "attack" in win.rating_bar._chip_label.text()


def test_chips_go_back_to_the_serve_once_the_next_serve_is_drawn(win):
    win.on_trajectory(4.0, 4.5, -9.8, 4.5)
    assert "attack" in win.rating_bar._chip_label.text()

    server = win.engine.expected_server()
    win.on_trajectory(-9.0, 4.5, 4.0, 4.5)     # HOME serves in
    assert win.engine.events[-1].player_id == server
    # the chips now belong to that serve again, not the finished attack
    assert "serve" in win.rating_bar._chip_label.text()


def test_chips_are_hidden_while_an_attack_awaits_its_rating(win):
    win.on_trajectory(4.0, 4.5, -5.0, 4.5)     # lands in -- primes, no chips
    assert win.pending_attack is not None
    assert win.rating_bar._chip_widgets[Rating.ERROR].isHidden()


def test_block_gesture_survives_the_rule(win):
    """Stroke 1 of a block is drawn just ACROSS the net, so it is never an
    error and still primes the deflection stroke."""
    win.on_trajectory(4.0, 4.5, -0.2, 4.5)
    assert win.pending_attack is not None
    n = len(win.engine.events)

    win.on_trajectory(-0.1, 4.6, 9.7, 4.5)     # block puts it out -> kill
    assert len(win.engine.events) == n + 1
    ev = win.engine.events[-1]
    assert ev.rating == Rating.PERFECT
    assert ev.block_touch == (-0.2, 4.5)


def test_undo_restores_the_pre_attack_state(win):
    before = _score(win)
    n = len(win.engine.events)
    win.on_trajectory(4.0, 4.5, -9.8, 4.5)
    assert len(win.engine.events) == n + 1

    win.on_undo()

    assert len(win.engine.events) == n
    assert _score(win) == before
    assert win.engine.state.phase == Phase.ATTACK
