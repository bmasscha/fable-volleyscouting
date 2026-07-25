# Premium Dark Mode Theme QSS with High-Contrast Tabs

DARK_THEME_QSS = """
QMainWindow {
    background-color: #0F172A;
    color: #F8FAFC;
}

QWidget {
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
    color: #F8FAFC;
}

QGroupBox {
    border: 1px solid #334155;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 12px;
    background-color: #1E293B;
    font-weight: bold;
    color: #38BDF8;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    background-color: #1E293B;
}

QLineEdit, QComboBox, QSpinBox {
    background-color: #0F172A;
    border: 1px solid #475569;
    border-radius: 6px;
    padding: 6px 10px;
    color: #F8FAFC;
}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
    border: 1px solid #38BDF8;
}

QPushButton {
    background-color: #0284C7;
    color: #FFFFFF;
    font-weight: bold;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
}

QPushButton:hover {
    background-color: #0369A1;
}

QPushButton:pressed {
    background-color: #075985;
}

QPushButton:disabled {
    background-color: #334155;
    color: #94A3B8;
}

QPushButton#btn_start {
    background-color: #059669;
    font-size: 14px;
    padding: 10px 20px;
}

QPushButton#btn_start:hover {
    background-color: #047857;
}

QCheckBox {
    spacing: 8px;
    color: #E2E8F0;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 1px solid #475569;
    border-radius: 4px;
    background-color: #0F172A;
}

QCheckBox::indicator:checked {
    background-color: #38BDF8;
    border-color: #38BDF8;
}

/* HIGH CONTRAST TAB WIDGET & TAB BAR STYLING */
QTabWidget::pane {
    border: 1px solid #334155;
    border-radius: 6px;
    background-color: #1E293B;
    top: -1px;
}

QTabBar::tab {
    background-color: #0F172A;
    color: #94A3B8;
    border: 1px solid #334155;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 8px 18px;
    margin-right: 4px;
    font-weight: bold;
}

QTabBar::tab:hover {
    background-color: #1E293B;
    color: #38BDF8;
}

QTabBar::tab:selected {
    background-color: #1E293B;
    color: #38BDF8;
    border-top: 3px solid #38BDF8;
    border-bottom: 1px solid #1E293B;
}

QTableWidget {
    background-color: #1E293B;
    gridline-color: #334155;
    border: 1px solid #334155;
    border-radius: 6px;
    selection-background-color: #0284C7;
    selection-color: #FFFFFF;
}

QHeaderView::section {
    background-color: #0F172A;
    color: #38BDF8;
    padding: 6px;
    font-weight: bold;
    border: 1px solid #334155;
}

QProgressBar {
    border: 1px solid #334155;
    border-radius: 6px;
    text-align: center;
    background-color: #0F172A;
    color: #F8FAFC;
}

QProgressBar::chunk {
    background-color: #0284C7;
    border-radius: 5px;
}

QTextEdit#log_console {
    background-color: #020617;
    border: 1px solid #334155;
    border-radius: 6px;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 12px;
    color: #38BDF8;
}
"""
