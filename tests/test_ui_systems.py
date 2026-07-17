"""Desktop playing-systems UI: the toolbar's per-team system pickers drive
core.systems (positions, acting setter) instead of the old core.formations
5-1-only path, and the setup wizard lets each team pick its system. Runs the
real MainWindow / MatchSetupDialog headlessly (offscreen Qt)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6.QtWidgets")
from PyQt6.QtWidgets import QApplication          # noqa: E402

from core.engine import MatchEngine, Phase        # noqa: E402
from core.models import AWAY, HOME, MatchConfig, Role  # noqa: E402
from core.systems import DEFAULT_SYSTEM           # noqa: E402
from ui.main_window import MainWindow             # noqa: E402
from ui.setup_wizard import MatchSetupDialog, _TeamPanel  # noqa: E402

from .test_engine import make_teams, set_start_event  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def make_window(app):
    """MainWindow with a set running, AWAY serving so HOME is in RECEIVE
    formation. HOME's P1 is a real setter so the 5-1 chart is not just the
    no-setter grid fallback -- a meaningful baseline to diff 6-6 against."""
    teams = make_teams()
    teams[HOME].players[0].role = Role.SETTER
    w = MainWindow()
    w.teams = teams
    w.config = MatchConfig()
    w.engine = MatchEngine(w.config, teams)
    w.engine.append(set_start_event(teams, serving=AWAY, left=HOME))
    w.refresh()
    return w


def test_switching_home_to_six_six_via_toolbar_changes_positions(app):
    win = make_window(app)
    assert win.engine.state.phase == Phase.AWAIT_SERVE
    assert win.engine.state.serving_team == AWAY   # HOME is receiving
    assert win.config.systems[HOME] == "5-1"

    before = win._positions(HOME)

    win.system_actions[HOME]["6-6"].trigger()

    assert win.config.systems[HOME] == "6-6"
    assert win.system_buttons[HOME].text() == "Home: 6-6"
    after = win._positions(HOME)
    assert after != before
    win.close()


def test_acting_setter_id_for_six_six_is_lineup_slot_two_regardless_of_roles(app):
    teams = make_teams()
    # a SETTER-role player sits at P5 (slot 4) -- irrelevant for a 6-6,
    # which always credits whoever stands at P3 (slot 2)
    teams[HOME].players[4].role = Role.SETTER
    w = MainWindow()
    w.teams = teams
    w.config = MatchConfig(systems={HOME: "6-6", AWAY: DEFAULT_SYSTEM})
    w.engine = MatchEngine(w.config, teams)
    w.engine.append(set_start_event(teams, serving=AWAY, left=HOME))
    w.refresh()

    expected = w.engine.state.team[HOME].lineup[2]
    assert w._acting_setter_id(HOME) == expected
    w.close()


def test_team_panel_defaults_to_five_one_and_exposes_selection(app):
    panel = _TeamPanel("Home team")
    assert panel.system_id() == DEFAULT_SYSTEM
    idx = panel.system_combo.findData("6-2")
    assert idx >= 0
    panel.system_combo.setCurrentIndex(idx)
    assert panel.system_id() == "6-2"


def test_wizard_config_reflects_the_two_system_selections(app):
    dlg = MatchSetupDialog()
    teams = make_teams()
    # override whatever roster library is on disk with a known pair
    dlg.home_panel.set_library([teams[HOME]], keep_selection=False)
    dlg.away_panel.set_library([teams[AWAY]], keep_selection=False)
    dlg.home_panel.select_index(0)
    dlg.away_panel.select_index(0)

    home_idx = dlg.home_panel.system_combo.findData("6-2")
    away_idx = dlg.away_panel.system_combo.findData("6-6")
    dlg.home_panel.system_combo.setCurrentIndex(home_idx)
    dlg.away_panel.system_combo.setCurrentIndex(away_idx)

    error = dlg.build_result()
    assert error is None
    assert dlg.config.systems == {HOME: "6-2", AWAY: "6-6"}
    dlg.close()


def test_wizard_hint_flags_a_setter_count_mismatch(app):
    panel = _TeamPanel("Home team")
    teams = make_teams()
    teams[HOME].players[0].role = Role.SETTER   # only one setter in lineup
    panel.set_library([teams[HOME]], keep_selection=False)
    panel.select_index(0)

    idx = panel.system_combo.findData("6-2")   # 6-2 expects two setters
    panel.system_combo.setCurrentIndex(idx)
    assert "expects 2 setter" in panel.system_hint.text()

    idx = panel.system_combo.findData(DEFAULT_SYSTEM)  # 5-1 expects one
    panel.system_combo.setCurrentIndex(idx)
    assert panel.system_hint.text() == ""

    idx = panel.system_combo.findData("6-6")   # keyless: never a hint
    panel.system_combo.setCurrentIndex(idx)
    assert panel.system_hint.text() == ""
