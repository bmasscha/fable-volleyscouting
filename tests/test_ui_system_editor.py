"""Graphical playing-system editor: loading a base poses the tokens at its
chart coordinates, dragging a token clamps + snaps + stores it, live FIVB
overlap feedback appears in serve-contact situations, and Save/Delete drive
core.user_systems against an injectable tmp systems dir (never the real
folder, never leaving SYSTEMS polluted). Runs headlessly (offscreen Qt)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6.QtWidgets")
from PyQt6.QtWidgets import QApplication, QMessageBox   # noqa: E402
from PyQt6.QtWidgets import QGraphicsItem                # noqa: E402

from core import user_systems                            # noqa: E402
from core.formations import Mode                         # noqa: E402
from core.rotation import serve_xy                       # noqa: E402
from core.systems import SYSTEMS                          # noqa: E402
from ui.main_window import MainWindow                     # noqa: E402
from ui.player_token import (SETTER_ALT_COLOR,            # noqa: E402
                             SETTER_COLOR)
from ui.system_editor import (M, TEAM_GREEN,              # noqa: E402
                              SystemEditorWindow)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def clean_registry():
    """Snapshot and restore core.systems.SYSTEMS so a Save/Delete test never
    leaks its registry mutations into the rest of the suite."""
    snapshot = dict(SYSTEMS)
    yield
    SYSTEMS.clear()
    SYSTEMS.update(snapshot)


def _pos_m(tok):
    return (tok.pos().x() / M, tok.pos().y() / M)


def _colors(ed):
    """Each slot's token colour as lowercase hex (QColor.name())."""
    return {slot: tok.color.name() for slot, tok in ed._tokens.items()}


# --------------------------------------------------------------- posing

def test_loading_six_six_poses_tokens_at_receive_chart(app):
    ed = SystemEditorWindow()
    ed._load_base("6-6")
    chart = SYSTEMS["6-6"].charts[Mode.RECEIVE][0]
    for slot, (x, y) in chart.items():
        px, py = _pos_m(ed._tokens[slot])
        assert px == pytest.approx(x)
        assert py == pytest.approx(y)
    ed.close()


def test_loading_five_one_key_three_offense_poses_that_chart(app):
    ed = SystemEditorWindow()
    ed._load_base("5-1")
    ed._set_key(3)
    ed._tabs.setCurrentIndex(ed._tab_index(Mode.OFFENSE))
    assert ed._current_mode() is Mode.OFFENSE
    chart = SYSTEMS["5-1"].charts[Mode.OFFENSE][3]
    for slot, (x, y) in chart.items():
        px, py = _pos_m(ed._tokens[slot])
        assert px == pytest.approx(x)
        assert py == pytest.approx(y)
    ed.close()


# --------------------------------------------------------- setter colours

def test_six_two_paints_both_setters(app):
    """A 6-2 declares two setters, so the acting setter and its diagonal
    are both blue -- the whole point of the alt colour."""
    ed = SystemEditorWindow()
    ed._load_base("6-2")
    ed._set_key(1)
    assert ed._setter_slots() == [1, 4]
    colors = _colors(ed)
    assert colors[1] == SETTER_COLOR
    assert colors[4] == SETTER_ALT_COLOR
    for slot in (0, 2, 3, 5):
        assert colors[slot] == TEAM_GREEN
    # and the second setter reads "S", not the "OPP" slot it stands in
    assert ed._tokens[1].hint == "S"
    assert ed._tokens[4].hint == "S"
    ed.close()


def test_raising_expected_setters_to_three_reposes_as_a_six_three(app):
    """The spin box is a live display control: bumping it to 3 must
    re-pose straight away and light up the 6-3's three setters."""
    ed = SystemEditorWindow()
    ed._load_base("6-2")
    ed._set_key(1)
    ed._expected_spin.setValue(3)               # fires valueChanged
    assert ed._setter_slots() == [1, 3, 5]
    colors = _colors(ed)
    assert colors[1] == SETTER_COLOR
    assert colors[3] == SETTER_ALT_COLOR
    assert colors[5] == SETTER_ALT_COLOR
    for slot in (0, 2, 4):
        assert colors[slot] == TEAM_GREEN
        assert ed._tokens[slot].hint != "S"
    ed.close()


def test_five_one_paints_exactly_one_setter(app):
    ed = SystemEditorWindow()
    ed._load_base("5-1")
    ed._set_key(2)
    colors = _colors(ed)
    assert colors[2] == SETTER_COLOR
    assert [s for s, c in colors.items()
            if c in (SETTER_COLOR, SETTER_ALT_COLOR)] == [2]
    ed.close()


def test_keyless_six_six_paints_only_its_fixed_setting_slot(app):
    """A keyless system has no setter role, so its 0 expected setters must
    not blank the one slot that actually sets (P3)."""
    ed = SystemEditorWindow()
    ed._load_base("6-6")
    assert ed._expected_spin.value() == 0
    colors = _colors(ed)
    assert colors[2] == SETTER_COLOR
    assert [s for s, c in colors.items()
            if c in (SETTER_COLOR, SETTER_ALT_COLOR)] == [2]
    assert ed._tokens[2].hint == "sets"
    assert ed._tokens[0].hint == ""
    ed.close()


# ----------------------------------------------------------- drag / clamp

def test_moving_a_token_snaps_to_tenths_and_stores(app):
    ed = SystemEditorWindow()
    ed._load_base("6-6")                       # RECEIVE, key 0
    ed._tokens[1].setPos(-2.03 * M, 3.07 * M)
    ed._token_released(1)
    assert ed._working[Mode.RECEIVE][0][1] == (-2.0, 3.1)
    ed.close()


def test_dropping_outside_bounds_is_clamped(app):
    ed = SystemEditorWindow()
    ed._load_base("6-6")
    ed._tokens[1].setPos(-99 * M, 99 * M)      # far past both bounds
    ed._token_released(1)
    assert ed._working[Mode.RECEIVE][0][1] == (-13.0, 11.5)
    ed.close()


# ----------------------------------------------------- overlap feedback

def test_receive_overlap_warning_appears_and_clears(app):
    ed = SystemEditorWindow()
    ed._load_base("6-6")                       # a legal RECEIVE chart
    assert ed._warning.text() == ""
    p6x = ed._tokens[5].pos().x()
    p3y = ed._tokens[2].pos().y()
    # push P3 (front middle) behind P6 (back middle): only the P3/P6 front
    # pair is broken (smaller x = further from the net on the left half)
    ed._tokens[2].setPos(p6x - 1.5 * M, p3y)
    ed._token_released(2)
    assert "P3 must be in front of P6" in ed._warning.text()
    assert ed._tokens[2].warn and ed._tokens[5].warn
    # move it back in front of P6 -> legal again, label + rings clear
    ed._tokens[2].setPos(p6x + 3.0 * M, p3y)
    ed._token_released(2)
    assert ed._warning.text() == ""
    assert not ed._tokens[2].warn and not ed._tokens[5].warn
    ed.close()


def test_offense_tab_has_no_overlap_ui(app):
    ed = SystemEditorWindow()
    ed._load_base("6-6")
    ed._tabs.setCurrentIndex(ed._tab_index(Mode.OFFENSE))
    # even a wildly illegal drop shows no overlap warning off the serve
    ed._tokens[2].setPos(-8.0 * M, 4.5 * M)
    ed._token_released(2)
    assert ed._warning.text() == ""
    ed.close()


# -------------------------------------------------------------- serve tab

def test_serve_server_is_pinned_and_not_stored(app):
    ed = SystemEditorWindow()
    ed._load_base("6-6")
    ed._tabs.setCurrentIndex(ed._tab_index(Mode.SERVE_BASE))
    server = ed._tokens[0]
    assert not (server.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
    sx, sy = serve_xy("left")
    px, py = _pos_m(server)
    assert px == pytest.approx(sx)
    assert py == pytest.approx(sy)
    # the serve chart holds slots 1..5 only; a release of slot 0 stores nothing
    assert set(ed._working[Mode.SERVE_BASE][0]) == {1, 2, 3, 4, 5}
    ed._token_released(0)
    assert 0 not in ed._working[Mode.SERVE_BASE][0]
    # a real serve-slot edit lands in slots 1..5
    ed._tokens[3].setPos(-1.2 * M, 2.4 * M)
    ed._token_released(3)
    assert ed._working[Mode.SERVE_BASE][0][3] == (-1.2, 2.4)
    ed.close()


# ------------------------------------------------------------ save / delete

def test_save_is_offered_on_a_builtin_id_with_a_copy_hint(app):
    ed = SystemEditorWindow()
    ed._load_base("6-6")                       # id field is now the built-in
    assert ed._save_btn.isEnabled()            # never a dead button
    assert "keeps your changes as a copy" in ed._id_hint.text()
    ed._id_edit.setText("my-6-6")
    assert ed._save_btn.isEnabled()
    assert ed._id_hint.text() == ""
    ed._id_edit.setText("not a valid id")      # only a malformed id blocks
    assert not ed._save_btn.isEnabled()
    assert "id must start alphanumeric" in ed._id_hint.text()
    ed.close()


def test_saving_on_top_of_a_builtin_stores_a_copy(
        app, tmp_path, clean_registry):
    builtin = SYSTEMS["6-6"]
    ed = SystemEditorWindow(systems_base=str(tmp_path))
    ed._load_base("6-6")                       # id field is the built-in
    ed._on_save()

    # the built-in is untouched and the edits landed under a free copy id
    assert not (tmp_path / "6-6.json").exists()
    assert (tmp_path / "6-6-copy.json").exists()
    assert SYSTEMS["6-6"] is builtin
    assert "6-6-copy" in SYSTEMS
    assert "cannot be changed" in ed.statusBar().currentMessage()
    # the editor now edits the copy, so a second Save updates it in place
    assert ed._id_edit.text() == "6-6-copy"
    assert ed._delete_btn.isEnabled()

    # a further save straight off the built-in must not clobber that copy
    ed._load_base("6-6")
    ed._on_save()
    assert (tmp_path / "6-6-copy-2.json").exists()
    ed.close()


def test_save_then_delete_round_trips_through_the_registry(
        app, tmp_path, clean_registry, monkeypatch):
    ed = SystemEditorWindow(systems_base=str(tmp_path))
    ed._load_base("6-6")
    ed._id_edit.setText("my-6-6")

    fired = []
    ed.systems_changed.connect(lambda: fired.append(1))
    ed._on_save()

    # the signal fired and the file round-trips to an equal spec
    assert fired
    loaded, problems = user_systems.load_user_systems(base=tmp_path)
    assert problems == []
    assert "my-6-6" in loaded
    assert loaded["my-6-6"] == ed._build_spec("my-6-6")
    # refresh put it into the live registry, after the built-ins
    assert "my-6-6" in SYSTEMS
    assert (tmp_path / "my-6-6.json").exists()

    # delete removes the file and drops it from the registry again
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    ed._id_edit.setText("my-6-6")
    assert ed._delete_btn.isEnabled()
    fired.clear()
    ed._on_delete()
    assert fired
    assert not (tmp_path / "my-6-6.json").exists()
    assert "my-6-6" not in SYSTEMS
    ed.close()


# --------------------------------------------------------- main window hook

def test_toolbar_action_opens_the_editor(app):
    w = MainWindow()
    assert hasattr(w, "system_editor_action")
    assert w.system_editor_action.isEnabled()   # no match needed
    assert w.system_editor is None
    w.open_system_editor()
    assert isinstance(w.system_editor, SystemEditorWindow)
    # opening again re-uses the one instance
    same = w.system_editor
    w.open_system_editor()
    assert w.system_editor is same
    w.system_editor.close()
    w.close()
