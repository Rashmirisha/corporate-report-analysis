"""Ingest package: PDF → page-aware chunks + structured tables."""
from .pdf_reader import PdfReadResult, read_pdf
from .chunker import chunk_pages
from .table_extractor import extract_tables
from .pipeline import IngestError, ingest_pdf_bytes

__all__ = [
    "PdfReadResult",
    "read_pdf",
    "chunk_pages",
    "extract_tables",
    "IngestError",
    "ingest_pdf_bytes",
]
