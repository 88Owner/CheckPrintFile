"""Điều phối quét thư mục, đối chiếu lệnh in (Event 307 / Spooler) với PDF."""

from __future__ import annotations

from pathlib import Path

from app.core.database import Database, PdfRecord, PrintStatus
from app.core.hasher import file_sha256
from app.core.matcher import list_pdfs_in_folder, match_document_to_pdfs
from app.core.print_event_log import PrintServiceEvent307, iter_event_307
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
            return self.current_records()

        self._watch_folder = str(Path(target).resolve())
        paths = list_pdfs_in_folder(self._watch_folder)
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
                folder_path=self._watch_folder,
                reset_if_hash_changed=True,
            )

        # Chỉ dọn file thiếu trong thư mục hiện tại — giữ lịch sử thư mục khác
        self.db.remove_missing_in_folder(self._watch_folder, existing)
        return self.current_records()

    def current_records(self) -> list[PdfRecord]:
        if not self._watch_folder:
            return []
        return self.db.list_by_folder(self._watch_folder)

    def _pdf_paths_for_match(self) -> list[str]:
        """File trên đĩa + record đã lưu của thư mục đang mở."""
        if not self._watch_folder:
            return []
        disk = list_pdfs_in_folder(self._watch_folder)
        saved = [r.file_path for r in self.db.list_by_folder(self._watch_folder)]
        return list(dict.fromkeys([*disk, *saved]))

    def sync_history_from_event_log(self, *, max_events: int = 2000) -> dict[str, int]:
        """
        Mỗi lần mở/đổi thư mục: đọc lại Event 307 và gắn vào PDF đang mở.

        Không bỏ qua event từng ghi unmatched/no_folder — đó là lý do trước đây
        mở lại app không thấy file đã in.
        """
        stats = {
            "matched": 0,
            "unmatched": 0,
            "ambiguous": 0,
            "generic": 0,
            "skipped": 0,
            "restored": 0,
            "events_read": 0,
            "error": 0,
        }
        if not self._watch_folder:
            return stats

        # 1) Khôi phục từ SQLite (các lần matched cũ)
        stats["restored"] = self._restore_matches_from_db()

        # 2) Đọc Event Viewer — đối chiếu lại toàn bộ với folder hiện tại
        try:
            events = iter_event_307(max_events=max_events)
        except RuntimeError:
            stats["error"] = 1
            return stats

        stats["events_read"] = len(events)
        max_rid = self.db.get_last_event_record_id()

        for ev in events:
            max_rid = max(max_rid, ev.record_id)
            # Luôn thử khớp lại với PDF thư mục hiện tại
            outcome, _matched = self.handle_event_307(ev, persist_non_match=False)
            key = outcome if outcome in stats else "unmatched"
            stats[key] = stats.get(key, 0) + 1

        if events:
            self.db.set_last_event_record_id(max_rid)
        return stats

    def _restore_matches_from_db(self) -> int:
        """Gắn lại ĐÃ IN từ lịch sử SQLite khi mở lại thư mục."""
        restored = 0
        folder_pdfs = {p.lower(): p for p in self._pdf_paths_for_match()}

        for row in self.db.list_matched_event_paths():
            matched_path = row.get("matched_path") or ""
            if not matched_path:
                continue

            path = None
            if matched_path.lower() in folder_pdfs:
                path = folder_pdfs[matched_path.lower()]
            else:
                name = Path(matched_path).name.lower()
                hits = [p for p in folder_pdfs.values() if Path(p).name.lower() == name]
                if len(hits) == 1:
                    path = hits[0]

            if not path:
                continue

            rec = self.db.get_by_path(path)
            if rec and rec.status == PrintStatus.PRINTED:
                continue

            # Nội dung đổi so với lúc lưu → không khôi phục lệnh in cũ
            if Path(path).is_file() and rec is not None:
                try:
                    digest = file_sha256(path)
                except OSError:
                    continue
                if digest != rec.file_hash:
                    continue

            self.db.mark_printed(
                path,
                printer_name=row.get("printer_name"),
                job_document=row.get("document"),
                printed_at=row.get("event_time"),
                printed_by=row.get("user_name"),
                pages=row.get("pages"),
                event_record_id=row.get("event_record_id"),
            )
            restored += 1
        return restored

    def handle_event_307(
        self,
        event: PrintServiceEvent307,
        *,
        persist_non_match: bool = True,
    ) -> tuple[str, str | None]:
        """
        Xử lý Event 307 (Document / User / Printer / Time / Pages).

        persist_non_match=False: khi sync theo folder, không ghi unmatched vào DB
        (tránh lần sau bị “đánh dấu đã xử lý” oan).
        """
        event_time = event.event_time.isoformat(timespec="seconds")

        def _log_non_match(outcome: str) -> None:
            if not persist_non_match:
                return
            self.db.log_print_event(
                printer_name=event.printer_name,
                job_id=event.job_id,
                document=event.document_name,
                matched_path=None,
                outcome=outcome,
                user_name=event.user_name,
                pages=event.pages,
                event_record_id=event.record_id,
                event_time=event_time,
            )

        if not self._watch_folder:
            _log_non_match("no_folder")
            self.db.set_last_event_record_id(event.record_id)
            return "no_folder", None

        if event.document_is_generic:
            _log_non_match("generic")
            self.db.set_last_event_record_id(event.record_id)
            return "generic", None

        pdfs = self._pdf_paths_for_match()
        result = match_document_to_pdfs(event.document_name, pdfs)

        if result.confidence == "ambiguous":
            _log_non_match("ambiguous")
            self.db.set_last_event_record_id(event.record_id)
            return "ambiguous", None

        if result.confidence not in {"exact", "basename", "cleaned"} or not result.matched_path:
            _log_non_match("unmatched")
            self.db.set_last_event_record_id(event.record_id)
            return "unmatched", None

        path = result.matched_path

        # Nếu nội dung file đã đổi sau lần in → không gắn lại event cũ
        rec = self.db.get_by_path(path)
        if Path(path).is_file():
            try:
                digest = file_sha256(path)
                if rec is not None and rec.file_hash != digest:
                    # Hash lệch: cập nhật record (có thể reset printed) rồi thôi không
                    # áp event cũ — trừ khi đây là event mới hơn sẽ do caller quyết.
                    self.db.upsert_file(
                        path,
                        Path(path).name,
                        digest,
                        folder_path=self._watch_folder,
                        reset_if_hash_changed=True,
                    )
                    _log_non_match("unmatched")
                    return "unmatched", None
                self.db.upsert_file(
                    path,
                    Path(path).name,
                    digest,
                    folder_path=self._watch_folder,
                    reset_if_hash_changed=False,
                )
            except OSError:
                pass

        self.db.mark_printed(
            path,
            printer_name=event.printer_name or None,
            job_document=event.document_name,
            printed_at=event_time,
            printed_by=event.user_name or None,
            pages=event.pages,
            client_computer=event.client_computer or None,
            event_record_id=event.record_id,
        )
        if not self.db.has_matched_event(event.record_id):
            self.db.log_print_event(
                printer_name=event.printer_name,
                job_id=event.job_id,
                document=event.document_name,
                matched_path=path,
                outcome="matched",
                user_name=event.user_name,
                pages=event.pages,
                event_record_id=event.record_id,
                event_time=event_time,
            )
        self.db.set_last_event_record_id(event.record_id)
        return "matched", path

    def handle_completed_job(self, event: CompletedPrintEvent) -> tuple[str, str | None]:
        """Fallback Spooler (khi chưa có Event 307)."""
        if not self._watch_folder:
            return "no_folder", None

        pdfs = self._pdf_paths_for_match()
        result = match_document_to_pdfs(event.document, pdfs)

        if result.confidence == "ambiguous":
            return "ambiguous", None

        if result.confidence not in {"exact", "basename", "cleaned"} or not result.matched_path:
            return "unmatched", None

        path = result.matched_path
        existing = self.db.get_by_path(path)
        if existing and existing.status == PrintStatus.PRINTED and existing.event_record_id:
            return "matched", path

        if Path(path).is_file():
            try:
                digest = file_sha256(path)
                self.db.upsert_file(
                    path,
                    Path(path).name,
                    digest,
                    folder_path=self._watch_folder,
                    reset_if_hash_changed=True,
                )
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
        records = self.current_records()
        printed = sum(1 for r in records if r.status == PrintStatus.PRINTED)
        unknown = sum(1 for r in records if r.status == PrintStatus.UNKNOWN)
        not_printed = sum(1 for r in records if r.status == PrintStatus.NOT_PRINTED)
        return {
            "total": len(records),
            "printed": printed,
            "not_printed": not_printed,
            "unknown": unknown,
        }
