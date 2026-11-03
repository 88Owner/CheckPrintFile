"""Theo dõi Event Viewer PrintService/Operational — Event ID 307."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from app.core.print_event_log import (
    PrintServiceEvent307,
    is_channel_enabled,
    watch_new_events,
)


class EventLogMonitorWorker(QThread):
    """
    Poll Event ID 307. Emit print_event khi có sự kiện mới.
    Không treo UI.
    """

    print_event = Signal(object)  # PrintServiceEvent307
    status_message = Signal(str)
    monitor_error = Signal(str)
    channel_disabled = Signal()

    def __init__(
        self,
        *,
        poll_interval: float = 2.0,
        start_after_record_id: int = 0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._poll_interval = poll_interval
        self._last_record_id = start_after_record_id
        self._running = False
        self._warned_disabled = False

    def set_last_record_id(self, record_id: int) -> None:
        if record_id > self._last_record_id:
            self._last_record_id = record_id

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        self._running = True
        self.status_message.emit("Đang theo dõi Event Viewer (PrintService / Event 307)…")

        while self._running:
            try:
                if not is_channel_enabled():
                    if not self._warned_disabled:
                        self._warned_disabled = True
                        self.channel_disabled.emit()
                        self.monitor_error.emit(
                            "Log PrintService/Operational đang TẮT. "
                            "Bấm «Bật Event Log in» (cần Admin)."
                        )
                    self.msleep(int(self._poll_interval * 1000))
                    continue

                self._warned_disabled = False
                events = watch_new_events(self._last_record_id, limit=80)
                for ev in events:
                    if not self._running:
                        break
                    if ev.record_id <= self._last_record_id:
                        continue
                    self._last_record_id = ev.record_id
                    self.print_event.emit(ev)
            except Exception as exc:  # noqa: BLE001
                self.monitor_error.emit(f"Lỗi đọc Event Log: {exc}")

            self.msleep(int(self._poll_interval * 1000))

        self.status_message.emit("Đã dừng theo dõi Event Log.")
