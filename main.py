"""Điểm vào ứng dụng PDF Print Checker."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.core.paths import resource_path
from app.ui.main_window import MainWindow


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("PDF Print Checker")
    app.setOrganizationName("PDFPrintChecker")
    app.setStyle("Fusion")

    icon_file = resource_path("assets", "app.ico")
    if not icon_file.exists():
        icon_file = resource_path("assets", "app.png")
    if icon_file.exists():
        app.setWindowIcon(QIcon(str(icon_file)))

    window = MainWindow()
    if icon_file.exists():
        window.setWindowIcon(QIcon(str(icon_file)))
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
