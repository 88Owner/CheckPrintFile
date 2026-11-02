"""Đối chiếu tên tài liệu Print Job với file PDF trong thư mục.

Ưu tiên độ chính xác: nếu không khớp chắc chắn → không đánh dấu đã in.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


# Hậu tố / tiền tố thường gặp khi ứng dụng gửi lệnh in
_DOC_NOISE_PATTERNS = [
    re.compile(r"\s*[-–—]\s*Adobe\s*(Acrobat|Reader).*", re.IGNORECASE),
    re.compile(r"\s*[-–—]\s*Microsoft\s*Edge.*", re.IGNORECASE),
    re.compile(r"\s*[-–—]\s*Google\s*Chrome.*", re.IGNORECASE),
    re.compile(r"\s*[-–—]\s*Firefox.*", re.IGNORECASE),
    re.compile(r"\s*[-–—]\s*PDF-XChange.*", re.IGNORECASE),
    re.compile(r"\s*[-–—]\s*Foxit.*", re.IGNORECASE),
    re.compile(r"\s*[-–—]\s*SumatraPDF.*", re.IGNORECASE),
    re.compile(r"\s*[-–—]\s*Notepad.*", re.IGNORECASE),
    re.compile(r"^Microsoft\s+Print\s+to\s+PDF\s*[-–—]\s*", re.IGNORECASE),
    re.compile(r"\s*\(\d+\)\s*$"),  # (1), (2) khi in lại
]


@dataclass(frozen=True)
class MatchResult:
    """Kết quả đối chiếu Print Job → PDF."""

    matched_path: str | None
    confidence: str  # exact | basename | cleaned | none | ambiguous
    candidates: tuple[str, ...] = ()


def _normalize(name: str) -> str:
    name = name.strip().lower()
    name = name.replace("/", "\\")
    return name


def _strip_noise(document: str) -> str:
    cleaned = document.strip()
    for pattern in _DOC_NOISE_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    return cleaned.strip()


def _stem_and_name(path_or_name: str) -> tuple[str, str]:
    base = os.path.basename(path_or_name.replace("/", "\\"))
    stem, ext = os.path.splitext(base)
    return _normalize(stem), _normalize(base)


def match_document_to_pdfs(
    document_name: str | None,
    pdf_paths: list[str],
) -> MatchResult:
    """
    Khớp tên tài liệu spooler với danh sách PDF.

    Quy tắc:
    - Khớp đường dẫn đầy đủ hoặc tên file đầy đủ (.pdf) → exact
    - Khớp stem sau khi bỏ nhiễu ứng dụng → cleaned
    - Nhiều file khớp → ambiguous (không đánh dấu đã in)
    - Không khớp → none
    """
    if not document_name or not pdf_paths:
        return MatchResult(None, "none")

    raw = document_name.strip()
    cleaned = _strip_noise(raw)
    doc_stem, doc_base = _stem_and_name(cleaned)
    raw_stem, raw_base = _stem_and_name(raw)

    # Nếu document chứa đường dẫn tuyệt đối trùng một file đang theo dõi
    norm_doc_path = _normalize(cleaned.replace("/", "\\"))
    exact_path_hits = [
        p for p in pdf_paths if _normalize(p) == norm_doc_path
    ]
    if len(exact_path_hits) == 1:
        return MatchResult(exact_path_hits[0], "exact", (exact_path_hits[0],))
    if len(exact_path_hits) > 1:
        return MatchResult(None, "ambiguous", tuple(exact_path_hits))

    by_fullname: list[str] = []
    by_stem: list[str] = []

    for path in pdf_paths:
        stem, base = _stem_and_name(path)
        if base and base in {doc_base, raw_base}:
            by_fullname.append(path)
        elif stem and stem in {doc_stem, raw_stem}:
            by_stem.append(path)

    # Ưu tiên khớp tên đầy đủ có .pdf
    unique_full = list(dict.fromkeys(by_fullname))
    if len(unique_full) == 1:
        return MatchResult(unique_full[0], "basename", (unique_full[0],))
    if len(unique_full) > 1:
        return MatchResult(None, "ambiguous", tuple(unique_full))

    unique_stem = list(dict.fromkeys(by_stem))
    if len(unique_stem) == 1:
        # Chỉ chấp nhận nếu document nhìn giống tên file (có hoặc không .pdf)
        # Tránh khớp nhầm khi stem quá ngắn / chung chung
        if len(doc_stem) < 3 and not cleaned.lower().endswith(".pdf"):
            return MatchResult(None, "none", tuple(unique_stem))
        return MatchResult(unique_stem[0], "cleaned", (unique_stem[0],))
    if len(unique_stem) > 1:
        return MatchResult(None, "ambiguous", tuple(unique_stem))

    return MatchResult(None, "none")


def list_pdfs_in_folder(folder: str | Path) -> list[str]:
    folder_path = Path(folder)
    if not folder_path.is_dir():
        return []
    return sorted(
        str(p.resolve())
        for p in folder_path.iterdir()
        if p.is_file() and p.suffix.lower() == ".pdf"
    )
