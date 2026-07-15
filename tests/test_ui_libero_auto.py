"""Desktop automatic libero exchange: _append drains the engine-proposed
swaps (forced front-row exit, learned re-entry), one undo removes the
whole group, and auto_libero=False keeps everything manual. Runs the real
MainWindow headlessly (offscreen Qt)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6.QtWidgets")
from PyQt6.QtWidgets import QApplication          # noqa: E402

from core.engine import MatchEngine, Phase        # noqa: E402
from core.events import LiberoSwapEvent, RallyPointEvent  # noqa: E402
from core.models import AWAY, HOME, MatchConfig, Role     # noqa: E402
from ui.main_window import MainWindow             # noqa: E402

from .test_engine import make_teams, set_start_event  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def make_window(app, config=None):
    """MainWindow with a set running, AWAY serving, HOME receiving
    (lineup H1..H6, libero H7; H3 and H5 are the middles)."""
    teams = make_teams()
    teams[HOME].players[2].role = Role.MIDDLE
    teams[HOME].players[4].role = Role.MIDDLE
    w = MainWindow()
    w.teams = teams
    w.config = config or MatchConfig()
    w.engine = MatchEngine(w.config, teams)
    w.engine.append(set_start_event(teams, serving=AWAY, left=HOME))
    w.refresh()
    return w


def lib_id(win):
    return win.teams[HOME].players[6].id


def hid(win, roster_index):
    return win.teams[HOME].players[roster_index].id


def enter_libero(win):
    win._append(LiberoSwapEvent(team=HOME, libero_id=lib_id(win),
                                partner_id=hid(win, 4)))     # H5 at P5


def test_forced_exit_is_auto_appended(app):
    win = make_window(app)
    enter_libero(win)
    n = len(win.engine.events)
    win._append(RallyPointEvent(team=HOME))    # side-out: libero -> P4
    assert len(win.engine.events) == n + 2     # rally point + auto exit
    ev = win.engine.events[-1]
    assert isinstance(ev, LiberoSwapEvent) and ev.auto
    assert ev.ts is not None
    lineup = win.engine.state.team[HOME].lineup
    assert lineup[3] == hid(win, 4)            # H5 back at P4
    assert lib_id(win) not in lineup
    assert win.engine.pending_alerts() == []
    win.close()


def test_learned_reentry_is_auto_appended(app):
    win = make_window(app)
    enter_libero(win)
    # exit at P4, then rotate the middle H3 through P1 and receive:
    # the fallback entry for H3 happens on the last rally point
    for winner in (HOME, AWAY, HOME, AWAY):
        win._append(RallyPointEvent(team=winner))
    ev = win.engine.events[-1]
    assert isinstance(ev, LiberoSwapEvent) and ev.auto
    assert ev.libero_id == lib_id(win)
    assert ev.partner_id == hid(win, 2)        # H3, back-row middle
    assert lib_id(win) in win.engine.state.team[HOME].lineup
    win.close()


def test_single_undo_removes_auto_group(app):
    win = make_window(app)
    enter_libero(win)
    n = len(win.engine.events)
    win._append(RallyPointEvent(team=HOME))    # appends rally + auto exit
    assert len(win.engine.events) == n + 2
    win.on_undo()
    assert len(win.engine.events) == n         # both gone in one tap
    assert win.engine.state.phase == Phase.AWAIT_SERVE
    assert lib_id(win) in win.engine.state.team[HOME].lineup   # back at P5
    assert win.engine.state.serving_team == AWAY
    win.close()


def test_auto_libero_disabled_stays_manual(app):
    win = make_window(app, config=MatchConfig(auto_libero=False))
    enter_libero(win)
    n = len(win.engine.events)
    win._append(RallyPointEvent(team=HOME))    # libero at P4: exit is due
    assert len(win.engine.events) == n + 1     # nothing auto-appended
    assert lib_id(win) in win.engine.state.team[HOME].lineup
    assert len(win.engine.pending_alerts()) == 1
    win.close()
