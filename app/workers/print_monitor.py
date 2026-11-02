"""Theo dõi Windows Print Spooler — bắt lệnh in ngay khi job xuất hiện."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

from PySide6.QtCore import QThread, Signal

try:
    import win32print
except ImportError:  # pragma: no cover
    win32print = None  # type: ignore


# winspool.h
JOB_STATUS_DELETING = 0x00000004
JOB_STATUS_DELETED = 0x00000100

_CANCEL_FLAGS = JOB_STATUS_DELETING | JOB_STATUS_DELETED

JobKey = Tuple[str, int]


@dataclass
class TrackedJob:
    printer_name: str
    job_id: int
    document: str
    status: int
    emitted: bool = False


@dataclass(frozen=True)
class PrintJobEvent:
    """Sự kiện: đã phát hiện lệnh in (job) trên Spooler."""

    printer_name: str
    job_id: int
    document: str
    status: int


# Alias giữ tương thích chỗ import cũ
CompletedPrintEvent = PrintJobEvent


class PrintMonitorWorker(QThread):
    """
    Poll EnumJobs trên mọi máy in.

    Emit print_detected ngay khi thấy job mới có tên tài liệu
    (= đã gọi lệnh Print), để đối chiếu với PDF trong thư mục.
    """

    print_detected = Signal(object)  # PrintJobEvent
    job_completed = Signal(object)  # alias cùng sự kiện (tương thích UI cũ)
    status_message = Signal(str)
    monitor_error = Signal(str)

    def __init__(self, poll_interval: float = 0.25, parent=None) -> None:
        super().__init__(parent)
        self._poll_interval = poll_interval
        self._running = False
        self._jobs: Dict[JobKey, TrackedJob] = {}
        self._seen_keys: set[JobKey] = set()

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        if win32print is None:
            self.monitor_error.emit("Thiếu thư viện pywin32 — không theo dõi được máy in.")
            return

        self._running = True
        # Snapshot job đang có sẵn — không coi là lệnh in mới
        try:
            self._snapshot_existing_jobs()
        except Exception as exc:  # noqa: BLE001
            self.monitor_error.emit(f"Không đọc được Spooler lúc khởi động: {exc}")

        self.status_message.emit("Đang theo dõi lệnh in (Print Spooler)…")

        while self._running:
            try:
                self._poll_once()
            except Exception as exc:  # noqa: BLE001
                self.monitor_error.emit(f"Lỗi theo dõi máy in: {exc}")
            self.msleep(int(self._poll_interval * 1000))

        self.status_message.emit("Đã dừng theo dõi máy in.")

    def _enumerate_printer_names(self) -> list[str]:
        flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        names: list[str] = []
        try:
            for item in win32print.EnumPrinters(flags, None, 2):
                name = item.get("pPrinterName") or item.get("PrinterName")
                if name:
                    names.append(name)
        except Exception:
            for entry in win32print.EnumPrinters(flags):
                if len(entry) >= 3 and entry[2]:
                    names.append(entry[2])
        return names

    def _iter_jobs(self):
        for printer_name in self._enumerate_printer_names():
            try:
                handle = win32print.OpenPrinter(printer_name)
            except Exception:
                continue
            try:
                try:
                    jobs = win32print.EnumJobs(handle, 0, 999, 1) or []
                except Exception:
                    jobs = []
                for job in jobs:
                    job_id = int(job.get("JobId", 0))
                    if job_id <= 0:
                        continue
                    document = str(job.get("pDocument") or job.get("Document") or "").strip()
                    status = int(job.get("Status", 0))
                    yield printer_name, job_id, document, status
            finally:
                try:
                    win32print.ClosePrinter(handle)
                except Exception:
                    pass

    def _snapshot_existing_jobs(self) -> None:
        for printer_name, job_id, document, status in self._iter_jobs():
            key: JobKey = (printer_name, job_id)
            self._seen_keys.add(key)
            self._jobs[key] = TrackedJob(
                printer_name=printer_name,
                job_id=job_id,
                document=document,
                status=status,
                emitted=True,  # bỏ qua job có sẵn trước khi mở app
            )

    def _poll_once(self) -> None:
        seen_now: set[JobKey] = set()

        for printer_name, job_id, document, status in self._iter_jobs():
            key: JobKey = (printer_name, job_id)
            seen_now.add(key)

            tracked = self._jobs.get(key)
            if tracked is None:
                tracked = TrackedJob(
                    printer_name=printer_name,
                    job_id=job_id,
                    document=document,
                    status=status,
                )
                self._jobs[key] = tracked
            else:
                if document:
                    tracked.document = document
                tracked.status = status

            # Job đang bị hủy → không thống kê là đã gọi lệnh in thành công
            if status & _CANCEL_FLAGS:
                tracked.emitted = True
                self._seen_keys.add(key)
                continue

            # Job mới (chưa từng thấy) có tên tài liệu → đã gọi lệnh Print
            if key not in self._seen_keys and not tracked.emitted:
                if tracked.document:
                    self._emit_detected(tracked)
                else:
                    # Chưa có tên — đợi poll sau (một số driver gắn tên muộn)
                    continue

            self._seen_keys.add(key)

            # Job cũ nhưng trước đó chưa có document, nay mới có
            if not tracked.emitted and tracked.document:
                self._emit_detected(tracked)

        # Dọn job đã biến mất
        for key in [k for k in self._jobs if k not in seen_now]:
            self._jobs.pop(key, None)

        if len(self._seen_keys) > 8000:
            # Giữ lại key đang còn trong spooler
            self._seen_keys = set(self._jobs.keys())

    def _emit_detected(self, tracked: TrackedJob) -> None:
        if tracked.emitted or not tracked.document.strip():
            return
        tracked.emitted = True
        event = PrintJobEvent(
            printer_name=tracked.printer_name,
            job_id=tracked.job_id,
            document=tracked.document,
            status=tracked.status,
        )
        self.print_detected.emit(event)
        self.job_completed.emit(event)
