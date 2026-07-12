"""Statistics report dialog: one sortable table per team + exporters."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.models import HOME, AWAY, Rating, Skill, Team
from core.stats import (
    ACES,
    KILLS,
    MANUAL_OTHER,
    OPPONENT_ERRORS,
    TeamStats,
    compute_stats,
    export_csv,
    export_html,
)

_RATING_COLS = (Rating.ERROR, Rating.POOR, Rating.GOOD, Rating.PERFECT)

_HEADERS = (
    ["#", "Name", "Role"]
    + ["Srv tot", "Srv !", "Srv -", "Srv +", "Srv #", "Srv eff%"]
    + ["Rec tot", "Rec !", "Rec -", "Rec +", "Rec #", "Rec pos%"]
    + ["Att tot", "Att !", "Att -", "Att +", "Att #", "Kill%", "Att eff%"]
    + ["Dig tot", "Dig !", "Dig -", "Dig +", "Dig #"]
    + ["Points"]
)


class _NumItem(QTableWidgetItem):
    """Table item that sorts numerically while displaying formatted text."""

    def __init__(self, value: float, text: str):
        super().__init__(text)
        self._value = value
        self.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFlags(self.flags() & ~Qt.ItemFlag.ItemIsEditable)

    def __lt__(self, other):  # noqa: D105
        if isinstance(other, _NumItem):
            return self._value < other._value
        return super().__lt__(other)


def _num(value: float, decimals: int = 0) -> _NumItem:
    text = f"{value:.{decimals}f}" if decimals else str(int(value))
    return _NumItem(float(value), text)


def _text(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item


class ReportDialog(QDialog):
    """Match statistics report: one tab per team, CSV/HTML export."""

    def __init__(self, teams: dict, events: list, parent=None):
        super().__init__(parent)
        self._teams = teams
        self._stats = compute_stats(events, teams)

        home = teams.get(HOME)
        away = teams.get(AWAY)
        self.setWindowTitle(
            f"Match report — {home.name if home else 'Home'} vs "
            f"{away.name if away else 'Away'}")
        self.resize(1200, 640)
        self.setStyleSheet("""
            QWidget { font-size: 15px; }
            QHeaderView::section { font-size: 15px; padding: 6px; }
            QPushButton { font-size: 16px; padding: 10px 22px; }
            QTabBar::tab { font-size: 16px; padding: 10px 24px; }
        """)

        layout = QVBoxLayout(self)
        self._tabs = QTabWidget(self)
        layout.addWidget(self._tabs, stretch=1)

        for key in (HOME, AWAY):
            team = teams.get(key)
            if team is None:
                continue
            self._tabs.addTab(self._make_team_tab(team, self._stats[key]),
                              team.name)

        buttons = QHBoxLayout()
        btn_csv = QPushButton("Export CSV…", self)
        btn_csv.clicked.connect(self._export_csv)
        btn_html = QPushButton("Export HTML…", self)
        btn_html.clicked.connect(self._export_html)
        btn_close = QPushButton("Close", self)
        btn_close.clicked.connect(self.accept)
        buttons.addWidget(btn_csv)
        buttons.addWidget(btn_html)
        buttons.addStretch(1)
        buttons.addWidget(btn_close)
        layout.addLayout(buttons)

    # ------------------------------------------------------------- tabs

    def _make_team_tab(self, team: Team, ts: TeamStats) -> QWidget:
        page = QWidget(self)
        vbox = QVBoxLayout(page)

        active = [p for p in sorted(team.players, key=lambda p: p.number)
                  if (ps := ts.players.get(p.id)) and ps.total_actions > 0]

        table = QTableWidget(len(active) + 1, len(_HEADERS), page)
        table.setHorizontalHeaderLabels(_HEADERS)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)

        for row, player in enumerate(active):
            ps = ts.players[player.id]
            self._fill_row(table, row, str(player.number), player.name,
                           player.role.abbrev, ps.skills, ps.points)

        total_row = len(active)
        self._fill_row(table, total_row, "", "TEAM TOTAL", "",
                       ts.totals, ts.total_points, bold=True)

        table.resizeColumnsToContents()
        header = table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.sortItems(0, Qt.SortOrder.AscendingOrder)
        table.setSortingEnabled(True)
        vbox.addWidget(table, stretch=1)

        bd = ts.points_breakdown
        summary = QLabel(
            f"<b>Points: {ts.total_points}</b> &nbsp;—&nbsp; "
            f"aces {bd[ACES]}, kills {bd[KILLS]}, "
            f"opponent errors {bd[OPPONENT_ERRORS]}, "
            f"manual/other {bd[MANUAL_OTHER]}", page)
        summary.setTextFormat(Qt.TextFormat.RichText)
        vbox.addWidget(summary)
        return page

    def _fill_row(self, table: QTableWidget, row: int, number: str, name: str,
                  role: str, skills: dict, points: int, bold: bool = False):
        # The totals row gets an infinite sort key so it stays last when
        # sorting ascending by jersey number.
        items: list[QTableWidgetItem] = [
            _num(int(number), 0) if number else _NumItem(float("inf"), ""),
            _text(name),
            _text(role),
        ]
        serve = skills[Skill.SERVE]
        items += [_num(serve.total)] + [_num(serve.count(r)) for r in _RATING_COLS]
        items += [_num(serve.efficiency, 1)]

        rec = skills[Skill.RECEPTION]
        items += [_num(rec.total)] + [_num(rec.count(r)) for r in _RATING_COLS]
        items += [_num(rec.positive_pct, 1)]

        att = skills[Skill.ATTACK]
        items += [_num(att.total)] + [_num(att.count(r)) for r in _RATING_COLS]
        items += [_num(att.pct(Rating.PERFECT), 1), _num(att.efficiency, 1)]

        dig = skills[Skill.DIG]
        items += [_num(dig.total)] + [_num(dig.count(r)) for r in _RATING_COLS]

        items += [_num(points)]

        for col, item in enumerate(items):
            if bold:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            table.setItem(row, col, item)

    # ---------------------------------------------------------- exports

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export statistics as CSV", "match_stats.csv",
            "CSV files (*.csv);;All files (*)")
        if not path:
            return
        try:
            export_csv(self._stats, self._teams, path)
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))

    def _export_html(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export report as HTML", "match_report.html",
            "HTML files (*.html *.htm);;All files (*)")
        if not path:
            return
        try:
            export_html(self._stats, self._teams, path)
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
