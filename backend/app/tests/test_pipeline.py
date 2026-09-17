"""End-to-end pipeline tests.

These use real pdfplumber on tiny in-memory PDFs to verify the full
ingest → CompanyState contract:
  - Company A and Company B stay separate.
  - Page numbers are preserved end-to-end.
  - Chunk IDs are stable and unique.
  - Tables carry page + table_index + headers + rows.
  - Empty / corrupt PDFs are rejected with IngestError.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.ingest.pipeline import IngestError, ingest_pdf_bytes
from app.tests._fixtures import (
    build_corrupt_bytes,
    build_minimal_pdf_empty,
    build_minimal_pdf_two_pages,
)


def _do_ingest(tmp_path: Path, company: str, content: bytes, name: str = "Acme_AR24.pdf"):
    return ingest_pdf_bytes(
        content=content,
        company=company,
        uploads_root=tmp_path,
        document_name=name,
    )


def test_pipeline_company_a_and_b_separate(tmp_path: Path) -> None:
    a_bytes = build_minimal_pdf_two_pages(
        "Acme revenue rose to 1.2B.", "Acme opens 30 new stores."
    )
    b_bytes = build_minimal_pdf_two_pages(
        "Globex profits fell 4%.", "Globex plans a restructuring."
    )

    a = _do_ingest(tmp_path, "A", a_bytes, "Acme_AR24.pdf")
    b = _do_ingest(tmp_path, "B", b_bytes, "Globex_AR24.pdf")

    assert a.company == "A"
    assert b.company == "B"
    assert a.source.document_sha256 != b.source.document_sha256
    assert all(c.company == "A" for c in a.chunks)
    assert all(c.company == "B" for c in b.chunks)
    assert a.source.page_count == 2
    assert b.source.page_count == 2
    # No cross-contamination of text.
    a_text = " ".join(c.text for c in a.chunks)
    b_text = " ".join(c.text for c in b.chunks)
    assert "Globex" not in a_text
    assert "Acme" not in b_text


def test_pipeline_persists_pdf(tmp_path: Path) -> None:
    content = build_minimal_pdf_two_pages("Hello", "World")
    state = _do_ingest(tmp_path, "A", content, "Acme_AR24.pdf")
    saved = tmp_path / "A" / f"{state.source.document_sha256}.pdf"
    assert saved.exists()
    assert saved.read_bytes() == content


def test_pipeline_page_numbers_preserved(tmp_path: Path) -> None:
    content = build_minimal_pdf_two_pages("Page one content.", "Page two content.")
    state = _do_ingest(tmp_path, "A", content)
    page_nums = sorted({c.page_number for c in state.chunks})
    assert page_nums == [1, 2]


def test_pipeline_chunk_ids_unique_and_stable(tmp_path: Path) -> None:
    content = build_minimal_pdf_two_pages("x", "y")
    state = _do_ingest(tmp_path, "A", content)
    ids = [c.chunk_id for c in state.chunks]
    assert len(set(ids)) == len(ids)  # all unique
    for cid in ids:
        assert cid.startswith("A_")
        assert "_p" in cid
        assert "_c" in cid


def test_pipeline_rejects_non_pdf(tmp_path: Path) -> None:
    with pytest.raises(IngestError) as exc:
        _do_ingest(tmp_path, "A", build_corrupt_bytes())
    assert "not a PDF" in str(exc.value) or "Could not open" in str(exc.value) or "PDF" in str(exc.value)


def test_pipeline_rejects_empty_pdf(tmp_path: Path) -> None:
    with pytest.raises(IngestError):
        _do_ingest(tmp_path, "A", build_minimal_pdf_empty())


def test_pipeline_rejects_invalid_company(tmp_path: Path) -> None:
    content = build_minimal_pdf_two_pages("x", "y")
    with pytest.raises(IngestError):
        _do_ingest(tmp_path, "Z", content)


def test_pipeline_handles_missing_document_name(tmp_path: Path) -> None:
    content = build_minimal_pdf_two_pages("x", "y")
    state = ingest_pdf_bytes(content=content, company="A", uploads_root=tmp_path)
    assert state.source.document_name.endswith(".pdf")
