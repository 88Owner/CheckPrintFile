"""Lưu trạng thái in PDF bằng SQLite."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Iterator

from app.core.paths import db_path


class PrintStatus(str, Enum):
    NOT_PRINTED = "not_printed"
    PRINTED = "printed"
    UNKNOWN = "unknown"


@dataclass
class PdfRecord:
    file_path: str
    file_name: str
    file_hash: str
    status: PrintStatus
    folder_path: str | None = None
    printed_at: str | None = None
    printer_name: str | None = None
    job_document: str | None = None
    printed_by: str | None = None
    pages: int | None = None
    client_computer: str | None = None
    event_record_id: int | None = None
    updated_at: str | None = None


def normalize_folder(folder: str | Path) -> str:
    """Chuẩn hóa đường dẫn thư mục để so sánh ổn định trên Windows."""
    return str(Path(folder).resolve()).rstrip("\\/").lower()


def path_in_folder(file_path: str, folder: str) -> bool:
    try:
        Path(file_path).resolve().relative_to(Path(folder).resolve())
        return True
    except (ValueError, OSError):
        # Fallback so sánh chuỗi (ổ đĩa / quyền)
        fp = str(Path(file_path)).rstrip("\\/").lower()
        fd = normalize_folder(folder)
        return fp == fd or fp.startswith(fd + "\\") or fp.startswith(fd + "/")



def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or db_path()
        self._lock = threading.RLock()
        self._init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = sqlite3.connect(self._path, timeout=30)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pdf_files (
                    file_path   TEXT PRIMARY KEY,
                    file_name   TEXT NOT NULL,
                    file_hash   TEXT NOT NULL,
                    status      TEXT NOT NULL DEFAULT 'not_printed',
                    printed_at  TEXT,
                    printer_name TEXT,
                    job_document TEXT,
                    printed_by  TEXT,
                    pages       INTEGER,
                    client_computer TEXT,
                    event_record_id INTEGER,
                    updated_at  TEXT NOT NULL
                )
                """
            )
            self._ensure_columns(
                conn,
                "pdf_files",
                {
                    "folder_path": "TEXT",
                    "printed_by": "TEXT",
                    "pages": "INTEGER",
                    "client_computer": "TEXT",
                    "event_record_id": "INTEGER",
                },
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_pdf_files_folder ON pdf_files(folder_path)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS print_events (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    printer_name TEXT,
                    job_id      INTEGER,
                    document    TEXT,
                    matched_path TEXT,
                    outcome     TEXT NOT NULL,
                    user_name   TEXT,
                    pages       INTEGER,
                    event_record_id INTEGER,
                    event_time  TEXT,
                    created_at  TEXT NOT NULL
                )
                """
            )
            self._ensure_columns(
                conn,
                "print_events",
                {
                    "user_name": "TEXT",
                    "pages": "INTEGER",
                    "event_record_id": "INTEGER",
                    "event_time": "TEXT",
                },
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_meta (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _ensure_columns(
        conn: sqlite3.Connection, table: str, columns: dict[str, str]
    ) -> None:
        existing = {
            row[1]
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for name, col_type in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {col_type}")

    def get_meta(self, key: str, default: str = "") -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM app_meta WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO app_meta(key, value) VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def get_last_event_record_id(self) -> int:
        try:
            return int(self.get_meta("last_event_record_id", "0") or "0")
        except ValueError:
            return 0

    def set_last_event_record_id(self, record_id: int) -> None:
        current = self.get_last_event_record_id()
        if record_id > current:
            self.set_meta("last_event_record_id", str(record_id))

    def upsert_file(
        self,
        file_path: str,
        file_name: str,
        file_hash: str,
        *,
        folder_path: str | None = None,
        reset_if_hash_changed: bool = True,
    ) -> PdfRecord:
        now = _utc_now()
        folder = str(Path(folder_path).resolve()) if folder_path else str(Path(file_path).parent.resolve())
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM pdf_files WHERE file_path = ?", (file_path,)
            ).fetchone()

            if row is None:
                conn.execute(
                    """
                    INSERT INTO pdf_files
                    (file_path, file_name, file_hash, status, folder_path, printed_at,
                     printer_name, job_document, printed_by, pages,
                     client_computer, event_record_id, updated_at)
                    VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, ?)
                    """,
                    (
                        file_path,
                        file_name,
                        file_hash,
                        PrintStatus.NOT_PRINTED.value,
                        folder,
                        now,
                    ),
                )
                return PdfRecord(
                    file_path=file_path,
                    file_name=file_name,
                    file_hash=file_hash,
                    status=PrintStatus.NOT_PRINTED,
                    folder_path=folder,
                    updated_at=now,
                )

            old_hash = row["file_hash"]
            status = PrintStatus(row["status"])
            printed_at = row["printed_at"]
            printer_name = row["printer_name"]
            job_document = row["job_document"]
            printed_by = row["printed_by"]
            pages = row["pages"]
            client_computer = row["client_computer"]
            event_record_id = row["event_record_id"]

            if reset_if_hash_changed and old_hash != file_hash:
                status = PrintStatus.NOT_PRINTED
                printed_at = None
                printer_name = None
                job_document = None
                printed_by = None
                pages = None
                client_computer = None
                event_record_id = None

            conn.execute(
                """
                UPDATE pdf_files
                SET file_name = ?, file_hash = ?, status = ?, folder_path = ?,
                    printed_at = ?, printer_name = ?, job_document = ?,
                    printed_by = ?, pages = ?, client_computer = ?,
                    event_record_id = ?, updated_at = ?
                WHERE file_path = ?
                """,
                (
                    file_name,
                    file_hash,
                    status.value,
                    folder,
                    printed_at,
                    printer_name,
                    job_document,
                    printed_by,
                    pages,
                    client_computer,
                    event_record_id,
                    now,
                    file_path,
                ),
            )
            return PdfRecord(
                file_path=file_path,
                file_name=file_name,
                file_hash=file_hash,
                status=status,
                folder_path=folder,
                printed_at=printed_at,
                printer_name=printer_name,
                job_document=job_document,
                printed_by=printed_by,
                pages=pages,
                client_computer=client_computer,
                event_record_id=event_record_id,
                updated_at=now,
            )

    def remove_missing_in_folder(self, folder: str, existing_paths: set[str]) -> int:
        """
        Chỉ xóa file thiếu trong đúng thư mục đang quét.
        Không đụng lịch sử của thư mục khác khi đổi folder.
        File đã in vẫn giữ lại (lịch sử) dù file đã bị xóa khỏi đĩa.
        """
        with self._connect() as conn:
            rows = conn.execute("SELECT file_path, status, folder_path FROM pdf_files").fetchall()
            to_delete: list[str] = []
            for row in rows:
                path = row["file_path"]
                if not path_in_folder(path, folder):
                    # Thư mục khác → giữ nguyên lịch sử
                    continue
                if path in existing_paths:
                    continue
                # Giữ record đã in để không mất lịch sử
                if row["status"] == PrintStatus.PRINTED.value:
                    continue
                to_delete.append(path)
            for path in to_delete:
                conn.execute("DELETE FROM pdf_files WHERE file_path = ?", (path,))
            return len(to_delete)

    def remove_missing(self, existing_paths: set[str]) -> int:
        """Deprecated: dùng remove_missing_in_folder để không mất lịch sử khi đổi thư mục."""
        with self._connect() as conn:
            rows = conn.execute("SELECT file_path FROM pdf_files").fetchall()
            to_delete = [r["file_path"] for r in rows if r["file_path"] not in existing_paths]
            for path in to_delete:
                conn.execute("DELETE FROM pdf_files WHERE file_path = ?", (path,))
            return len(to_delete)

    def list_by_folder(self, folder: str) -> list[PdfRecord]:
        """Danh sách PDF thuộc một thư mục theo dõi (kể cả file đã in nhưng đã xóa)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM pdf_files ORDER BY file_name COLLATE NOCASE"
            ).fetchall()
        records = [self._row_to_record(r) for r in rows]
        return [r for r in records if path_in_folder(r.file_path, folder)]

    def mark_printed(
        self,
        file_path: str,
        *,
        printer_name: str | None,
        job_document: str | None,
        printed_at: str | None = None,
        printed_by: str | None = None,
        pages: int | None = None,
        client_computer: str | None = None,
        event_record_id: int | None = None,
    ) -> bool:
        now = printed_at or _utc_now()
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE pdf_files
                SET status = ?, printed_at = ?, printer_name = ?,
                    job_document = ?, printed_by = ?, pages = ?,
                    client_computer = ?, event_record_id = ?, updated_at = ?
                WHERE file_path = ?
                """,
                (
                    PrintStatus.PRINTED.value,
                    now,
                    printer_name,
                    job_document,
                    printed_by,
                    pages,
                    client_computer,
                    event_record_id,
                    _utc_now(),
                    file_path,
                ),
            )
            return cur.rowcount > 0

    def mark_unknown(self, file_path: str, *, job_document: str | None = None) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE pdf_files
                SET status = ?, job_document = ?, updated_at = ?
                WHERE file_path = ? AND status != ?
                """,
                (
                    PrintStatus.UNKNOWN.value,
                    job_document,
                    _utc_now(),
                    file_path,
                    PrintStatus.PRINTED.value,
                ),
            )
            return cur.rowcount > 0

    def reset_status(self, file_path: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE pdf_files
                SET status = ?, printed_at = NULL, printer_name = NULL,
                    job_document = NULL, printed_by = NULL, pages = NULL,
                    client_computer = NULL, event_record_id = NULL,
                    updated_at = ?
                WHERE file_path = ?
                """,
                (PrintStatus.NOT_PRINTED.value, _utc_now(), file_path),
            )

    def list_all(self) -> list[PdfRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM pdf_files ORDER BY file_name COLLATE NOCASE"
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def get_by_path(self, file_path: str) -> PdfRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM pdf_files WHERE file_path = ?", (file_path,)
            ).fetchone()
        return self._row_to_record(row) if row else None

    def log_print_event(
        self,
        *,
        printer_name: str | None,
        job_id: int | None,
        document: str | None,
        matched_path: str | None,
        outcome: str,
        user_name: str | None = None,
        pages: int | None = None,
        event_record_id: int | None = None,
        event_time: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO print_events
                (printer_name, job_id, document, matched_path, outcome,
                 user_name, pages, event_record_id, event_time, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    printer_name,
                    job_id,
                    document,
                    matched_path,
                    outcome,
                    user_name,
                    pages,
                    event_record_id,
                    event_time,
                    _utc_now(),
                ),
            )

    def has_processed_event(self, event_record_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM print_events WHERE event_record_id = ? LIMIT 1",
                (event_record_id,),
            ).fetchone()
        return row is not None

    def has_matched_event(self, event_record_id: int) -> bool:
        """Chỉ true khi Event 307 đã từng khớp thành công với một PDF."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM print_events
                WHERE event_record_id = ? AND outcome = 'matched'
                LIMIT 1
                """,
                (event_record_id,),
            ).fetchone()
        return row is not None

    def list_matched_event_paths(self) -> list[dict]:
        """Các lần khớp thành công đã lưu — dùng khôi phục khi mở lại thư mục."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT matched_path, document, printer_name, user_name,
                       pages, event_record_id, event_time
                FROM print_events
                WHERE outcome = 'matched' AND matched_path IS NOT NULL
                ORDER BY id ASC
                """
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> PdfRecord:
        keys = row.keys()
        return PdfRecord(
            file_path=row["file_path"],
            file_name=row["file_name"],
            file_hash=row["file_hash"],
            status=PrintStatus(row["status"]),
            folder_path=row["folder_path"] if "folder_path" in keys else None,
            printed_at=row["printed_at"],
            printer_name=row["printer_name"],
            job_document=row["job_document"],
            printed_by=row["printed_by"] if "printed_by" in keys else None,
            pages=row["pages"] if "pages" in keys else None,
            client_computer=row["client_computer"] if "client_computer" in keys else None,
            event_record_id=row["event_record_id"] if "event_record_id" in keys else None,
            updated_at=row["updated_at"],
        )
