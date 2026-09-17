"""Structured table extraction.

`pdf_reader.read_pdf` already returns normalized table cells. This module
just reshapes them into dicts that the pipeline converts to TableRecord.

Why a separate module?
- It gives us a clean place to add row-level column typing later
  (e.g. mark numeric columns for Stage 2 numeric comparison) without
  touching pdf_reader.py.
- It isolates the "table → JSON" contract so every table in the corpus
  has a guaranteed preview string for the dashboard.
"""
from __future__ import annotations

from typing import List

from app.ingest.pdf_reader import RawTable


def _preview(headers: List[str], rows: List[List[str]], max_chars: int = 240) -> str:
    parts: List[str] = []
    if headers:
        parts.append(" | ".join(headers))
    for r in rows[:3]:
        parts.append(" | ".join(r))
    s = "  ‖  ".join(parts)
    if len(s) > max_chars:
        s = s[: max_chars - 1] + "…"
    return s


def extract_tables(raw_tables: List[RawTable]) -> List[dict]:
    out: List[dict] = []
    for t in raw_tables:
        headers = t.headers
        rows = t.rows
        col_count = max((len(r) for r in rows), default=0)
        if headers:
            col_count = max(col_count, len(headers))
        if col_count == 0:
            continue
        out.append(
            {
                "page_number": t.page_number,
                "table_index": t.table_index,
                "headers": headers,
                "rows": rows,
                "row_count": len(rows),
                "col_count": col_count,
                "preview": _preview(headers, rows),
            }
        )
    return out
