"""PyQt6 desktop app: detect volleyball actions in a video and extract clips.

Source (local mp4 or URL) -> pick model + actions -> chunked Gemini detection on
a background thread -> results table + extracted clips. Designed so a later
"trajectory" add-on can consume the same timestamped detections.

Run:  python run_gui.py    (or:  python -m gui)
"""
from __future__ import annotations

import os
import sys
import json
import traceback
from typing import Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QUrl
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QLineEdit, QPushButton, QComboBox, QCheckBox, QRadioButton,
    QButtonGroup, QDoubleSpinBox, QPlainTextEdit, QTableWidget, QTableWidgetItem,
    QProgressBar, QFileDialog, QHeaderView, QMessageBox, QAbstractItemView, QMenu,
)

import action_detector as ad
import video_clipper as vc
import trajectory as tj
import court_chart
from results_store import ResultsStore
from actions_registry import ACTION_TYPES, cues_for
from gemini_models import VIDEO_MODELS, DEFAULT_MODEL

HERE = os.path.dirname(os.path.abspath(__file__))


# --------------------------------------------------------------------------- #
# Worker thread
# --------------------------------------------------------------------------- #
class DetectionWorker(QThread):
    log = pyqtSignal(str)
    status = pyqtSignal(str)
    progress = pyqtSignal(int)
    finished_ok = pyqtSignal(list)      # list[dict]
    failed = pyqtSignal(str)

    def __init__(self, params: dict):
        super().__init__()
        self.p = params
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        p = self.p
        try:
            analyzer = ad.VideoAnalyzer(p["source"])
            self.status.emit("Preparing source...")
            analyzer.prepare(log=self.log.emit)

            start_s = ad.parse_timestamp(p["start"]) if p["start"] else 0.0
            end_s = ad.parse_timestamp(p["end"]) if p["end"] else None
            if end_s is None:
                if analyzer.is_url:
                    end_s = start_s + p["chunk_seconds"]
                    self.log.emit("No end given for a URL -> analyzing a single chunk. "
                                  "Set an end time to cover more.")
                else:
                    dur = vc.probe_duration(p["source"])
                    end_s = dur if dur else start_s + p["chunk_seconds"]
                    self.log.emit(f"Video duration: {ad.format_timestamp(end_s)}")

            actions = cues_for(p["action_keys"])
            windows = list(ad.chunk_windows(start_s, end_s, p["chunk_seconds"], p["overlap_seconds"]))
            self.log.emit(f"Analyzing {ad.format_timestamp(start_s)}–{ad.format_timestamp(end_s)} "
                          f"in {len(windows)} chunk(s) with {p['model']}.")

            all_actions: list[ad.Action] = []
            clip_phase = 70 if p["extract_clips"] else 100
            for i, (ws, we) in enumerate(windows):
                if self._stop:
                    self.log.emit("Stopped.")
                    break
                self.status.emit(f"Analyzing chunk {i+1}/{len(windows)} "
                                 f"[{ad.format_timestamp(ws)}–{ad.format_timestamp(we)}]")
                acts = analyzer.detect(
                    actions, start=ws, end=we, model=p["model"],
                    fps=p["fps"], media_resolution=p["media_resolution"],
                )
                all_actions.extend(acts)
                self.log.emit(f"  chunk {i+1}: {len(acts)} detection(s)")
                self.progress.emit(int((i + 1) / len(windows) * clip_phase))

            merged = ad.merge_actions(all_actions)
            self.log.emit(f"{len(merged)} action(s) after merging overlaps.")

            results = [self._row(a) for a in merged]

            if p["extract_clips"] and merged and not self._stop:
                self.status.emit("Extracting clips...")
                cut_source, offset = self._clip_source(analyzer, p, start_s, end_s)
                os.makedirs(p["out_dir"], exist_ok=True)
                clip_end = 85 if p["estimate_trajectories"] else 100
                for j, a in enumerate(merged):
                    if self._stop:
                        break
                    name = (f"{j+1:02d}_{a.action}_{vc.safe_name(a.video_timestamp)}"
                            f"_{vc.safe_name(a.team)}_{vc.safe_name(a.player or 'x')}.mp4")
                    out_path = os.path.join(p["out_dir"], name)
                    try:
                        vc.cut_clip(cut_source, a.video_seconds - offset, out_path, p["pre"], p["post"])
                        results[j]["clip_path"] = out_path
                    except Exception as e:
                        self.log.emit(f"  clip {j+1} failed: {e}")
                    self.progress.emit(70 + int((j + 1) / len(merged) * (clip_end - 70)))
                self.log.emit(f"Clips written to {p['out_dir']}")

                if p["estimate_trajectories"] and not self._stop:
                    self._trajectories(p, merged, results)

                with open(os.path.join(p["out_dir"], "_actions.json"), "w", encoding="utf-8") as fh:
                    json.dump({"source": p["source"], "model": p["model"], "results": results},
                              fh, indent=2, ensure_ascii=False)

            self.progress.emit(100)
            self.status.emit("Done.")
            self.finished_ok.emit(results)
        except Exception as e:
            self.failed.emit(f"{e}\n\n{traceback.format_exc()}")

    @staticmethod
    def _row(a: ad.Action) -> dict:
        return {
            "action": a.action, "video_timestamp": a.video_timestamp,
            "video_seconds": round(a.video_seconds, 2), "team": a.team,
            "player": a.player, "confidence": a.confidence, "reasoning": a.reasoning,
            "clip_path": None,
        }

    def _clip_source(self, analyzer, p, start_s, end_s):
        """Return (file_to_cut_from, offset_seconds_at_its_t0)."""
        if not analyzer.is_url:
            return p["source"], 0.0  # cut straight from the user's mp4
        # URL: download the analyzed window once, cut from it
        here = os.path.dirname(os.path.abspath(__file__))
        media = os.path.join(here, "media")
        win = os.path.join(media, f"clipsrc_{int(start_s)}_{int(end_s)}.mp4")
        self.log.emit("Downloading analyzed window for clip extraction...")
        vc.download_url_window(p["source"], start_s, end_s, win)
        return win, start_s

    def _trajectories(self, p, merged, results):
        """Estimate a serve trajectory per serve clip and render the aggregate chart."""
        self.status.emit("Estimating serve trajectories...")
        traj_dir = os.path.join(p["out_dir"], "trajectories")
        os.makedirs(traj_dir, exist_ok=True)
        serve_idx = [j for j, a in enumerate(merged)
                     if a.action == "serve" and results[j].get("clip_path")]
        if not serve_idx:
            self.log.emit("No serve clips to trace.")
            return
        for k, j in enumerate(serve_idx):
            if self._stop:
                break
            clip = results[j]["clip_path"]
            base = os.path.splitext(os.path.basename(clip))[0]
            try:
                sa = tj.estimate_serve(clip, model=p["model"])
                tj.render_trajectory(clip, sa.keypoints,
                                     os.path.join(traj_dir, base + "_traj.mp4"),
                                     os.path.join(traj_dir, base + "_preview.png"))
                results[j]["traj_video"] = os.path.join(traj_dir, base + "_traj.mp4")
                results[j]["traj_preview"] = os.path.join(traj_dir, base + "_preview.png")
                # store court placement on the row so it lands in the results store
                results[j].update({
                    "serve_from_lateral": sa.serve_from_lateral,
                    "target_depth": sa.target_depth,
                    "target_lateral": sa.target_lateral,
                    "target_zone": sa.target_zone,
                })
                self.log.emit(f"  trajectory {base}: zone {sa.target_zone}")
            except Exception as e:
                self.log.emit(f"  trajectory {base} failed: {e}")
            self.progress.emit(85 + int((k + 1) / len(serve_idx) * 15))


# --------------------------------------------------------------------------- #
# Main window
# --------------------------------------------------------------------------- #
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Volleyball Video Action Detector")
        self.resize(1040, 820)
        self.worker: Optional[DetectionWorker] = None
        self.store = ResultsStore(os.path.join(HERE, "results", "results_db.json"))
        self._filtered: list = []
        self._build_ui()
        self._refresh_filter_options()
        self._apply_filter()

    # ---- UI construction --------------------------------------------------- #
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(10)

        root.addWidget(self._source_group())
        row = QHBoxLayout()
        row.addWidget(self._detection_group(), 3)
        row.addWidget(self._output_group(), 2)
        root.addLayout(row)

        # run controls
        ctrl = QHBoxLayout()
        self.run_btn = QPushButton("▶  Detect actions")
        self.run_btn.setMinimumHeight(38)
        self.run_btn.clicked.connect(self._on_run)
        self.stop_btn = QPushButton("■ Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._on_stop)
        ctrl.addWidget(self.run_btn, 3)
        ctrl.addWidget(self.stop_btn, 1)
        root.addLayout(ctrl)

        self.progress = QProgressBar()
        self.status_lbl = QLabel("Ready.")
        root.addWidget(self.progress)
        root.addWidget(self.status_lbl)

        # filter bar (operates on the whole stored history)
        filt = QHBoxLayout()
        filt.addWidget(QLabel("Filter —"))
        self.f_team = QComboBox(); self.f_team.currentIndexChanged.connect(self._apply_filter)
        self.f_player = QComboBox(); self.f_player.currentIndexChanged.connect(self._apply_filter)
        self.f_action = QComboBox(); self.f_action.currentIndexChanged.connect(self._apply_filter)
        for lbl, cb in (("Team:", self.f_team), ("Player:", self.f_player), ("Action:", self.f_action)):
            filt.addWidget(QLabel(lbl)); filt.addWidget(cb)
        filt.addWidget(QLabel("Chart:"))
        self.chart_type = QComboBox(); self.chart_type.addItems(["Arrows", "Heatmap", "Split by team"])
        filt.addWidget(self.chart_type)
        filt.addWidget(QLabel("Color by:"))
        self.color_by = QComboBox(); self.color_by.addItems(["team", "player"])
        filt.addWidget(self.color_by)
        filt.addStretch(1)
        self.count_lbl = QLabel("0 shown")
        filt.addWidget(self.count_lbl)
        root.addLayout(filt)

        # results + log
        res_head = QHBoxLayout()
        res_head.addWidget(QLabel("Results  (double-click a row to open its clip; right-click for more):"))
        res_head.addStretch(1)
        self.chart_btn = QPushButton("Open placement chart")
        self.chart_btn.setEnabled(False)
        self.chart_btn.clicked.connect(self._open_chart)
        self.clear_btn = QPushButton("Clear stored results")
        self.clear_btn.clicked.connect(self._clear_store)
        res_head.addWidget(self.clear_btn)
        res_head.addWidget(self.chart_btn)
        root.addLayout(res_head)

        self.COLS = ["Time", "Action", "Team", "Player", "Zone", "Conf", "Reasoning"]
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.doubleClicked.connect(self._open_clip)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_menu)
        root.addWidget(self.table, 2)
        self.color_by.currentIndexChanged.connect(self._update_chart_btn)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumBlockCount(2000)
        f = QFont("Consolas"); f.setPointSize(9); self.log_box.setFont(f)
        root.addWidget(QLabel("Log:"))
        root.addWidget(self.log_box, 1)

    def _source_group(self) -> QGroupBox:
        g = QGroupBox("1 · Video source")
        lay = QGridLayout(g)
        self.rb_file = QRadioButton("Local mp4 file")
        self.rb_url = QRadioButton("URL (YouTube / public)")
        self.rb_file.setChecked(True)
        grp = QButtonGroup(self); grp.addButton(self.rb_file); grp.addButton(self.rb_url)
        self.file_edit = QLineEdit()
        browse = QPushButton("Browse…"); browse.clicked.connect(self._pick_video)
        self.url_edit = QLineEdit(); self.url_edit.setPlaceholderText("https://youtu.be/…")
        lay.addWidget(self.rb_file, 0, 0)
        lay.addWidget(self.file_edit, 0, 1)
        lay.addWidget(browse, 0, 2)
        lay.addWidget(self.rb_url, 1, 0)
        lay.addWidget(self.url_edit, 1, 1, 1, 2)
        return g

    def _detection_group(self) -> QGroupBox:
        g = QGroupBox("2 · Detection")
        lay = QGridLayout(g)

        lay.addWidget(QLabel("Model:"), 0, 0)
        self.model_combo = QComboBox(); self.model_combo.setEditable(True)
        for mid, label in VIDEO_MODELS:
            self.model_combo.addItem(f"{label}", mid)
        self.model_combo.setCurrentIndex(0)
        lay.addWidget(self.model_combo, 0, 1, 1, 3)

        lay.addWidget(QLabel("Actions:"), 1, 0)
        acts = QHBoxLayout(); self.action_checks = {}
        for a in ACTION_TYPES:
            cb = QCheckBox(a.label + ("" if a.reliable else " *"))
            cb.setChecked(a.key == "serve")
            cb.setToolTip(a.cues + ("" if a.reliable else "\n(* experimental — lower accuracy)"))
            self.action_checks[a.key] = cb
            acts.addWidget(cb)
        holder = QWidget(); holder.setLayout(acts)
        lay.addWidget(holder, 1, 1, 1, 3)
        lay.addWidget(QLabel("* experimental"), 2, 1, 1, 3)

        lay.addWidget(QLabel("Start / End:"), 3, 0)
        self.start_edit = QLineEdit(); self.start_edit.setPlaceholderText("0:00")
        self.end_edit = QLineEdit(); self.end_edit.setPlaceholderText("end (blank = whole video)")
        lay.addWidget(self.start_edit, 3, 1)
        lay.addWidget(self.end_edit, 3, 2, 1, 2)

        lay.addWidget(QLabel("Chunk (min):"), 4, 0)
        self.chunk_spin = QDoubleSpinBox(); self.chunk_spin.setRange(0.5, 30); self.chunk_spin.setValue(5.0)
        lay.addWidget(self.chunk_spin, 4, 1)
        lay.addWidget(QLabel("Resolution:"), 4, 2)
        self.res_combo = QComboBox()
        self.res_combo.addItem("Low (cheap)", "MEDIA_RESOLUTION_LOW")
        self.res_combo.addItem("Medium", "MEDIA_RESOLUTION_MEDIUM")
        lay.addWidget(self.res_combo, 4, 3)

        lay.addWidget(QLabel("API key:"), 5, 0)
        self.key_edit = QLineEdit(); self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        if os.environ.get("GOOGLE_API_KEY"):
            self.key_edit.setPlaceholderText("using GOOGLE_API_KEY from environment")
        else:
            self.key_edit.setPlaceholderText("GOOGLE_API_KEY not set — paste it here")
        lay.addWidget(self.key_edit, 5, 1, 1, 3)
        return g

    def _output_group(self) -> QGroupBox:
        g = QGroupBox("3 · Output clips")
        lay = QGridLayout(g)
        self.extract_cb = QCheckBox("Extract a clip per detection")
        self.extract_cb.setChecked(True)
        lay.addWidget(self.extract_cb, 0, 0, 1, 3)

        lay.addWidget(QLabel("Folder:"), 1, 0)
        self.out_edit = QLineEdit(os.path.join(os.getcwd(), "clips_out"))
        outbtn = QPushButton("Browse…"); outbtn.clicked.connect(self._pick_out)
        lay.addWidget(self.out_edit, 1, 1)
        lay.addWidget(outbtn, 1, 2)

        lay.addWidget(QLabel("Before (s):"), 2, 0)
        self.pre_spin = QDoubleSpinBox(); self.pre_spin.setRange(0, 30); self.pre_spin.setValue(4.0)
        lay.addWidget(self.pre_spin, 2, 1)
        lay.addWidget(QLabel("After (s):"), 3, 0)
        self.post_spin = QDoubleSpinBox(); self.post_spin.setRange(0, 30); self.post_spin.setValue(5.0)
        lay.addWidget(self.post_spin, 3, 1)

        self.traj_cb = QCheckBox("Estimate serve trajectories + placement chart")
        self.traj_cb.setToolTip("For each serve clip, ask Gemini for ball keypoints and draw the arc.\n"
                                "Also builds an aggregate placement chart. Adds ~1 Gemini call per serve.")
        lay.addWidget(self.traj_cb, 4, 0, 1, 3)
        lay.setRowStretch(5, 1)
        return g

    # ---- pickers ----------------------------------------------------------- #
    def _pick_video(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose video", "", "Video (*.mp4 *.mov *.mkv *.webm);;All files (*)")
        if path:
            self.file_edit.setText(path); self.rb_file.setChecked(True)

    def _pick_out(self):
        d = QFileDialog.getExistingDirectory(self, "Choose clip folder", self.out_edit.text())
        if d:
            self.out_edit.setText(d)

    # ---- run / stop -------------------------------------------------------- #
    def _collect_params(self) -> Optional[dict]:
        source = self.file_edit.text().strip() if self.rb_file.isChecked() else self.url_edit.text().strip()
        if not source:
            QMessageBox.warning(self, "Missing source", "Choose an mp4 file or enter a URL."); return None
        if self.rb_file.isChecked() and not os.path.exists(source):
            QMessageBox.warning(self, "Not found", f"File does not exist:\n{source}"); return None
        keys = [k for k, cb in self.action_checks.items() if cb.isChecked()]
        if not keys:
            QMessageBox.warning(self, "No actions", "Select at least one action to detect."); return None
        if self.key_edit.text().strip():
            os.environ["GOOGLE_API_KEY"] = self.key_edit.text().strip()
        if not os.environ.get("GOOGLE_API_KEY"):
            QMessageBox.warning(self, "No API key", "Set GOOGLE_API_KEY or paste a key."); return None
        want_traj = self.traj_cb.isChecked()
        if want_traj and "serve" not in keys:
            QMessageBox.warning(self, "Serve needed",
                                "Trajectory estimation currently covers serves — tick the Serve action."); return None
        return {
            "source": source,
            "action_keys": keys,
            "model": self.model_combo.currentData() or self.model_combo.currentText().strip(),
            "start": self.start_edit.text().strip(),
            "end": self.end_edit.text().strip(),
            "chunk_seconds": self.chunk_spin.value() * 60.0,
            "overlap_seconds": 15.0,
            "fps": 1.0,
            "media_resolution": self.res_combo.currentData(),
            # trajectories need the clip files, so force extraction on when requested
            "extract_clips": self.extract_cb.isChecked() or want_traj,
            "estimate_trajectories": want_traj,
            "out_dir": self.out_edit.text().strip(),
            "pre": self.pre_spin.value(),
            "post": self.post_spin.value(),
        }

    def _on_run(self):
        params = self._collect_params()
        if not params:
            return
        self._last_params = params
        self.log_box.clear()
        self.progress.setValue(0)
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.worker = DetectionWorker(params)
        self.worker.log.connect(self._append_log)
        self.worker.status.connect(self.status_lbl.setText)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.finished_ok.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_stop(self):
        if self.worker:
            self.worker.stop()
            self.status_lbl.setText("Stopping after current chunk…")

    def _append_log(self, msg: str):
        self.log_box.appendPlainText(msg)

    def _on_done(self, results: list):
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        p = getattr(self, "_last_params", {})
        if results:
            self.store.add_run(results, source=p.get("source", ""), model=p.get("model", ""))
        self._refresh_filter_options()
        self._apply_filter()
        self.status_lbl.setText(f"Done — {len(results)} new; {len(self.store.records)} stored total.")

    # ---- filtering + persistence ------------------------------------------ #
    def _refresh_filter_options(self):
        for cb, field in ((self.f_team, "team"), (self.f_player, "player"), (self.f_action, "action")):
            cur = cb.currentText()
            cb.blockSignals(True)
            cb.clear(); cb.addItem("All")
            for v in self.store.distinct(field):
                cb.addItem(v)
            i = cb.findText(cur)
            cb.setCurrentIndex(i if i >= 0 else 0)
            cb.blockSignals(False)

    @staticmethod
    def _sel(cb) -> Optional[str]:
        t = cb.currentText()
        return None if t in ("", "All") else t

    def _apply_filter(self, *_):
        self._filtered = self.store.filter(self._sel(self.f_team), self._sel(self.f_player),
                                           self._sel(self.f_action))
        self._fill_table(self._filtered)
        self.count_lbl.setText(f"{len(self._filtered)} shown / {len(self.store.records)} stored")
        self._update_chart_btn()

    def _update_chart_btn(self, *_):
        self.chart_btn.setEnabled(bool(ResultsStore.serve_placements(self._filtered)))

    def _clear_store(self):
        if QMessageBox.question(self, "Clear stored results",
                                f"Delete all {len(self.store.records)} stored results?") \
                == QMessageBox.StandardButton.Yes:
            self.store.clear()
            self._refresh_filter_options()
            self._apply_filter()

    def _open_chart(self):
        serves = ResultsStore.serve_placements(self._filtered)
        if not serves:
            self.status_lbl.setText("No serve placements in the current filter."); return
        out = os.path.join(HERE, "results", "placement_filtered.png")
        parts = [self._sel(self.f_team) or "all teams",
                 self._sel(self.f_player) and f"#{self._sel(self.f_player)}" or ""]
        scope = ", ".join(x for x in parts if x)
        ctype = self.chart_type.currentText()
        if ctype == "Heatmap":
            court_chart.render_zone_heatmap(serves, out, title=f"Serve landing heatmap — {scope}")
        elif ctype == "Split by team":
            court_chart.render_split_by_team(serves, out, color_by=self.color_by.currentText())
        else:
            court_chart.render_court_chart(serves, out, color_by=self.color_by.currentText(),
                                           title=f"Serve placement — {scope}")
        QDesktopServices.openUrl(QUrl.fromLocalFile(out))

    def _table_menu(self, pos):
        row = self.table.rowAt(pos.y())
        if row < 0 or row >= len(self._filtered):
            return
        data = self._filtered[row]
        menu = QMenu(self)
        a_clip = menu.addAction("Open clip")
        a_clip.setEnabled(bool(data.get("clip_path")))
        a_tvid = menu.addAction("Open trajectory video")
        a_tvid.setEnabled(bool(data.get("traj_video")))
        a_timg = menu.addAction("Open trajectory image")
        a_timg.setEnabled(bool(data.get("traj_preview")))
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        target = None
        if chosen == a_clip:
            target = data.get("clip_path")
        elif chosen == a_tvid:
            target = data.get("traj_video")
        elif chosen == a_timg:
            target = data.get("traj_preview")
        if target and os.path.exists(target):
            QDesktopServices.openUrl(QUrl.fromLocalFile(target))

    def _on_failed(self, msg: str):
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_lbl.setText("Failed.")
        self._append_log("ERROR:\n" + msg)
        QMessageBox.critical(self, "Detection failed", msg.splitlines()[0] if msg else "Unknown error")

    def _fill_table(self, records: list):
        self.table.setRowCount(len(records))
        for r, rec in enumerate(records):
            zone = rec.get("target_zone")
            zone_txt = str(zone) if rec.get("action") == "serve" and zone else ""
            cells = [rec.get("video_timestamp", ""), rec.get("action", ""), rec.get("team", ""),
                     rec.get("player", ""), zone_txt, f"{rec.get('confidence', 0):.2f}",
                     rec.get("reasoning", "")]
            for c, val in enumerate(cells):
                item = QTableWidgetItem(str(val))
                if c == 0 and rec.get("clip_path"):
                    item.setData(Qt.ItemDataRole.UserRole, rec["clip_path"])
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)

    def _open_clip(self, index):
        item = self.table.item(index.row(), 0)
        path = item.data(Qt.ItemDataRole.UserRole) if item else None
        if path and os.path.exists(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            self.status_lbl.setText("No clip for this row (was clip extraction enabled?).")


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
