"""Bottom action bar: the four big rating buttons, manual point buttons,
undo, the phase prompt, and the small serve-rating override chips."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QButtonGroup, QHBoxLayout, QLabel, QPushButton,
                             QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from core.models import Rating

RATING_STYLE = {
    Rating.ERROR: ("#d32f2f", "fail"),
    Rating.POOR: ("#f57c00", "not good"),
    Rating.GOOD: ("#7cb342", "good"),
    Rating.PERFECT: ("#2e7d32", "point"),
}

# Per-phase hint text for the big rating buttons (second line, under the symbol).
# "serve" matches RATING_STYLE's default hints and is also the fallback for
# unrecognized contexts.
CONTEXT_HINTS = {
    "serve": {Rating.ERROR: "fail", Rating.POOR: "not good", Rating.GOOD: "good", Rating.PERFECT: "point"},
    "reception": {Rating.ERROR: "fail", Rating.POOR: "poor", Rating.GOOD: "good", Rating.PERFECT: "perfect"},
    "attack": {Rating.ERROR: "error-out", Rating.POOR: "poor", Rating.GOOD: "good", Rating.PERFECT: "kill"},
    "dig": {Rating.ERROR: "fail", Rating.POOR: "poor", Rating.GOOD: "good", Rating.PERFECT: "perfect"},
}


class RatingBar(QWidget):
    rating_clicked = pyqtSignal(object)        # Rating
    serve_rating_clicked = pyqtSignal(object)  # Rating (override of last serve)
    overpass_clicked = pyqtSignal()            # reception went straight back
    undo_clicked = pyqtSignal()
    point_left_clicked = pyqtSignal()
    point_right_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 2, 8, 6)
        root.setSpacing(4)

        # --- prompt row + serve override chips
        top = QHBoxLayout()
        self.prompt = QLabel("")
        self.prompt.setStyleSheet("font-size: 19px; font-weight: 600; color: #ddd;")
        top.addWidget(self.prompt, 1)
        top.addWidget(QLabel("<span style='color:#999'>serve:</span>"))
        self._chips = QButtonGroup(self)
        self._chip_widgets: dict[Rating, QToolButton] = {}
        for r in (Rating.ERROR, Rating.POOR, Rating.GOOD, Rating.PERFECT):
            b = QToolButton()
            b.setText(r.symbol)
            b.setCheckable(True)
            b.setFixedSize(46, 40)
            b.setStyleSheet(
                f"QToolButton {{ font-size:18px; font-weight:bold; color:white; "
                f"background:{RATING_STYLE[r][0]}; border-radius:6px; }}"
                "QToolButton:checked { border: 3px solid #ffd600; }")
            b.clicked.connect(lambda _=False, rr=r: self.serve_rating_clicked.emit(rr))
            self._chips.addButton(b)
            self._chip_widgets[r] = b
            top.addWidget(b)
        self._serve_chip_holder = [w for w in self._chip_widgets.values()]
        root.addLayout(top)

        # --- big buttons row
        row = QHBoxLayout()
        row.setSpacing(10)

        self.point_left = QPushButton("◀ point")
        self.point_right = QPushButton("point ▶")
        for b in (self.point_left, self.point_right):
            b.setMinimumHeight(76)
            b.setStyleSheet("QPushButton { font-size:20px; color:white;"
                            " background:#455a64; border-radius:10px; }"
                            "QPushButton:pressed { background:#263238; }")
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.point_left.clicked.connect(self.point_left_clicked)
        self.point_right.clicked.connect(self.point_right_clicked)
        row.addWidget(self.point_left, 2)

        self._rating_buttons: dict[Rating, QPushButton] = {}
        self._context = "serve"
        for r in (Rating.ERROR, Rating.POOR, Rating.GOOD, Rating.PERFECT):
            color, hint = RATING_STYLE[r]
            b = QPushButton(f"{r.symbol}\n{hint}")
            b.setMinimumHeight(76)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            b.setStyleSheet(
                f"QPushButton {{ font-size:24px; font-weight:bold; color:white;"
                f" background:{color}; border-radius:10px; }}"
                "QPushButton:pressed { border: 4px solid #ffd600; }")
            b.clicked.connect(lambda _=False, rr=r: self.rating_clicked.emit(rr))
            row.addWidget(b, 3)
            self._rating_buttons[r] = b

        self.overpass = QPushButton("↷\noverpass")
        self.overpass.setMinimumHeight(76)
        self.overpass.setSizePolicy(QSizePolicy.Policy.Expanding,
                                    QSizePolicy.Policy.Fixed)
        self.overpass.setStyleSheet(
            "QPushButton { font-size:18px; font-weight:bold; color:white;"
            " background:#5e35b1; border-radius:10px; }"
            "QPushButton:pressed { border: 4px solid #ffd600; }")
        self.overpass.setToolTip(
            "Reception crossed straight back over the net — "
            "the serving team plays the ball")
        self.overpass.clicked.connect(self.overpass_clicked)
        self.overpass.setVisible(False)
        row.addWidget(self.overpass, 2)

        row.addWidget(self.point_right, 2)

        self.undo = QPushButton("⟲\nundo")
        self.undo.setMinimumHeight(76)
        self.undo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.undo.setStyleSheet("QPushButton { font-size:18px; color:white;"
                                " background:#6d4c41; border-radius:10px; }"
                                "QPushButton:pressed { background:#3e2723; }")
        self.undo.clicked.connect(self.undo_clicked)
        row.addWidget(self.undo, 2)

        root.addLayout(row)
        self.show_serve_chips(False)

    def set_prompt(self, text: str) -> None:
        self.prompt.setText(text)

    def show_serve_chips(self, visible: bool, current: Rating | None = None) -> None:
        for r, w in self._chip_widgets.items():
            w.setVisible(visible)
            w.setChecked(current == r)

    def set_context(self, context: str) -> None:
        """Relabel the four big rating buttons' hint text for the given rally
        phase ("serve", "reception", "attack", "dig"). Unknown values fall
        back to "serve". Idempotent and cheap; safe to call on every refresh."""
        if context == self._context:
            return
        hints = CONTEXT_HINTS.get(context, CONTEXT_HINTS["serve"])
        self._context = context if context in CONTEXT_HINTS else "serve"
        for r, b in self._rating_buttons.items():
            b.setText(f"{r.symbol}\n{hints[r]}")
        self.overpass.setVisible(self._context == "reception")

    def set_point_labels(self, left_name: str, right_name: str) -> None:
        self.point_left.setText(f"◀ point\n{left_name}")
        self.point_right.setText(f"point ▶\n{right_name}")
