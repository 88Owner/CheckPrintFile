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
from app.core.tracker import PdfTracker
from app.ui.styles import APP_STYLESHEET
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
        self.resize(self.config.window_width, self.config.window_height)

        self.tracker = PdfTracker()
        self._print_worker: PrintMonitorWorker | None = None
        self._folder_worker: FolderWatcherWorker | None = None

        self._build_ui()
        self.setStyleSheet(APP_STYLESHEET)

        # Quét + theo dõi sau khi UI sẵn sàng
        QTimer.singleShot(0, self._bootstrap)

    # ── UI ────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(12)

        # Header
        header = QVBoxLayout()
        title = QLabel("PDF Print Checker")
        title.setObjectName("titleLabel")
        subtitle = QLabel(
            "Quét PDF trong thư mục → thống kê file nào đã gửi lệnh Print trên Windows"
        )
        subtitle.setObjectName("subtitleLabel")
        header.addWidget(title)
        header.addWidget(subtitle)
        root.addLayout(header)

        # Stats
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
            stats_layout, "Đã gửi lệnh in", "0",
            card_id="statCardPrinted", value_id="statPrinted", cap_id="statPrintedCap",
        )
        self.lbl_pending_val = self._make_stat_card(
            stats_layout, "Chưa gửi lệnh in", "0",
            card_id="statCardPending", value_id="statPending", cap_id="statPendingCap",
        )
        self.lbl_folder = QLabel("Thư mục: (chưa chọn)")
        self.lbl_folder.setObjectName("folderLabel")
        self.lbl_folder.setWordWrap(True)
        stats_layout.addStretch(1)
        stats_layout.addWidget(self.lbl_folder, stretch=2)
        root.addWidget(stats)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.btn_choose = QPushButton("Chọn thư mục")
        self.btn_choose.setObjectName("primaryButton")
        self.btn_rescan = QPushButton("Quét lại thư mục")
        self.btn_refresh = QPushButton("Làm mới trạng thái")
        self.btn_open_file = QPushButton("Mở file PDF")
        self.btn_open_folder = QPushButton("Mở thư mục chứa file")

        for btn in (
            self.btn_choose,
            self.btn_rescan,
            self.btn_refresh,
            self.btn_open_file,
            self.btn_open_folder,
        ):
            btn_row.addWidget(btn)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        # Lists — màu tách rõ: xanh = đã gửi, cam = chưa gửi
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.tree_printed = self._make_tree("treePrinted")
        self.tree_pending = self._make_tree("treePending")

        box_printed = QGroupBox("ĐÃ GỬI LỆNH IN")
        box_printed.setObjectName("boxPrinted")
        lay_p = QVBoxLayout(box_printed)
        lay_p.setContentsMargins(10, 16, 10, 10)
        lay_p.addWidget(self.tree_printed)

        box_pending = QGroupBox("CHƯA GỬI LỆNH IN")
        box_pending.setObjectName("boxPending")
        lay_u = QVBoxLayout(box_pending)
        lay_u.setContentsMargins(10, 16, 10, 10)
        lay_u.addWidget(self.tree_pending)

        splitter.addWidget(box_printed)
        splitter.addWidget(box_pending)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, stretch=1)

        # Status bar
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Sẵn sàng")

        # Signals
        self.btn_choose.clicked.connect(self.choose_folder)
        self.btn_rescan.clicked.connect(self.rescan_folder)
        self.btn_refresh.clicked.connect(self.refresh_status)
        self.btn_open_file.clicked.connect(self.open_selected_pdf)
        self.btn_open_folder.clicked.connect(self.open_selected_folder)

        self.tree_printed.itemDoubleClicked.connect(lambda *_: self.open_selected_pdf())
        self.tree_pending.itemDoubleClicked.connect(lambda *_: self.open_selected_pdf())

        # Context-ish: keep selection exclusive between trees
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

    def _make_tree(self, object_name: str) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setObjectName(object_name)
        tree.setColumnCount(3)
        tree.setHeaderLabels(["Tên file PDF", "Thời gian gửi lệnh", "Máy in"])
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        tree.setUniformRowHeights(True)
        tree.setMinimumHeight(220)
        header = tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        return tree

    # ── Bootstrap / workers ───────────────────────────────────────────
    def _bootstrap(self) -> None:
        folder = self.config.watch_folder
        if folder and Path(folder).is_dir():
            self.tracker.set_watch_folder(folder)
            self.lbl_folder.setText(f"Thư mục: {folder}")
            self._scan_and_refresh()
            self._start_folder_watcher(folder)
        else:
            self.status.showMessage("Hãy chọn thư mục chứa file PDF để theo dõi.")

        self._start_print_monitor()

    def _start_print_monitor(self) -> None:
        if self._print_worker and self._print_worker.isRunning():
            return
        self._print_worker = PrintMonitorWorker(poll_interval=0.25)
        self._print_worker.print_detected.connect(self._on_print_detected)
        self._print_worker.status_message.connect(self.status.showMessage)
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

        if self._print_worker:
            self._print_worker.stop()
            self._print_worker.wait(3000)
        if self._folder_worker:
            self._folder_worker.stop()
            self._folder_worker.wait(3000)
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
        self._scan_and_refresh()
        self._start_folder_watcher(folder)
        self.status.showMessage(f"Đã chọn thư mục: {folder}")

    @Slot()
    def rescan_folder(self) -> None:
        if not self.tracker.watch_folder:
            QMessageBox.information(self, "Thông báo", "Chưa chọn thư mục theo dõi.")
            return
        self._scan_and_refresh()
        self.status.showMessage("Đã quét lại thư mục.")

    @Slot()
    def refresh_status(self) -> None:
        """Làm mới hiển thị từ SQLite (không đổi trạng thái đã lưu)."""
        if self.tracker.watch_folder:
            # Quét nhẹ để bắt file mới / hash đổi
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
        folder = None
        if path:
            folder = str(Path(path).parent)
        elif self.tracker.watch_folder:
            folder = self.tracker.watch_folder
        if not folder:
            QMessageBox.information(self, "Thông báo", "Chưa có thư mục để mở.")
            return
        self._open_path(folder)

    # ── Data / rendering ──────────────────────────────────────────────
    def _scan_and_refresh(self) -> None:
        self.tracker.scan_folder()
        self._reload_lists()

    def _reload_lists(self) -> None:
        records = self.tracker.db.list_all()
        printed = [r for r in records if r.status == PrintStatus.PRINTED]
        pending = [r for r in records if r.status != PrintStatus.PRINTED]

        self._fill_tree(self.tree_printed, printed, printed_side=True)
        self._fill_tree(self.tree_pending, pending, printed_side=False)

        counts = self.tracker.counts()
        # "Chưa in" trên UI = chưa in + chưa xác định (không tự đánh dấu đã in)
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
            item = QTreeWidgetItem(
                [
                    rec.file_name,
                    _format_local_time(rec.printed_at) if printed_side else "—",
                    rec.printer_name or ("—" if printed_side else ""),
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, rec.file_path)
            tip = rec.file_path
            if rec.status == PrintStatus.UNKNOWN:
                tip += "\nTrạng thái: chưa xác định (không khớp chắc chắn với lệnh in)"
                item.setForeground(0, QBrush(QColor("#b45309")))
                if not printed_side:
                    item.setText(1, "Chưa xác định")
            elif not printed_side:
                item.setForeground(0, QBrush(QColor("#9a3412")))
            else:
                item.setForeground(0, QBrush(QColor("#14532d")))

            item.setToolTip(0, tip)
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
    def _on_print_detected(self, event: object) -> None:
        if not isinstance(event, CompletedPrintEvent):
            return
        outcome, matched = self.tracker.handle_completed_job(event)
        self._reload_lists()
        doc = event.document
        if outcome == "matched" and matched:
            self.status.showMessage(
                f"Đã gửi lệnh in: {Path(matched).name}  →  {event.printer_name}"
            )
        elif outcome == "ambiguous":
            self.status.showMessage(
                f"Có lệnh in «{doc}» nhưng khớp nhiều file — không tự đánh dấu."
            )
        elif outcome == "unmatched":
            self.status.showMessage(
                f"Có lệnh in «{doc}» nhưng không khớp PDF nào trong thư mục."
            )
        elif outcome == "no_folder":
            self.status.showMessage("Có lệnh in nhưng chưa chọn thư mục theo dõi.")

    @Slot()
    def _on_folder_changed(self) -> None:
        self._scan_and_refresh()
        self.status.showMessage("Thư mục thay đổi — đã cập nhật danh sách PDF.")

    @Slot(str)
    def _on_monitor_error(self, message: str) -> None:
        self.status.showMessage(message)
