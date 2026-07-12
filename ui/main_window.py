"""Main window: wires the court UI to the MatchEngine.

All rally input happens on one screen with tap/drag gestures:
  AWAIT_SERVE  drag = serve trajectory (auto-rated '+', out-of-court = '!')
  RECEPTION    big rating buttons rate the auto-selected receiver;
               small chips re-rate the serve; a drag skips ahead to the attack
  ATTACK       drag = attack trajectory (attacker auto-picked from start
               point), then a rating button completes the attack
  DEFENSE      rating buttons rate the auto-selected digger; a drag is the
               counter-attack (implicit unrated dig)
Terminal ratings ('#'/'!') end the rally: the engine scores, side-outs and
rotates automatically.
"""
from __future__ import annotations

import datetime
import threading
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtWidgets import (QButtonGroup, QComboBox, QDialog,
                             QDialogButtonBox, QFileDialog, QGridLayout,
                             QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                             QPushButton, QRadioButton, QToolBar, QVBoxLayout,
                             QWidget)

from core import persistence, rotation
from core.engine import MatchEngine, Phase
from core.events import (AttackEvent, DigEvent, LiberoSwapEvent,
                         ManualScoreEvent, RallyPointEvent, ReceptionEvent,
                         ServeEvent, ServeOverrideEvent, SetStartEvent,
                         SubstitutionEvent, TimeoutEvent)
from core.models import AWAY, HOME, MatchConfig, Rating, Role, Team, other
from core.rotation import LEFT, RIGHT, position_xy, serve_xy

from .bench_panel import BenchPanel
from .court_view import CourtView
from .player_token import LIBERO_COLOR, SETTER_COLOR
from .rating_bar import RatingBar
from .scoreboard import Scoreboard

OUT_TOLERANCE = 0.4    # metres beyond the lines before a serve counts as out
MATCHES_DIR = Path(__file__).resolve().parent.parent / "matches"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Fable Scouter — Volleyball")
        self.engine: MatchEngine | None = None
        self.teams: dict[str, Team] = {}
        self.config = MatchConfig()
        self.match_path: Path | None = None
        self._save_lock = threading.Lock()

        # UI-level pending state (never authoritative — the engine is)
        self.candidate: tuple[str, str] | None = None       # (team, player_id)
        self.pending_attack: tuple[str, str, tuple] | None = None
        self.armed_bench: tuple[str, str] | None = None
        self._transient_warning = ""

        self._build_ui()
        self._build_shortcuts()
        self.refresh()

    # ----------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        self.setStyleSheet("QMainWindow, QWidget { background: #263238; }"
                           "QToolBar { background:#1c262b; spacing:6px; }"
                           "QToolButton { color:#eee; font-size:15px; padding:8px; }"
                           "QLabel { color:#ddd; }")
        tb = QToolBar()
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(tb)
        for text, slot in (("New match", self.new_match),
                           ("Rosters", self.open_rosters),
                           ("Load", self.load_match),
                           ("Save as", self.save_match_as),
                           ("Next set", self.next_set),
                           ("Adjust", self.open_adjust),
                           ("Report", self.open_report)):
            act = QAction(text, self)
            act.triggered.connect(slot)
            tb.addAction(act)
            if text == "Next set":
                self.next_set_action = act

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.scoreboard = Scoreboard()
        root.addWidget(self.scoreboard)

        mid = QHBoxLayout()
        mid.setContentsMargins(4, 2, 4, 2)
        self.bench_left = BenchPanel(HOME)
        self.bench_right = BenchPanel(AWAY)
        self.court = CourtView()
        mid.addWidget(self.bench_left)
        mid.addWidget(self.court, 1)
        mid.addWidget(self.bench_right)
        root.addLayout(mid, 1)

        self.rating_bar = RatingBar()
        root.addWidget(self.rating_bar)
        self.setCentralWidget(central)

        self.court.trajectory_drawn.connect(self.on_trajectory)
        self.court.player_tapped.connect(self.on_player_tapped)
        self.court.court_tapped.connect(self.on_court_tapped)
        self.rating_bar.rating_clicked.connect(self.on_rating)
        self.rating_bar.serve_rating_clicked.connect(self.on_serve_chip)
        self.rating_bar.undo_clicked.connect(self.on_undo)
        self.rating_bar.point_left_clicked.connect(lambda: self.on_point_side(LEFT))
        self.rating_bar.point_right_clicked.connect(lambda: self.on_point_side(RIGHT))
        self.bench_left.player_tapped.connect(self.on_bench_tapped)
        self.bench_right.player_tapped.connect(self.on_bench_tapped)
        self.scoreboard.timeout_left_clicked.connect(lambda: self.on_timeout(LEFT))
        self.scoreboard.timeout_right_clicked.connect(lambda: self.on_timeout(RIGHT))

    def _build_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self.on_undo)
        for key, r in (("1", Rating.ERROR), ("2", Rating.POOR),
                       ("3", Rating.GOOD), ("4", Rating.PERFECT)):
            QShortcut(QKeySequence(key), self,
                      activated=lambda rr=r: self.on_rating(rr))

    # -------------------------------------------------------------- match

    def new_match(self) -> None:
        from .setup_wizard import MatchSetupDialog
        dlg = MatchSetupDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        teams, config, start = dlg.teams, dlg.config, dlg.set_start_event
        if teams[HOME].color == teams[AWAY].color:
            teams[AWAY].color = "#6a1b9a"
        self.teams, self.config = teams, config
        self.engine = MatchEngine(config, teams)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
        safe = lambda s: "".join(c for c in s if c.isalnum() or c in "-_")
        self.match_path = MATCHES_DIR / (
            f"{stamp}_{safe(teams[HOME].name)}_{safe(teams[AWAY].name)}.json")
        self._append(start)

    def open_rosters(self) -> None:
        from .roster_dialog import RosterDialog
        RosterDialog(self).exec()

    def load_match(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load match", str(MATCHES_DIR), "Match files (*.json)")
        if not path:
            return
        config, teams, events = persistence.load_match(path)
        self.config, self.teams = config, teams
        self.engine = MatchEngine(config, teams)
        self.engine.load_events(events)
        self.match_path = Path(path)
        self._clear_pending()
        self.refresh()

    def save_match_as(self) -> None:
        if not self.engine:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save match", str(self.match_path or MATCHES_DIR),
            "Match files (*.json)")
        if path:
            self.match_path = Path(path)
            persistence.save_match(self.match_path, self.config, self.teams,
                                   self.engine.events)

    def open_report(self) -> None:
        if not self.engine:
            return
        from .report_view import ReportDialog
        ReportDialog(self.teams, self.engine.events, self).exec()

    def open_adjust(self) -> None:
        if self.engine:
            AdjustDialog(self).exec()

    # ------------------------------------------------------ rally gestures

    def on_trajectory(self, x1: float, y1: float, x2: float, y2: float) -> None:
        if not self.engine:
            return
        st = self.engine.state
        traj = (round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2))
        if st.phase == Phase.AWAIT_SERVE:
            team = st.serving_team
            server = self.engine.expected_server()
            rating = (Rating.ERROR if self._serve_is_out(team, x2, y2)
                      else Rating.GOOD)
            self.court.clear_trajectories()
            self.court.add_trajectory(*traj, kind="serve")
            self._append(ServeEvent(team, server, rating, traj))
            if self.engine.state.phase == Phase.RECEPTION:
                self.candidate = (other(team), self._nearest(other(team), x2, y2))
                self.refresh()
        elif st.phase == Phase.RECEPTION:
            # scouter skipped rating the reception: log it '+' and treat the
            # drag as the attack
            recv = other(st.serving_team)
            receiver = (self.candidate[1] if self.candidate
                        and self.candidate[0] == recv
                        else self._nearest(recv, x1, y1))
            self._append(ReceptionEvent(recv, receiver, Rating.GOOD))
            self.candidate = None      # attacker gets picked from the drag
            self._begin_pending_attack(recv, traj)
        elif st.phase == Phase.ATTACK:
            self._begin_pending_attack(st.attacking_team, traj)
        elif st.phase == Phase.DEFENSE:
            # counter-attack with implicit unrated dig
            self._begin_pending_attack(other(st.attacking_team), traj)

    def _begin_pending_attack(self, team: str, traj: tuple) -> None:
        if (self.candidate and self.candidate[0] == team):
            attacker = self.candidate[1]
        else:
            attacker = self._nearest(team, traj[0], traj[1])
        self.pending_attack = (team, attacker, traj)
        self.candidate = (team, attacker)
        self.court.add_trajectory(*traj, kind="attack")
        self.refresh()

    def on_rating(self, rating: Rating) -> None:
        if not self.engine:
            return
        st = self.engine.state
        if self.pending_attack is not None:
            team, attacker, traj = self.pending_attack
            self.pending_attack = None
            self._append(AttackEvent(team, attacker, rating, traj))
            self._auto_select_digger(traj)
        elif st.phase == Phase.RECEPTION:
            recv = other(st.serving_team)
            if not (self.candidate and self.candidate[0] == recv):
                self._hint("tap the receiving player first")
                return
            self._append(ReceptionEvent(recv, self.candidate[1], rating))
            self.candidate = None      # next attacker comes from the drag
            self.refresh()
        elif st.phase == Phase.ATTACK:
            if self.candidate and self.candidate[0] == st.attacking_team:
                self._append(AttackEvent(st.attacking_team, self.candidate[1],
                                         rating, None))
            else:
                self._hint("draw the attack trajectory or tap the attacker")
        elif st.phase == Phase.DEFENSE:
            defender_team = other(st.attacking_team)
            if not (self.candidate and self.candidate[0] == defender_team):
                self._hint("tap the defending player first")
                return
            self._append(DigEvent(defender_team, self.candidate[1], rating))
            self.candidate = None      # counter-attacker comes from the drag
            self.refresh()
        else:
            self._hint("draw the serve first")

    def _auto_select_digger(self, traj: tuple | None) -> None:
        """After a non-terminal attack, preselect the most likely digger:
        the defending player nearest to where the attack landed."""
        st = self.engine.state
        if st.phase != Phase.DEFENSE:
            return
        defender_team = other(st.attacking_team)
        if traj is not None:
            digger = self._nearest(defender_team, traj[2], traj[3])
        else:
            digger = st.team[defender_team].lineup[5]   # P6, middle back
        self.candidate = (defender_team, digger)
        self.refresh()

    def on_serve_chip(self, rating: Rating) -> None:
        """Re-rate the serve that was just entered with the default '+'."""
        if not self.engine or not self.engine.events:
            return
        last = self.engine.events[-1]
        if not isinstance(last, ServeEvent):
            self._hint("serve rating can only be changed right after the serve")
            self.refresh()
            return
        self.engine.undo()
        self._append(ServeEvent(last.team, last.player_id, rating,
                                last.trajectory))

    def on_player_tapped(self, team_key: str, player_id: str) -> None:
        if not self.engine:
            return
        if self.armed_bench and self.armed_bench[0] == team_key:
            self._complete_exchange(team_key, court_pid=player_id)
            return
        self.candidate = (team_key, player_id)
        if self.pending_attack and self.pending_attack[0] == team_key:
            t, _, traj = self.pending_attack
            self.pending_attack = (t, player_id, traj)
        self.refresh()

    def on_court_tapped(self, x: float, y: float) -> None:
        if self.armed_bench:
            self.armed_bench = None
            self.refresh()

    def on_bench_tapped(self, team_key: str, player_id: str) -> None:
        if not self.engine:
            return
        if self.armed_bench == (team_key, player_id):
            self.armed_bench = None           # tap again to cancel
        else:
            self.armed_bench = (team_key, player_id)
            # quick path: libero exchange auto-completes when unambiguous
            ts = self.engine.state.team[team_key]
            if player_id in ts.liberos:
                pass  # scouter now taps the court player to replace
        self.refresh()

    def _complete_exchange(self, team_key: str, court_pid: str) -> None:
        bench_pid = self.armed_bench[1]
        self.armed_bench = None
        ts = self.engine.state.team[team_key]
        if bench_pid in ts.liberos:
            ev = LiberoSwapEvent(team_key, libero_id=bench_pid,
                                 partner_id=court_pid)
        elif court_pid in ts.liberos:
            ev = LiberoSwapEvent(team_key, libero_id=court_pid,
                                 partner_id=bench_pid)
        else:
            ev = SubstitutionEvent(team_key, player_out=court_pid,
                                   player_in=bench_pid)
        self._append(ev)

    def on_point_side(self, side: str) -> None:
        if self.engine and self.engine.state.phase not in (
                Phase.BEFORE_SET, Phase.SET_OVER, Phase.MATCH_OVER):
            self._append(RallyPointEvent(self.engine.team_on_side(side)))

    def on_timeout(self, side: str) -> None:
        if self.engine:
            team = self.engine.team_on_side(side)
            self._append(TimeoutEvent(team))
            self._hint(f"timeout {self.teams[team].name}")

    def on_undo(self) -> None:
        if not self.engine:
            return
        removed = self.engine.undo()
        self._clear_pending()
        self._rebuild_arrows()
        if removed is not None:
            self._hint(f"undid: {removed.TYPE}")
        self._autosave()
        self.refresh()

    # ------------------------------------------------------------ plumbing

    def _append(self, event) -> None:
        warnings = self.engine.append(event)
        if isinstance(event, (RallyPointEvent,)) or self.engine.state.phase \
                in (Phase.AWAIT_SERVE, Phase.SET_OVER, Phase.MATCH_OVER):
            self._clear_pending(keep_arrows=True)
        if warnings:
            self._hint("⚠ " + "; ".join(warnings))
        self._autosave()
        self.refresh()
        if self.engine.state.phase == Phase.SET_OVER:
            QTimer.singleShot(50, self._set_over_dialog)
        elif self.engine.state.phase == Phase.MATCH_OVER:
            QTimer.singleShot(50, self._match_over_dialog)

    def _clear_pending(self, keep_arrows: bool = False) -> None:
        self.candidate = None
        self.pending_attack = None
        self.armed_bench = None

    def _hint(self, text: str) -> None:
        self._transient_warning = text
        QTimer.singleShot(4000, self._expire_hint)
        self.refresh()

    def _expire_hint(self) -> None:
        self._transient_warning = ""
        self.refresh()

    def _autosave(self) -> None:
        if not (self.engine and self.match_path):
            return
        events = list(self.engine.events)

        def work():
            with self._save_lock:
                persistence.save_match(self.match_path, self.config,
                                       self.teams, events)
        threading.Thread(target=work, daemon=True).start()

    def _serve_is_out(self, serving_team: str, x2: float, y2: float) -> bool:
        opp_side = self.engine.side_of(other(serving_team))
        t = OUT_TOLERANCE
        if not (-t <= y2 <= rotation.COURT_WIDTH + t):
            return True
        if opp_side == LEFT:
            return not (-rotation.COURT_HALF_LENGTH - t <= x2 <= t)
        return not (-t <= x2 <= rotation.COURT_HALF_LENGTH + t)

    def _nearest(self, team_key: str, x: float, y: float) -> str:
        st = self.engine.state
        side = self.engine.side_of(team_key)
        best, best_d = None, 1e9
        for idx, pid in enumerate(st.team[team_key].lineup):
            px, py = position_xy(idx, side)
            d = (px - x) ** 2 + (py - y) ** 2
            if d < best_d:
                best, best_d = pid, d
        return best

    def _rebuild_arrows(self) -> None:
        self.court.clear_trajectories()
        if not self.engine:
            return
        events = self.engine.events
        start = None
        for i in range(len(events) - 1, -1, -1):
            if isinstance(events[i], ServeEvent):
                start = i
                break
            if isinstance(events[i], SetStartEvent):
                break
        if start is None:
            return
        for e in events[start:]:
            if isinstance(e, ServeEvent) and e.trajectory:
                self.court.add_trajectory(*e.trajectory, kind="serve")
            elif isinstance(e, AttackEvent) and e.trajectory:
                self.court.add_trajectory(*e.trajectory, kind="attack")

    # ------------------------------------------------------------- refresh

    def refresh(self) -> None:
        if not self.engine or self.engine.state.set_number == 0:
            self.rating_bar.set_prompt("Toolbar → New match to start scouting")
            self.rating_bar.show_serve_chips(False)
            self.scoreboard.show_alert("")
            return
        st = self.engine.state
        left = st.left_team
        right = other(left)

        # --- tokens
        specs = []
        for tk in (HOME, AWAY):
            ts = st.team[tk]
            side = self.engine.side_of(tk)
            for idx, pid in enumerate(ts.lineup):
                p = self.teams[tk].player(pid)
                if p is None:
                    continue
                serving = (tk == st.serving_team and idx == 0)
                x, y = position_xy(idx, side)
                if serving and st.phase == Phase.AWAIT_SERVE:
                    x, y = serve_xy(side)
                if pid in ts.liberos or p.role == Role.LIBERO:
                    color, badge = LIBERO_COLOR, "L"
                elif p.role == Role.SETTER:
                    color, badge = SETTER_COLOR, "S"
                else:
                    color, badge = self.teams[tk].color, ""
                highlight = (self.candidate == (tk, pid))
                specs.append(dict(team_key=tk, player_id=pid, number=p.number,
                                  name=p.name, color=color, badge=badge,
                                  x=x, y=y, highlight=highlight,
                                  serving=serving))
        self.court.update_tokens(specs)

        # --- benches follow court sides
        for panel, tk in ((self.bench_left, left), (self.bench_right, right)):
            panel.team_key = tk
            ts = st.team[tk]
            entries = []
            for p in sorted(self.teams[tk].players, key=lambda q: q.number):
                if p.id in ts.lineup:
                    continue
                if p.id in ts.liberos:
                    color, badge = LIBERO_COLOR, "L"
                elif p.role == Role.SETTER:
                    color, badge = SETTER_COLOR, "S"
                else:
                    color, badge = self.teams[tk].color, ""
                entries.append(dict(player_id=p.id, number=p.number,
                                    name=p.name, color=color, badge=badge))
            panel.update_bench(
                self.teams[tk].name, entries,
                f"subs {ts.subs_used}/{self.config.subs_per_set}   "
                f"TO {ts.timeouts}/2")
            panel.set_armed(self.armed_bench[1]
                            if self.armed_bench and self.armed_bench[0] == tk
                            else None)

        # --- scoreboard
        serving_side = self.engine.side_of(st.serving_team)
        server_txt = ""
        server_id = self.engine.expected_server()
        if server_id:
            sp = self.teams[st.serving_team].player(server_id)
            if sp:
                server_txt = f"serve: #{sp.number} {sp.name}"
        self.scoreboard.update_view(
            self.teams[left].name, self.teams[right].name,
            st.scores[left], st.scores[right],
            st.set_scores[left], st.set_scores[right], st.set_number,
            serving_side, server_txt)
        self.rating_bar.set_point_labels(self.teams[left].name,
                                         self.teams[right].name)

        alerts = self.engine.pending_alerts()
        sp_info = self.engine.set_point_info()
        if sp_info:
            alerts.append(sp_info.upper())
        if self._transient_warning:
            alerts.insert(0, self._transient_warning)
        self.scoreboard.show_alert("   |   ".join(alerts))

        # --- prompt + serve chips
        self._refresh_prompt(st)
        self.next_set_action.setEnabled(st.phase == Phase.SET_OVER)

    def _refresh_prompt(self, st) -> None:
        chips = False
        chip_rating = None
        if st.phase == Phase.AWAIT_SERVE:
            sp = self.teams[st.serving_team].player(
                self.engine.expected_server() or "")
            who = f"#{sp.number} {sp.name}" if sp else "server"
            prompt = f"SERVE {self.teams[st.serving_team].name} {who}: drag the ball trajectory"
        elif st.phase == Phase.RECEPTION:
            prompt = "RECEPTION: rate " + self._cand_txt() + " with ! - + #"
            last = self.engine.events[-1] if self.engine.events else None
            if isinstance(last, ServeEvent):
                chips, chip_rating = True, last.rating
        elif st.phase == Phase.ATTACK:
            if self.pending_attack:
                prompt = "ATTACK: rate " + self._cand_txt() + " with ! - + #"
            else:
                prompt = (f"ATTACK {self.teams[st.attacking_team].name}: "
                          "drag the attack trajectory (or tap the attacker)")
        elif st.phase == Phase.DEFENSE:
            if self.pending_attack:
                prompt = "COUNTER-ATTACK: rate " + self._cand_txt()
            else:
                dteam = other(st.attacking_team)
                prompt = (f"DEFENSE {self.teams[dteam].name}: rate the dig "
                          + self._cand_txt() + " — or drag the counter-attack")
        elif st.phase == Phase.SET_OVER:
            prompt = "Set finished — toolbar 'Next set' to continue"
        elif st.phase == Phase.MATCH_OVER:
            prompt = "Match finished — open the Report"
        else:
            prompt = ""
        self.rating_bar.set_prompt(prompt)
        self.rating_bar.show_serve_chips(chips, chip_rating)

    def _cand_txt(self) -> str:
        if not self.candidate:
            return "(tap player)"
        tk, pid = self.candidate
        p = self.teams[tk].player(pid)
        return f"#{p.number} {p.name}" if p else "(tap player)"

    # ------------------------------------------------------------ set flow

    def _set_over_dialog(self) -> None:
        st = self.engine.state
        w = st.last_set_winner
        box = QMessageBox(self)
        box.setWindowTitle("Set finished")
        box.setText(f"Set {st.set_number}: {self.teams[w].name} wins "
                    f"{st.scores[w]}–{st.scores[other(w)]}.\n"
                    "Teams switch sides.")
        b_start = box.addButton("Start next set", QMessageBox.ButtonRole.AcceptRole)
        b_edit = box.addButton("Edit lineups…", QMessageBox.ButtonRole.ActionRole)
        box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is b_start:
            self._append(self.engine.suggest_next_set_start())
        elif box.clickedButton() is b_edit:
            self.next_set(edit=True)

    def next_set(self, edit: bool = False) -> None:
        if not self.engine or self.engine.state.phase != Phase.SET_OVER:
            return
        suggestion = self.engine.suggest_next_set_start()
        if not edit:
            self._append(suggestion)
            return
        dlg = LineupDialog(self.teams, suggestion, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._append(dlg.get_event())

    def _match_over_dialog(self) -> None:
        st = self.engine.state
        w = HOME if st.set_scores[HOME] > st.set_scores[AWAY] else AWAY
        box = QMessageBox(self)
        box.setWindowTitle("Match finished")
        box.setText(f"{self.teams[w].name} wins the match "
                    f"{st.set_scores[w]}–{st.set_scores[other(w)]}!")
        b_rep = box.addButton("Show report", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Close", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is b_rep:
            self.open_report()


class LineupDialog(QDialog):
    """Edit the starting lineups / serving team / sides for the next set."""

    def __init__(self, teams: dict, suggestion: SetStartEvent, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Set {suggestion.set_number} lineups")
        self.teams = teams
        self.suggestion = suggestion
        self._combos: dict[str, list[QComboBox]] = {HOME: [], AWAY: []}
        grid = QGridLayout(self)
        pos_names = ["P1 (serves first)", "P2 right front", "P3 middle front",
                     "P4 left front", "P5 left back", "P6 middle back"]
        for col, tk in enumerate((HOME, AWAY)):
            grid.addWidget(QLabel(f"<b>{teams[tk].name}</b>"), 0, col + 1)
            eligible = [p for p in teams[tk].players
                        if p.id not in suggestion.liberos.get(tk, [])]
            for row in range(6):
                if col == 0:
                    grid.addWidget(QLabel(pos_names[row]), row + 1, 0)
                cb = QComboBox()
                cb.setMinimumHeight(38)
                for p in eligible:
                    cb.addItem(f"#{p.number} {p.name}", p.id)
                want = suggestion.lineups[tk][row]
                idx = cb.findData(want)
                cb.setCurrentIndex(max(0, idx))
                self._combos[tk].append(cb)
                grid.addWidget(cb, row + 1, col + 1)

        self._serve_group = QButtonGroup(self)
        r = 7
        grid.addWidget(QLabel("First serve:"), r, 0)
        self.rb_serve = {}
        for col, tk in enumerate((HOME, AWAY)):
            rb = QRadioButton(teams[tk].name)
            rb.setChecked(suggestion.serving_team == tk)
            self._serve_group.addButton(rb)
            self.rb_serve[tk] = rb
            grid.addWidget(rb, r, col + 1)
        grid.addWidget(QLabel("Left side:"), r + 1, 0)
        self._side_group = QButtonGroup(self)
        self.rb_left = {}
        for col, tk in enumerate((HOME, AWAY)):
            rb = QRadioButton(teams[tk].name)
            rb.setChecked(suggestion.left_team == tk)
            self._side_group.addButton(rb)
            self.rb_left[tk] = rb
            grid.addWidget(rb, r + 1, col + 1)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._validate_accept)
        bb.rejected.connect(self.reject)
        grid.addWidget(bb, r + 2, 0, 1, 3)

    def _validate_accept(self) -> None:
        for tk in (HOME, AWAY):
            ids = [cb.currentData() for cb in self._combos[tk]]
            if len(set(ids)) != 6:
                QMessageBox.warning(self, "Lineup",
                                    f"{self.teams[tk].name}: six distinct "
                                    "players required.")
                return
        self.accept()

    def get_event(self) -> SetStartEvent:
        return SetStartEvent(
            set_number=self.suggestion.set_number,
            lineups={tk: [cb.currentData() for cb in self._combos[tk]]
                     for tk in (HOME, AWAY)},
            liberos=self.suggestion.liberos,
            serving_team=HOME if self.rb_serve[HOME].isChecked() else AWAY,
            left_team=HOME if self.rb_left[HOME].isChecked() else AWAY)


class AdjustDialog(QDialog):
    """Manual corrections: score +/- and serve possession. Every press is a
    normal engine event, so it shows up in the log and is undoable."""

    def __init__(self, main: MainWindow):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("Manual adjustment")
        lay = QGridLayout(self)
        self.info = QLabel()
        self.info.setStyleSheet("font-size:20px; font-weight:700;")
        lay.addWidget(self.info, 0, 0, 1, 4)
        for col, tk in enumerate((HOME, AWAY)):
            name = main.teams[tk].name
            for i, (txt, delta) in enumerate((("+1", 1), ("−1", -1))):
                b = QPushButton(f"{name} {txt}")
                b.setMinimumHeight(52)
                b.clicked.connect(lambda _=False, t=tk, d=delta: self._score(t, d))
                lay.addWidget(b, 1 + i, col * 2, 1, 2)
            b = QPushButton(f"serve → {name}")
            b.setMinimumHeight(52)
            b.clicked.connect(lambda _=False, t=tk: self._serve(t))
            lay.addWidget(b, 3, col * 2, 1, 2)
        close = QPushButton("Close")
        close.setMinimumHeight(46)
        close.clicked.connect(self.accept)
        lay.addWidget(close, 4, 0, 1, 4)
        self._sync()

    def _sync(self) -> None:
        st = self.main.engine.state
        self.info.setText(
            f"{self.main.teams[HOME].name} {st.scores[HOME]} : "
            f"{st.scores[AWAY]} {self.main.teams[AWAY].name}   "
            f"(serve: {self.main.teams[st.serving_team].name})")

    def _score(self, team: str, delta: int) -> None:
        self.main._append(ManualScoreEvent(team, delta))
        self._sync()

    def _serve(self, team: str) -> None:
        self.main._append(ServeOverrideEvent(team))
        self._sync()
