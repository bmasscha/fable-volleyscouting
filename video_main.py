"""Fable Scouter — Video review.

Load an exported match .json plus a match video (local file or YouTube), filter
the scouted actions, and play or export the matching 7 s fragments.

Run with:  .venv\\Scripts\\python.exe video_main.py [match.json]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PyQt6.QtCore import Qt, QCoreApplication
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

from ui.theme import build_dark_palette
from ui.video_review import VideoReviewWindow


def main() -> int:
    # QtWebEngine (the YouTube player) requires shared GL contexts, and the flag
    # must be set before the QApplication is constructed.
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setPalette(build_dark_palette())
    app.setFont(QFont("Segoe UI", 11))
    win = VideoReviewWindow()
    win.showMaximized()
    # optional: open a match handed on the command line
    if len(sys.argv) > 1 and Path(sys.argv[1]).exists():
        win.open_match_path(sys.argv[1])
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
