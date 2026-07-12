"""Top scoreboard: scores by court side, set score, serve indicator,
set number, alert banner, and per-side timeout buttons."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                             QWidget)


class Scoreboard(QWidget):
    timeout_left_clicked = pyqtSignal()
    timeout_right_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 4, 10, 0)
        root.setSpacing(2)

        row = QHBoxLayout()
        self.t_left = QPushButton("T")
        self.t_right = QPushButton("T")
        for b in (self.t_left, self.t_right):
            b.setFixedSize(44, 44)
            b.setToolTip("Timeout")
            b.setStyleSheet("QPushButton { font-size:18px; font-weight:bold;"
                            " color:white; background:#546e7a; border-radius:8px; }")
        self.t_left.clicked.connect(self.timeout_left_clicked)
        self.t_right.clicked.connect(self.timeout_right_clicked)

        self.left_name = QLabel("—")
        self.right_name = QLabel("—")
        self.left_score = QLabel("0")
        self.right_score = QLabel("0")
        self.center = QLabel(":")
        self.sets = QLabel("sets 0 : 0")
        self.set_no = QLabel("set 1")
        self.server = QLabel("")

        for lbl, sz, w in ((self.left_name, 22, 600), (self.right_name, 22, 600),
                           (self.left_score, 40, 800), (self.right_score, 40, 800),
                           (self.center, 34, 800)):
            lbl.setStyleSheet(f"font-size:{sz}px; font-weight:{w}; color:#eee;")
        self.sets.setStyleSheet("font-size:17px; color:#bbb;")
        self.set_no.setStyleSheet("font-size:17px; color:#bbb;")
        self.server.setStyleSheet("font-size:16px; color:#ffd600;")

        mid = QVBoxLayout()
        mid.setSpacing(0)
        srow = QHBoxLayout()
        srow.addStretch(1)
        srow.addWidget(self.left_score)
        srow.addWidget(self.center)
        srow.addWidget(self.right_score)
        srow.addStretch(1)
        mid.addLayout(srow)
        info = QHBoxLayout()
        info.addStretch(1)
        info.addWidget(self.set_no)
        info.addSpacing(18)
        info.addWidget(self.sets)
        info.addSpacing(18)
        info.addWidget(self.server)
        info.addStretch(1)
        mid.addLayout(info)

        row.addWidget(self.t_left)
        row.addSpacing(8)
        row.addWidget(self.left_name, 1, Qt.AlignmentFlag.AlignLeft)
        row.addLayout(mid, 2)
        row.addWidget(self.right_name, 1, Qt.AlignmentFlag.AlignRight)
        row.addSpacing(8)
        row.addWidget(self.t_right)
        root.addLayout(row)

        self.alert = QLabel("")
        self.alert.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.alert.setStyleSheet("font-size:16px; font-weight:600; color:#111;"
                                 " background:#ffd600; border-radius:6px;"
                                 " padding:3px;")
        self.alert.hide()
        root.addWidget(self.alert)

    def update_view(self, left_name: str, right_name: str,
                    left_score: int, right_score: int,
                    sets_left: int, sets_right: int, set_number: int,
                    serving_side: str | None, server_text: str,
                    left_color: str = "#eee", right_color: str = "#eee") -> None:
        dot_l = "● " if serving_side == "left" else ""
        dot_r = " ●" if serving_side == "right" else ""
        self.left_name.setText(f"{dot_l}{left_name}")
        self.right_name.setText(f"{right_name}{dot_r}")
        self.left_name.setStyleSheet(
            f"font-size:22px; font-weight:600; color:{left_color};")
        self.right_name.setStyleSheet(
            f"font-size:22px; font-weight:600; color:{right_color};")
        self.left_score.setText(str(left_score))
        self.right_score.setText(str(right_score))
        self.sets.setText(f"sets {sets_left} : {sets_right}")
        self.set_no.setText(f"set {set_number}")
        self.server.setText(server_text)

    def show_alert(self, text: str) -> None:
        if text:
            self.alert.setText(text)
            self.alert.show()
        else:
            self.alert.hide()
