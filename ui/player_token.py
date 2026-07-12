"""On-court player token: colored disc + jersey number + name.
Setter is blue, libero red, everyone else in the team color."""
from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QPen
from PyQt6.QtWidgets import QGraphicsObject

TOKEN_RADIUS = 30.0  # px; 60 px diameter = comfortable touch target

SETTER_COLOR = "#1565c0"
LIBERO_COLOR = "#c62828"


class PlayerToken(QGraphicsObject):
    def __init__(self, team_key: str, player_id: str):
        super().__init__()
        self.team_key = team_key
        self.player_id = player_id
        self.number = 0
        self.name = ""
        self.color = QColor("#2e7d32")
        self.badge = ""
        self.highlight = False
        self.serving = False
        self.setZValue(10)

    def set_appearance(self, number: int, name: str, color: str, badge: str = "",
                       highlight: bool = False, serving: bool = False) -> None:
        changed = (number != self.number or name != self.name
                   or color != self.color.name() or badge != self.badge
                   or highlight != self.highlight or serving != self.serving)
        self.number, self.name, self.badge = number, name, badge
        self.color = QColor(color)
        self.highlight, self.serving = highlight, serving
        if changed:
            self.update()

    def boundingRect(self) -> QRectF:
        r = TOKEN_RADIUS + 6
        return QRectF(-r, -r, 2 * r, 2 * r + 18)

    def paint(self, painter, option, widget=None) -> None:
        r = TOKEN_RADIUS
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        if self.highlight:
            painter.setPen(QPen(QColor("#ffd600"), 5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(-r - 4, -r - 4, 2 * r + 8, 2 * r + 8))
        painter.setPen(QPen(QColor("white"), 2))
        painter.setBrush(QBrush(self.color))
        painter.drawEllipse(QRectF(-r, -r, 2 * r, 2 * r))
        # jersey number
        f = QFont("Segoe UI", 15, QFont.Weight.Bold)
        painter.setFont(f)
        painter.setPen(QColor("white"))
        painter.drawText(QRectF(-r, -r, 2 * r, 2 * r),
                         Qt.AlignmentFlag.AlignCenter, str(self.number))
        # role badge (S / L / ...)
        if self.badge:
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            painter.drawText(QRectF(-r, -r + 4, 2 * r, 14),
                             Qt.AlignmentFlag.AlignHCenter, self.badge)
        # serving ball marker
        if self.serving:
            painter.setPen(QPen(QColor("#333333"), 1))
            painter.setBrush(QBrush(QColor("#ffd600")))
            painter.drawEllipse(QRectF(r - 8, -r - 6, 14, 14))
        # name below the disc
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
        painter.setPen(QColor("#1b1b1b"))
        painter.drawText(QRectF(-r - 6, r + 2, 2 * r + 12, 14),
                         Qt.AlignmentFlag.AlignHCenter, self.name)
