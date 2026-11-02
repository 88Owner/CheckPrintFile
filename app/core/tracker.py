"""Điều phối quét thư mục, đối chiếu Print Job và cập nhật SQLite."""

from __future__ import annotations

from pathlib import Path

from app.core.database import Database, PdfRecord, PrintStatus
from app.core.hasher import file_sha256
from app.core.matcher import list_pdfs_in_folder, match_document_to_pdfs
from app.workers.print_monitor import CompletedPrintEvent


class PdfTracker:
    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database()
        self._watch_folder: str = ""

    @property
    def watch_folder(self) -> str:
        return self._watch_folder

    def set_watch_folder(self, folder: str) -> None:
        self._watch_folder = folder or ""

    def scan_folder(self, folder: str | None = None) -> list[PdfRecord]:
        target = folder if folder is not None else self._watch_folder
        if not target or not Path(target).is_dir():
            return self.db.list_all()

        self._watch_folder = target
        paths = list_pdfs_in_folder(target)
        existing: set[str] = set()

        for path in paths:
            existing.add(path)
            try:
                digest = file_sha256(path)
            except OSError:
                continue
            self.db.upsert_file(
                path,
                Path(path).name,
                digest,
                reset_if_hash_changed=True,
            )

        self.db.remove_missing(existing)
        return self.db.list_all()

    def handle_completed_job(self, event: CompletedPrintEvent) -> tuple[str, str | None]:
        """
        Xử lý khi phát hiện lệnh Print trên Spooler.
        Đối chiếu tên tài liệu với PDF trong thư mục đang theo dõi.

        Returns:
            (outcome, matched_path)
            outcome: matched | ambiguous | unmatched | no_folder
        """
        if not self._watch_folder:
            self.db.log_print_event(
                printer_name=event.printer_name,
                job_id=event.job_id,
                document=event.document,
                matched_path=None,
                outcome="no_folder",
            )
            return "no_folder", None

        pdfs = [r.file_path for r in self.db.list_all()]
        # Đồng bộ với disk để tránh lệch tên mới
        disk = list_pdfs_in_folder(self._watch_folder)
        pdfs = list(dict.fromkeys([*pdfs, *disk]))

        result = match_document_to_pdfs(event.document, pdfs)

        if result.confidence == "ambiguous":
            self.db.log_print_event(
                printer_name=event.printer_name,
                job_id=event.job_id,
                document=event.document,
                matched_path=None,
                outcome="ambiguous",
            )
            # Không đánh dấu đã in; ghi chú unknown nếu chỉ có 1 thư mục theo dõi
            return "ambiguous", None

        if result.confidence == "none" or not result.matched_path:
            self.db.log_print_event(
                printer_name=event.printer_name,
                job_id=event.job_id,
                document=event.document,
                matched_path=None,
                outcome="unmatched",
            )
            return "unmatched", None

        # Chỉ chấp nhận khớp chắc chắn
        if result.confidence not in {"exact", "basename", "cleaned"}:
            self.db.log_print_event(
                printer_name=event.printer_name,
                job_id=event.job_id,
                document=event.document,
                matched_path=None,
                outcome="unmatched",
            )
            return "unmatched", None

        # Đảm bảo record tồn tại
        path = result.matched_path
        if Path(path).is_file():
            try:
                digest = file_sha256(path)
                self.db.upsert_file(path, Path(path).name, digest, reset_if_hash_changed=True)
            except OSError:
                pass

        self.db.mark_printed(
            path,
            printer_name=event.printer_name,
            job_document=event.document,
        )
        self.db.log_print_event(
            printer_name=event.printer_name,
            job_id=event.job_id,
            document=event.document,
            matched_path=path,
            outcome="matched",
        )
        return "matched", path

    def counts(self) -> dict[str, int]:
        records = self.db.list_all()
        printed = sum(1 for r in records if r.status == PrintStatus.PRINTED)
        unknown = sum(1 for r in records if r.status == PrintStatus.UNKNOWN)
        not_printed = sum(1 for r in records if r.status == PrintStatus.NOT_PRINTED)
        return {
            "total": len(records),
            "printed": printed,
            "not_printed": not_printed,
            "unknown": unknown,
        }
