"""Đường dẫn dữ liệu ứng dụng (local, không cần Internet)."""

from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "PDFPrintChecker"


def app_data_dir() -> Path:
    """Thư mục lưu cấu hình + SQLite trên máy người dùng."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return app_data_dir() / "print_status.db"


def config_path() -> Path:
    return app_data_dir() / "config.json"


def resource_path(*parts: str) -> Path:
    """Hỗ trợ cả chạy script và chạy từ PyInstaller EXE."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS, *parts)
    return Path(__file__).resolve().parents[2].joinpath(*parts)
