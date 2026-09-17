"""Retriever isolation tests — Agent A must NEVER see Company B chunks/tables."""
from __future__ import annotations

import pytest

from app.retrieval.retriever import Retriever
from app.schemas import CompanyState, SourceMetadata, TableRecord, TextChunk


def _state(company: str, *, n_chunks: int = 3, n_tables: int = 1) -> CompanyState:
    sha = ("a" * 64) if company == "A" else ("b" * 64)
    chunks = [
        TextChunk(
            chunk_id=f"{company}_{sha[:12]}_p{i+1:03d}_c000",
            company=company,  # type: ignore[arg-type]
            document_name=f"{company}_AR.pdf",
            document_sha256=sha,
            page_number=i + 1,
            text=f"{company} chunk text about revenue and growth.",
            char_count=40,
            word_count=8,
        )
        for i in range(n_chunks)
    ]
    tables = [
        TableRecord(
            table_id=f"{company}_{sha[:12]}_p1_t{i+1:03d}",
            company=company,  # type: ignore[arg-type]
            document_name=f"{company}_AR.pdf",
            document_sha256=sha,
            page_number=1,
            table_index=i + 1,
            headers=["Item", "Value"],
            rows=[["Revenue", "1000"], ["Profit", "200"]],
            row_count=2,
            col_count=2,
            preview=f"{company} table {i+1}",
        )
        for i in range(n_tables)
    ]
    return CompanyState(
        company=company,  # type: ignore[arg-type]
        source=SourceMetadata(
            company=company,  # type: ignore[arg-type]
            document_name=f"{company}_AR.pdf",
            document_sha256=sha,
            document_bytes=1024,
            page_count=n_chunks,
        ),
        chunks=chunks,
        tables=tables,
        chunk_count=n_chunks,
        table_count=n_tables,
    )


def test_retriever_company_property() -> None:
    ra = Retriever(_state("A"))
    rb = Retriever(_state("B"))
    assert ra.company == "A"
    assert rb.company == "B"


def test_search_chunks_returns_only_own_company() -> None:
    ra = Retriever(_state("A", n_chunks=4))
    out = ra.search_chunks("revenue growth")
    assert all(h.company == "A" for h in out)


def test_chunk_by_id_rejects_other_company() -> None:
    ra = Retriever(_state("A", n_chunks=2))
    rb = Retriever(_state("B", n_chunks=2))
    # Each retriever can fetch its OWN chunk
    assert ra.chunk_by_id(ra.state.chunks[0].chunk_id) is not None
    # Cross-company access is REFUSED (returns None).
    b_chunk_id = rb.state.chunks[0].chunk_id  # starts with "B_"
    assert ra.chunk_by_id(b_chunk_id) is None


def test_table_by_id_rejects_other_company() -> None:
    ra = Retriever(_state("A"))
    rb = Retriever(_state("B"))
    assert ra.table_by_id(ra.state.tables[0].table_id) is not None
    assert ra.table_by_id(rb.state.tables[0].table_id) is None


def test_evidence_pack_returns_only_own_company() -> None:
    ra = Retriever(_state("A", n_chunks=5, n_tables=2))
    rb = Retriever(_state("B", n_chunks=5, n_tables=2))
    pack_a = ra.evidence_pack(["revenue", "operations", "risks"])
    pack_b = rb.evidence_pack(["revenue", "operations", "risks"])
    assert all(h.company == "A" for h in pack_a)
    assert all(h.company == "B" for h in pack_b)


def test_retriever_isolates_even_when_query_targets_other() -> None:
    """Even an aggressive query can't surface the wrong company's data."""
    ra = Retriever(_state("A", n_chunks=2))
    hits = ra.evidence_pack(["B Globex revenue"], top_k_chunks=10, top_k_tables=10)
    assert all(h.company == "A" for h in hits), "A's retriever must never yield B hits"
