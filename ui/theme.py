"""Application-wide dark QPalette.

The Fusion style (set in main.py) paints every widget from QPalette, so a
complete palette here is what actually fixes contrast for QComboBox,
QSpinBox, QListWidget/QTableWidget, QRadioButton, QCheckBox, QGroupBox
titles, QMessageBox buttons, etc. — widgets that MainWindow's own
stylesheet (background #263238 / #1c262b) does not give an explicit text
color to, so they fell back to the default (light-theme, black-on-white)
palette. Colors here are chosen to match that existing stylesheet.
"""
from __future__ import annotations

from PyQt6.QtGui import QColor, QPalette

WINDOW = "#263238"      # matches MainWindow's stylesheet background
BASE = "#1c262b"        # matches MainWindow's toolbar background
ALT_BASE = "#32424a"
TEXT = "#e8e8e8"
DISABLED_TEXT = "#78878e"
BUTTON = "#37474f"
HIGHLIGHT = "#1565c0"   # same blue as the setter token color
LINK = "#4fc3f7"


def build_dark_palette() -> QPalette:
    """A coherent dark QPalette consistent with the app's existing colors."""
    pal = QPalette()

    window, base, alt_base = QColor(WINDOW), QColor(BASE), QColor(ALT_BASE)
    text, button = QColor(TEXT), QColor(BUTTON)
    highlight, highlighted_text = QColor(HIGHLIGHT), QColor("#ffffff")

    pal.setColor(QPalette.ColorRole.Window, window)
    pal.setColor(QPalette.ColorRole.WindowText, text)
    pal.setColor(QPalette.ColorRole.Base, base)
    pal.setColor(QPalette.ColorRole.AlternateBase, alt_base)
    pal.setColor(QPalette.ColorRole.Text, text)
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor("#8a9599"))
    pal.setColor(QPalette.ColorRole.Button, button)
    pal.setColor(QPalette.ColorRole.ButtonText, text)
    pal.setColor(QPalette.ColorRole.BrightText, QColor("#ff5252"))
    pal.setColor(QPalette.ColorRole.ToolTipBase, base)
    pal.setColor(QPalette.ColorRole.ToolTipText, text)
    pal.setColor(QPalette.ColorRole.Highlight, highlight)
    pal.setColor(QPalette.ColorRole.HighlightedText, highlighted_text)
    pal.setColor(QPalette.ColorRole.Link, QColor(LINK))
    pal.setColor(QPalette.ColorRole.LinkVisited, QColor("#ba68c8"))

    disabled = QPalette.ColorGroup.Disabled
    dtext = QColor(DISABLED_TEXT)
    pal.setColor(disabled, QPalette.ColorRole.WindowText, dtext)
    pal.setColor(disabled, QPalette.ColorRole.Text, dtext)
    pal.setColor(disabled, QPalette.ColorRole.ButtonText, dtext)
    pal.setColor(disabled, QPalette.ColorRole.Base, window)
    pal.setColor(disabled, QPalette.ColorRole.Button, window)
    pal.setColor(disabled, QPalette.ColorRole.Highlight, QColor("#455a64"))
    pal.setColor(disabled, QPalette.ColorRole.HighlightedText, dtext)

    return pal
