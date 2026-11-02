"""Theo dõi thay đổi thư mục PDF bằng Watchdog (chạy nền)."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer


class _PdfEventHandler(FileSystemEventHandler):
    def __init__(self, notify) -> None:
        super().__init__()
        self._notify = notify

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory and self._is_pdf(event.src_path):
            self._notify()

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory and self._is_pdf(event.src_path):
            self._notify()

    def on_deleted(self, event: FileSystemEvent) -> None:
        if not event.is_directory and self._is_pdf(event.src_path):
            self._notify()

    def on_moved(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        if self._is_pdf(event.src_path):
            self._notify()
        dest = getattr(event, "dest_path", None)
        if dest and self._is_pdf(dest):
            self._notify()

    @staticmethod
    def _is_pdf(path: str) -> bool:
        return str(path).lower().endswith(".pdf")


class FolderWatcherWorker(QThread):
    """Quan sát thư mục; debounce rồi báo folder_changed để quét lại."""

    folder_changed = Signal()
    status_message = Signal(str)

    def __init__(self, folder: str = "", debounce_ms: int = 600, parent=None) -> None:
        super().__init__(parent)
        self._folder = folder
        self._debounce_ms = debounce_ms
        self._running = False
        self._observer: Observer | None = None
        self._lock = threading.Lock()
        self._dirty = False
        self._last_event = 0.0

    def set_folder(self, folder: str) -> None:
        self._folder = folder

    def stop(self) -> None:
        self._running = False

    def _mark_dirty(self) -> None:
        with self._lock:
            self._dirty = True
            self._last_event = time.monotonic()

    def run(self) -> None:
        self._running = True
        while self._running:
            folder = self._folder
            if not folder or not Path(folder).is_dir():
                self.msleep(500)
                continue

            self._start_observer(folder)
            self.status_message.emit(f"Đang theo dõi thư mục: {folder}")

            while self._running and self._folder == folder:
                emit_now = False
                with self._lock:
                    if self._dirty and (time.monotonic() - self._last_event) * 1000 >= self._debounce_ms:
                        self._dirty = False
                        emit_now = True
                if emit_now:
                    self.folder_changed.emit()
                self.msleep(100)

            self._stop_observer()

    def _start_observer(self, folder: str) -> None:
        self._stop_observer()
        handler = _PdfEventHandler(self._mark_dirty)
        observer = Observer()
        observer.schedule(handler, folder, recursive=False)
        observer.start()
        self._observer = observer

    def _stop_observer(self) -> None:
        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=2)
            except Exception:
                pass
            self._observer = None
