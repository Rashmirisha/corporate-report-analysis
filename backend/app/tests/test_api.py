"""API tests using FastAPI's TestClient (no running server required)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.storage import store
from app.tests._fixtures import build_minimal_pdf_two_pages


client = TestClient(app)


def setup_module(_module):
    store.reset()


def teardown_function(_func):
    store.reset()


def test_health() -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["stage"] == 1


def test_upload_company_a_then_b() -> None:
    pdf_a = build_minimal_pdf_two_pages("Acme FY24 revenue grew.", "Acme FY24 profit improved.")
    pdf_b = build_minimal_pdf_two_pages("Globex FY24 revenue fell.", "Globex FY24 profit declined.")

    r1 = client.post(
        "/api/ingest/upload",
        data={"company": "A"},
        files={"file": ("Acme.pdf", pdf_a, "application/pdf")},
    )
    assert r1.status_code == 200, r1.text
    body_a = r1.json()
    assert body_a["company"] == "A"
    assert body_a["page_count"] == 2
    assert body_a["chunk_count"] >= 1
    assert body_a["sample_chunk_ids"]

    r2 = client.post(
        "/api/ingest/upload",
        data={"company": "B"},
        files={"file": ("Globex.pdf", pdf_b, "application/pdf")},
    )
    assert r2.status_code == 200, r2.text

    # Corpus now ready, both sides populated.
    r3 = client.get("/api/corpus")
    assert r3.status_code == 200
    body3 = r3.json()
    assert body3["ready"] is True
    assert body3["state_a"] is not None
    assert body3["state_b"] is not None


def test_upload_invalid_company() -> None:
    pdf = build_minimal_pdf_two_pages("x", "y")
    r = client.post(
        "/api/ingest/upload",
        data={"company": "Z"},
        files={"file": ("x.pdf", pdf, "application/pdf")},
    )
    # FastAPI returns 422 for bad Literal fields; we also accept 400 from
    # our own validator if the constraint is ever loosened. Either is fine —
    # what matters is the upload is REJECTED.
    assert r.status_code in (400, 422)


def test_upload_non_pdf() -> None:
    r = client.post(
        "/api/ingest/upload",
        data={"company": "A"},
        files={"file": ("x.pdf", b"%PDF- but the body is not really a pdf", "application/pdf")},
    )
    # Either 400 (validation) or 400 from pdfplumber failing to parse; either
    # way the API must NOT return 200.
    assert r.status_code == 400, r.text


def test_get_company_corpus_404_when_missing() -> None:
    r = client.get("/api/corpus/A")
    assert r.status_code == 404
