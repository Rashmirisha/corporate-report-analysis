"""Chunker tests: page-boundary preservation, target word size, IDs."""
from __future__ import annotations

from app.ingest.chunker import chunk_pages
from app.ingest.pdf_reader import PageData


def _page(n: int, text: str, section: str | None = None) -> PageData:
    return PageData(page_number=n, text=text, section_hint=section)


def test_empty_page_yields_no_chunks() -> None:
    chunks = chunk_pages([_page(1, ""), _page(2, "")])
    assert chunks == []


def test_chunk_ids_carry_page_number() -> None:
    page_text = " ".join(f"word{i}" for i in range(600))
    chunks = chunk_pages([_page(7, page_text)])
    assert chunks, "expected at least one chunk"
    for c in chunks:
        assert c["page_number"] == 7


def test_chunker_never_crosses_page_boundary() -> None:
    chunks = chunk_pages(
        [
            _page(1, " ".join(f"a{i}" for i in range(300))),
            _page(2, " ".join(f"b{i}" for i in range(300))),
        ]
    )
    seen_pages = sorted({c["page_number"] for c in chunks})
    assert seen_pages == [1, 2]


def test_chunker_handles_long_page() -> None:
    page_text = " ".join(f"w{i}" for i in range(1500))
    chunks = chunk_pages([_page(1, page_text)])
    # Roughly 1500 / 220 ≈ 7 chunks. Allow a wide band; we only assert
    # it's more than one and each chunk fits HARD_MAX_WORDS.
    assert len(chunks) > 1
    for c in chunks:
        assert c["word_count"] <= 380


def test_chunker_section_hint_propagates() -> None:
    chunks = chunk_pages([_page(3, "Some report text here", section="Financial Highlights")])
    assert chunks[0]["section"] == "Financial Highlights"
