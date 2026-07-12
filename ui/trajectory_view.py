"""Live trajectory charts: every recorded serve / attack of a player (or
the whole team) drawn on a court, normalized so the acting team always
plays left -> right (core/trajectories.py handles the side mirroring).

Colors: red = fault ('!'), green = direct point ('#', ace / kill),
white = ball stayed in play. The dialog is non-modal so it can stay open
next to the scouting screen and refreshes after every rally.
"""
from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel,
                             QVBoxLayout, QWidget)

from core.models import AWAY, HOME, Skill
from core.rotation import (ATTACK_LINE, COURT_HALF_LENGTH, COURT_WIDTH,
                           FREE_ZONE_X, FREE_ZONE_Y)
from core.trajectories import TrajectoryStat, collect_trajectories, outcome

FREE_ZONE_COLOR = QColor("#2a6f97")
COURT_COLOR = QColor("#e8853b")
FRONT_ZONE_COLOR = QColor("#d9702a")

OUTCOME_COLORS = {
    "error": QColor("#e53935"),    # fault
    "point": QColor("#43a047"),    # ace / kill
    "neutral": QColor("#ffffff"),  # in play
}

ALL_PLAYERS = "__all__"
ALL_SETS = 0


class ChartCourt(QWidget):
    """Static court drawing with colored trajectory arrows on top."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lines: list[tuple[tuple, str]] = []   # (x1,y1,x2,y2), outcome
        self.setMinimumSize(360, 220)

    def set_lines(self, lines: list[tuple[tuple, str]]) -> None:
        self._lines = lines
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # court metres -> widget pixels, aspect preserved and centred
        ext_x = 2 * (COURT_HALF_LENGTH + FREE_ZONE_X)
        ext_y = COURT_WIDTH + 2 * FREE_ZONE_Y
        s = min(self.width() / ext_x, self.height() / ext_y)
        ox = (self.width() - ext_x * s) / 2
        oy = (self.height() - ext_y * s) / 2

        def pt(x: float, y: float) -> QPointF:
            return QPointF(ox + (x + COURT_HALF_LENGTH + FREE_ZONE_X) * s,
                           oy + (y + FREE_ZONE_Y) * s)

        p.fillRect(QRectF(pt(-COURT_HALF_LENGTH - FREE_ZONE_X, -FREE_ZONE_Y),
                          pt(COURT_HALF_LENGTH + FREE_ZONE_X,
                             COURT_WIDTH + FREE_ZONE_Y)), FREE_ZONE_COLOR)
        court = QRectF(pt(-COURT_HALF_LENGTH, 0),
                       pt(COURT_HALF_LENGTH, COURT_WIDTH))
        p.fillRect(court, COURT_COLOR)
        p.fillRect(QRectF(pt(-ATTACK_LINE, 0), pt(ATTACK_LINE, COURT_WIDTH)),
                   FRONT_ZONE_COLOR)
        p.setPen(QPen(QColor("white"), 2))
        p.drawRect(court)
        p.drawLine(pt(-ATTACK_LINE, 0), pt(-ATTACK_LINE, COURT_WIDTH))
        p.drawLine(pt(ATTACK_LINE, 0), pt(ATTACK_LINE, COURT_WIDTH))
        p.setPen(QPen(QColor("#222222"), 4))
        p.drawLine(pt(0, -0.6), pt(0, COURT_WIDTH + 0.6))

        for (x1, y1, x2, y2), oc in self._lines:
            color = OUTCOME_COLORS[oc]
            a, b = pt(x1, y1), pt(x2, y2)
            p.setPen(QPen(color, 2.5, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap))
            p.drawLine(a, b)
            angle = math.atan2(b.y() - a.y(), b.x() - a.x())
            head = min(10.0, math.hypot(b.x() - a.x(), b.y() - a.y()))
            for da in (math.radians(155), math.radians(-155)):
                p.drawLine(b, QPointF(b.x() + head * math.cos(angle + da),
                                      b.y() + head * math.sin(angle + da)))
        p.end()


class TrajectoryDialog(QDialog):
    """Non-modal serve / attack chart viewer, usable while scouting.
    `provider` returns (config, teams, events) or None when no match."""

    def __init__(self, provider, parent=None):
        super().__init__(parent)
        self._provider = provider
        self._stats: list[TrajectoryStat] = []
        self._teams: dict = {}
        self.setWindowTitle("Trajectory charts")
        self.setModal(False)
        self.resize(1150, 480)
        self.setStyleSheet("QComboBox { font-size: 15px; padding: 4px; }"
                           "QLabel { font-size: 15px; }")

        root = QVBoxLayout(self)
        filters = QHBoxLayout()
        self.team_combo = QComboBox()
        self.player_combo = QComboBox()
        self.set_combo = QComboBox()
        filters.addWidget(self.team_combo)
        filters.addWidget(self.player_combo, 1)
        filters.addWidget(self.set_combo)
        legend = QLabel(
            "playing left → right &nbsp;&nbsp; "
            "<span style='color:#43a047'>■</span> ace / kill &nbsp; "
            "<span style='color:#e53935'>■</span> fault &nbsp; "
            "<span style='color:#ffffff'>■</span> in play")
        legend.setTextFormat(Qt.TextFormat.RichText)
        filters.addStretch(1)
        filters.addWidget(legend)
        root.addLayout(filters)

        charts = QHBoxLayout()
        self.serve_title = QLabel("<b>Serves</b>")
        self.attack_title = QLabel("<b>Attacks</b>")
        self.serve_court = ChartCourt()
        self.attack_court = ChartCourt()
        for title, court in ((self.serve_title, self.serve_court),
                             (self.attack_title, self.attack_court)):
            col = QVBoxLayout()
            title.setTextFormat(Qt.TextFormat.RichText)
            col.addWidget(title)
            col.addWidget(court, 1)
            charts.addLayout(col, 1)
        root.addLayout(charts, 1)

        self.team_combo.currentIndexChanged.connect(self._on_team_changed)
        self.player_combo.currentIndexChanged.connect(self._redraw)
        self.set_combo.currentIndexChanged.connect(self._redraw)

    # ---------------------------------------------------------------- data

    def refresh_data(self) -> None:
        """Recollect trajectories from the live event log and redraw,
        preserving the current filter selections."""
        data = self._provider()
        if data is None:
            self._stats, self._teams = [], {}
            self._redraw()
            return
        config, teams, events = data
        self._teams = teams
        self._stats = collect_trajectories(config, teams, events)
        self._repopulate_filters()
        self._redraw()

    def _repopulate_filters(self) -> None:
        team_keep = self.team_combo.currentData()
        for combo in (self.team_combo, self.player_combo, self.set_combo):
            combo.blockSignals(True)
        self.team_combo.clear()
        for tk in (HOME, AWAY):
            if tk in self._teams:
                self.team_combo.addItem(self._teams[tk].name, tk)
        idx = self.team_combo.findData(team_keep)
        self.team_combo.setCurrentIndex(max(0, idx))
        self._fill_player_combo()

        set_keep = self.set_combo.currentData()
        self.set_combo.clear()
        self.set_combo.addItem("All sets", ALL_SETS)
        for n in sorted({t.set_number for t in self._stats}):
            self.set_combo.addItem(f"Set {n}", n)
        idx = self.set_combo.findData(set_keep)
        self.set_combo.setCurrentIndex(max(0, idx))
        for combo in (self.team_combo, self.player_combo, self.set_combo):
            combo.blockSignals(False)

    def _fill_player_combo(self) -> None:
        keep = self.player_combo.currentData()
        self.player_combo.clear()
        self.player_combo.addItem("All players", ALL_PLAYERS)
        tk = self.team_combo.currentData()
        team = self._teams.get(tk)
        if team:
            for pl in sorted(team.players, key=lambda q: q.number):
                self.player_combo.addItem(f"#{pl.number} {pl.name}", pl.id)
        idx = self.player_combo.findData(keep)
        self.player_combo.setCurrentIndex(max(0, idx))

    def _on_team_changed(self) -> None:
        self.player_combo.blockSignals(True)
        self._fill_player_combo()
        self.player_combo.blockSignals(False)
        self._redraw()

    # ---------------------------------------------------------------- draw

    def _redraw(self) -> None:
        tk = self.team_combo.currentData()
        pid = self.player_combo.currentData()
        set_n = self.set_combo.currentData()
        selected = [t for t in self._stats
                    if t.team == tk
                    and (pid in (None, ALL_PLAYERS) or t.player_id == pid)
                    and (set_n in (None, ALL_SETS) or t.set_number == set_n)]
        for skill, court, title, label, win in (
                (Skill.SERVE, self.serve_court, self.serve_title,
                 "Serves", "ace"),
                (Skill.ATTACK, self.attack_court, self.attack_title,
                 "Attacks", "kill")):
            lines = [(t.line, outcome(t.rating)) for t in selected
                     if t.skill == skill]
            court.set_lines(lines)
            n = len(lines)
            points = sum(1 for _, oc in lines if oc == "point")
            errors = sum(1 for _, oc in lines if oc == "error")
            title.setText(f"<b>{label}</b> — {n} total, "
                          f"<span style='color:#43a047'>{points} {win}"
                          f"{'s' if points != 1 else ''}</span>, "
                          f"<span style='color:#e53935'>{errors} fault"
                          f"{'s' if errors != 1 else ''}</span>")
