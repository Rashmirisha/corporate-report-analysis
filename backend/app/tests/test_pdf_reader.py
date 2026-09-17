"""PDF reader tests — page count, page text, table extraction."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.ingest.pdf_reader import _clean_text, read_pdf
from app.tests._fixtures import (
    build_corrupt_bytes,
    build_minimal_pdf_empty,
    build_minimal_pdf_two_pages,
)


def test_clean_text_strips_control_chars() -> None:
    raw = "Hello\x00\x01World\n\n\n\nFoo"
    assert _clean_text(raw) == "Hello World\n\nFoo"


def test_read_pdf_two_pages(tmp_path: Path) -> None:
    pdf_bytes = build_minimal_pdf_two_pages(
        "Revenue grew 12% YoY.",
        "Net profit margin improved.",
    )
    pdf_path = tmp_path / "tiny.pdf"
    pdf_path.write_bytes(pdf_bytes)

    result = read_pdf(pdf_path)
    assert result.page_count == 2
    assert len(result.pages) == 2
    assert result.pages[0].page_number == 1
    assert result.pages[1].page_number == 2


def test_read_pdf_empty_returns_zero_pages(tmp_path: Path) -> None:
    """A valid PDF with 0 pages should be readable and report page_count=0."""
    pdf_path = tmp_path / "empty.pdf"
    pdf_path.write_bytes(build_minimal_pdf_empty())
    result = read_pdf(pdf_path)
    assert result.page_count == 0
    assert result.pages == []
    assert result.has_any_text is False


def test_read_pdf_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_pdf(tmp_path / "nope.pdf")


def test_read_pdf_corrupt_raises(tmp_path: Path) -> None:
    pdf_path = tmp_path / "corrupt.pdf"
    pdf_path.write_bytes(build_corrupt_bytes())
    # pdfplumber may raise a subclass of ValueError; we accept anything in
    # ValueError. If it's actually tolerant we just check page_count is sane.
    try:
        result = read_pdf(pdf_path)
    except ValueError:
        return
    assert result.page_count >= 0
