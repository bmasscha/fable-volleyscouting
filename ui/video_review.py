"""Desktop video-review window: filter a scouted match's actions and play or
export the matching 7 s video fragments.

Local files play through QMediaPlayer; a YouTube video plays through an embedded
web view driving the IFrame Player API. Both sit behind PlayerController, so the
filtering / clip / sync / export logic is player-agnostic.
"""
from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import QObject, Qt, QTimer, QUrl
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (QComboBox, QDoubleSpinBox, QFileDialog,
                             QHBoxLayout, QInputDialog, QLabel, QListWidget,
                             QListWidgetItem, QMainWindow, QMessageBox,
                             QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from core.models import AWAY, HOME, Rating, Role, Skill
from core.persistence import load_match
from core.query import Action, ActionFilter, build_actions, filter_actions
from core.video_export import (clip_filename, concat_list_text, export_clip,
                              ffmpeg_concat_cmd, ffmpeg_exe, run)
from core.video_sync import (FILE, YOUTUBE, Anchor, VideoLink, clip_window,
                             event_to_video_time, youtube_id)

_ANY = "— any —"

# YouTube IFrame API host page; loadVideo(id) is called from Python.
_YOUTUBE_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8">
<style>html,body{margin:0;height:100%;background:#000}#p{width:100%;height:100%}</style>
</head><body><div id="p"></div>
<script src="https://www.youtube.com/iframe_api"></script>
<script>
var player=null, pending=null;
function onYouTubeIframeAPIReady(){ if(pending!==null) loadVideo(pending); }
function loadVideo(id){
  pending=id;
  if(typeof YT==='undefined'||!YT.Player){ return; }
  if(player){ player.loadVideoById(id); return; }
  player=new YT.Player('p',{videoId:id,playerVars:{controls:1,rel:0,modestbranding:1}});
}
</script></body></html>"""


# --------------------------------------------------------------- players

class PlayerController(QObject):
    """Common interface over the local and YouTube players. Times in seconds."""

    def widget(self) -> QWidget:            # pragma: no cover - interface
        raise NotImplementedError

    def load(self, source_ref: str) -> None:   # pragma: no cover - interface
        raise NotImplementedError

    def play(self) -> None: ...
    def pause(self) -> None: ...
    def seek(self, seconds: float) -> None: ...
    def current_time(self) -> float: return 0.0
    def set_rate(self, rate: float) -> None: ...


class LocalPlayer(PlayerController):
    def __init__(self) -> None:
        super().__init__()
        self._video = QVideoWidget()
        self._player = QMediaPlayer()
        self._audio = QAudioOutput()
        self._player.setAudioOutput(self._audio)
        self._player.setVideoOutput(self._video)

    def widget(self) -> QWidget:
        return self._video

    def load(self, source_ref: str) -> None:
        self._player.setSource(QUrl.fromLocalFile(source_ref))

    def play(self) -> None:
        self._player.play()

    def pause(self) -> None:
        self._player.pause()

    def seek(self, seconds: float) -> None:
        self._player.setPosition(int(max(0.0, seconds) * 1000))

    def current_time(self) -> float:
        return self._player.position() / 1000.0

    def set_rate(self, rate: float) -> None:
        self._player.setPlaybackRate(rate)


class YouTubePlayer(PlayerController):
    def __init__(self) -> None:
        super().__init__()
        from PyQt6.QtWebEngineWidgets import QWebEngineView  # lazy: heavy import
        self._view = QWebEngineView()
        self._view.setHtml(_YOUTUBE_HTML, QUrl("https://www.youtube.com"))
        self._current = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(200)

    def widget(self) -> QWidget:
        return self._view

    def _js(self, code: str, cb=None) -> None:
        if cb is None:
            self._view.page().runJavaScript(code)
        else:
            self._view.page().runJavaScript(code, cb)

    def load(self, source_ref: str) -> None:
        self._js(f"loadVideo('{source_ref}')")

    def play(self) -> None:
        self._js("player && player.playVideo()")

    def pause(self) -> None:
        self._js("player && player.pauseVideo()")

    def seek(self, seconds: float) -> None:
        self._js(f"player && player.seekTo({max(0.0, seconds)}, true)")

    def set_rate(self, rate: float) -> None:
        self._js(f"player && player.setPlaybackRate({rate})")

    def _poll(self) -> None:
        self._js("(player && player.getCurrentTime) ? player.getCurrentTime() : 0",
                 self._set_current)

    def _set_current(self, value) -> None:
        try:
            self._current = float(value)
        except (TypeError, ValueError):
            pass

    def current_time(self) -> float:
        return self._current


# --------------------------------------------------------------- window

def sidecar_path(match_path: str | Path) -> Path:
    """Where the video link for a match file is stored (match.json ->
    match.videolink.json)."""
    return Path(match_path).with_suffix(".videolink.json")


class VideoReviewWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Fable Scouter — Video review")
        self.resize(1200, 760)

        self._match_path: Path | None = None
        self._teams: dict = {}
        self._events: list = []
        self._actions: list[Action] = []
        self._filtered: list[Action] = []
        self._link = VideoLink()
        self._player: PlayerController | None = None
        self._clip_end: float | None = None
        self._play_queue: list[int] = []

        self._build_ui()

        self._clip_timer = QTimer(self)
        self._clip_timer.timeout.connect(self._tick)
        self._clip_timer.start(120)

    # ---- UI construction -------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        root = QHBoxLayout(central)

        # left: filters
        left = QVBoxLayout()
        left.addWidget(QLabel("<b>Filters</b>"))
        self.team_combo = self._combo(left, "Team", [_ANY, "Home", "Away"])
        self.player_combo = self._combo(left, "Player", [_ANY])
        self.role_combo = self._combo(
            left, "Role", [_ANY] + [r.value for r in Role])
        self.skill_combo = self._combo(
            left, "Skill", [_ANY] + [s.value for s in Skill])
        self.rating_combo = self._combo(
            left, "Rating", [_ANY] + [r.symbol for r in Rating])
        self.set_combo = self._combo(left, "Set", [_ANY])
        for combo in (self.team_combo, self.player_combo, self.role_combo,
                      self.skill_combo, self.rating_combo, self.set_combo):
            combo.currentIndexChanged.connect(self.refresh_clip_list)
        left.addStretch(1)
        left.addWidget(QLabel("<b>Open</b>"))
        left.addWidget(self._button("Open match…", self._on_open_match))
        left.addWidget(self._button("Open video file…", self._on_open_video_file))
        left.addWidget(self._button("Use YouTube URL…", self._on_open_youtube))
        root.addLayout(left, 0)

        # center: player + transport
        center = QVBoxLayout()
        self.player_stack = QStackedWidget()
        self._placeholder = QLabel("Open a match and a video to begin.")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.player_stack.addWidget(self._placeholder)
        center.addWidget(self.player_stack, 1)
        transport = QHBoxLayout()
        transport.addWidget(self._button("Play", lambda: self._player and self._player.play()))
        transport.addWidget(self._button("Pause", self._pause))
        self.speed_combo = QComboBox()
        self.speed_combo.addItems(["0.5x", "1x", "1.5x", "2x"])
        self.speed_combo.setCurrentText("1x")
        self.speed_combo.currentTextChanged.connect(self._on_speed)
        transport.addWidget(self.speed_combo)
        transport.addWidget(QLabel("Before"))
        self.before_spin = self._clip_spin(self._link.pre_roll)
        transport.addWidget(self.before_spin)
        transport.addWidget(QLabel("After"))
        self.after_spin = self._clip_spin(self._link.post_roll)
        transport.addWidget(self.after_spin)
        for spin in (self.before_spin, self.after_spin):
            spin.valueChanged.connect(self._on_clip_window_changed)
        self.status_label = QLabel("")
        transport.addWidget(self.status_label, 1)
        center.addLayout(transport)
        root.addLayout(center, 1)

        # right: clip list + sync + export
        right = QVBoxLayout()
        right.addWidget(QLabel("<b>Matching actions</b>"))
        self.clip_list = QListWidget()
        self.clip_list.itemActivated.connect(lambda _i: self.play_selected())
        right.addWidget(self.clip_list, 1)
        right.addWidget(self._button("Play selected", self.play_selected))
        right.addWidget(self._button("Play all", self.play_all))
        right.addWidget(QLabel("<b>Sync</b>"))
        self.sync_label = QLabel("No anchors yet.")
        right.addWidget(self.sync_label)
        right.addWidget(self._button("Sync here (pin selected action)", self.add_anchor_for_selected))
        right.addWidget(QLabel("<b>Export (local/YouTube)</b>"))
        right.addWidget(self._button("Export selected clip", self.export_selected))
        right.addWidget(self._button("Export all matching", self.export_all))
        right.addWidget(self._button("Export highlight reel", self.export_reel))
        root.addLayout(right, 0)

        self.setCentralWidget(central)

    def _combo(self, layout: QVBoxLayout, label: str, items: list[str]) -> QComboBox:
        layout.addWidget(QLabel(label))
        combo = QComboBox()
        combo.addItems(items)
        layout.addWidget(combo)
        return combo

    def _button(self, text: str, slot) -> QPushButton:
        b = QPushButton(text)
        b.clicked.connect(slot)
        return b

    def _clip_spin(self, value: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 60.0)
        spin.setSingleStep(0.5)
        spin.setDecimals(1)
        spin.setSuffix(" s")
        spin.setValue(value)
        return spin

    def _on_clip_window_changed(self) -> None:
        """The user edited the before/after seconds: store them on the link
        (so play and export both use them) and persist."""
        self._link.pre_roll = self.before_spin.value()
        self._link.post_roll = self.after_spin.value()
        self._save_link()
        self.refresh_clip_list()

    def _sync_clip_spins(self) -> None:
        """Reflect the loaded link's window onto the spin boxes without
        triggering a save."""
        for spin, value in ((self.before_spin, self._link.pre_roll),
                            (self.after_spin, self._link.post_roll)):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)

    # ---- match / video loading ------------------------------------------

    def open_match_path(self, path: str | Path) -> None:
        config, teams, events = load_match(path)
        self._match_path = Path(path)
        self._teams = teams
        self._events = events
        self._actions = build_actions(events, teams)
        self._populate_player_and_set_filters()
        # restore a previously saved video link, if any
        sc = sidecar_path(path)
        if sc.exists():
            try:
                self._link = VideoLink.from_dict(json.loads(sc.read_text("utf-8")))
                self._load_link_source()
            except (OSError, ValueError, KeyError):
                self._link = VideoLink()
        self._sync_clip_spins()
        self.refresh_clip_list()
        self._update_sync_label()

    def _populate_player_and_set_filters(self) -> None:
        self.player_combo.blockSignals(True)
        self.player_combo.clear()
        self.player_combo.addItem(_ANY, userData=None)
        for key, label in ((HOME, "Home"), (AWAY, "Away")):
            team = self._teams.get(key)
            if team is None:
                continue
            for p in sorted(team.players, key=lambda p: p.number):
                self.player_combo.addItem(f"{label} #{p.number} {p.name}", userData=p.id)
        self.player_combo.blockSignals(False)

        sets = sorted({a.set_number for a in self._actions})
        self.set_combo.blockSignals(True)
        self.set_combo.clear()
        self.set_combo.addItem(_ANY)
        for s in sets:
            self.set_combo.addItem(str(s))
        self.set_combo.blockSignals(False)

    def set_video_source_file(self, path: str) -> None:
        self._link.source_kind = FILE
        self._link.source_ref = path
        self._save_link()
        self._load_link_source()
        self.refresh_clip_list()

    def set_video_source_youtube(self, url_or_id: str) -> bool:
        vid = youtube_id(url_or_id)
        if vid is None:
            return False
        self._link.source_kind = YOUTUBE
        self._link.source_ref = vid
        self._save_link()
        self._load_link_source()
        self.refresh_clip_list()
        return True

    def _load_link_source(self) -> None:
        if not self._link.source_ref:
            return
        kind = self._link.source_kind
        try:
            self._ensure_player(YOUTUBE if kind == YOUTUBE else FILE)
        except Exception as e:  # e.g. PyQt6-WebEngine missing for a YouTube link
            self._warn(f"Could not start the {kind} player: {e}")
            return
        assert self._player is not None
        self._player.load(self._link.source_ref)

    def _ensure_player(self, kind: str) -> None:
        want = YouTubePlayer if kind == YOUTUBE else LocalPlayer
        if isinstance(self._player, want):
            return
        self._player = want()
        self.player_stack.addWidget(self._player.widget())
        self.player_stack.setCurrentWidget(self._player.widget())

    # ---- filtering / clip list ------------------------------------------

    def current_filter(self) -> ActionFilter:
        team_txt = self.team_combo.currentText()
        team_key = {"Home": HOME, "Away": AWAY}.get(team_txt)
        player_id = self.player_combo.currentData()
        role_txt = self.role_combo.currentText()
        role = None if role_txt == _ANY else Role(role_txt)
        skill_txt = self.skill_combo.currentText()
        skill = None if skill_txt == _ANY else Skill(skill_txt)
        rating_txt = self.rating_combo.currentText()
        rating = None if rating_txt == _ANY else Rating(rating_txt)
        set_txt = self.set_combo.currentText()
        set_number = None if set_txt == _ANY else int(set_txt)
        return ActionFilter(team_key=team_key, player_id=player_id, role=role,
                            skill=skill, rating=rating, set_number=set_number)

    def refresh_clip_list(self) -> None:
        self._filtered = filter_actions(self._actions, self.current_filter())
        self.clip_list.clear()
        for a in self._filtered:
            item = QListWidgetItem(self._clip_label(a))
            item.setData(Qt.ItemDataRole.UserRole, a.index)
            self.clip_list.addItem(item)
        self.status_label.setText(f"{len(self._filtered)} matching action(s)")

    def _clip_label(self, a: Action) -> str:
        vt = event_to_video_time(self._link, a.ts)
        when = f"@ {_fmt_time(vt)}" if vt is not None else "unsynced"
        return f"{when}  ·  {_player_label(a)}  ·  {_skill_label(a)}"

    def _selected_action(self) -> Action | None:
        items = self.clip_list.selectedItems()
        if not items:
            return None
        idx = items[0].data(Qt.ItemDataRole.UserRole)
        for a in self._filtered:
            if a.index == idx:
                return a
        return None

    # ---- playback --------------------------------------------------------

    def play_selected(self) -> None:
        a = self._selected_action()
        if a is not None:
            self._play_action(a)

    def play_all(self) -> None:
        if not self._filtered:
            return
        self._play_queue = [a.index for a in self._filtered[1:]]
        self._play_action(self._filtered[0])

    def _play_action(self, a: Action) -> None:
        window = clip_window(self._link, a.ts)
        if window is None or self._player is None:
            self._warn("Set a sync anchor first (Sync here) so actions map to the video.")
            return
        start, end = window
        self._clip_end = end
        self._player.seek(start)
        self._player.play()

    def _pause(self) -> None:
        self._play_queue = []
        self._clip_end = None
        if self._player is not None:
            self._player.pause()

    def _tick(self) -> None:
        if self._player is None or self._clip_end is None:
            return
        if self._player.current_time() >= self._clip_end:
            self._player.pause()
            self._clip_end = None
            if self._play_queue:
                idx = self._play_queue.pop(0)
                nxt = next((a for a in self._filtered if a.index == idx), None)
                if nxt is not None:
                    self._play_action(nxt)

    def _on_speed(self, text: str) -> None:
        if self._player is not None:
            self._player.set_rate(float(text.rstrip("x")))

    # ---- sync ------------------------------------------------------------

    def add_anchor_for_selected(self) -> None:
        a = self._selected_action()
        if a is None or a.ts is None or self._player is None:
            self._warn("Select an action and load a video, then pause at that "
                       "moment before syncing.")
            return
        self._link.anchors.append(Anchor(event_ts=a.ts,
                                         video_seconds=self._player.current_time()))
        self._save_link()
        self._update_sync_label()
        self.refresh_clip_list()

    def _update_sync_label(self) -> None:
        n = len(self._link.anchors)
        self.sync_label.setText(f"{n} anchor(s) set." if n else "No anchors yet.")

    # ---- export ----------------------------------------------------------

    def export_selected(self) -> None:
        a = self._selected_action()
        if a is None:
            return
        out_dir = self._ask_out_dir()
        if out_dir:
            self._run_export([a], out_dir)

    def export_all(self) -> None:
        if not self._filtered:
            return
        out_dir = self._ask_out_dir()
        if out_dir:
            self._run_export(self._filtered, out_dir)

    def _export_actions(self, actions: list[Action], out_dir: str) -> tuple[list[str], list[str]]:
        """Export each action's clip. Returns (written_paths, failed_names). Pure
        of any UI (no dialogs) so it is testable; raises ValueError when an
        action cannot be mapped to the video (no anchor set)."""
        done: list[str] = []
        failures: list[str] = []
        for a in actions:
            team = self._teams.get(a.team_key)
            team_name = team.name if team is not None else ""
            out, result = export_clip(self._link, a, out_dir, team_name=team_name)
            if result.returncode == 0:
                done.append(out)
            else:
                failures.append(Path(out).name)
        return done, failures

    def _run_export(self, actions: list[Action], out_dir: str) -> list[str]:
        try:
            done, failures = self._export_actions(actions, out_dir)
        except ValueError as e:
            self._warn(str(e))
            return []
        msg = f"Exported {len(done)} clip(s) to\n{out_dir}"
        if failures:
            msg += f"\n\nFailed: {', '.join(failures[:5])}"
        self._info(msg)
        return done

    def export_reel(self) -> None:
        if not self._filtered:
            return
        out_dir = self._ask_out_dir()
        if not out_dir:
            return
        try:
            clips, _failures = self._export_actions(self._filtered, out_dir)
        except ValueError as e:
            self._warn(str(e))
            return
        if len(clips) < 2:
            self._warn("Need at least two exported clips to build a reel.")
            return
        list_file = Path(out_dir) / "_reel_list.txt"
        list_file.write_text(concat_list_text(clips), encoding="utf-8")
        reel = str(Path(out_dir) / "highlight_reel.mp4")
        result = run(ffmpeg_concat_cmd(str(list_file), reel, ffmpeg=ffmpeg_exe()))
        list_file.unlink(missing_ok=True)
        if result.returncode == 0:
            self._info(f"Highlight reel written:\n{reel}")
        else:
            self._warn("Reel concat failed (clips may have differing codecs).")

    def _ask_out_dir(self) -> str:
        return QFileDialog.getExistingDirectory(self, "Export clips to folder")

    # ---- persistence / dialogs ------------------------------------------

    def _save_link(self) -> None:
        if self._match_path is None:
            return
        try:
            sidecar_path(self._match_path).write_text(
                json.dumps(self._link.to_dict(), indent=1), encoding="utf-8")
        except OSError:
            pass

    def _on_open_match(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open match", "", "Match files (*.json);;All files (*)")
        if path:
            self.open_match_path(path)

    def _on_open_video_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open video", "",
            "Video files (*.mp4 *.avi *.mkv *.mov *.webm);;All files (*)")
        if path:
            self.set_video_source_file(path)

    def _on_open_youtube(self) -> None:
        url, ok = QInputDialog.getText(self, "YouTube video", "Paste a YouTube URL:")
        if ok and url and not self.set_video_source_youtube(url):
            self._warn("That does not look like a YouTube URL.")

    def _warn(self, text: str) -> None:
        QMessageBox.warning(self, "Video review", text)

    def _info(self, text: str) -> None:
        QMessageBox.information(self, "Video review", text)


def _player_label(a: Action) -> str:
    """The player performing the action, e.g. "Middle 2". Falls back to the
    name (or a bare number) when the role is unknown."""
    num = str(a.player_number) if a.player_number is not None else "?"
    if a.role is not None:
        return f"{a.role.value.capitalize()} {num}"
    return a.player_name or f"#{num}"


def _skill_label(a: Action) -> str:
    """The action and its rating, e.g. "Attack +"."""
    skill = getattr(a.skill, "value", str(a.skill)).capitalize()
    rating = getattr(a.rating, "symbol", a.rating)
    return f"{skill} {rating}"


def _fmt_time(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    seconds = max(0.0, seconds)
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"
