"""Desktop 6-2 rendering: only the setter actually running the offence
is painted as a setter; the front-row setter reads as the attacker they
are. Ambiguous lineups keep both marked and say why. Runs the real
MainWindow headlessly (offscreen Qt)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6.QtWidgets")
from PyQt6.QtWidgets import QApplication          # noqa: E402

from core.engine import MatchEngine              # noqa: E402
from core.events import RotationAdjustEvent      # noqa: E402
from core.models import AWAY, HOME, MatchConfig, Role  # noqa: E402
from ui.main_window import MainWindow            # noqa: E402
from ui.player_token import SETTER_COLOR         # noqa: E402

from .test_engine import make_teams, set_start_event  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def make_window(app, setter_slots=(0, 3)):
    """MainWindow with a set running and HOME set up as a 6-2: setters at
    the two given lineup slots (diagonal by default), the rest hitters."""
    teams = make_teams()
    for i in range(6):
        teams[HOME].players[i].role = (Role.SETTER if i in setter_slots
                                       else Role.OUTSIDE)
    w = MainWindow()
    w.teams = teams
    w.config = MatchConfig()
    w.engine = MatchEngine(w.config, teams)
    w.engine.append(set_start_event(teams, serving=AWAY, left=HOME))
    w.formations_enabled = True
    # capture what refresh() actually hands to the court
    w.captured = {}
    original = w.court.update_tokens

    def spy(specs):
        w.captured = {s["player_id"]: s for s in specs}
        original(specs)

    w.court.update_tokens = spy
    w.refresh()
    return w


def token_of(win, player_id):
    return win.captured[player_id]


def test_only_the_acting_setter_is_painted_as_setter(app):
    win = make_window(app)                     # setters at P1 and P4
    s1 = win.teams[HOME].players[0].id         # P1, back row -> acting
    s2 = win.teams[HOME].players[3].id         # P4, front row -> hitting
    assert win._acting_setter_id(HOME) == s1
    assert token_of(win, s1)["color"] == SETTER_COLOR
    assert token_of(win, s2)["color"] == win.teams[HOME].color
    # both keep the S badge: they are setters by trade, one is hitting
    assert token_of(win, s1)["badge"] == "S"
    assert token_of(win, s2)["badge"] == "S"
    win.close()


def test_the_blue_setter_changes_hands_on_the_handover(app):
    win = make_window(app)
    s1 = win.teams[HOME].players[0].id
    s2 = win.teams[HOME].players[3].id
    # three rotations put S1 in the front row and S2 at P1
    win._append(RotationAdjustEvent(team=HOME, steps=3))
    assert win.engine.state.team[HOME].lineup[0] == s2
    assert win._acting_setter_id(HOME) == s2
    assert token_of(win, s2)["color"] == SETTER_COLOR
    assert token_of(win, s1)["color"] == win.teams[HOME].color
    win.close()


def test_five_one_setter_stays_blue_in_the_front_row(app):
    win = make_window(app, setter_slots=(0,))  # a single setter
    s = win.teams[HOME].players[0].id
    win._append(RotationAdjustEvent(team=HOME, steps=3))   # rotate to front
    assert win.engine.state.team[HOME].lineup.index(s) in (1, 2, 3)
    assert win._acting_setter_id(HOME) == s
    assert token_of(win, s)["color"] == SETTER_COLOR
    win.close()


def test_ambiguous_lineup_marks_both_and_explains(app):
    win = make_window(app, setter_slots=(0, 4))   # both back row
    s1 = win.teams[HOME].players[0].id
    s2 = win.teams[HOME].players[4].id
    assert win._acting_setter_id(HOME) is None
    # cannot tell who is setting -> keep both marked rather than neither
    assert token_of(win, s1)["color"] == SETTER_COLOR
    assert token_of(win, s2)["color"] == SETTER_COLOR
    assert "diagonal" in win.scoreboard.alert.text()
    win.close()


def test_valid_six_two_says_nothing(app):
    win = make_window(app)
    assert "diagonal" not in win.scoreboard.alert.text()
    win.close()
