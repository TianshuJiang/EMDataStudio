"""
EMDataStudio — HyperSpy Data Visualizer
Entry point. Run: python main.py
"""
import sys
import os

# ── Fix hdf5.dll path on Windows (Anaconda) ──────────────────────────────────
try:
    os.add_dll_directory(os.path.join(sys.prefix, "Library", "bin"))
except (AttributeError, OSError):
    pass  # Not Windows or path not needed

# Make sure src/ is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QFont
from src.app import EMDataStudioApp
from src.config import AppConfig


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("EMDataStudio")
    app.setOrganizationName("TU Darmstadt — Advanced Electron Microscopy")

    # Load configuration and set font size
    config = AppConfig()
    font_size = config.get("font_size", 11)
    font = QFont("Segoe UI", font_size)
    app.setFont(font)

    window = EMDataStudioApp()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
