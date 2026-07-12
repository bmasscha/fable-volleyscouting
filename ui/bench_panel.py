"""Bench panel for one team: tap a bench player to arm a substitution
(or libero exchange), then tap the on-court player to complete it."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QLabel, QPushButton, QScrollArea, QVBoxLayout,
                             QWidget)


class BenchPanel(QWidget):
    player_tapped = pyqtSignal(str, str)   # team_key, player_id

    def __init__(self, team_key: str, parent=None):
        super().__init__(parent)
        self.team_key = team_key
        self._buttons: dict[str, QPushButton] = {}
        self._armed: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)
        self.title = QLabel("Bench")
        self.title.setStyleSheet("font-size:15px; font-weight:700; color:#ccc;")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.title)

        self.subs_label = QLabel("")
        self.subs_label.setStyleSheet("font-size:13px; color:#999;")
        self.subs_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.subs_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        self._list = QVBoxLayout(inner)
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(4)
        self._list.addStretch(1)
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)
        self.setFixedWidth(150)

    def update_bench(self, title: str, entries: list[dict], subs_text: str) -> None:
        """entries: dicts with player_id, number, name, color, badge."""
        self.title.setText(title)
        self.subs_label.setText(subs_text)
        seen = set()
        for i, e in enumerate(entries):
            pid = e["player_id"]
            seen.add(pid)
            btn = self._buttons.get(pid)
            if btn is None:
                btn = QPushButton()
                btn.setMinimumHeight(48)
                btn.setCheckable(True)
                btn.clicked.connect(
                    lambda _=False, p=pid: self.player_tapped.emit(self.team_key, p))
                self._buttons[pid] = btn
                self._list.insertWidget(self._list.count() - 1, btn)
            badge = f" {e['badge']}" if e.get("badge") else ""
            btn.setText(f"#{e['number']}{badge}\n{e['name']}")
            btn.setStyleSheet(
                f"QPushButton {{ font-size:14px; font-weight:600; color:white;"
                f" background:{e['color']}; border-radius:8px; text-align:center; }}"
                "QPushButton:checked { border: 3px solid #ffd600; }")
            btn.setChecked(pid == self._armed)
        for pid in list(self._buttons):
            if pid not in seen:
                btn = self._buttons.pop(pid)
                self._list.removeWidget(btn)
                btn.deleteLater()

    def set_armed(self, player_id: str | None) -> None:
        self._armed = player_id
        for pid, btn in self._buttons.items():
            btn.setChecked(pid == player_id)

    @property
    def armed(self) -> str | None:
        return self._armed
