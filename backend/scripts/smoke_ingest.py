"""Manual smoke test for Stage 1 ingestion.

Run:
    cd backend
    .\.venv\Scripts\python.exe scripts\smoke_ingest.py

It synthesises a tiny 2-page PDF with one page containing a financial-style
table, ingests it as both 'A' and 'B' (with slightly different content), and
prints a human-readable summary. No real annual report is needed.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.ingest.pipeline import ingest_pdf_bytes  # noqa: E402
from app.tests._fixtures import build_minimal_pdf_two_pages  # noqa: E402


def main() -> int:
    uploads = BACKEND_ROOT / "data" / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)

    a_pdf = build_minimal_pdf_two_pages(
        page1_text=(
            "Acme Corp — Annual Report FY24\n\n"
            "Financial Highlights\n"
            "Revenue: 1,200 million\n"
            "Operating profit: 300 million\n"
            "Net profit: 210 million\n"
        ),
        page2_text=(
            "Risk Factors\n"
            "Acme faces currency volatility and supply-chain risks.\n"
        ),
    )
    b_pdf = build_minimal_pdf_two_pages(
        page1_text=(
            "Globex Industries — Annual Report FY24\n\n"
            "Financial Highlights\n"
            "Revenue: 980 million\n"
            "Operating profit: 180 million\n"
            "Net profit: 95 million\n"
        ),
        page2_text=(
            "Risk Factors\n"
            "Globex faces regulatory headwinds and rising input costs.\n"
        ),
    )

    state_a = ingest_pdf_bytes(a_pdf, "A", uploads, document_name="Acme_FY24.pdf")
    state_b = ingest_pdf_bytes(b_pdf, "B", uploads, document_name="Globex_FY24.pdf")

    for s in (state_a, state_b):
        print("=" * 72)
        print(f"Company {s.company} — {s.source.document_name}")
        print(f"  sha256:        {s.source.document_sha256}")
        print(f"  size:          {s.source.document_bytes} bytes")
        print(f"  pages:         {s.source.page_count}")
        print(f"  chunks:        {s.chunk_count}")
        print(f"  tables:        {s.table_count}")
        print("  first 3 chunk ids:")
        for cid in [c.chunk_id for c in s.chunks[:3]]:
            print(f"    - {cid}")
        print("  chunks preview:")
        for c in s.chunks[:2]:
            snippet = c.text[:100].replace("\n", " ")
            print(f"    page {c.page_number} ({c.word_count}w): {snippet!r}")
        if s.tables:
            print("  tables preview:")
            for t in s.tables:
                print(f"    page {t.page_number} #{t.table_index}: {t.preview}")

    # Save a copy of the corpora to a JSON file for inspection.
    import json

    out = BACKEND_ROOT / "data" / "smoke_corpus.json"
    out.write_text(
        json.dumps(
            {
                "A": state_a.model_dump(),
                "B": state_b.model_dump(),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    print()
    print(f"Full corpus dumped to: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
