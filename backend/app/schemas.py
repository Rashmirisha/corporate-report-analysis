"""Pydantic schemas for Stage 1 ingestion.

These types are the public contract for every downstream stage. Stage 2 agents
must cite `chunk_id` / `page_number` from these objects — that's how the
"no hallucinated numbers" rule is enforced across stages.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

Company = Literal["A", "B"]


# ---------- Metadata / evidence ----------

class SourceMetadata(BaseModel):
    """Describes the source PDF that a chunk/table came from."""
    company: Company
    document_name: str = Field(..., description="Original uploaded file name.")
    document_sha256: str = Field(..., description="SHA-256 of the saved PDF bytes.")
    document_bytes: int = Field(..., description="Size of the saved PDF in bytes.")
    page_count: int = Field(..., ge=0)


# ---------- Text chunks ----------

class TextChunk(BaseModel):
    """A page-bounded slice of cleaned PDF text."""
    chunk_id: str = Field(..., description="Stable id: {company}_{sha_prefix}_{page:>03}_c{idx:>03}")
    company: Company
    document_name: str
    document_sha256: str
    page_number: int = Field(..., ge=1)
    section: Optional[str] = Field(
        None,
        description="Best-effort section heading (taken from preceding heading on the page).",
    )
    text: str = Field(..., description="Cleaned, page-bounded text.")
    char_count: int = Field(..., ge=0)
    word_count: int = Field(..., ge=0)


# ---------- Tables ----------

class TableRecord(BaseModel):
    """A single table extracted from a PDF page."""
    table_id: str = Field(..., description="Stable id: {company}_{sha_prefix}_p{page:>03}_t{idx:>03}")
    company: Company
    document_name: str
    document_sha256: str
    page_number: int = Field(..., ge=1)
    table_index: int = Field(..., ge=1, description="1-based index of this table on its page.")
    headers: List[str] = Field(default_factory=list)
    rows: List[List[str]] = Field(default_factory=list)
    row_count: int = Field(..., ge=0)
    col_count: int = Field(..., ge=0)
    preview: str = Field(..., description="Short text preview of the table for UI display.")


# ---------- Company state ----------

class CompanyState(BaseModel):
    """All extracted evidence for a single company."""
    company: Company
    source: SourceMetadata
    chunks: List[TextChunk] = Field(default_factory=list)
    tables: List[TableRecord] = Field(default_factory=list)
    chunk_count: int = Field(..., ge=0)
    table_count: int = Field(..., ge=0)

    def chunk_by_id(self, chunk_id: str) -> Optional[TextChunk]:
        for c in self.chunks:
            if c.chunk_id == chunk_id:
                return c
        return None

    def table_by_id(self, table_id: str) -> Optional[TableRecord]:
        for t in self.tables:
            if t.table_id == table_id:
                return t
        return None


class Corpus(BaseModel):
    """Stage-1 output. Two disjoint CompanyState blobs (no cross-contamination)."""
    state_a: Optional[CompanyState] = None
    state_b: Optional[CompanyState] = None

    def has_both(self) -> bool:
        return self.state_a is not None and self.state_b is not None

    def total_chunks(self) -> int:
        return sum((s.chunk_count if s else 0) for s in (self.state_a, self.state_b))

    def total_tables(self) -> int:
        return sum((s.table_count if s else 0) for s in (self.state_a, self.state_b))


# ---------- API I/O ----------

class UploadResponse(BaseModel):
    company: Company
    document_name: str
    document_sha256: str
    document_bytes: int
    page_count: int
    chunk_count: int
    table_count: int
    sample_chunk_ids: List[str] = Field(default_factory=list)
    sample_table_ids: List[str] = Field(default_factory=list)


class CorpusResponse(BaseModel):
    ready: bool
    state_a: Optional[CompanyState] = None
    state_b: Optional[CompanyState] = None


class HealthResponse(BaseModel):
    status: Literal["ok"]
    stage: int
    version: str
