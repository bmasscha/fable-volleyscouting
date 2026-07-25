from pathlib import Path
from .qt_compat import (
    Qt, Slot, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLineEdit,
    QPushButton, QComboBox, QCheckBox, QSpinBox, QProgressBar, QTextEdit,
    QFileDialog, QTabWidget, QSplitter, QLabel, QRadioButton
)

from .style import DARK_THEME_QSS
from .worker_thread import AnalysisWorker
from .widgets.video_player import MediaPreviewWidget
from .widgets.results_table import ResultsTableWidget
from .addons_widget import AddonsWidget
from ..config import DEFAULT_YOUTUBE_URL, DEFAULT_MODEL, OUTPUT_DIR

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Fable Volleyball Scout - Automatic Video Analysis Engine")
        self.resize(1280, 800)
        self.setStyleSheet(DARK_THEME_QSS)

        self.worker = None

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        # -------------------------------------------------------------
        # LEFT PANEL: Controls & Settings
        # -------------------------------------------------------------
        left_panel = QWidget(self)
        left_layout = QVBoxLayout(left_panel)
        left_panel.setMaximumWidth(420)

        # 1. Video Source Selection Box
        group_source = QGroupBox("Video Input Source", left_panel)
        source_layout = QVBoxLayout(group_source)
        
        self.radio_youtube = QRadioButton("YouTube Video URL", group_source)
        self.radio_youtube.setChecked(True)
        self.radio_youtube.toggled.connect(self._toggle_source_mode)
        
        self.txt_url = QLineEdit(group_source)
        self.txt_url.setText(DEFAULT_YOUTUBE_URL)
        
        self.radio_local = QRadioButton("Local MP4 Video File", group_source)
        
        local_file_layout = QHBoxLayout()
        self.txt_file = QLineEdit(group_source)
        self.txt_file.setPlaceholderText("Select local .mp4 video...")
        self.btn_browse_file = QPushButton("Browse...", group_source)
        self.btn_browse_file.clicked.connect(self._browse_file)
        local_file_layout.addWidget(self.txt_file)
        local_file_layout.addWidget(self.btn_browse_file)
        
        source_layout.addWidget(self.radio_youtube)
        source_layout.addWidget(self.txt_url)
        source_layout.addWidget(self.radio_local)
        source_layout.addLayout(local_file_layout)
        left_layout.addWidget(group_source)

        # 2. Model & Range Configuration Box
        group_config = QGroupBox("Model & Time Window", left_panel)
        config_layout = QVBoxLayout(group_config)
        
        config_layout.addWidget(QLabel("Gemini AI Model:"))
        self.combo_model = QComboBox(group_config)
        self.combo_model.addItems(["gemini-2.5-flash", "gemini-2.5-pro"])
        config_layout.addWidget(self.combo_model)
        
        range_layout = QHBoxLayout()
        range_layout.addWidget(QLabel("Start (s):"))
        self.spin_start = QSpinBox(group_config)
        self.spin_start.setRange(0, 36000)
        self.spin_start.setValue(0)
        
        range_layout.addWidget(QLabel("End (s):"))
        self.spin_end = QSpinBox(group_config)
        self.spin_end.setRange(5, 36000)
        self.spin_end.setValue(300)
        
        range_layout.addWidget(self.spin_start)
        range_layout.addWidget(self.spin_end)
        config_layout.addLayout(range_layout)
        left_layout.addWidget(group_config)

        # 3. Targeted Actions Checkboxes Box
        group_actions = QGroupBox("Targeted Game Actions", left_panel)
        actions_layout = QVBoxLayout(group_actions)
        
        self.chk_serves = QCheckBox("Serves (Endline tosses & strikes)", group_actions)
        self.chk_serves.setChecked(True)
        self.chk_spikes = QCheckBox("Spikes / Attacks (Rally spikes & tips)", group_actions)
        self.chk_spikes.setChecked(False)
        self.chk_blocks = QCheckBox("Blocks (Net block deflections)", group_actions)
        self.chk_digs = QCheckBox("Digs / Receptions (Defensive passes)", group_actions)
        
        actions_layout.addWidget(self.chk_serves)
        actions_layout.addWidget(self.chk_spikes)
        actions_layout.addWidget(self.chk_blocks)
        actions_layout.addWidget(self.chk_digs)
        left_layout.addWidget(group_actions)

        # 4. Clip Export Settings Box
        group_export = QGroupBox("Clip Export Settings", left_panel)
        export_layout = QVBoxLayout(group_export)
        
        padding_layout = QHBoxLayout()
        padding_layout.addWidget(QLabel("Clip Padding (s):"))
        self.spin_padding = QSpinBox(group_export)
        self.spin_padding.setRange(0, 10)
        self.spin_padding.setValue(3)
        padding_layout.addWidget(self.spin_padding)
        export_layout.addLayout(padding_layout)
        
        folder_layout = QHBoxLayout()
        self.txt_out_dir = QLineEdit(group_export)
        self.txt_out_dir.setText(str(OUTPUT_DIR))
        self.btn_browse_out = QPushButton("Output Dir", group_export)
        self.btn_browse_out.clicked.connect(self._browse_output_dir)
        folder_layout.addWidget(self.txt_out_dir)
        folder_layout.addWidget(self.btn_browse_out)
        export_layout.addLayout(folder_layout)
        left_layout.addWidget(group_export)

        # 5. Start Execution Button & Progress Bar
        self.btn_start = QPushButton("START AUTOMATIC ANALYSIS", left_panel)
        self.btn_start.setObjectName("btn_start")
        self.btn_start.clicked.connect(self.start_analysis)
        left_layout.addWidget(self.btn_start)
        
        self.progress_bar = QProgressBar(left_panel)
        self.progress_bar.setValue(0)
        left_layout.addWidget(self.progress_bar)
        
        left_layout.addStretch()
        main_layout.addWidget(left_panel)

        # -------------------------------------------------------------
        # RIGHT PANEL: Results, Media Previewer, Addons & Console Tabs
        # -------------------------------------------------------------
        right_panel = QTabWidget(self)
        
        # TAB 1: Results & Media Preview
        tab_results = QWidget()
        tab_results_layout = QVBoxLayout(tab_results)
        
        splitter = QSplitter(Qt.Vertical, tab_results)
        
        self.results_table = ResultsTableWidget(splitter)
        self.results_table.sig_event_selected.connect(self._on_clip_selected)
        splitter.addWidget(self.results_table)
        
        self.preview_widget = MediaPreviewWidget(splitter)
        splitter.addWidget(self.preview_widget)
        
        splitter.setSizes([400, 350])
        tab_results_layout.addWidget(splitter)
        right_panel.addTab(tab_results, "Analysis Results & Preview")

        # TAB 2: Scouting Addons
        self.addons_widget = AddonsWidget()
        right_panel.addTab(self.addons_widget, "Scouting Addons")

        # TAB 3: Execution Log Console
        self.log_console = QTextEdit()
        self.log_console.setObjectName("log_console")
        self.log_console.setReadOnly(True)
        right_panel.addTab(self.log_console, "Console Logs")

        main_layout.addWidget(right_panel, stretch=1)
        self._toggle_source_mode()

    def _toggle_source_mode(self):
        is_yt = self.radio_youtube.isChecked()
        self.txt_url.setEnabled(is_yt)
        self.txt_file.setEnabled(not is_yt)
        self.btn_browse_file.setEnabled(not is_yt)

    def _browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Volleyball Video", "", "Video Files (*.mp4 *.mov *.avi)")
        if file_path:
            self.txt_file.setText(file_path)

    def _browse_output_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Output Directory", self.txt_out_dir.text())
        if dir_path:
            self.txt_out_dir.setText(dir_path)

    def log(self, message: str):
        self.log_console.append(message)

    @Slot(str)
    def _on_clip_selected(self, media_path: str):
        self.log(f"Loading media preview: {media_path}")
        self.preview_widget.load_media(media_path)

    def start_analysis(self):
        is_local = self.radio_local.isChecked()
        url_or_path = self.txt_file.text() if is_local else self.txt_url.text()
        
        if not url_or_path:
            self.log("Error: Please provide a valid video URL or file path.")
            return

        target_actions = []
        if self.chk_serves.isChecked():
            target_actions.append("Serve")
        if self.chk_spikes.isChecked():
            target_actions.append("Spike/Attack")
        if self.chk_blocks.isChecked():
            target_actions.append("Block")
        if self.chk_digs.isChecked():
            target_actions.append("Dig/Reception")

        if not target_actions:
            self.log("Error: Please select at least one target action checkbox.")
            return

        self.btn_start.setEnabled(False)
        self.progress_bar.setValue(0)
        self.log_console.clear()
        
        self.worker = AnalysisWorker(
            url_or_path=url_or_path,
            is_local_file=is_local,
            start_sec=self.spin_start.value(),
            end_sec=self.spin_end.value(),
            model_name=self.combo_model.currentText(),
            target_actions=target_actions,
            output_dir=Path(self.txt_out_dir.text()),
            clip_padding_sec=float(self.spin_padding.value())
        )
        
        self.worker.sig_log.connect(self.log)
        self.worker.sig_progress.connect(self.progress_bar.setValue)
        self.worker.sig_finished.connect(self.on_analysis_finished)
        self.worker.sig_error.connect(self.on_analysis_error)
        self.worker.start()

    @Slot(object, str)
    def on_analysis_finished(self, analysis_data, output_dir_str):
        self.btn_start.setEnabled(True)
        self.results_table.populate_events(analysis_data.events, Path(output_dir_str))
        self.log(f"Successfully populated {len(analysis_data.events)} events in the results table.")

    @Slot(str)
    def on_analysis_error(self, err_msg):
        self.btn_start.setEnabled(True)
        self.log(f"Analysis failed: {err_msg}")
