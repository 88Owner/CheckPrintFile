"""Cửa sổ chính — PDF Print Checker."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.config import AppConfig
from app.core.database import PdfRecord, PrintStatus
from app.core.print_event_log import (
    PrintServiceEvent307,
    enable_channel_elevated,
    is_channel_enabled,
)
from app.core.tracker import PdfTracker
from app.ui.styles import APP_STYLESHEET
from app.workers.event_log_monitor import EventLogMonitorWorker
from app.workers.folder_watcher import FolderWatcherWorker
from app.workers.print_monitor import CompletedPrintEvent, PrintMonitorWorker


def _format_local_time(iso_utc: str | None) -> str:
    if not iso_utc:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_utc)
        if dt.tzinfo is not None:
            dt = dt.astimezone()
        return dt.strftime("%d/%m/%Y %H:%M:%S")
    except ValueError:
        return iso_utc


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PDF Print Checker")
        self.config = AppConfig.load()
        self.resize(max(self.config.window_width, 1100), max(self.config.window_height, 680))

        self.tracker = PdfTracker()
        self._print_worker: PrintMonitorWorker | None = None
        self._event_worker: EventLogMonitorWorker | None = None
        self._folder_worker: FolderWatcherWorker | None = None

        self._build_ui()
        self.setStyleSheet(APP_STYLESHEET)
        QTimer.singleShot(0, self._bootstrap)

    # ── UI ────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(12)

        header = QVBoxLayout()
        title = QLabel("PDF Print Checker")
        title.setObjectName("titleLabel")
        subtitle = QLabel(
            "Đối chiếu PDF trong thư mục với lịch sử in Event Viewer "
            "(PrintService/Operational — Event ID 307)"
        )
        subtitle.setObjectName("subtitleLabel")
        header.addWidget(title)
        header.addWidget(subtitle)
        root.addLayout(header)

        stats = QFrame()
        stats.setObjectName("statsBar")
        stats_layout = QHBoxLayout(stats)
        stats_layout.setContentsMargins(14, 12, 14, 12)
        stats_layout.setSpacing(12)

        self.lbl_total_val = self._make_stat_card(
            stats_layout, "Tổng số PDF", "0",
            card_id="statCardTotal", value_id="statTotalValue", cap_id="statTotalCap",
        )
        self.lbl_printed_val = self._make_stat_card(
            stats_layout, "Đã in (Event 307)", "0",
            card_id="statCardPrinted", value_id="statPrinted", cap_id="statPrintedCap",
        )
        self.lbl_pending_val = self._make_stat_card(
            stats_layout, "Chưa in", "0",
            card_id="statCardPending", value_id="statPending", cap_id="statPendingCap",
        )
        self.lbl_folder = QLabel("Thư mục: (chưa chọn)")
        self.lbl_folder.setObjectName("folderLabel")
        self.lbl_folder.setWordWrap(True)
        stats_layout.addStretch(1)
        stats_layout.addWidget(self.lbl_folder, stretch=2)
        root.addWidget(stats)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.btn_choose = QPushButton("Chọn thư mục")
        self.btn_choose.setObjectName("primaryButton")
        self.btn_enable_log = QPushButton("Bật Event Log in")
        self.btn_sync_history = QPushButton("Đồng bộ lịch sử Event 307")
        self.btn_rescan = QPushButton("Quét lại thư mục")
        self.btn_refresh = QPushButton("Làm mới trạng thái")
        self.btn_open_file = QPushButton("Mở file PDF")
        self.btn_open_folder = QPushButton("Mở thư mục chứa file")
        self.btn_detail = QPushButton("Chi tiết sự kiện")

        for btn in (
            self.btn_choose,
            self.btn_enable_log,
            self.btn_sync_history,
            self.btn_rescan,
            self.btn_refresh,
            self.btn_open_file,
            self.btn_open_folder,
            self.btn_detail,
        ):
            btn_row.addWidget(btn)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.tree_printed = self._make_tree("treePrinted", printed_side=True)
        self.tree_pending = self._make_tree("treePending", printed_side=False)

        box_printed = QGroupBox("ĐÃ IN (Event 307)")
        box_printed.setObjectName("boxPrinted")
        lay_p = QVBoxLayout(box_printed)
        lay_p.setContentsMargins(10, 16, 10, 10)
        lay_p.addWidget(self.tree_printed)

        box_pending = QGroupBox("CHƯA IN")
        box_pending.setObjectName("boxPending")
        lay_u = QVBoxLayout(box_pending)
        lay_u.setContentsMargins(10, 16, 10, 10)
        lay_u.addWidget(self.tree_pending)

        splitter.addWidget(box_printed)
        splitter.addWidget(box_pending)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, stretch=1)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Sẵn sàng")

        self.btn_choose.clicked.connect(self.choose_folder)
        self.btn_enable_log.clicked.connect(self.enable_event_log)
        self.btn_sync_history.clicked.connect(self.sync_event_history)
        self.btn_rescan.clicked.connect(self.rescan_folder)
        self.btn_refresh.clicked.connect(self.refresh_status)
        self.btn_open_file.clicked.connect(self.open_selected_pdf)
        self.btn_open_folder.clicked.connect(self.open_selected_folder)
        self.btn_detail.clicked.connect(self.show_selected_detail)

        self.tree_printed.itemDoubleClicked.connect(lambda *_: self.show_selected_detail())
        self.tree_pending.itemDoubleClicked.connect(lambda *_: self.open_selected_pdf())

        self.tree_printed.itemSelectionChanged.connect(
            lambda: self.tree_pending.clearSelection()
            if self.tree_printed.selectedItems()
            else None
        )
        self.tree_pending.itemSelectionChanged.connect(
            lambda: self.tree_printed.clearSelection()
            if self.tree_pending.selectedItems()
            else None
        )

    def _make_stat_card(
        self,
        layout: QHBoxLayout,
        caption: str,
        value: str,
        *,
        card_id: str,
        value_id: str,
        cap_id: str,
    ) -> QLabel:
        card = QFrame()
        card.setObjectName(card_id)
        col = QVBoxLayout(card)
        col.setContentsMargins(14, 10, 14, 10)
        col.setSpacing(2)

        val = QLabel(value)
        val.setObjectName(value_id)
        val.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        cap = QLabel(caption)
        cap.setObjectName(cap_id)

        col.addWidget(val)
        col.addWidget(cap)
        layout.addWidget(card)
        return val

    def _make_tree(self, object_name: str, *, printed_side: bool) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setObjectName(object_name)
        if printed_side:
            tree.setColumnCount(5)
            tree.setHeaderLabels(
                ["Tên file PDF", "Thời gian in", "Máy in", "Người in", "Số trang"]
            )
        else:
            tree.setColumnCount(3)
            tree.setHeaderLabels(["Tên file PDF", "Trạng thái", "Ghi chú"])
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        tree.setUniformRowHeights(True)
        tree.setMinimumHeight(220)
        header = tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, tree.columnCount()):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        return tree

    # ── Bootstrap / workers ───────────────────────────────────────────
    def _bootstrap(self) -> None:
        folder = self.config.watch_folder
        if folder and Path(folder).is_dir():
            self.tracker.set_watch_folder(folder)
            self.lbl_folder.setText(f"Thư mục: {folder}")
            self._scan_and_refresh(sync_history=True)
            self._start_folder_watcher(folder)
        else:
            self.status.showMessage("Hãy chọn thư mục chứa file PDF để theo dõi.")

        self._start_event_log_monitor()
        self._start_print_monitor()  # fallback Spooler

        if not is_channel_enabled():
            self.status.showMessage(
                "PrintService/Operational đang TẮT — bấm «Bật Event Log in» (Admin)."
            )

    def _start_event_log_monitor(self) -> None:
        if self._event_worker and self._event_worker.isRunning():
            return
        last_id = self.tracker.db.get_last_event_record_id()
        self._event_worker = EventLogMonitorWorker(
            poll_interval=2.0,
            start_after_record_id=last_id,
        )
        self._event_worker.print_event.connect(self._on_event_307)
        self._event_worker.status_message.connect(self.status.showMessage)
        self._event_worker.monitor_error.connect(self._on_monitor_error)
        self._event_worker.channel_disabled.connect(self._on_channel_disabled)
        self._event_worker.start()

    def _start_print_monitor(self) -> None:
        if self._print_worker and self._print_worker.isRunning():
            return
        self._print_worker = PrintMonitorWorker(poll_interval=0.35)
        self._print_worker.print_detected.connect(self._on_print_detected)
        self._print_worker.monitor_error.connect(self._on_monitor_error)
        self._print_worker.start()

    def _start_folder_watcher(self, folder: str) -> None:
        if self._folder_worker and self._folder_worker.isRunning():
            self._folder_worker.set_folder(folder)
            return
        self._folder_worker = FolderWatcherWorker(folder=folder)
        self._folder_worker.folder_changed.connect(self._on_folder_changed)
        self._folder_worker.status_message.connect(self.status.showMessage)
        self._folder_worker.start()

    def closeEvent(self, event) -> None:  # noqa: N802
        self.config.window_width = self.width()
        self.config.window_height = self.height()
        self.config.save()

        for worker in (self._print_worker, self._event_worker, self._folder_worker):
            if worker:
                worker.stop()
                worker.wait(3000)
        super().closeEvent(event)

    # ── Actions ───────────────────────────────────────────────────────
    @Slot()
    def choose_folder(self) -> None:
        start = self.config.watch_folder or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục PDF", start)
        if not folder:
            return
        self.config.set_watch_folder(folder)
        self.tracker.set_watch_folder(folder)
        self.lbl_folder.setText(f"Thư mục: {folder}")
        self._scan_and_refresh(sync_history=True)
        self._start_folder_watcher(folder)
        self.status.showMessage(f"Đã chọn thư mục: {folder}")

    @Slot()
    def enable_event_log(self) -> None:
        if is_channel_enabled():
            QMessageBox.information(
                self,
                "Event Log",
                "PrintService/Operational đã BẬT.\n"
                "Hãy in một PDF rồi bấm «Đồng bộ lịch sử Event 307».",
            )
            return

        reply = QMessageBox.question(
            self,
            "Bật Event Log in",
            "Cần quyền Administrator để bật:\n"
            "• Microsoft-Windows-PrintService/Operational\n"
            "• Allow job name in event logs (ghi tên file vào Event 307)\n\n"
            "Windows sẽ hiện hộp thoại UAC. Tiếp tục?",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        ok, message = enable_channel_elevated()
        if ok:
            QMessageBox.information(self, "Thành công", message)
            self.status.showMessage(message)
            if self._event_worker:
                self._event_worker.set_last_record_id(
                    self.tracker.db.get_last_event_record_id()
                )
        else:
            QMessageBox.warning(
                self,
                "Chưa bật được",
                f"{message}\n\n"
                "Cách thủ công:\n"
                "1. Mở eventvwr.msc\n"
                "2. Applications and Services Logs → Microsoft → Windows → PrintService\n"
                "3. Chuột phải Operational → Enable Log",
            )

    @Slot()
    def sync_event_history(self) -> None:
        if not self.tracker.watch_folder:
            QMessageBox.information(self, "Thông báo", "Chưa chọn thư mục theo dõi.")
            return
        if not is_channel_enabled():
            QMessageBox.warning(
                self,
                "Event Log tắt",
                "PrintService/Operational đang tắt. Bấm «Bật Event Log in» trước.",
            )
            return

        self.tracker.scan_folder()
        self.tracker.scan_folder()
        stats = self.tracker.sync_history_from_event_log()
        self._reload_lists()
        if self._event_worker:
            self._event_worker.set_last_record_id(
                self.tracker.db.get_last_event_record_id()
            )
        self.status.showMessage(
            "Đồng bộ Event 307 — "
            f"đọc: {stats.get('events_read', 0)}, "
            f"khớp: {stats.get('matched', 0)}, "
            f"khôi phục: {stats.get('restored', 0)}, "
            f"không khớp: {stats.get('unmatched', 0)}, "
            f"generic: {stats.get('generic', 0)}, "
            f"mơ hồ: {stats.get('ambiguous', 0)}"
        )

    @Slot()
    def rescan_folder(self) -> None:
        if not self.tracker.watch_folder:
            QMessageBox.information(self, "Thông báo", "Chưa chọn thư mục theo dõi.")
            return
        # Quét lại + đối chiếu lịch sử Event 307 để hiện file đã in trước đó
        self._scan_and_refresh(sync_history=True)

    @Slot()
    def refresh_status(self) -> None:
        if self.tracker.watch_folder:
            self.tracker.scan_folder()
        self._reload_lists()
        self.status.showMessage("Đã làm mới trạng thái.")

    @Slot()
    def open_selected_pdf(self) -> None:
        path = self._selected_path()
        if not path:
            QMessageBox.information(self, "Thông báo", "Hãy chọn một file PDF.")
            return
        if not Path(path).is_file():
            QMessageBox.warning(self, "Lỗi", "File không tồn tại.")
            return
        self._open_path(path)

    @Slot()
    def open_selected_folder(self) -> None:
        path = self._selected_path()
        folder = str(Path(path).parent) if path else self.tracker.watch_folder
        if not folder:
            QMessageBox.information(self, "Thông báo", "Chưa có thư mục để mở.")
            return
        self._open_path(folder)

    @Slot()
    def show_selected_detail(self) -> None:
        path = self._selected_path()
        if not path:
            QMessageBox.information(self, "Thông báo", "Hãy chọn một file để xem chi tiết.")
            return
        rec = self.tracker.db.get_by_path(path)
        if not rec:
            return

        lines = [
            f"Document Name: {rec.job_document or rec.file_name}",
            f"File: {rec.file_path}",
            f"User: {rec.printed_by or '—'}",
            f"Printer Name: {rec.printer_name or '—'}",
            f"Time: {_format_local_time(rec.printed_at)}",
            f"Pages: {rec.pages if rec.pages is not None else '—'}",
            f"Client: {rec.client_computer or '—'}",
            f"Event Record ID: {rec.event_record_id if rec.event_record_id is not None else '—'}",
            f"Status: {rec.status.value}",
        ]
        QMessageBox.information(self, "Chi tiết sự kiện in", "\n".join(lines))

    # ── Data / rendering ──────────────────────────────────────────────
    def _scan_and_refresh(self, *, sync_history: bool = False) -> None:
        self.tracker.scan_folder()
        if sync_history:
            if not is_channel_enabled():
                self.status.showMessage(
                    "Đã quét thư mục — PrintService/Operational đang TẮT nên "
                    "chưa đọc được lịch sử Event 307. Bấm «Bật Event Log in»."
                )
            else:
                stats = self.tracker.sync_history_from_event_log()
                if self._event_worker:
                    self._event_worker.set_last_record_id(
                        self.tracker.db.get_last_event_record_id()
                    )
                self.status.showMessage(
                    "Đã đối chiếu lịch sử in — "
                    f"Event 307 đọc: {stats.get('events_read', 0)}, "
                    f"khớp: {stats.get('matched', 0)}, "
                    f"khôi phục SQLite: {stats.get('restored', 0)}, "
                    f"generic: {stats.get('generic', 0)}, "
                    f"không khớp: {stats.get('unmatched', 0)}"
                )
        self._reload_lists()

    def _reload_lists(self) -> None:
        # Chỉ hiển thị thư mục đang chọn; lịch sử thư mục khác vẫn giữ trong SQLite
        records = self.tracker.current_records()
        printed = [r for r in records if r.status == PrintStatus.PRINTED]
        pending = [r for r in records if r.status != PrintStatus.PRINTED]

        self._fill_tree(self.tree_printed, printed, printed_side=True)
        self._fill_tree(self.tree_pending, pending, printed_side=False)

        counts = self.tracker.counts()
        self.lbl_total_val.setText(str(counts["total"]))
        self.lbl_printed_val.setText(str(counts["printed"]))
        self.lbl_pending_val.setText(str(counts["not_printed"] + counts["unknown"]))

    def _fill_tree(
        self,
        tree: QTreeWidget,
        records: list[PdfRecord],
        *,
        printed_side: bool,
    ) -> None:
        tree.clear()
        for rec in records:
            if printed_side:
                item = QTreeWidgetItem(
                    [
                        rec.file_name,
                        _format_local_time(rec.printed_at),
                        rec.printer_name or "—",
                        rec.printed_by or "—",
                        str(rec.pages) if rec.pages is not None else "—",
                    ]
                )
                item.setForeground(0, QBrush(QColor("#14532d")))
            else:
                note = ""
                status_text = "Chưa in"
                if rec.status == PrintStatus.UNKNOWN:
                    status_text = "Chưa xác định"
                    note = "Không khớp chắc chắn"
                item = QTreeWidgetItem([rec.file_name, status_text, note])
                item.setForeground(0, QBrush(QColor("#9a3412")))

            item.setData(0, Qt.ItemDataRole.UserRole, rec.file_path)
            tip_parts = [
                rec.file_path,
                f"Document: {rec.job_document or '—'}",
                f"User: {rec.printed_by or '—'}",
                f"Printer: {rec.printer_name or '—'}",
                f"Time: {_format_local_time(rec.printed_at)}",
                f"Pages: {rec.pages if rec.pages is not None else '—'}",
            ]
            item.setToolTip(0, "\n".join(tip_parts))
            tree.addTopLevelItem(item)

    def _selected_path(self) -> str | None:
        for tree in (self.tree_printed, self.tree_pending):
            items = tree.selectedItems()
            if items:
                return items[0].data(0, Qt.ItemDataRole.UserRole)
        return None

    @staticmethod
    def _open_path(path: str) -> None:
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except OSError as exc:
            QMessageBox.warning(None, "Lỗi", f"Không mở được:\n{exc}")

    # ── Worker slots ──────────────────────────────────────────────────
    @Slot(object)
    def _on_event_307(self, event: object) -> None:
        if not isinstance(event, PrintServiceEvent307):
            return
        outcome, matched = self.tracker.handle_event_307(event)
        self._reload_lists()

        doc = event.document_name
        detail = (
            f"User={event.user_name or '?'} | "
            f"Printer={event.printer_name or '?'} | "
            f"Pages={event.pages if event.pages is not None else '?'} | "
            f"Time={_format_local_time(event.event_time.isoformat(timespec='seconds'))}"
        )
        if outcome == "matched" and matched:
            self.status.showMessage(f"Event 307 khớp: {Path(matched).name} — {detail}")
        elif outcome == "generic":
            self.status.showMessage(
                "Event 307 có Document Name generic («Print Document»). "
                "Cần bật Allow job name in event logs."
            )
        elif outcome == "ambiguous":
            self.status.showMessage(f"Event 307 mơ hồ «{doc}» — không đánh dấu. {detail}")
        elif outcome == "unmatched":
            self.status.showMessage(f"Event 307 không khớp PDF: «{doc}». {detail}")
        elif outcome == "no_folder":
            self.status.showMessage(f"Event 307 nhưng chưa chọn thư mục. {detail}")

    @Slot(object)
    def _on_print_detected(self, event: object) -> None:
        if not isinstance(event, CompletedPrintEvent):
            return
        outcome, matched = self.tracker.handle_completed_job(event)
        self._reload_lists()
        if outcome == "matched" and matched:
            self.status.showMessage(
                f"Spooler: đã gửi lệnh in {Path(matched).name} → {event.printer_name}"
            )

    @Slot()
    def _on_folder_changed(self) -> None:
        self._scan_and_refresh(sync_history=False)
        self.status.showMessage("Thư mục thay đổi — đã cập nhật danh sách PDF.")

    @Slot()
    def _on_channel_disabled(self) -> None:
        self.status.showMessage(
            "PrintService/Operational đang TẮT — bấm «Bật Event Log in»."
        )

    @Slot(str)
    def _on_monitor_error(self, message: str) -> None:
        self.status.showMessage(message)
