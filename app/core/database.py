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
    UNKNOWN = "unknown"  # Có tín hiệu in nhưng không khớp chắc chắn


@dataclass
class PdfRecord:
    file_path: str
    file_name: str
    file_hash: str
    status: PrintStatus
    printed_at: str | None = None
    printer_name: str | None = None
    job_document: str | None = None
    updated_at: str | None = None


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
                    updated_at  TEXT NOT NULL
                )
                """
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
                    created_at  TEXT NOT NULL
                )
                """
            )

    def upsert_file(
        self,
        file_path: str,
        file_name: str,
        file_hash: str,
        *,
        reset_if_hash_changed: bool = True,
    ) -> PdfRecord:
        """Thêm / cập nhật file. Nếu hash đổi → reset trạng thái in."""
        now = _utc_now()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM pdf_files WHERE file_path = ?", (file_path,)
            ).fetchone()

            if row is None:
                conn.execute(
                    """
                    INSERT INTO pdf_files
                    (file_path, file_name, file_hash, status, printed_at,
                     printer_name, job_document, updated_at)
                    VALUES (?, ?, ?, ?, NULL, NULL, NULL, ?)
                    """,
                    (file_path, file_name, file_hash, PrintStatus.NOT_PRINTED.value, now),
                )
                return PdfRecord(
                    file_path=file_path,
                    file_name=file_name,
                    file_hash=file_hash,
                    status=PrintStatus.NOT_PRINTED,
                    updated_at=now,
                )

            old_hash = row["file_hash"]
            status = PrintStatus(row["status"])
            printed_at = row["printed_at"]
            printer_name = row["printer_name"]
            job_document = row["job_document"]

            if reset_if_hash_changed and old_hash != file_hash:
                status = PrintStatus.NOT_PRINTED
                printed_at = None
                printer_name = None
                job_document = None

            conn.execute(
                """
                UPDATE pdf_files
                SET file_name = ?, file_hash = ?, status = ?,
                    printed_at = ?, printer_name = ?, job_document = ?,
                    updated_at = ?
                WHERE file_path = ?
                """,
                (
                    file_name,
                    file_hash,
                    status.value,
                    printed_at,
                    printer_name,
                    job_document,
                    now,
                    file_path,
                ),
            )
            return PdfRecord(
                file_path=file_path,
                file_name=file_name,
                file_hash=file_hash,
                status=status,
                printed_at=printed_at,
                printer_name=printer_name,
                job_document=job_document,
                updated_at=now,
            )

    def remove_missing(self, existing_paths: set[str]) -> int:
        """Xóa record không còn tồn tại trong thư mục theo dõi."""
        with self._connect() as conn:
            rows = conn.execute("SELECT file_path FROM pdf_files").fetchall()
            to_delete = [r["file_path"] for r in rows if r["file_path"] not in existing_paths]
            for path in to_delete:
                conn.execute("DELETE FROM pdf_files WHERE file_path = ?", (path,))
            return len(to_delete)

    def mark_printed(
        self,
        file_path: str,
        *,
        printer_name: str | None,
        job_document: str | None,
        printed_at: str | None = None,
    ) -> bool:
        now = printed_at or _utc_now()
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE pdf_files
                SET status = ?, printed_at = ?, printer_name = ?,
                    job_document = ?, updated_at = ?
                WHERE file_path = ?
                """,
                (
                    PrintStatus.PRINTED.value,
                    now,
                    printer_name,
                    job_document,
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
                    job_document = NULL, updated_at = ?
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
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO print_events
                (printer_name, job_id, document, matched_path, outcome, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (printer_name, job_id, document, matched_path, outcome, _utc_now()),
            )

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> PdfRecord:
        return PdfRecord(
            file_path=row["file_path"],
            file_name=row["file_name"],
            file_hash=row["file_hash"],
            status=PrintStatus(row["status"]),
            printed_at=row["printed_at"],
            printer_name=row["printer_name"],
            job_document=row["job_document"],
            updated_at=row["updated_at"],
        )
