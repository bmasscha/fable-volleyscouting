"""New-match setup dialog.

Pick home/away teams from the roster library, assign a starting lineup
(P1..P6) and libero(s) per team, choose first server and starting sides,
and set the match format.  After accept() the dialog exposes:

    .teams            -> {HOME: Team, AWAY: Team}
    .config           -> core.models.MatchConfig
    .set_start_event  -> core.events.SetStartEvent for set 1
"""
from __future__ import annotations

import sys
from pathlib import Path

if __name__ == "__main__" and __package__ in (None, ""):
    # allow running this file directly: python ui/setup_wizard.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QRadioButton, QSpinBox, QVBoxLayout,
)

from core.events import SetStartEvent
from core.models import AWAY, HOME, MatchConfig, Role, Team
from core.persistence import load_teams
from ui.roster_dialog import RosterDialog

_STYLE = """
QWidget { font-size: 12pt; }  /* = 16 px at 96 dpi, scales on high-DPI */
QPushButton { min-height: 40px; padding: 4px 18px; }
QComboBox, QSpinBox { min-height: 40px; }
QListWidget::item { min-height: 40px; padding: 2px 6px; }
QGroupBox { font-weight: bold; margin-top: 12px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; }
QCheckBox::indicator, QRadioButton::indicator { width: 24px; height: 24px; }
"""

_POSITIONS = [
    ("P1", "right back — first server"),
    ("P2", "right front"),
    ("P3", "middle front"),
    ("P4", "left front"),
    ("P5", "left back"),
    ("P6", "middle back"),
]


class _TeamPanel(QGroupBox):
    """Team picker + lineup (P1..P6) + libero checklist for one side."""

    def __init__(self, title: str, parent=None):
        super().__init__(title, parent)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        self.team_combo = QComboBox()
        self.team_combo.currentIndexChanged.connect(self._on_team_selected)
        lay.addWidget(self.team_combo)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        self.lineup_combos: list[QComboBox] = []
        for i, (pos, desc) in enumerate(_POSITIONS):
            grid.addWidget(QLabel(f"{pos} ({desc})"), i, 0)
            combo = QComboBox()
            self.lineup_combos.append(combo)
            grid.addWidget(combo, i, 1)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)

        rot = QHBoxLayout()
        rot.addWidget(QLabel("Start rotation:"))
        for txt, steps in (("⟲ rotate", -1), ("rotate ⟳", 1)):
            b = QPushButton(txt)
            b.setToolTip("Shift the whole lineup one rotation — assign the "
                         "base six once, then rotate to the coach's "
                         "starting rotation")
            b.clicked.connect(lambda _=False, s=steps: self._rotate(s))
            rot.addWidget(b)
        rot.addStretch(1)
        lay.addLayout(rot)

        lay.addWidget(QLabel("Libero(s) — check to designate:"))
        self.libero_list = QListWidget()
        self.libero_list.setMinimumHeight(120)
        self.libero_list.setMaximumHeight(190)
        lay.addWidget(self.libero_list)

    # ------------------------------------------------------------- library

    def set_library(self, teams: list[Team], keep_selection: bool = True) -> None:
        prev = self.team_combo.currentText() if keep_selection else None
        self.team_combo.blockSignals(True)
        self.team_combo.clear()
        for t in teams:
            self.team_combo.addItem(t.name, t)
        idx = self.team_combo.findText(prev) if prev else -1
        self.team_combo.setCurrentIndex(max(idx, 0) if self.team_combo.count() else -1)
        self.team_combo.blockSignals(False)
        self._on_team_selected()

    def select_index(self, index: int) -> None:
        if 0 <= index < self.team_combo.count():
            self.team_combo.setCurrentIndex(index)

    def current_team(self) -> Team | None:
        return self.team_combo.currentData()

    # ----------------------------------------------------- lineup / liberos

    def _on_team_selected(self, *_args) -> None:
        team = self.current_team()
        players = team.players if team else []

        for combo in self.lineup_combos:
            combo.clear()
            combo.addItem("— select —", None)
            for p in players:
                combo.addItem(f"#{p.number} {p.name} ({p.role.abbrev})", p.id)

        self.libero_list.clear()
        for p in players:
            item = QListWidgetItem(f"#{p.number} {p.name} ({p.role.abbrev})")
            item.setData(Qt.ItemDataRole.UserRole, p.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if p.role == Role.LIBERO
                else Qt.CheckState.Unchecked)
            self.libero_list.addItem(item)

        # default lineup: first six non-libero players in P1..P6
        non_liberos = [p for p in players if p.role != Role.LIBERO]
        for combo, p in zip(self.lineup_combos, non_liberos[:6]):
            combo.setCurrentIndex(combo.findData(p.id))

    def _rotate(self, steps: int) -> None:
        """Shift the six P1..P6 assignments one rotation (P2 -> P1 etc.)."""
        ids = [c.currentData() for c in self.lineup_combos]
        k = steps % 6
        ids = ids[k:] + ids[:k]
        for combo, pid in zip(self.lineup_combos, ids):
            idx = combo.findData(pid)
            if idx >= 0:
                combo.setCurrentIndex(idx)

    def lineup_ids(self) -> list[str | None]:
        return [c.currentData() for c in self.lineup_combos]

    def libero_ids(self) -> list[str]:
        ids = []
        for i in range(self.libero_list.count()):
            item = self.libero_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                ids.append(item.data(Qt.ItemDataRole.UserRole))
        return ids


class MatchSetupDialog(QDialog):
    """New-match setup wizard.  Results in .teams / .config / .set_start_event."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New match setup")
        self.setStyleSheet(_STYLE)
        self.setMinimumSize(1050, 780)

        self.teams: dict[str, Team] | None = None
        self.config: MatchConfig | None = None
        self.set_start_event: SetStartEvent | None = None

        root = QVBoxLayout(self)
        root.setSpacing(14)
        root.setContentsMargins(16, 16, 16, 16)

        # -------------------------------------------------------- team row
        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Pick teams from the library:"))
        top_row.addStretch(1)
        self.edit_rosters_btn = QPushButton("Edit team library…")
        self.edit_rosters_btn.clicked.connect(self._on_edit_rosters)
        top_row.addWidget(self.edit_rosters_btn)
        root.addLayout(top_row)

        panels = QHBoxLayout()
        panels.setSpacing(16)
        self.home_panel = _TeamPanel("Home team")
        self.away_panel = _TeamPanel("Away team")
        panels.addWidget(self.home_panel, 1)
        panels.addWidget(self.away_panel, 1)
        root.addLayout(panels, 1)

        # ------------------------------------------- serve / side / format
        bottom = QHBoxLayout()
        bottom.setSpacing(16)

        serve_box = QGroupBox("First serving team")
        sv = QVBoxLayout(serve_box)
        self.serve_home = QRadioButton("Home")
        self.serve_away = QRadioButton("Away")
        self.serve_home.setChecked(True)
        sv.addWidget(self.serve_home)
        sv.addWidget(self.serve_away)
        bottom.addWidget(serve_box)

        side_box = QGroupBox("Team starting on the LEFT side")
        sd = QVBoxLayout(side_box)
        self.left_home = QRadioButton("Home")
        self.left_away = QRadioButton("Away")
        self.left_home.setChecked(True)
        sd.addWidget(self.left_home)
        sd.addWidget(self.left_away)
        bottom.addWidget(side_box)

        fmt_box = QGroupBox("Match format")
        fg = QGridLayout(fmt_box)
        fg.setHorizontalSpacing(10)
        fg.setVerticalSpacing(8)
        self.best5 = QRadioButton("Best of 5")
        self.best3 = QRadioButton("Best of 3")
        self.best5.setChecked(True)
        fg.addWidget(self.best5, 0, 0)
        fg.addWidget(self.best3, 0, 1)

        fg.addWidget(QLabel("Points per set"), 1, 0)
        self.points_spin = QSpinBox()
        self.points_spin.setRange(5, 99)
        self.points_spin.setValue(25)
        fg.addWidget(self.points_spin, 1, 1)

        fg.addWidget(QLabel("Deciding set points"), 2, 0)
        self.deciding_spin = QSpinBox()
        self.deciding_spin.setRange(5, 99)
        self.deciding_spin.setValue(15)
        fg.addWidget(self.deciding_spin, 2, 1)

        fg.addWidget(QLabel("Substitutions per set"), 3, 0)
        self.subs_spin = QSpinBox()
        self.subs_spin.setRange(0, 20)
        self.subs_spin.setValue(6)
        fg.addWidget(self.subs_spin, 3, 1)

        self.libero_serve_chk = QCheckBox("Libero may serve")
        self.libero_serve_chk.setChecked(False)
        fg.addWidget(self.libero_serve_chk, 4, 0, 1, 2)

        self.auto_libero_chk = QCheckBox("Automatic libero exchange")
        self.auto_libero_chk.setChecked(True)
        self.auto_libero_chk.setToolTip(
            "The app enters forced front-row swap-backs and the learned\n"
            "serve-receive re-entry itself; the libero's first entry of a\n"
            "set is always yours.")
        fg.addWidget(self.auto_libero_chk, 5, 0, 1, 2)
        bottom.addWidget(fmt_box, 1)
        root.addLayout(bottom)

        # ---------------------------------------------------------- buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Start match")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._reload_library(initial=True)

    # -------------------------------------------------------------- library

    def _reload_library(self, initial: bool = False) -> None:
        teams = load_teams()
        self.home_panel.set_library(teams, keep_selection=not initial)
        self.away_panel.set_library(teams, keep_selection=not initial)
        if initial and len(teams) >= 2:
            self.home_panel.select_index(0)
            self.away_panel.select_index(1)

    def _on_edit_rosters(self) -> None:
        dlg = RosterDialog(self)
        dlg.exec()
        self._reload_library()

    # ----------------------------------------------------- build / validate

    def build_result(self) -> str | None:
        """Validate the form.  On success set .teams / .config /
        .set_start_event and return None; otherwise return an error string."""
        home = self.home_panel.current_team()
        away = self.away_panel.current_team()
        if home is None or away is None:
            return ("Select a team for both Home and Away.\n"
                    "Use 'Edit team library…' to create teams first.")
        if home is away or home.name == away.name:
            return "Home and Away must be two different teams."

        lineups: dict[str, list[str]] = {}
        liberos: dict[str, list[str]] = {}
        for key, panel, team in ((HOME, self.home_panel, home),
                                 (AWAY, self.away_panel, away)):
            label = f"{'Home' if key == HOME else 'Away'} ({team.name})"
            ids = panel.lineup_ids()
            if any(i is None for i in ids):
                return f"{label}: assign a player to every position P1..P6."
            if len(set(ids)) != 6:
                dupes = sorted({f"#{team.player(i).number} {team.player(i).name}"
                                for i in ids if ids.count(i) > 1})
                return (f"{label}: each player may appear only once in the "
                        f"lineup (duplicated: {', '.join(dupes)}).")
            lib = panel.libero_ids()
            clash = [i for i in lib if i in ids]
            if clash:
                names = ", ".join(f"#{team.player(i).number} "
                                  f"{team.player(i).name}" for i in clash)
                return (f"{label}: libero(s) may not be part of the starting "
                        f"lineup ({names}).")
            lineups[key] = ids
            liberos[key] = lib

        self.teams = {HOME: home, AWAY: away}
        self.config = MatchConfig(
            sets_to_win=3 if self.best5.isChecked() else 2,
            points_per_set=self.points_spin.value(),
            points_deciding_set=self.deciding_spin.value(),
            subs_per_set=self.subs_spin.value(),
            libero_may_serve=self.libero_serve_chk.isChecked(),
            auto_libero=self.auto_libero_chk.isChecked(),
        )
        self.set_start_event = SetStartEvent(
            set_number=1,
            lineups=lineups,
            liberos=liberos,
            serving_team=HOME if self.serve_home.isChecked() else AWAY,
            left_team=HOME if self.left_home.isChecked() else AWAY,
        )
        return None

    def accept(self) -> None:
        error = self.build_result()
        if error:
            QMessageBox.warning(self, "Match setup", error)
            return
        super().accept()


if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    dlg = MatchSetupDialog()
    if dlg.exec() == QDialog.DialogCode.Accepted:
        print("teams:", {k: t.name for k, t in dlg.teams.items()})
        print("config:", dlg.config)
        print("set_start_event:", dlg.set_start_event)
