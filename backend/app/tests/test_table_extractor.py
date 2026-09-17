"""Table extractor tests (no PDF needed — uses RawTable fixtures)."""
from __future__ import annotations

from app.ingest.pdf_reader import RawTable
from app.ingest.table_extractor import extract_tables


def test_extract_tables_emits_metadata() -> None:
    raw = [
        RawTable(
            page_number=4,
            table_index=1,
            headers=["Revenue", "FY24", "FY23"],
            rows=[
                ["Total revenue", "1200", "1100"],
                ["Operating profit", "300", "250"],
            ],
        )
    ]
    out = extract_tables(raw)
    assert len(out) == 1
    t = out[0]
    assert t["page_number"] == 4
    assert t["table_index"] == 1
    assert t["row_count"] == 2
    assert t["col_count"] == 3
    assert "Revenue" in t["preview"]
    assert "1200" in t["preview"]


def test_extract_tables_drops_empty_tables() -> None:
    raw = [RawTable(page_number=1, table_index=1, headers=[], rows=[])]
    assert extract_tables(raw) == []


def test_extract_tables_preview_truncates() -> None:
    rows = [["row " * 30 + str(i)] for i in range(20)]
    raw = [RawTable(page_number=1, table_index=1, headers=[], rows=rows)]
    [t] = extract_tables(raw)
    assert len(t["preview"]) <= 240
    assert t["preview"].endswith("…")
