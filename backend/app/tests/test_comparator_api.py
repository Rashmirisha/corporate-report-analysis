"""Stage 3 API tests — exercise /api/comparison/* with stubbed agents."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _force_stub(monkeypatch):
    monkeypatch.setenv("CRA_LLM_STUB", "1")
    yield


@pytest.fixture
def client() -> TestClient:
    from app.main import app
    from app.agents import runner as _runner
    from app.storage import store
    from app.comparator import runner as _comp

    store.reset()
    _runner.reset_state("A")
    _runner.reset_state("B")
    _comp.reset_comparison()
    return TestClient(app)


def _upload_pair(client: TestClient):
    from app.tests._fixtures import build_minimal_pdf_two_pages
    pdf_a = build_minimal_pdf_two_pages("Acme revenue 1200 widgets.", "Acme risks: supply chain.")
    pdf_b = build_minimal_pdf_two_pages("Globex revenue 900 logistics.", "Globex risks: regulation.")
    a = client.post("/api/ingest/upload", data={"company": "A"},
                    files={"file": ("Acme.pdf", pdf_a, "application/pdf")}).json()
    b = client.post("/api/ingest/upload", data={"company": "B"},
                    files={"file": ("Globex.pdf", pdf_b, "application/pdf")}).json()
    return a, b


def _run_agents(client: TestClient, *, a_sha: str, a_name: str, b_sha: str, b_name: str, monkeypatch) -> None:
    import app.agents.runner as r
    from app.agents.llm_client import StubLLMClient

    def stub_for(company: str, sha: str, doc: str) -> StubLLMClient:
        payload = {
            "company": company,
            "company_overview": {
                "summary": f"{company} operates in the widgets industry.",
                "evidence": [{
                    "company": company, "document_name": doc,
                    "document_sha256": sha, "page_number": 1,
                    "kind": "chunk", "ref_id": f"{company}_{sha[:12]}_p001_c000",
                    "snippet": f"{company} widgets operations.",
                }],
            },
            "financial_performance": {"summary": "Revenue figures follow the financial highlights.", "key_metrics": [], "evidence": []},
            "operational_information": {"summary": "Ops.", "evidence": []},
            "strategic_information": {"summary": "Strategy.", "evidence": []},
            "business_information": {"summary": "Business.", "evidence": []},
            "strengths": [],
            "weaknesses": [],
            "risks": [],
            "important_observations": [],
        }
        s = StubLLMClient()
        s.expect(system_contains=f"Agent {company}", user_contains=doc, response=json.dumps(payload))
        return s

    q = iter([stub_for("A", a_sha, a_name), stub_for("B", b_sha, b_name)])
    r.make_default_client = lambda *, force_stub=False: next(q)  # type: ignore[assignment]
    try:
        response = client.post("/api/agents/run", params={"target": "both"})
        response.raise_for_status()
    finally:
        # Reset to the original factory for subsequent tests using this fixture.
        r.make_default_client = lambda *, force_stub=False: StubLLMClient()  # type: ignore[assignment]


def _stub_comparator_payload(*, a_name: str, a_sha: str, b_name: str, b_sha: str) -> dict:
    return {
        "company_a_name": a_name,
        "company_b_name": b_name,
        "overview_comparison": {
            "a": {"company": "A", "summary": "Acme is a manufacturer.",
                  "evidence": [{"company": "A", "document_name": a_name, "document_sha256": a_sha,
                                "page_number": 1, "ref_kind": "chunk",
                                "ref_id": f"A_{a_sha[:12]}_p001_c000",
                                "snippet": "Acme is a manufacturer.", "kind": "fact"}]},
            "b": {"company": "B", "summary": "Globex is a logistics company.",
                  "evidence": [{"company": "B", "document_name": b_name, "document_sha256": b_sha,
                                "page_number": 1, "ref_kind": "chunk",
                                "ref_id": f"B_{b_sha[:12]}_p001_c000",
                                "snippet": "Globex provides logistics.", "kind": "fact"}]},
            "narrative": "Different industries.",
            "narrative_kind": "derived",
            "evidence": [],
        },
        "financial_comparison": {
            "a": [], "b": [],
            "narrative": "Not available in the provided reports.",
            "narrative_kind": "insight",
            "evidence": [],
        },
        "operational_comparison": {
            "a": {"company": "A", "summary": "Plants.", "evidence": []},
            "b": {"company": "B", "summary": "Fleet.", "evidence": []},
            "narrative": "Different asset bases.",
            "narrative_kind": "derived",
            "evidence": [],
        },
        "business_comparison": {
            "a": {"company": "A", "summary": "Industrial goods.", "evidence": []},
            "b": {"company": "B", "summary": "Logistics.", "evidence": []},
            "narrative": "Different industries.",
            "narrative_kind": "derived",
            "evidence": [],
        },
        "strategic_comparison": {
            "a": {"company": "A", "summary": "Expansion.", "evidence": []},
            "b": {"company": "B", "summary": "Cost optimisation.", "evidence": []},
            "narrative": "Acme grows, Globex tightens.",
            "narrative_kind": "derived",
            "evidence": [],
        },
        "strengths_comparison": {
            "a": {"company": "A", "summary": "Not available in the provided reports.", "evidence": []},
            "b": {"company": "B", "summary": "Not available in the provided reports.", "evidence": []},
            "narrative": "Not available in the provided reports.",
            "narrative_kind": "insight",
            "evidence": [],
        },
        "weaknesses_comparison": {
            "a": {"company": "A", "summary": "Not available in the provided reports.", "evidence": []},
            "b": {"company": "B", "summary": "Not available in the provided reports.", "evidence": []},
            "narrative": "Not available in the provided reports.",
            "narrative_kind": "insight",
            "evidence": [],
        },
        "risks_comparison": {
            "a": {"company": "A", "summary": "Supply chain.", "evidence": []},
            "b": {"company": "B", "summary": "Regulatory.", "evidence": []},
            "narrative": "Different risks.",
            "narrative_kind": "derived",
            "evidence": [],
        },
        "important_observations_comparison": {
            "a": {"company": "A", "summary": "Not available in the provided reports.", "evidence": []},
            "b": {"company": "B", "summary": "Not available in the provided reports.", "evidence": []},
            "narrative": "Not available in the provided reports.",
            "narrative_kind": "insight",
            "evidence": [],
        },
        "trends": [],
        "key_differences": [{
            "title": "Industry and growth",
            "description": "Acme manufactures; Globex does logistics.",
            "kind": "derived",
            "evidence": [
                {"company": "A", "document_name": a_name, "document_sha256": a_sha,
                 "page_number": 1, "ref_kind": "chunk", "ref_id": f"A_{a_sha[:12]}_p001_c000",
                 "snippet": "Acme is a manufacturer.", "kind": "fact"},
                {"company": "B", "document_name": b_name, "document_sha256": b_sha,
                 "page_number": 1, "ref_kind": "chunk", "ref_id": f"B_{b_sha[:12]}_p001_c000",
                 "snippet": "Globex provides logistics.", "kind": "fact"},
            ],
        }],
        "evidence": [],
        "overall_comparative_insights": [{
            "title": "Different industries",
            "claim": "Acme manufactures widgets; Globex provides logistics.",
            "kind": "insight",
            "evidence": [],
        }],
        "warnings": [],
    }


def test_run_comparison_400_when_agents_unavailable(client: TestClient) -> None:
    r = client.post("/api/comparison/run")
    assert r.status_code == 400
    body = r.json()
    # Both A and B missing — error must mention both, or at least indicate.
    assert "agent" in body["detail"].lower() or "POST" in body["detail"]


def test_comparison_get_idle_when_nothing_ran(client: TestClient) -> None:
    r = client.get("/api/comparison")
    assert r.status_code == 200
    assert r.json()["status"] == "idle"
    assert r.json()["analysis"] is None


def test_comparison_clear_resets_state(client: TestClient) -> None:
    r = client.delete("/api/comparison")
    assert r.status_code == 204


def test_full_flow_with_stubs(client: TestClient, monkeypatch) -> None:
    a, b = _upload_pair(client)
    _run_agents(client, a_sha=a["document_sha256"], a_name=a["document_name"],
                b_sha=b["document_sha256"], b_name=b["document_name"], monkeypatch=monkeypatch)

    # Wire the comparator stub.
    import app.comparator.runner as cr
    from app.agents.llm_client import StubLLMClient
    payload = _stub_comparator_payload(
        a_name=a["document_name"], a_sha=a["document_sha256"],
        b_name=b["document_name"], b_sha=b["document_sha256"],
    )

    def factory(*, force_stub: bool = False):
        s = StubLLMClient()
        s.expect(system_contains="COMPARATIVE ANALYSIS",
                 user_contains="Acme.pdf",
                 response=json.dumps(payload))
        return s

    cr.make_default_client = factory  # type: ignore[assignment]

    r = client.post("/api/comparison/run")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["company_a_name"] == a["document_name"]
    assert body["company_b_name"] == b["document_name"]
    assert body["overview_comparison"]["a"]["company"] == "A"
    assert body["overview_comparison"]["b"]["company"] == "B"
    # Cross-company check: the A-only ref must not appear in B-side structures.
    a_ref = f"A_{a['document_sha256'][:12]}_p001_c000"
    blob = json.dumps(body)
    assert a_ref in blob, "A's evidence ref should be cited at least once"
    # Walk the comparison: B's evidence list must contain no A-only ids.
    for sec in (
        "overview_comparison", "operational_comparison", "business_comparison",
        "strategic_comparison", "strengths_comparison", "weaknesses_comparison",
        "risks_comparison", "important_observations_comparison",
    ):
        for ev in body[sec]["b"]["evidence"]:
            assert not ev["ref_id"].startswith("A_"), f"{sec}.b contains A_-prefixed ref_id"

    # Subsequent GET should return 'completed' with the analysis.
    s = client.get("/api/comparison").json()
    assert s["status"] == "completed"
    assert s["analysis"] is not None
