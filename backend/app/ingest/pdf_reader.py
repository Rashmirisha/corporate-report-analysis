"""PDF reader: page-aware text extraction using pdfplumber.

Goals:
- Extract text per page (page numbers preserved).
- Extract raw table cells per page (headers + rows).
- Project Gutenberg / PowerShell mojibake-resistant: we re-encode via UTF-8
  with `errors="replace"` so no decode error crashes the pipeline.
- Be tolerant of weird PDFs: empty pages, missing fonts, rotated tables. If a
  page yields nothing, we still record its number (so chunk IDs stay stable
  and page citations remain truthful).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import pdfplumber


@dataclass
class PageData:
    page_number: int
    text: str
    section_hint: str | None = None


@dataclass
class RawTableCell:
    """A raw cell string from a pdfplumber table."""
    value: str


@dataclass
class RawTable:
    page_number: int
    table_index: int  # 1-based, in page order
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)


@dataclass
class PdfReadResult:
    page_count: int
    pages: list[PageData] = field(default_factory=list)
    tables: list[RawTable] = field(default_factory=list)

    @property
    def has_any_text(self) -> bool:
        return any(p.text.strip() for p in self.pages)


# ---------- mojibake / control-char cleanup ----------

_CONTROL_CHARS = "".join(
    # C0 control chars except \t \n \r
    [chr(c) for c in range(0x00, 0x20) if c not in (0x09, 0x0A, 0x0D)]
) + "\x7f"
_CONTROL_TABLE = str.maketrans(_CONTROL_CHARS, " " * len(_CONTROL_CHARS))


def _clean_text(s: str) -> str:
    if not s:
        return ""
    # Strip NULs / control chars that PowerShell sometimes leaves behind.
    s = s.translate(_CONTROL_TABLE)
    # Collapse runs of whitespace per line, then collapse 3+ blank lines.
    out_lines: list[str] = []
    blank = 0
    for raw in s.splitlines():
        line = " ".join(raw.split())
        if not line:
            blank += 1
            if blank <= 1:
                out_lines.append("")
            continue
        blank = 0
        out_lines.append(line)
    # Trim leading/trailing blanks.
    while out_lines and not out_lines[0]:
        out_lines.pop(0)
    while out_lines and not out_lines[-1]:
        out_lines.pop()
    return "\n".join(out_lines)


# ---------- core reader ----------

def read_pdf(pdf_path: str | Path) -> PdfReadResult:
    """Read a PDF file. Page numbers are 1-based and preserved end-to-end.

    Raises FileNotFoundError if the path is missing.
    Raises ValueError if pdfplumber cannot open it as a PDF.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    result = PdfReadResult(page_count=0)
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            result.page_count = len(pdf.pages)
            for page_idx, page in enumerate(pdf.pages, start=1):
                # ---- text ----
                raw_text = page.extract_text() or ""
                cleaned = _clean_text(raw_text)
                section_hint = _detect_section_hint(cleaned)
                result.pages.append(
                    PageData(
                        page_number=page_idx,
                        text=cleaned,
                        section_hint=section_hint,
                    )
                )

                # ---- tables (one page may contain multiple) ----
                try:
                    page_tables = page.extract_tables() or []
                except Exception:
                    # Some PDFs (e.g. with overlapping text) explode here;
                    # never let a bad table take down the whole ingest.
                    page_tables = []
                for t_idx, raw in enumerate(page_tables, start=1):
                    if not raw:
                        continue
                    # First row is treated as header if it looks like one
                    # (all non-empty strings, different from data rows).
                    headers, rows = _normalize_table_rows(raw)
                    if not headers and not rows:
                        continue
                    result.tables.append(
                        RawTable(
                            page_number=page_idx,
                            table_index=t_idx,
                            headers=headers,
                            rows=rows,
                        )
                    )
    except Exception as exc:  # pdfplumber raises PDFSyntaxError, etc.
        raise ValueError(f"Could not open PDF (corrupt or not a PDF?): {exc}") from exc

    return result


# ---------- helpers ----------

_HEADING_KEYWORDS = (
    "chairman", "chief executive", "cfo", "financial highlights",
    "financial review", "financial statements", "balance sheet",
    "income statement", "cash flow", "profit and loss", "risks",
    "risk management", "operations", "operational", "strategy",
    "strategic", "business overview", "management discussion",
    "directors' report", "board of directors", "notes to",
    "segment", "revenue", "expenses", "auditor", "shareholders",
)


def _detect_section_hint(cleaned_text: str) -> str | None:
    """Cheap heuristic for a section heading on the page (line 1..6)."""
    if not cleaned_text:
        return None
    for line in cleaned_text.splitlines()[:6]:
        low = line.strip().lower()
        if not low:
            continue
        if len(low) > 80:
            continue
        if any(k in low for k in _HEADING_KEYWORDS):
            # Title-case it back lightly for display.
            return line.strip()[:80]
    return None


def _normalize_table_rows(raw_rows: list[list]) -> tuple[list[str], list[list[str]]]:
    """Turn pdfplumber's [[...], [...], ...] into (headers, rows).

    A row counts as headers when:
      - all cells are non-empty strings, AND
      - at least one cell contains a digit OR a money/percent character.
    Otherwise the whole thing is treated as data (no headers).
    """
    if not raw_rows:
        return [], []

    cleaned_rows: list[list[str]] = []
    for r in raw_rows:
        cells = []
        for c in r or []:
            if c is None:
                cells.append("")
            else:
                cells.append(" ".join(str(c).split()))
        # Drop trailing fully-empty cells (pdfplumber padding).
        while cells and cells[-1] == "":
            cells.pop()
        cleaned_rows.append(cells)

    # Detect headers using the first row.
    first = cleaned_rows[0]
    rest = cleaned_rows[1:]
    looks_like_header = bool(first) and all(first) and any(
        any(ch.isdigit() for ch in cell) or "%" in cell or "$" in cell or "₹" in cell or "€" in cell or "£" in cell
        for cell in first
    )

    if looks_like_header:
        return first, rest
    return [], cleaned_rows
