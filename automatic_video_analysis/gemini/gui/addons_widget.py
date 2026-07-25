from .qt_compat import (
    QWidget, QVBoxLayout, QGroupBox, QCheckBox, QLabel, QPushButton, QHBoxLayout
)

class AddonsWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        group = QGroupBox("Scouting Addons & Visual Analytics", self)
        g_layout = QVBoxLayout(group)
        
        self.chk_trajectory = QCheckBox("Ball Trajectory Overlay (Plots ball arc for serves & spikes)", group)
        self.chk_heatmap = QCheckBox("Court Placement Heatmap (Generates landing zone density map)", group)
        self.chk_player_pose = QCheckBox("Player Spike Mechanics & Jump Height Estimation", group)
        
        g_layout.addWidget(self.chk_trajectory)
        g_layout.addWidget(self.chk_heatmap)
        g_layout.addWidget(self.chk_player_pose)
        
        info_label = QLabel(
            "Addons integrate computer vision ball tracking to draw trajectory arcs and hit maps directly onto exported MP4 clips.",
            group
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #94A3B8; font-size: 11px; margin-top: 4px;")
        g_layout.addWidget(info_label)
        
        layout.addWidget(group)
