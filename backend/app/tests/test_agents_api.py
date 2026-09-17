"""Stage 2 API tests — exercise /api/agents/* with a stubbed LLM."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _force_stub_env(monkeypatch):
    monkeypatch.setenv("CRA_LLM_STUB", "1")
    yield


@pytest.fixture
def client() -> TestClient:
    # Reset module-level registries without re-importing (which collides
    # with the FastAPI `app` symbol).
    from app.main import app as fastapi_app
    from app.agents import runner as _runner
    from app.storage import store
    store.reset()
    _runner.reset_state("A")
    _runner.reset_state("B")
    return TestClient(fastapi_app)


def _stub_response(company: str, doc: str, sha: str, page: int) -> dict:
    """Produce a valid AgentAnalysis JSON for the stub LLM to return."""
    chunk_ref = f"{company}_{sha[:12]}_p001_c000"
    return {
        "company": company,
        "company_overview": {
            "summary": f"{company} operates in widgets.",
            "evidence": [{
                "company": company, "document_name": doc,
                "document_sha256": sha, "page_number": 1,
                "kind": "chunk", "ref_id": chunk_ref,
                "snippet": "Company operates in widgets.",
            }],
        },
        "financial_performance": {"summary": "Revenue grew.", "key_metrics": [], "evidence": []},
        "operational_information": {"summary": "Ops.", "evidence": []},
        "strategic_information": {"summary": "Strategy.", "evidence": []},
        "business_information": {"summary": "Business.", "evidence": []},
        "strengths": [],
        "weaknesses": [],
        "risks": [],
        "important_observations": [],
    }


def test_run_agents_requires_corpus(client: TestClient, monkeypatch) -> None:
    r = client.post("/api/agents/run", params={"target": "both"})
    assert r.status_code == 400


def test_run_agents_with_stub(client: TestClient, monkeypatch) -> None:
    # Upload Company A and Company B.
    from app.tests._fixtures import build_minimal_pdf_two_pages
    pdf_a = build_minimal_pdf_two_pages("Acme revenue 1200.", "Acme profit 200.")
    pdf_b = build_minimal_pdf_two_pages("Globex revenue 900.", "Globex profit 80.")
    a = client.post("/api/ingest/upload", data={"company": "A"},
                    files={"file": ("Acme.pdf", pdf_a, "application/pdf")}).json()
    b = client.post("/api/ingest/upload", data={"company": "B"},
                    files={"file": ("Globex.pdf", pdf_b, "application/pdf")}).json()

    # Wire the stub to return Company A's payload when user_prompt
    # mentions A's document and Company B's when it mentions B's.
    import app.agents.llm_client as llm_client
    real_make_default = llm_client.make_default_client

    def factory(*, force_stub: bool = False):
        from app.agents.llm_client import StubLLMClient
        s = StubLLMClient()
        s.expect(system_contains="Agent A", user_contains=a["document_name"], response=json.dumps(_stub_response("A", a["document_name"], a["document_sha256"], a["page_count"])))
        s.expect(system_contains="Agent B", user_contains=b["document_name"], response=json.dumps(_stub_response("B", b["document_name"], b["document_sha256"], b["page_count"])))
        return s

    monkeypatch.setattr("app.agents.runner.make_default_client", factory)

    r = client.post("/api/agents/run", params={"target": "both"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["ran"]) == {"A", "B"}

    # Per-company retrieval.
    ra = client.get("/api/agents/A/analysis").json()
    rb = client.get("/api/agents/B/analysis").json()
    assert ra["company"] == "A"
    assert rb["company"] == "B"
    # Cross-company contamination guard.
    assert all(ev["company"] == "A" for ev in ra["company_overview"]["evidence"])
    assert all(ev["company"] == "B" for ev in rb["company_overview"]["evidence"])
    assert all(m["metric"] for m in ra["financial_performance"]["key_metrics"]) or ra["financial_performance"]["key_metrics"] == []
    # A's analysis must not contain B_* ids anywhere.
    blob = json.dumps(ra)
    assert "B_" not in blob
    blob = json.dumps(rb)
    assert "A_" not in blob


def test_get_analysis_404_when_not_run(client: TestClient) -> None:
    r = client.get("/api/agents/A/analysis")
    assert r.status_code == 404


def test_clear_agent_analysis(client: TestClient, monkeypatch) -> None:
    from app.tests._fixtures import build_minimal_pdf_two_pages
    pdf_a = build_minimal_pdf_two_pages("Acme revenue 1200.", "Acme profit 200.")
    a = client.post("/api/ingest/upload", data={"company": "A"},
                    files={"file": ("Acme.pdf", pdf_a, "application/pdf")}).json()

    import app.agents.llm_client as llm_client
    from app.agents.llm_client import StubLLMClient

    def factory(*, force_stub: bool = False):
        s = StubLLMClient()
        s.expect(system_contains="Agent A", user_contains=a["document_name"], response=json.dumps(_stub_response("A", a["document_name"], a["document_sha256"], a["page_count"])))
        return s

    monkeypatch.setattr("app.agents.runner.make_default_client", factory)
    assert client.post("/api/agents/run", params={"target": "A"}).status_code == 200
    assert client.delete("/api/agents/A").status_code == 204
    assert client.get("/api/agents/A/analysis").status_code == 404
