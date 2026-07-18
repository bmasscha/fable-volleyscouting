"""Graphical playing-system editor.

A coach opens a built-in system (5-1, 6-2, 6-6, ...), drags the six
player tokens around the court per situation and per setter rotation,
and saves the result as a NEW custom system. Persistence, validation
and the registry merge already live in ``core.user_systems`` -- this
module is only the editing surface on top of them; it never writes a
file or mutates the registry itself except through those functions.

Why the token drag can never produce an unsaveable system: every token
is clamped live (``_EditorToken.itemChange``) to the deserializer's
coordinate box (x in [-13, 0], y in [-2.5, 11.5]) and snapped to the
0.1 m grid the built-in charts are authored on when it is dropped, so a
``save_user_system`` of the working state always passes validation.

The editor edits a deep working copy of a base system's charts, keyed
exactly like ``core.systems``: ``charts[mode][key][slot] -> (x, y)`` on
the LEFT half. ``key`` is the acting setter's slot 0..5 for setter-keyed
systems, the single constant 0 for keyless ones (which instead carry a
``fixed_setter_slot``). ``Mode.SERVE_BASE`` holds slots 1..5 only -- slot
0 is the server, pinned at ``serve_xy`` and never stored. ``Mode.GRID``
is the rotational fallback and is not editable here.

The id field IS the save target: Save is a unified save / save-as /
overwrite-your-own-copy that is only enabled for a regex-valid,
non-built-in id (built-ins can never be shadowed). ``systems_changed``
lets the main window rebuild its per-team menus once a system is saved
or deleted. A ``systems_base`` constructor kwarg (default = the real
``systems_dir``) is threaded through every persistence call so tests can
point the whole editor at a tmp directory.
"""
from __future__ import annotations

import re

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (QButtonGroup, QComboBox, QGraphicsItem,
                             QGraphicsObject, QGraphicsScene, QGraphicsView,
                             QHBoxLayout, QLabel, QLineEdit, QMainWindow,
                             QMessageBox, QPushButton, QSpinBox, QTabBar,
                             QVBoxLayout, QWidget)

from core import user_systems
from core.formations import Mode, _OFFSET_CATEGORY, overlap_violations
from core.rotation import serve_xy
from core.systems import (DEFAULT_SYSTEM, SYSTEMS, SystemSpec, get_system,
                          system_ids)
from core.user_systems import BUILTIN_IDS, systems_dir

from .court_view import (COURT_COLOR, FREE_ZONE_COLOR, FRONT_ZONE_COLOR,
                         LINE_PEN, M, NET_PEN)
from .player_token import SETTER_COLOR, TOKEN_RADIUS

# Neutral team colour for the non-setting tokens (matches the app's
# default token green in ui/player_token.py).
TEAM_GREEN = "#2e7d32"
OVERLAP_RING = "#e53935"

# The deserializer's coordinate box (mirrors core.user_systems); clamping
# to it live guarantees a save never fails validation.
X_MIN, X_MAX = -13.0, 0.0
Y_MIN, Y_MAX = -2.5, 11.5

# Must agree with core.user_systems._ID_RE -- the authority that actually
# accepts or rejects the id on save; duplicated here only to drive the
# Save button's enabled state live as the user types.
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")

# Situation tabs in display order -> chart mode. GRID is never edited.
_TAB_MODES = [Mode.RECEIVE, Mode.SERVE_BASE, Mode.OFFENSE, Mode.DEFENSE]
_TAB_LABELS = ["Receive", "Serve", "Offense", "Defense"]
_STORED_MODES = (Mode.RECEIVE, Mode.SERVE_BASE, Mode.OFFENSE, Mode.DEFENSE)

# From core.rotation.COURT_HALF_LENGTH + FREE_ZONE_X etc., but pinned to
# the deserializer box so the drawable area and the clamp box coincide.
COURT_HALF = 9.0
COURT_W = 9.0
ATTACK = 3.0


class _EditorToken(QGraphicsObject):
    """One draggable player disc. Movable + live-clamped to the coordinate
    box; the owning editor is notified on drag (for live overlap feedback)
    and on release (to snap + store the new coordinate)."""

    def __init__(self, slot: int, editor: "SystemEditorWindow"):
        super().__init__()
        self.slot = slot
        self._editor = editor
        self.label = f"P{slot + 1}"
        self.hint = ""
        self.color = QColor(TEAM_GREEN)
        self.ghost = False   # the serve server: pinned + dimmed
        self.warn = False    # named in an overlap violation -> red ring
        self.setZValue(10)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges,
                     True)

    def set_movable(self, movable: bool) -> None:
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, movable)

    def boundingRect(self) -> QRectF:
        r = TOKEN_RADIUS + 6
        return QRectF(-r, -r, 2 * r, 2 * r + 18)

    def paint(self, painter, option, widget=None) -> None:
        r = TOKEN_RADIUS
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self.ghost:
            painter.setOpacity(0.4)
        if self.warn:
            painter.setPen(QPen(QColor(OVERLAP_RING), 5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(-r - 4, -r - 4, 2 * r + 8, 2 * r + 8))
        painter.setPen(QPen(QColor("white"), 2))
        painter.setBrush(QBrush(self.color))
        painter.drawEllipse(QRectF(-r, -r, 2 * r, 2 * r))
        painter.setPen(QColor("white"))
        painter.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        painter.drawText(QRectF(-r, -r, 2 * r, 2 * r),
                         Qt.AlignmentFlag.AlignCenter, self.label)
        if self.hint:
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            painter.setPen(QColor("#101010"))
            painter.drawText(QRectF(-r - 6, r + 2, 2 * r + 12, 14),
                             Qt.AlignmentFlag.AlignHCenter, self.hint)

    def itemChange(self, change, value):
        Change = QGraphicsItem.GraphicsItemChange
        if change == Change.ItemPositionChange and self.scene() is not None:
            x = min(max(value.x(), X_MIN * M), X_MAX * M)
            y = min(max(value.y(), Y_MIN * M), Y_MAX * M)
            return QPointF(x, y)
        if change == Change.ItemPositionHasChanged:
            self._editor._token_dragged(self.slot)
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        self._editor._token_released(self.slot)


class _EditorCourt(QGraphicsView):
    """Left half of the court plus its free zone, drawn in the app's court
    colours. Tokens are added to its scene by the editor."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        # x from -(court + free zone) to a hair past the net; y over the
        # full width plus the free zone on both sidelines -- exactly the
        # clamp box, so a token can be dropped anywhere it is drawable.
        self._scene.setSceneRect(X_MIN * M, Y_MIN * M,
                                 (X_MAX - X_MIN) * M + 0.5 * M,
                                 (Y_MAX - Y_MIN) * M)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setMinimumSize(520, 460)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.fitInView(self._scene.sceneRect(),
                       Qt.AspectRatioMode.KeepAspectRatio)

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, FREE_ZONE_COLOR)
        L, W, A = COURT_HALF * M, COURT_W * M, ATTACK * M
        court = QRectF(-L, 0, L, W)             # left half only
        painter.fillRect(court, COURT_COLOR)
        painter.fillRect(QRectF(-A, 0, A, W), FRONT_ZONE_COLOR)
        painter.setPen(LINE_PEN)
        painter.drawRect(court)
        painter.drawLine(QPointF(-A, 0), QPointF(-A, W))      # attack line
        painter.setPen(NET_PEN)                               # net at x = 0
        painter.drawLine(QPointF(0, -0.6 * M), QPointF(0, W + 0.6 * M))
        painter.setPen(QPen(QColor("white"), 2, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(0, 0), QPointF(0, W))        # centre line


class SystemEditorWindow(QMainWindow):
    """Non-modal editor. Emits ``systems_changed`` after every save or
    delete so the main window can rebuild its per-team system menus."""

    systems_changed = pyqtSignal()

    def __init__(self, systems_base=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Playing-system editor")
        self._systems_base = systems_base

        # working state (a deep copy of the loaded base; see _load_base)
        self._working: dict = {}
        self._uses_setter_roles = True
        self._fixed_setter_slot = 0
        self._current_key = 0
        self._base_id = DEFAULT_SYSTEM
        self._suspend_feedback = False     # guards programmatic re-posing

        self._tokens: dict[int, _EditorToken] = {}
        self._build_ui()
        self._refresh_base_combo(select=DEFAULT_SYSTEM)

    # ----------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # --- top bar: base picker + Save / Delete / Revert
        top = QHBoxLayout()
        top.addWidget(QLabel("Base system:"))
        self._base_combo = QComboBox()
        self._base_combo.setMinimumWidth(220)
        self._base_combo.currentIndexChanged.connect(self._on_base_changed)
        top.addWidget(self._base_combo)
        top.addStretch(1)
        self._save_btn = QPushButton("Save")
        self._save_btn.clicked.connect(self._on_save)
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.clicked.connect(self._on_delete)
        revert = QPushButton("Revert")
        revert.clicked.connect(self._on_revert)
        for b in (self._save_btn, self._delete_btn, revert):
            top.addWidget(b)
        root.addLayout(top)

        # --- metadata row
        meta = QHBoxLayout()
        meta.addWidget(QLabel("id:"))
        self._id_edit = QLineEdit()
        self._id_edit.setMaximumWidth(160)
        self._id_edit.textChanged.connect(self._update_button_states)
        meta.addWidget(self._id_edit)
        meta.addWidget(QLabel("label:"))
        self._label_edit = QLineEdit()
        meta.addWidget(self._label_edit, 1)
        meta.addWidget(QLabel("description:"))
        self._desc_edit = QLineEdit()
        meta.addWidget(self._desc_edit, 2)
        meta.addWidget(QLabel("Expected setters:"))
        self._expected_spin = QSpinBox()
        self._expected_spin.setRange(0, 2)
        self._expected_spin.setMaximumWidth(60)
        meta.addWidget(self._expected_spin)
        root.addLayout(meta)

        self._id_hint = QLabel("")
        self._id_hint.setStyleSheet("color:#ffb74d;")
        root.addWidget(self._id_hint)

        # --- situation tabs
        self._tabs = QTabBar()
        for text in _TAB_LABELS:
            self._tabs.addTab(text)
        self._tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self._tabs)

        # --- rotation selector (setter-keyed) / setting-slot (keyless)
        self._rotation_row = QWidget()
        rot = QHBoxLayout(self._rotation_row)
        rot.setContentsMargins(0, 0, 0, 0)
        rot.addWidget(QLabel("Rotation:"))
        self._rotation_buttons = QButtonGroup(self)
        self._rotation_buttons.setExclusive(True)
        for k in range(6):
            b = QPushButton(f"Setter at P{k + 1}")
            b.setCheckable(True)
            self._rotation_buttons.addButton(b, k)
            rot.addWidget(b)
        self._rotation_buttons.idClicked.connect(self._on_key_changed)
        rot.addSpacing(16)
        rot.addWidget(QLabel("Copy from:"))
        self._copy_combo = QComboBox()
        self._copy_combo.setMinimumWidth(130)
        rot.addWidget(self._copy_combo)
        copy_btn = QPushButton("Copy")
        copy_btn.clicked.connect(self._on_copy)
        rot.addWidget(copy_btn)
        rot.addStretch(1)
        root.addWidget(self._rotation_row)

        self._keyless_row = QWidget()
        kl = QHBoxLayout(self._keyless_row)
        kl.setContentsMargins(0, 0, 0, 0)
        kl.addWidget(QLabel("Setting slot:"))
        self._setting_combo = QComboBox()
        for s in range(6):
            self._setting_combo.addItem(f"P{s + 1}", s)
        self._setting_combo.currentIndexChanged.connect(
            self._on_setting_slot_changed)
        kl.addWidget(self._setting_combo)
        kl.addStretch(1)
        root.addWidget(self._keyless_row)

        # --- court
        self._court = _EditorCourt()
        for slot in range(6):
            tok = _EditorToken(slot, self)
            self._court.scene().addItem(tok)
            self._tokens[slot] = tok
        root.addWidget(self._court, 1)

        # --- live overlap warning
        self._warning = QLabel("")
        self._warning.setStyleSheet("color:#ff7043; font-weight:600;")
        root.addWidget(self._warning)

        self.setCentralWidget(central)
        self.statusBar()
        self.resize(1040, 720)

    # ------------------------------------------------------------- loading

    def _load_base(self, base_id: str) -> None:
        """Load a deep working copy of ``base_id``'s charts + metadata."""
        spec = SYSTEMS.get(base_id) or get_system(base_id)
        self._base_id = spec.id
        self._working = {
            mode: {key: {slot: (x, y) for slot, (x, y) in chart.items()}
                   for key, chart in spec.charts[mode].items()}
            for mode in _STORED_MODES}
        self._uses_setter_roles = spec.uses_setter_roles
        self._fixed_setter_slot = (spec.fixed_setter_slot
                                   if spec.fixed_setter_slot is not None else 0)
        self._current_key = 0

        for w in (self._id_edit, self._label_edit, self._desc_edit,
                  self._expected_spin, self._setting_combo):
            w.blockSignals(True)
        self._id_edit.setText(spec.id)
        self._label_edit.setText(spec.label)
        self._desc_edit.setText(spec.description)
        self._expected_spin.setValue(spec.expected_setters)
        self._setting_combo.setCurrentIndex(self._fixed_setter_slot)
        btn0 = self._rotation_buttons.button(0)
        if btn0 is not None:
            btn0.setChecked(True)
        for w in (self._id_edit, self._label_edit, self._desc_edit,
                  self._expected_spin, self._setting_combo):
            w.blockSignals(False)

        self._rotation_row.setVisible(self._uses_setter_roles)
        self._keyless_row.setVisible(not self._uses_setter_roles)
        self._update_copy_choices()
        self._repose()
        self._update_button_states()

    def _refresh_base_combo(self, select: str) -> None:
        """Rebuild the base picker from the (already refreshed) registry and
        load ``select``. Signals are blocked so the load happens exactly
        once, deterministically, rather than via currentIndexChanged."""
        self._base_combo.blockSignals(True)
        self._base_combo.clear()
        for sid in system_ids():
            self._base_combo.addItem(SYSTEMS[sid].label, sid)
        idx = self._base_combo.findData(select)
        self._base_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._base_combo.blockSignals(False)
        self._load_base(self._base_combo.currentData())

    def _on_base_changed(self, _index: int) -> None:
        data = self._base_combo.currentData()
        if data is not None:
            self._load_base(data)

    def _on_revert(self) -> None:
        self._load_base(self._base_id)

    # --------------------------------------------------------- posing tokens

    def _current_mode(self) -> Mode:
        return _TAB_MODES[self._tabs.currentIndex()]

    def _tab_index(self, mode: Mode) -> int:
        return _TAB_MODES.index(mode)

    def _acting_setter_slot(self) -> int:
        """The slot painted as the acting setter: the current chart key for
        setter-keyed systems, the fixed setting slot for keyless ones."""
        return (self._current_key if self._uses_setter_roles
                else self._fixed_setter_slot)

    def _role_hint(self, slot: int) -> str:
        if self._uses_setter_roles:
            return _OFFSET_CATEGORY[(slot - self._current_key) % 6]
        return "sets" if slot == self._fixed_setter_slot else ""

    def _repose(self) -> None:
        """Re-pose every token from the working chart of the current
        mode/key, then re-run the overlap check. Programmatic setPos here
        must not feed back into the live drag handler."""
        mode = self._current_mode()
        chart = self._working[mode][self._current_key]
        acting = self._acting_setter_slot()
        self._suspend_feedback = True
        for slot, tok in self._tokens.items():
            if mode is Mode.SERVE_BASE and slot == 0:
                sx, sy = serve_xy("left")          # server pinned off court
                tok.setPos(sx * M, sy * M)
                tok.set_movable(False)
                tok.ghost = True
                tok.hint = "serves"
            else:
                x, y = chart[slot]
                tok.setPos(x * M, y * M)
                tok.set_movable(True)
                tok.ghost = False
                tok.hint = self._role_hint(slot)
            tok.color = QColor(SETTER_COLOR if slot == acting else TEAM_GREEN)
            tok.warn = False
            tok.update()
        self._suspend_feedback = False
        self._update_overlap()

    def _on_tab_changed(self, _index: int) -> None:
        self._repose()

    def _on_key_changed(self, key: int) -> None:
        self._current_key = key
        self._update_copy_choices()
        self._repose()

    def _set_key(self, key: int) -> None:
        """Programmatic rotation change (used by tests and by _on_copy):
        idClicked only fires for real clicks, so drive the state directly."""
        btn = self._rotation_buttons.button(key)
        if btn is not None:
            btn.setChecked(True)
        self._on_key_changed(key)

    def _on_setting_slot_changed(self, index: int) -> None:
        self._fixed_setter_slot = index          # combo index == slot 0..5
        self._repose()

    # --------------------------------------------------------- copy-from

    def _update_copy_choices(self) -> None:
        self._copy_combo.blockSignals(True)
        self._copy_combo.clear()
        if self._uses_setter_roles:
            for k in range(6):
                if k != self._current_key:
                    self._copy_combo.addItem(f"Setter at P{k + 1}", k)
        self._copy_combo.blockSignals(False)

    def _on_copy(self) -> None:
        """Copy another key's chart of the current mode onto the current
        key -- a fast way to author six similar rotations."""
        if not self._uses_setter_roles:
            return
        other = self._copy_combo.currentData()
        if other is None:
            return
        mode = self._current_mode()
        src = self._working[mode][other]
        self._working[mode][self._current_key] = {
            slot: (x, y) for slot, (x, y) in src.items()}
        self._repose()

    # ----------------------------------------------------- drag feedback

    def _token_dragged(self, _slot: int) -> None:
        if self._suspend_feedback:
            return
        self._update_overlap()

    def _token_released(self, slot: int) -> None:
        """Snap the dropped token to the 0.1 m authoring grid and store it.
        The serve server (serve mode, slot 0) is pinned and never stored."""
        mode = self._current_mode()
        if mode is Mode.SERVE_BASE and slot == 0:
            return
        tok = self._tokens[slot]
        x = round(tok.pos().x() / M, 1)
        y = round(tok.pos().y() / M, 1)
        self._suspend_feedback = True
        tok.setPos(x * M, y * M)                  # show the snapped spot
        self._suspend_feedback = False
        self._working[mode][self._current_key][slot] = (x, y)
        self._update_overlap()

    def _update_overlap(self) -> None:
        """Live FIVB overlap feedback: a persistent warning label plus a red
        ring on every token named in a violation. Only serve-contact
        situations (Receive, Serve) have overlap rules; Offense/Defense show
        no overlap UI. Serve exempts the server (slot 0)."""
        mode = self._current_mode()
        if mode not in (Mode.RECEIVE, Mode.SERVE_BASE):
            self._warning.setText("")
            for tok in self._tokens.values():
                if tok.warn:
                    tok.warn = False
                    tok.update()
            return
        exempt = () if mode is Mode.RECEIVE else (0,)
        pos = {slot: (tok.pos().x() / M, tok.pos().y() / M)
               for slot, tok in self._tokens.items()}
        violations = overlap_violations(pos, "left", exempt)
        named = {slot for slot in range(6)
                 for v in violations if f"P{slot + 1}" in v}
        for slot, tok in self._tokens.items():
            want = slot in named
            if tok.warn != want:
                tok.warn = want
                tok.update()
        self._warning.setText(
            ("⚠ " + "; ".join(violations)) if violations else "")

    # -------------------------------------------------------- save / delete

    def _build_spec(self, sid: str) -> SystemSpec:
        """A SystemSpec from the working state, coordinates snapped to the
        0.1 m grid so the on-disk file is clean and byte-stable."""
        charts = {
            mode: {key: {slot: (round(x, 1), round(y, 1))
                         for slot, (x, y) in chart.items()}
                   for key, chart in self._working[mode].items()}
            for mode in _STORED_MODES}
        return SystemSpec(
            id=sid,
            label=self._label_edit.text().strip() or sid,
            description=self._desc_edit.text().strip(),
            uses_setter_roles=self._uses_setter_roles,
            expected_setters=self._expected_spin.value(),
            charts=charts,
            fixed_setter_slot=(None if self._uses_setter_roles
                               else self._fixed_setter_slot))

    def _is_existing_user_system(self, sid: str) -> bool:
        return bool(sid) and sid not in BUILTIN_IDS and (
            systems_dir(self._systems_base) / f"{sid}.json").exists()

    def _update_button_states(self) -> None:
        sid = self._id_edit.text().strip()
        valid = bool(_ID_RE.match(sid))
        self._save_btn.setEnabled(valid and sid not in BUILTIN_IDS)
        if sid in BUILTIN_IDS:
            self._id_hint.setText("change the id to save your own copy")
        elif sid and not valid:
            self._id_hint.setText(
                "id must start alphanumeric, then letters/digits/-/_ (max 32)")
        else:
            self._id_hint.setText("")
        self._delete_btn.setEnabled(self._is_existing_user_system(sid))

    def _on_save(self) -> None:
        sid = self._id_edit.text().strip()
        try:
            path = user_systems.save_user_system(
                self._build_spec(sid), base=self._systems_base)
        except ValueError as e:                   # built-in / malformed id
            QMessageBox.warning(self, "Save system", str(e))
            return
        user_systems.refresh_registry(self._systems_base)
        self._refresh_base_combo(select=sid)
        self.systems_changed.emit()
        self.statusBar().showMessage(
            f"saved {path.parent.name}\\{path.name}")
        self._update_button_states()

    def _on_delete(self) -> None:
        sid = self._id_edit.text().strip()
        if not self._is_existing_user_system(sid):
            return
        if QMessageBox.question(
                self, "Delete system",
                f"Delete the custom system '{sid}'?") \
                != QMessageBox.StandardButton.Yes:
            return
        user_systems.delete_user_system(sid, base=self._systems_base)
        user_systems.refresh_registry(self._systems_base)
        self._refresh_base_combo(select=system_ids()[0])
        self.systems_changed.emit()
        self.statusBar().showMessage(f"deleted {sid}")
        self._update_button_states()
