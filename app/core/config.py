"""Lưu / đọc cấu hình ứng dụng (thư mục theo dõi, ...)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.core.paths import config_path


@dataclass
class AppConfig:
    watch_folder: str = ""
    window_width: int = 980
    window_height: int = 640

    @classmethod
    def load(cls) -> "AppConfig":
        path = config_path()
        if not path.exists():
            return cls()
        try:
            data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                watch_folder=str(data.get("watch_folder", "") or ""),
                window_width=int(data.get("window_width", 980)),
                window_height=int(data.get("window_height", 640)),
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return cls()

    def save(self) -> None:
        path = config_path()
        path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def set_watch_folder(self, folder: str | Path) -> None:
        self.watch_folder = str(folder)
        self.save()
