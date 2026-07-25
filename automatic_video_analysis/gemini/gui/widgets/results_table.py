from pathlib import Path
from typing import List
from ..qt_compat import Qt, Signal, QTableWidget, QTableWidgetItem, QHeaderView

from ...schemas import GameActionEvent

class ResultsTableWidget(QTableWidget):
    sig_event_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(7)
        self.setHorizontalHeaderLabels([
            "#", "Action", "Time", "Team", "Details", "Player Info", "Confidence"
        ])
        
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setSelectionMode(QTableWidget.SingleSelection)
        self.cellClicked.connect(self._on_row_clicked)

        self.row_media_map = {}

    def populate_events(self, events: List[GameActionEvent], output_dir: Path):
        self.setRowCount(0)
        self.row_media_map.clear()
        
        clips_dir = output_dir / "serve_clips"
        
        for idx, event in enumerate(events, 1):
            row = self.rowCount()
            self.insertRow(row)
            
            self.setItem(row, 0, QTableWidgetItem(str(idx)))
            self.setItem(row, 1, QTableWidgetItem(event.action_type))
            self.setItem(row, 2, QTableWidgetItem(event.timestamp_formatted))
            self.setItem(row, 3, QTableWidgetItem(event.team))
            self.setItem(row, 4, QTableWidgetItem(event.action_details or "N/A"))
            self.setItem(row, 5, QTableWidgetItem(event.player_info or "N/A"))
            self.setItem(row, 6, QTableWidgetItem(f"{event.confidence:.2f}"))
            
            # Robust glob pattern search by index (supports action_{idx:02d}_* and legacy serve_{idx:02d}_*)
            matching_clips = list(clips_dir.glob(f"action_{idx:02d}_*.mp4")) + list(clips_dir.glob(f"serve_{idx:02d}_clip_*.mp4"))
            matching_imgs = list(clips_dir.glob(f"action_{idx:02d}_*.jpg")) + list(clips_dir.glob(f"serve_{idx:02d}_at_*.jpg"))
            
            if matching_clips:
                self.row_media_map[row] = str(matching_clips[0])
            elif matching_imgs:
                self.row_media_map[row] = str(matching_imgs[0])
            else:
                self.row_media_map[row] = ""

                
        # Auto-select first row if events exist
        if events and self.rowCount() > 0:
            self.selectRow(0)
            self._on_row_clicked(0, 0)

    def _on_row_clicked(self, row: int, col: int):
        media_path = self.row_media_map.get(row, "")
        if media_path:
            self.sig_event_selected.emit(media_path)
