import sys
from automatic_video_analysis.gemini.gui.qt_compat import QApplication
from automatic_video_analysis.gemini.gui.main_window import MainWindow

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec() if hasattr(app, 'exec') else app.exec_())

if __name__ == "__main__":
    main()
