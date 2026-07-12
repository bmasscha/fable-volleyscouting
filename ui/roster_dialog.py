"""Team / roster library editor dialog.

Left: list of saved teams (roster library) with New/Delete buttons plus
team-name edit and team-color picker.  Right: players table (number, name,
role) with Add/Remove buttons.  Save persists via core.persistence.save_team.
Touch-friendly: >=40 px controls, 16 px fonts.
"""
from __future__ import annotations

import sys
from pathlib import Path

if __name__ == "__main__" and __package__ in (None, ""):
    # allow running this file directly: python ui/roster_dialog.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView, QColorDialog, QComboBox, QDialog, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.models import Player, Role, Team
from core.persistence import delete_team, load_teams, save_team

_STYLE = """
QWidget { font-size: 12pt; }  /* = 16 px at 96 dpi, scales on high-DPI */
QPushButton { min-height: 40px; padding: 4px 18px; }
QComboBox, QLineEdit, QSpinBox { min-height: 40px; }
QListWidget::item { min-height: 44px; padding: 2px 6px; }
QHeaderView::section { min-height: 40px; }
"""

_ROLE_ORDER = [Role.SETTER, Role.OUTSIDE, Role.OPPOSITE,
               Role.MIDDLE, Role.LIBERO, Role.UNIVERSAL]


class RosterDialog(QDialog):
    """Editor for the saved-team library (rosters/ folder)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Team library")
        self.setStyleSheet(_STYLE)
        self.setMinimumSize(950, 620)

        self._current_team: Team | None = None
        self._color: str = "#2e7d32"
        self._dirty = False
        self._loading = False  # guard: suppress dirty flag while populating

        root = QHBoxLayout(self)
        root.setSpacing(16)
        root.setContentsMargins(16, 16, 16, 16)

        # ---------------------------------------------------------- left pane
        left = QVBoxLayout()
        left.setSpacing(10)
        left.addWidget(QLabel("Saved teams"))
        self.team_list = QListWidget()
        self.team_list.currentItemChanged.connect(self._on_team_changed)
        left.addWidget(self.team_list, 1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self.new_btn = QPushButton("New team")
        self.new_btn.clicked.connect(self._on_new_team)
        self.del_btn = QPushButton("Delete team")
        self.del_btn.clicked.connect(self._on_delete_team)
        btn_row.addWidget(self.new_btn)
        btn_row.addWidget(self.del_btn)
        left.addLayout(btn_row)

        left.addWidget(QLabel("Team name"))
        self.name_edit = QLineEdit()
        self.name_edit.textEdited.connect(self._mark_dirty)
        left.addWidget(self.name_edit)

        color_row = QHBoxLayout()
        color_row.setSpacing(10)
        color_row.addWidget(QLabel("Team color"))
        self.color_btn = QPushButton()
        self.color_btn.setFixedSize(120, 40)
        self.color_btn.clicked.connect(self._on_pick_color)
        color_row.addWidget(self.color_btn)
        color_row.addStretch(1)
        left.addLayout(color_row)

        left_w = QWidget()
        left_w.setLayout(left)
        left_w.setFixedWidth(320)
        root.addWidget(left_w)

        # --------------------------------------------------------- right pane
        right = QVBoxLayout()
        right.setSpacing(10)
        right.addWidget(QLabel("Players"))

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Number", "Name", "Role"])
        self.table.verticalHeader().setDefaultSectionSize(48)
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnWidth(0, 110)
        self.table.setColumnWidth(1, 280)
        self.table.setColumnWidth(2, 170)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.itemChanged.connect(self._on_item_changed)
        right.addWidget(self.table, 1)

        prow = QHBoxLayout()
        prow.setSpacing(10)
        self.add_btn = QPushButton("Add player")
        self.add_btn.clicked.connect(self._on_add_player)
        self.rem_btn = QPushButton("Remove player")
        self.rem_btn.clicked.connect(self._on_remove_player)
        prow.addWidget(self.add_btn)
        prow.addWidget(self.rem_btn)
        prow.addStretch(1)
        self.save_btn = QPushButton("Save team")
        self.save_btn.clicked.connect(self._on_save)
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        prow.addWidget(self.save_btn)
        prow.addWidget(self.close_btn)
        right.addLayout(prow)
        root.addLayout(right, 1)

        self._reload_library()

    # ------------------------------------------------------------- library

    def _reload_library(self, select_name: str | None = None) -> None:
        self._loading = True
        self.team_list.clear()
        for team in load_teams():
            item = QListWidgetItem(team.name)
            item.setData(Qt.ItemDataRole.UserRole, team)
            self.team_list.addItem(item)
        self._loading = False
        self._current_team = None
        self._dirty = False
        if self.team_list.count():
            row = 0
            if select_name is not None:
                for i in range(self.team_list.count()):
                    if self.team_list.item(i).text() == select_name:
                        row = i
                        break
            self.team_list.setCurrentRow(row)
        else:
            self._show_team(None)

    # ------------------------------------------------------- team switching

    def _on_team_changed(self, current, previous) -> None:
        if self._loading:
            return
        if previous is not None and self._dirty:
            choice = self._ask_unsaved()
            if choice == QMessageBox.StandardButton.Cancel or (
                    choice == QMessageBox.StandardButton.Save
                    and not self._save_current()):
                # stay on the previous team
                self.team_list.blockSignals(True)
                self.team_list.setCurrentItem(previous)
                self.team_list.blockSignals(False)
                return
        team = current.data(Qt.ItemDataRole.UserRole) if current else None
        self._show_team(team)

    def _ask_unsaved(self):
        return QMessageBox.warning(
            self, "Unsaved changes",
            f"Team '{self.name_edit.text().strip() or '(unnamed)'}' has "
            "unsaved changes.\nSave them?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save)

    def _show_team(self, team: Team | None) -> None:
        self._loading = True
        self._current_team = team
        self.table.setRowCount(0)
        if team is None:
            self.name_edit.clear()
            self._set_color("#2e7d32")
            for w in (self.name_edit, self.table, self.add_btn,
                      self.rem_btn, self.save_btn, self.color_btn,
                      self.del_btn):
                w.setEnabled(False)
        else:
            for w in (self.name_edit, self.table, self.add_btn,
                      self.rem_btn, self.save_btn, self.color_btn,
                      self.del_btn):
                w.setEnabled(True)
            self.name_edit.setText(team.name)
            self._set_color(team.color)
            for p in team.players:
                self._append_row(p)
        self._loading = False
        self._dirty = False

    # ------------------------------------------------------------- players

    def _append_row(self, player: Player) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)

        spin = QSpinBox()
        spin.setRange(0, 99)
        spin.setValue(player.number)
        spin.valueChanged.connect(self._mark_dirty)
        self.table.setCellWidget(row, 0, spin)

        name_item = QTableWidgetItem(player.name)
        name_item.setData(Qt.ItemDataRole.UserRole, player.id)
        self.table.setItem(row, 1, name_item)

        combo = QComboBox()
        for role in _ROLE_ORDER:
            combo.addItem(f"{role.value} ({role.abbrev})", role.value)
        combo.setCurrentIndex(_ROLE_ORDER.index(player.role))
        combo.currentIndexChanged.connect(self._mark_dirty)
        self.table.setCellWidget(row, 2, combo)

    def _on_add_player(self) -> None:
        used = {self.table.cellWidget(r, 0).value()
                for r in range(self.table.rowCount())}
        number = 1
        while number in used:
            number += 1
        self._append_row(Player(number=number, name="New player"))
        self._mark_dirty()
        self.table.scrollToBottom()

    def _on_remove_player(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()},
                      reverse=True)
        if not rows:
            QMessageBox.information(self, "Remove player",
                                    "Select a player row first.")
            return
        for r in rows:
            self.table.removeRow(r)
        self._mark_dirty()

    def _collect_players(self) -> list[Player] | None:
        """Read the table back into Player objects; None if validation fails."""
        players: list[Player] = []
        seen_numbers: set[int] = set()
        for row in range(self.table.rowCount()):
            number = self.table.cellWidget(row, 0).value()
            if number in seen_numbers:
                QMessageBox.warning(
                    self, "Duplicate number",
                    f"Jersey number {number} is used more than once.")
                return None
            seen_numbers.add(number)
            name_item = self.table.item(row, 1)
            name = (name_item.text() if name_item else "").strip()
            if not name:
                QMessageBox.warning(self, "Missing name",
                                    f"Player in row {row + 1} has no name.")
                return None
            role = Role(self.table.cellWidget(row, 2).currentData())
            pid = name_item.data(Qt.ItemDataRole.UserRole)
            player = Player(number=number, name=name, role=role)
            if pid:
                player.id = pid
            players.append(player)
        return players

    # --------------------------------------------------------------- color

    def _set_color(self, hex_color: str) -> None:
        self._color = hex_color
        self.color_btn.setText(hex_color)
        self.color_btn.setStyleSheet(
            f"background-color: {hex_color};"
            f"color: {'#000000' if QColor(hex_color).lightness() > 127 else '#ffffff'};")

    def _on_pick_color(self) -> None:
        color = QColorDialog.getColor(QColor(self._color), self, "Team color")
        if color.isValid():
            self._set_color(color.name())
            self._mark_dirty()

    # ---------------------------------------------------------------- save

    def _on_save(self) -> None:
        self._save_current()

    def _save_current(self) -> bool:
        team = self._current_team
        if team is None:
            return True
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Missing name",
                                "Please enter a team name.")
            return False
        # refuse a rename that collides with another saved team
        for i in range(self.team_list.count()):
            other = self.team_list.item(i).data(Qt.ItemDataRole.UserRole)
            if other is not team and other.name.lower() == name.lower():
                QMessageBox.warning(
                    self, "Name in use",
                    f"A team named '{other.name}' already exists.")
                return False
        players = self._collect_players()
        if players is None:
            return False

        old_name = team.name
        team.name, team.players, team.color = name, players, self._color
        if old_name != name:
            delete_team(Team(name=old_name))  # remove file under old name
        save_team(team)
        item = self.team_list.currentItem()
        if item is not None:
            item.setText(name)
        self._dirty = False
        return True

    # ---------------------------------------------------------- dirty state

    def _mark_dirty(self, *_args) -> None:
        if not self._loading:
            self._dirty = True

    def _on_item_changed(self, _item) -> None:
        self._mark_dirty()

    # ------------------------------------------------------- new / delete

    def _on_new_team(self) -> None:
        if self._dirty:
            choice = self._ask_unsaved()
            if choice == QMessageBox.StandardButton.Cancel:
                return
            if (choice == QMessageBox.StandardButton.Save
                    and not self._save_current()):
                return
            self._dirty = False
        existing = {self.team_list.item(i).text().lower()
                    for i in range(self.team_list.count())}
        base, name, n = "New Team", "New Team", 2
        while name.lower() in existing:
            name = f"{base} {n}"
            n += 1
        team = Team(name=name)
        save_team(team)
        item = QListWidgetItem(team.name)
        item.setData(Qt.ItemDataRole.UserRole, team)
        self.team_list.addItem(item)
        self.team_list.setCurrentItem(item)
        self.name_edit.setFocus()
        self.name_edit.selectAll()

    def _on_delete_team(self) -> None:
        team = self._current_team
        if team is None:
            return
        if QMessageBox.question(
                self, "Delete team",
                f"Delete team '{team.name}' from the library?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        delete_team(team)
        self._dirty = False
        row = self.team_list.currentRow()
        self._loading = True
        self.team_list.takeItem(row)
        self._loading = False
        self._current_team = None
        if self.team_list.count():
            self.team_list.setCurrentRow(min(row, self.team_list.count() - 1))
            cur = self.team_list.currentItem()
            self._show_team(cur.data(Qt.ItemDataRole.UserRole))
        else:
            self._show_team(None)

    # ------------------------------------------------------------- closing

    def _confirm_close(self) -> bool:
        if not self._dirty:
            return True
        choice = self._ask_unsaved()
        if choice == QMessageBox.StandardButton.Cancel:
            return False
        if choice == QMessageBox.StandardButton.Save:
            return self._save_current()
        return True  # Discard

    def closeEvent(self, event) -> None:  # window X button
        if self._confirm_close():
            event.accept()
        else:
            event.ignore()

    def reject(self) -> None:  # Esc key
        if self._confirm_close():
            super().reject()


if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    dlg = RosterDialog()
    dlg.show()
    sys.exit(app.exec())
