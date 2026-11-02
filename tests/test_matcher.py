"""Kiểm tra đối chiếu tên Print Job ↔ PDF."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.matcher import match_document_to_pdfs


def test_exact_basename():
    pdfs = [r"C:\docs\hoa_don_01.pdf", r"C:\docs\hoa_don_02.pdf"]
    r = match_document_to_pdfs("hoa_don_01.pdf", pdfs)
    assert r.matched_path == pdfs[0]
    assert r.confidence == "basename"


def test_adobe_suffix():
    pdfs = [r"C:\docs\report.pdf"]
    r = match_document_to_pdfs("report.pdf - Adobe Acrobat Reader", pdfs)
    assert r.matched_path == pdfs[0]
    assert r.confidence in {"basename", "cleaned"}


def test_ambiguous_same_stem_elsewhere():
    pdfs = [r"C:\a\invoice.pdf", r"C:\b\invoice.pdf"]
    r = match_document_to_pdfs("invoice.pdf", pdfs)
    assert r.matched_path is None
    assert r.confidence == "ambiguous"


def test_unmatched():
    pdfs = [r"C:\docs\a.pdf"]
    r = match_document_to_pdfs("something_else.pdf", pdfs)
    assert r.matched_path is None
    assert r.confidence == "none"


def test_full_path_exact():
    pdfs = [r"C:\docs\a.pdf"]
    r = match_document_to_pdfs(r"C:\docs\a.pdf", pdfs)
    assert r.matched_path == pdfs[0]
    assert r.confidence == "exact"


if __name__ == "__main__":
    test_exact_basename()
    test_adobe_suffix()
    test_ambiguous_same_stem_elsewhere()
    test_unmatched()
    test_full_path_exact()
    print("OK: matcher tests passed")
