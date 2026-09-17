"""End-to-end ingestion: PDF bytes → CompanyState.

Validates, persists the original PDF, runs extraction, and returns the
Stage-1 record. The on-disk layout is:

    backend/data/uploads/<company>/<sha256>.pdf

Storing under the SHA-256 hash makes the upload idempotent (same PDF twice
= same file, same chunks) and avoids filename collisions.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

from app.ingest.chunker import chunk_pages
from app.ingest.pdf_reader import read_pdf, _clean_text
from app.ingest.table_extractor import extract_tables
from app.schemas import (
    CompanyState,
    SourceMetadata,
    TableRecord,
    TextChunk,
)


class IngestError(ValueError):
    """Raised for any user-facing ingestion failure (bad file, empty PDF, etc.)."""


# ---------- Validation ----------

# PDFs always start with "%PDF-" — cheap magic-byte check.
_PDF_MAGIC = b"%PDF-"
_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass
class ValidationReport:
    ok: bool
    reason: str = ""


def validate_pdf_bytes(content: bytes, filename: str | None, max_bytes: int) -> ValidationReport:
    if not content:
        return ValidationReport(False, "empty file")
    if len(content) > max_bytes:
        return ValidationReport(False, f"file too large (>{max_bytes} bytes)")
    if not content.startswith(_PDF_MAGIC):
        return ValidationReport(False, "not a PDF (missing %PDF- header)")
    if filename:
        safe = _FILENAME_SAFE.sub("_", filename).strip("._") or "report.pdf"
        if not safe.lower().endswith(".pdf"):
            safe = safe + ".pdf"
    else:
        safe = "report.pdf"
    return ValidationReport(True, safe)


def safe_filename(filename: str | None) -> str:
    if not filename:
        return "report.pdf"
    safe = _FILENAME_SAFE.sub("_", filename).strip("._") or "report.pdf"
    if not safe.lower().endswith(".pdf"):
        safe = safe + ".pdf"
    return safe


# ---------- Pipeline ----------

def _hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def persist_pdf(content: bytes, uploads_root: Path, company: str, sha256_hex: str, filename: str) -> Path:
    """Write the PDF under <uploads_root>/<company>/<sha256>.pdf (atomic-ish)."""
    target_dir = uploads_root / company
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{sha256_hex}.pdf"
    if not target.exists():
        # write to temp then rename — atomic on the same volume
        tmp = target.with_suffix(".pdf.tmp")
        tmp.write_bytes(content)
        os.replace(tmp, target)
    return target


def ingest_pdf_bytes(
    content: bytes,
    company: str,
    uploads_root: Path,
    *,
    document_name: str | None = None,
) -> CompanyState:
    """Top-level ingest: bytes in, CompanyState out."""
    company = _normalize_company(company)

    max_bytes = int(os.environ.get("CRA_MAX_UPLOAD_BYTES", str(60 * 1024 * 1024)))  # 60 MiB
    report = validate_pdf_bytes(content, document_name, max_bytes)
    if not report.ok:
        raise IngestError(f"invalid PDF: {report.reason}")

    sha = _hash(content)
    safe_name = safe_filename(document_name or f"{company}_report.pdf")
    pdf_path = persist_pdf(content, uploads_root, company, sha, safe_name)

    try:
        read_result = read_pdf(pdf_path)
    except FileNotFoundError as exc:
        raise IngestError(f"could not read saved PDF: {exc}") from exc
    except ValueError as exc:
        raise IngestError(str(exc)) from exc

    if read_result.page_count == 0:
        raise IngestError("PDF has 0 pages — nothing to extract")
    if not read_result.has_any_text and not read_result.tables:
        # Text-only PDFs (image scans) are out of scope for Stage 1.
        raise IngestError(
            "PDF appears to be empty or scanned (no extractable text or tables). "
            "Stage 1 requires a text-based PDF; OCR is planned for a later stage."
        )

    # ----- chunks -----
    raw_chunks = chunk_pages(read_result.pages)
    sha_prefix = sha[:12]
    chunks: list[TextChunk] = []
    for c in raw_chunks:
        local_idx = c.pop("_page_local_index", 0)
        chunks.append(
            TextChunk(
                chunk_id=f"{company}_{sha_prefix}_p{c['page_number']:03d}_c{local_idx:03d}",
                company=company,
                document_name=safe_name,
                document_sha256=sha,
                page_number=c["page_number"],
                section=c["section"],
                text=c["text"],
                char_count=c["char_count"],
                word_count=c["word_count"],
            )
        )

    # ----- tables -----
    raw_tables = extract_tables(read_result.tables)
    tables: list[TableRecord] = []
    for t in raw_tables:
        tables.append(
            TableRecord(
                table_id=f"{company}_{sha_prefix}_p{t['page_number']:03d}_t{t['table_index']:03d}",
                company=company,
                document_name=safe_name,
                document_sha256=sha,
                page_number=t["page_number"],
                table_index=t["table_index"],
                headers=t["headers"],
                rows=t["rows"],
                row_count=t["row_count"],
                col_count=t["col_count"],
                preview=t["preview"],
            )
        )

    source = SourceMetadata(
        company=company,
        document_name=safe_name,
        document_sha256=sha,
        document_bytes=len(content),
        page_count=read_result.page_count,
    )

    return CompanyState(
        company=company,
        source=source,
        chunks=chunks,
        tables=tables,
        chunk_count=len(chunks),
        table_count=len(tables),
    )


def _normalize_company(c: str | None) -> str:
    if c is None:
        raise IngestError("company is required ('A' or 'B')")
    s = str(c).strip().upper()
    if s not in ("A", "B"):
        raise IngestError(f"company must be 'A' or 'B' (got {c!r})")
    return s
