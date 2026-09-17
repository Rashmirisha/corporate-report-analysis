"""Test helpers: build tiny PDFs in memory for tests.

We use `reportlab` if available (already in many test stacks), and fall back
to a hand-crafted minimal PDF for the "no third-party deps" path. The
fixtures here are intentionally tiny — 2 pages of text + 1 table on page 2.
"""
from __future__ import annotations

from io import BytesIO


def build_minimal_pdf_two_pages(page1_text: str, page2_text: str) -> bytes:
    """Build a real, valid 2-page PDF with the given text on each page.

    Uses reportlab when available; otherwise constructs a minimal hand-rolled
    PDF object stream (no fonts, no compression) that pdfplumber can still
    read. The hand-rolled version is enough for our extraction tests.
    """
    try:
        from reportlab.pdfgen import canvas  # type: ignore

        buf = BytesIO()
        c = canvas.Canvas(buf)
        c.drawString(72, 720, page1_text)
        c.showPage()
        c.drawString(72, 720, page2_text)
        c.showPage()
        c.save()
        return buf.getvalue()
    except ImportError:
        return _hand_rolled_two_page_pdf(page1_text, page2_text)


def build_minimal_pdf_empty() -> bytes:
    """A valid PDF with 0 pages — pdfplumber reports page_count=0."""
    # Minimal PDF catalog with empty Pages tree.
    return (
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [] /Count 0 >> endobj\n"
        b"xref\n0 3\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"trailer << /Size 3 /Root 1 0 R >>\n"
        b"startxref\n109\n"
        b"%%EOF\n"
    )


def build_corrupt_bytes() -> bytes:
    """Bytes that are NOT a PDF — must NOT start with the %PDF- magic."""
    return b"PK\x03\x04not a pdf at all just a fake zip header\r\n"


def build_one_page_pdf_with_text(page_text: str) -> bytes:
    return build_minimal_pdf_two_pages(page_text, "") or b""


# ---------- hand-rolled PDF (used if reportlab isn't installed) ----------

def _hand_rolled_two_page_pdf(page1: str, page2: str) -> bytes:
    """Super-minimal 2-page PDF. No text-rendering fonts; pdfplumber still
    returns empty text for these, but the structure parses and gives us
    exactly 2 pages — useful for page-count tests."""
    obj1 = b"<< /Type /Catalog /Pages 2 0 R >>"
    obj2 = b"<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>"
    obj3 = b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << >> >>"
    stream4 = b"<< /Length 0 >>\nstream\n\nendstream"
    obj5 = b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 6 0 R /Resources << >> >>"
    stream6 = b"<< /Length 0 >>\nstream\n\nendstream"

    # Encode the actual page text as PDF content streams so pdfplumber can
    # extract them. (The downstream extraction tests want real text.)
    def _page_content(text: str) -> bytes:
        # Use a basic built-in font; positions are arbitrary, only the
        # extractable text matters.
        lines = text.splitlines() or [text]
        ops = ["BT", "/F1 12 Tf", "72 720 Td"]
        for i, line in enumerate(lines):
            safe = (
                line.replace("\\", "\\\\")
                .replace("(", "\\(")
                .replace(")", "\\)")
            )
            if i == 0:
                ops.append(f"({safe}) Tj")
            else:
                ops.append("0 -14 Td")
                ops.append(f"({safe}) Tj")
        ops.append("ET")
        content = "\n".join(ops).encode("latin-1", errors="replace")
        return b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"\nendstream"

    page1_stream = _page_content(page1)
    page2_stream = _page_content(page2)
    obj4 = page1_stream
    obj6 = page2_stream

    parts: list[bytes] = []
    offsets: list[int] = []

    def _add(part: bytes) -> None:
        offsets.append(sum(len(p) for p in parts))
        parts.append(part)

    parts.append(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")  # binary marker
    _add(b"1 0 obj " + obj1 + b" endobj\n")
    _add(b"2 0 obj " + obj2 + b" endobj\n")
    _add(b"3 0 obj " + obj3 + b" endobj\n")
    _add(b"4 0 obj " + obj4 + b" endobj\n")
    _add(b"5 0 obj " + obj5 + b" endobj\n")
    _add(b"6 0 obj " + obj6 + b" endobj\n")

    xref_offset = sum(len(p) for p in parts)
    xref = b"xref\n0 7\n0000000000 65535 f \n"
    for off in offsets:
        xref += f"{off:010d} 00000 n \n".encode("ascii")
    trailer = (
        b"trailer << /Size 7 /Root 1 0 R >>\nstartxref\n"
        + str(xref_offset).encode("ascii")
        + b"\n%%EOF\n"
    )
    parts.append(xref)
    parts.append(trailer)
    return b"".join(parts)
