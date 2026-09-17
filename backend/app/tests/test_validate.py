"""Validation tests: real PDF, non-PDF, empty PDF, oversized (skip oversized)."""
from __future__ import annotations

import pytest

from app.ingest.pipeline import validate_pdf_bytes, safe_filename
from app.tests._fixtures import build_corrupt_bytes, build_minimal_pdf_two_pages


def test_valid_pdf_bytes_pass() -> None:
    content = build_minimal_pdf_two_pages("Revenue up 12%", "Cash flow strong")
    report = validate_pdf_bytes(content, "Annual Report FY24.pdf", max_bytes=10_000_000)
    assert report.ok, report.reason
    assert report.reason.endswith(".pdf")


def test_non_pdf_bytes_rejected() -> None:
    report = validate_pdf_bytes(build_corrupt_bytes(), "fake.pdf", max_bytes=10_000_000)
    assert not report.ok
    assert "missing %PDF-" in report.reason


def test_empty_bytes_rejected() -> None:
    report = validate_pdf_bytes(b"", "empty.pdf", max_bytes=10_000_000)
    assert not report.ok
    assert "empty" in report.reason


def test_oversized_rejected() -> None:
    content = b"%PDF-" + b"x" * 1024
    report = validate_pdf_bytes(content, "big.pdf", max_bytes=512)
    assert not report.ok
    assert "too large" in report.reason


def test_missing_filename_is_handled() -> None:
    report = validate_pdf_bytes(b"%PDF-fake", None, max_bytes=10_000_000)
    assert report.ok
    assert report.reason.endswith(".pdf")


def test_safe_filename_strips_bad_chars() -> None:
    assert safe_filename("Acme/Annual Report 2024.pdf").endswith(".pdf")
    # No path traversal allowed.
    out = safe_filename("../../etc/passwd.pdf")
    assert "/" not in out
    assert "\\" not in out
    assert out.endswith(".pdf")


@pytest.mark.parametrize(
    "name,expected_ok",
    [
        ("good.pdf", True),
        ("good.PDF", True),  # OK we treat the bytes as authoritative
        ("good.txt", True),  # not validated here; ingest stage renames
    ],
)
def test_safe_filename_always_pdf(name: str, expected_ok: bool) -> None:
    out = safe_filename(name)
    assert out.lower().endswith(".pdf") is expected_ok or out.lower().endswith(".pdf.pdf")
