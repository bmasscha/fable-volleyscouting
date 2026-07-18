"""Fable Scouter — real-time volleyball match scouting.

Run with:  .venv\\Scripts\\python.exe main.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

from core import user_systems
from ui.main_window import MainWindow
from ui.theme import build_dark_palette


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setPalette(build_dark_palette())
    app.setFont(QFont("Segoe UI", 11))
    # Merge any user-authored playing systems before the UI reads the
    # registry; a bad file is reported, never fatal (startup stays quiet).
    for problem in user_systems.refresh_registry():
        print(f"systems: {problem}", file=sys.stderr)
    win = MainWindow()
    win.showMaximized()
    # offer to resume the last match (crash recovery) or start a new one
    QTimer.singleShot(150, win.startup_prompt)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
