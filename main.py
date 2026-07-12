"""Fable Scouter — real-time volleyball match scouting.

Run with:  .venv\\Scripts\\python.exe main.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

from ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 11))
    win = MainWindow()
    win.showMaximized()
    # offer match setup right away on a fresh start
    QTimer.singleShot(150, lambda: win.new_match() if win.engine is None else None)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
