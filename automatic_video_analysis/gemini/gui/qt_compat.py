try:
    from PyQt6.QtCore import Qt, QUrl, QThread, QTimer, QSize, pyqtSignal as Signal, pyqtSlot as Slot
    from PyQt6.QtGui import QPixmap, QImage
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLineEdit,
        QPushButton, QComboBox, QCheckBox, QSpinBox, QProgressBar, QTextEdit,
        QFileDialog, QTabWidget, QSplitter, QLabel, QRadioButton, QTableWidget,
        QTableWidgetItem, QHeaderView, QFrame
    )
    try:
        from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
        from PyQt6.QtMultimediaWidgets import QVideoWidget
        HAS_MULTIMEDIA = True
        QMediaContent = None
    except ImportError:
        HAS_MULTIMEDIA = False
        QMediaPlayer = None
        QVideoWidget = None
        QAudioOutput = None
        QMediaContent = None
except ImportError:
    from PyQt5.QtCore import Qt, QUrl, QThread, QTimer, QSize, pyqtSignal as Signal, pyqtSlot as Slot
    from PyQt5.QtGui import QPixmap, QImage
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLineEdit,
        QPushButton, QComboBox, QCheckBox, QSpinBox, QProgressBar, QTextEdit,
        QFileDialog, QTabWidget, QSplitter, QLabel, QRadioButton, QTableWidget,
        QTableWidgetItem, QHeaderView, QFrame
    )
    try:
        from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
        from PyQt5.QtMultimediaWidgets import QVideoWidget
        HAS_MULTIMEDIA = True
        QAudioOutput = None
    except ImportError:
        HAS_MULTIMEDIA = False
        QMediaPlayer = None
        QVideoWidget = None
        QMediaContent = None
        QAudioOutput = None
