from pathlib import Path
import cv2
from ..qt_compat import (
    Qt, QPixmap, QImage, QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QFrame, Slot, QTimer, QSize
)

class MediaPreviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        self.container = QFrame(self)
        self.container.setStyleSheet("background-color: #020617; border: 1px solid #334155; border-radius: 8px;")
        container_layout = QVBoxLayout(self.container)
        
        # Display Screen (for both Images and Video Frames)
        self.display_label = QLabel(self.container)
        self.display_label.setAlignment(Qt.AlignmentFlag.AlignCenter if hasattr(Qt, 'AlignmentFlag') else Qt.AlignCenter)
        self.display_label.setStyleSheet("color: #94A3B8; font-size: 14px; background-color: #020617;")
        self.display_label.setMinimumSize(480, 270)
        self.display_label.setText("Select an action event from the table to preview the video clip or image snapshot.")
        container_layout.addWidget(self.display_label)
        
        # Playback Controls
        self.controls_layout = QHBoxLayout()
        self.btn_play = QPushButton("Play Clip", self.container)
        self.btn_play.clicked.connect(self.play_video)
        self.btn_pause = QPushButton("Pause", self.container)
        self.btn_pause.clicked.connect(self.pause_video)
        self.btn_stop = QPushButton("Stop / Reset", self.container)
        self.btn_stop.clicked.connect(self.stop_video)
        
        self.controls_layout.addWidget(self.btn_play)
        self.controls_layout.addWidget(self.btn_pause)
        self.controls_layout.addWidget(self.btn_stop)
        
        container_layout.addLayout(self.controls_layout)
        self.layout.addWidget(self.container)

        # OpenCV Video Player State
        self.cap = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._next_frame)
        self.current_video_path = None
        self.is_playing = False

    def load_media(self, file_path: str):
        self.stop_video()
        path = Path(file_path)
        
        if not path.exists():
            self.display_label.setText(f"File not found: {path.name}")
            return
            
        ext = path.suffix.lower()
        if ext in [".jpg", ".jpeg", ".png"]:
            self.current_video_path = None
            pixmap = QPixmap(str(path))
            self._display_pixmap(pixmap)
        elif ext in [".mp4", ".mov", ".avi"]:
            self.current_video_path = str(path)
            self.cap = cv2.VideoCapture(self.current_video_path)
            ret, frame = self.cap.read()
            if ret and frame is not None:
                self._render_opencv_frame(frame)
            self.play_video()

    def play_video(self):
        if not self.current_video_path:
            return
            
        if self.cap is None or not self.cap.isOpened():
            self.cap = cv2.VideoCapture(self.current_video_path)
            
        fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        interval_ms = max(10, int(1000.0 / fps))
        
        self.is_playing = True
        self.timer.start(interval_ms)

    def pause_video(self):
        self.is_playing = False
        self.timer.stop()

    def stop_video(self):
        self.is_playing = False
        self.timer.stop()
        if self.cap:
            self.cap.release()
            self.cap = None

    @Slot()
    def _next_frame(self):
        if not self.cap or not self.cap.isOpened():
            self.stop_video()
            return
            
        ret, frame = self.cap.read()
        if ret and frame is not None:
            self._render_opencv_frame(frame)
        else:
            # Loop playback seamlessly
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = self.cap.read()
            if ret and frame is not None:
                self._render_opencv_frame(frame)
            else:
                self.stop_video()

    def _render_opencv_frame(self, frame):
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_frame.shape
        bytes_per_line = ch * w
        fmt = QImage.Format.Format_RGB888 if hasattr(QImage.Format, 'Format_RGB888') else QImage.Format_RGB888
        qt_img = QImage(rgb_frame.data, w, h, bytes_per_line, fmt)
        pixmap = QPixmap.fromImage(qt_img)
        self._display_pixmap(pixmap)

    def _display_pixmap(self, pixmap: QPixmap):
        target_size = self.display_label.size()
        if target_size.width() < 100 or target_size.height() < 100:
            target_size = QSize(640, 360)
            
        keep_aspect = Qt.AspectRatioMode.KeepAspectRatio if hasattr(Qt, 'AspectRatioMode') else Qt.KeepAspectRatio
        smooth = Qt.TransformationMode.SmoothTransformation if hasattr(Qt, 'TransformationMode') else Qt.SmoothTransformation
        
        scaled = pixmap.scaled(target_size, keep_aspect, smooth)
        self.display_label.setPixmap(scaled)

    def closeEvent(self, event):
        self.stop_video()
        super().closeEvent(event)
